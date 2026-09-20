"""Interface locale de pilotage et de suivi des candidatures.

    python cli.py interface          puis http://127.0.0.1:5000

Le serveur ne fait que trois choses : servir l'interface statique, lire et
muter la base, et declencher les taches longues via taches.py. Aucun traitement
metier ici : il vit dans sourcing/filters/generer_lettres/postuler_*.

Securite : aucune authentification, le serveur n'ecoute que sur 127.0.0.1.
Ne jamais le passer en host='0.0.0.0'.
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from alternance import chemins
from alternance import config
from alternance import db
from alternance import journal
from alternance import parametres
from alternance.interface import taches
from alternance import texte

BASE = config.RACINE
WEB = Path(__file__).resolve().parent / "statique"

app = Flask(__name__, static_folder=None)

# Outil local en evolution constante : sans cela le navigateur sert une version
# en cache de style.css ou app.js et les modifications semblent sans effet.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.errorhandler(Exception)
def toute_erreur(e):
    """Aucune erreur ne doit finir en page HTML de Flask.

    L'interface ne parle que JSON : une exception non rattrapee lui arrivait
    sous forme de page d'erreur, que `reponse.json()` ne savait pas lire, et
    l'utilisateur voyait « HTTP 500 » sans rien de plus. La trace complete part
    dans data/logs/app.log, la phrase utile part a l'ecran.
    """
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return jsonify({"erreur": e.description, "code": e.code}), e.code

    journal.exception(f"{request.method} {request.path}", e)
    return jsonify({
        "erreur": journal.expliquer(f"{type(e).__name__}: {e}"),
        "detail": f"{type(e).__name__}: {e}",
        "journal": "data/logs/app.log",
    }), 500


@app.route("/api/journal")
def api_journal():
    """Les dernieres lignes du journal, pour diagnostiquer sans ouvrir un
    terminal ni chercher le fichier."""
    return jsonify({
        "chemin": str(journal.FICHIER),
        "existe": journal.FICHIER.exists(),
        "contenu": journal.lire(int(request.args.get("lignes", 120))),
    })


@app.route("/api/tache/<int:tache_id>/journal")
def api_journal_tache(tache_id):
    """Sortie complete d'une tache : c'est ce qu'on veut lire quand elle
    echoue, et le message resume ne suffit pas."""
    conn = db.connect()
    r = conn.execute("SELECT type, statut, message, journal FROM taches "
                     "WHERE id = ?", (tache_id,)).fetchone()
    conn.close()
    if r is None:
        return jsonify({"erreur": "tache introuvable"}), 404
    return jsonify(dict(r))


@app.after_request
def _sans_cache(reponse):
    if request.path.endswith((".css", ".js", ".html")) or request.path == "/":
        reponse.headers["Cache-Control"] = "no-store, must-revalidate"
    return reponse

# Toutes les vues, rebuts compris.
#
# Ils etaient masques tant que les filtres vivaient dans le code : rien n'y
# etait actionnable. Depuis que sept familles d'exclusion, des termes libres,
# trois seuils et deux natures de contrat se reglent depuis l'interface, ne pas
# pouvoir ouvrir ces piles revenait a regler des filtres a l'aveugle. 71 % de
# la base y dormait.
VUES = [
    {"cle": "a_valider", "titre": "À valider", "groupe": "tri", "couleur": "attente"},
    {"cle": "a_traiter", "titre": "Validé", "groupe": "tri", "couleur": "actif"},
    {"cle": "lettre_prete", "titre": "Lettre prête", "groupe": "pipeline", "couleur": "redige"},
    {"cle": "envoyee", "titre": "Envoyée", "groupe": "pipeline", "couleur": "actif"},
    {"cle": "entretien", "titre": "Entretien", "groupe": "pipeline", "couleur": "avance"},
    {"cle": "signee", "titre": "Signée", "groupe": "pipeline", "couleur": "avance"},
    {"cle": "refus", "titre": "Refus", "groupe": "pipeline", "couleur": "clos"},
    {"cle": "ecarte", "titre": "Score insuffisant", "groupe": "rebut", "couleur": "inerte"},
    {"cle": "hors_cible", "titre": "Mission hors cible", "groupe": "rebut", "couleur": "inerte"},
    {"cle": "sans_canal", "titre": "Sans moyen de postuler", "groupe": "rebut", "couleur": "inerte"},
    {"cle": "ecole", "titre": "Organisme de formation", "groupe": "rebut", "couleur": "inerte"},
    {"cle": "ats_externe", "titre": "ATS externe", "groupe": "rebut", "couleur": "inerte"},
]
CLES_VISIBLES = [v["cle"] for v in VUES]


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------

def _ligne(r, complet=False):
    """Transforme une ligne SQL en objet destine a l'interface.

    `complet` ajoute la description entiere et la lettre : inutile dans une
    liste de 50 elements, indispensable dans le panneau de detail.
    """
    d = dict(r)
    detail = {}
    if d.get("score_detail"):
        try:
            detail = json.loads(d["score_detail"])
        except json.JSONDecodeError:
            pass

    d["ventilation"] = detail.get("ventilation") or {}
    d["doute"] = detail.get("doute")
    d["motif"] = _motif(d, detail)
    d["grand_groupe"] = detail.get("grand_groupe")
    # Les mots-cles remplacent le salaire sur la carte : ce sont eux qui disent
    # au premier coup d'oeil pourquoi l'offre est remontee.
    d["mots_cles"] = (detail.get("mots_cles_trouves") or [])[:6]

    if complet:
        d["mots_cles"] = detail.get("mots_cles_trouves") or []
        d["score_detail"] = detail
        offre = {"id": d["id"], "entreprise": d["entreprise"]}
        fichier = chemins.lettre_txt(offre)
        d["lettre"] = fichier.read_text(encoding="utf-8") if fichier.exists() else None
        d["lettre_pdf"] = chemins.lettre_pdf(offre).exists()
    else:
        d.pop("description", None)
        d.pop("score_detail", None)
    return d


def _motif(d, detail):
    """Pourquoi cette offre a-t-elle ete ecartee, en une phrase lisible.

    Les raisons brutes sont des motifs d'expression reguliere et des codes
    internes : utiles pour auditer, illisibles pour decider. On les traduit.
    """
    statut = d.get("statut")
    if statut == "ecole":
        raison = (d.get("flag_ecole_raison") or "").split(";")[0].strip()
        return f"Annonce emise par un organisme de formation ({raison})" if raison \
            else "Annonce emise par un organisme de formation"

    if statut == "ats_externe":
        cible = d.get("url_ats") or ""
        hote = cible.split("/")[2] if cible.startswith("http") else ""
        return ("Candidature portee par l'ATS de l'employeur"
                + (f" ({hote})" if hote else "")
                + " : depot manuel, pas d'automatisation possible")

    if statut == "sans_canal":
        return ("Aucun moyen de postuler : ni adresse email, ni formulaire "
                "accessible sur cette annonce")

    if statut == "hors_cible":
        brut = detail.get("mission_technique") or ""
        if brut.startswith("veto_titre"):
            return f"L'intitule releve d'une famille exclue ({brut.split(':', 1)[-1]})"
        if brut.startswith("veto_non_it"):
            return "Intitule de gestion de projet sans qualificatif informatique"
        if brut == "aucun_signal_technique":
            return "Aucun signal technique dans l'annonce"
        if brut.startswith("pas_it"):
            return ("Intitule non informatique et trop peu de signaux techniques "
                    "dans la description")
        if detail.get("nature_exclue"):
            return "Nature de contrat non recherchee (stage ou alternance)"
        return brut or "Mission jugee hors cible"

    if statut == "ecarte":
        if detail.get("duree_insuffisante"):
            return "Duree de stage inferieure au minimum demande"
        if detail.get("nature_exclue"):
            return "Nature de contrat non recherchee"
        return f"Adequation {d.get('matching')} %, sous le seuil de {config.SEUIL_MATCHING} %"

    return None


# --------------------------------------------------------------------------
# Interface statique
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.route("/<path:fichier>")
def statique(fichier):
    return send_from_directory(WEB, fichier)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

@app.route("/api/contexte")
def api_contexte():
    """Tout ce dont l'interface a besoin au demarrage."""
    conn = db.connect()
    compte = {r["statut"]: r["n"] for r in conn.execute(
        "SELECT statut, COUNT(*) n FROM offres GROUP BY statut")}
    sources = [r["source"] for r in conn.execute(
        "SELECT source, COUNT(*) n FROM offres GROUP BY source ORDER BY n DESC")]
    conn.close()
    return jsonify({
        "vues": [dict(v, compte=compte.get(v["cle"], 0)) for v in VUES],
        "sources": sources,
        "profil": {
            "nom": config.PROFIL["nom"],
            "formation": config.PROFIL["formation"],
            "adresse": config.ADRESSE_REFERENCE,
            "rayon": config.RAYON_KM,
            "seuil": config.SEUIL_MATCHING,
        },
        "cv": {
            "present": chemins.CV.exists(),
            "nom": chemins.CV.name if chemins.CV.exists() else None,
            "taille_ko": round(chemins.CV.stat().st_size / 1024) if chemins.CV.exists() else 0,
        },
        "tache": taches.tache_en_cours(),
        # Sert a reafficher le panneau d'erreur apres un rechargement : sans
        # lui, un echec disparaissait de l'ecran des que la page repartait.
        "dernier_echec": taches.dernier_echec(),
    })


@app.route("/api/offres")
def api_offres():
    statut = request.args.get("statut", "a_valider")
    if statut not in CLES_VISIBLES:
        return jsonify({"erreur": "vue inconnue"}), 400

    sql = "SELECT * FROM offres WHERE statut = ?"
    params = [statut]
    for champ in ("genre", "source"):
        valeur = request.args.get(champ)
        if valeur:
            sql += f" AND {champ} = ?"
            params.append(valeur)
    sql += " ORDER BY matching DESC, score DESC LIMIT ?"
    params.append(int(request.args.get("limite", 400)))

    conn = db.connect()
    lignes = [_ligne(r) for r in conn.execute(sql, params)]
    conn.close()
    return jsonify(lignes)


@app.route("/api/offre/<int:offre_id>")
def api_offre(offre_id):
    conn = db.connect()
    r = conn.execute("SELECT * FROM offres WHERE id = ?", (offre_id,)).fetchone()
    if r is None:
        conn.close()
        return jsonify({"erreur": "introuvable"}), 404
    detail = _ligne(r, complet=True)
    detail["evenements"] = [dict(e) for e in conn.execute(
        "SELECT date, type, detail FROM evenements WHERE offre_id = ? "
        "ORDER BY id DESC LIMIT 12", (offre_id,))]
    conn.close()
    return jsonify(detail)


# --------------------------------------------------------------------------
# Mutation
# --------------------------------------------------------------------------

@app.route("/api/offre/<int:offre_id>/statut", methods=["POST"])
def api_statut(offre_id):
    nouveau = (request.json or {}).get("statut")
    autorises = db.STATUTS + ["valide_manuel", "rejete_manuel", "recuperer"]
    if nouveau not in autorises:
        return jsonify({"erreur": f"statut inconnu : {nouveau}"}), 400

    # Une validation manuelle renvoie l'offre dans le vivier actif, mais
    # l'intention est tracee pour qu'un rescore ne la remette pas en doute.
    effectif = "a_traiter" if nouveau in ("valide_manuel", "recuperer") else nouveau

    conn = db.connect()
    avant = conn.execute("SELECT statut FROM offres WHERE id = ?",
                         (offre_id,)).fetchone()
    if avant is None:
        conn.close()
        return jsonify({"erreur": "introuvable"}), 404

    # Le verrou survit au rescore : sans lui, le filtre qui avait ecarte
    # l'offre la reecarterait au calcul suivant, et la recuperation manuelle
    # n'aurait aucun effet durable.
    verrou = 1 if nouveau in ("valide_manuel", "recuperer") else 0
    if verrou:
        conn.execute("UPDATE offres SET statut = ?, verrou_manuel = 1 WHERE id = ?",
                     (effectif, offre_id))
    else:
        conn.execute("UPDATE offres SET statut = ? WHERE id = ?", (effectif, offre_id))
    _suivre_reponse(conn, offre_id, effectif)
    db.log(conn, offre_id, f"statut:{avant['statut']}->{effectif}", "depuis l'interface")
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "statut": effectif})


# Ce qu'une issue signifie pour la ligne de candidature. Une offre passee en
# entretien ou en refus a recu une reponse : la relance prevue n'a plus lieu
# d'etre, et la laisser en place ferait relancer un recruteur qui a deja
# repondu.
REPONSES = {"entretien": "entretien", "refus": "refus", "signee": "signature"}


def _suivre_reponse(conn, offre_id, statut):
    """Reporte l'issue sur la ligne de candidature, quand elle existe.

    Les deux tables ne disent pas la meme chose : `offres.statut` est l'etat
    courant, `candidatures` porte le journal de l'envoi et des relances. Sans
    ce report, la date de relance restait armee apres un refus.
    """
    if statut == "envoyee":
        existe = conn.execute(
            "SELECT 1 FROM candidatures WHERE offre_id = ?", (offre_id,)).fetchone()
        if existe:
            # Retour en arriere depuis un refus : "Rouvrir le suivi" remettait
            # l'offre en attente sans jamais rearmer la relance, qu'une reponse
            # precedente avait desarmee. L'offre restait donc en suspens sans
            # que rien ne la rappelle.
            conn.execute(
                "UPDATE candidatures SET statut = 'envoyee', type_reponse = NULL, "
                "date_reponse = NULL, date_relance_prevue = date('now', '+7 days') "
                "WHERE offre_id = ?", (offre_id,))
        else:
            # Depot fait a la main - email, formulaire d'un ATS, candidature en
            # personne. Sans cette ligne, l'offre serait "envoyee" sans qu'aucune
            # relance ne soit jamais prevue.
            conn.execute(
                "INSERT INTO candidatures (offre_id, canal, date_preparation, "
                "date_envoi, statut, date_relance_prevue) VALUES "
                "(?, 'manuel', datetime('now'), datetime('now'), 'envoyee', "
                "date('now', '+7 days'))", (offre_id,))
        return

    if statut in REPONSES:
        conn.execute(
            "UPDATE candidatures SET statut = ?, type_reponse = ?, "
            "date_reponse = COALESCE(date_reponse, datetime('now')), "
            "date_relance_prevue = NULL WHERE offre_id = ?",
            (statut, REPONSES[statut], offre_id))


@app.route("/api/parametres")
def api_parametres():
    """Etat complet des reglages modifiables, pour la page Parametres."""
    etat = parametres.etat()
    etat["cv"] = _etat_cv()
    etat["jeton"] = _etat_jeton()
    return jsonify(etat)


@app.route("/api/parametres", methods=["POST"])
def api_enregistrer_parametres():
    """Enregistre les reglages. L'adresse est geocodee avant d'etre acceptee.

    Les modifications prennent effet immediatement dans le processus courant,
    mais les offres deja en base gardent leur score : il faut un rescore pour
    que de nouveaux criteres se voient. L'interface le signale.
    """
    donnees = request.json or {}
    modifications = {}

    adresse = (donnees.get("adresse") or "").strip()
    if adresse and adresse != config.ADRESSE_REFERENCE:
        from alternance import geocode
        resultats = geocode.geocode(adresse)
        if not resultats:
            return jsonify({"erreur": "adresse introuvable"}), 400
        modifications["adresse"] = adresse
        modifications["origine"] = [resultats[0]["lat"], resultats[0]["lon"]]

    for cle, attribut in (("recherche_alternance", "RECHERCHE_ALTERNANCE"),
                          ("recherche_stages", "RECHERCHE_STAGES"),
                          ("lettre_relecture", "LETTRE_RELECTURE")):
        if donnees.get(cle) is not None:
            modifications[cle] = bool(donnees[cle])
    # Chercher ni l'un ni l'autre viderait toute collecte : on refuse plutot
    # que de laisser l'utilisateur lancer une analyse qui ne trouvera rien.
    if (modifications.get("recherche_alternance") is False
            and modifications.get("recherche_stages") is False):
        return jsonify({"erreur": "il faut chercher au moins l'alternance "
                                  "ou les stages"}), 400

    for cle, mini, maxi in (("rayon_km", 5, 150),
                            ("stage_duree_semaines", 2, 52),
                            ("stage_ecart_court", 0, 26),
                            ("stage_ecart_long", 0, 40),
                            ("seuil_matching", 0, 100),
                            ("duree_max_mois", 6, 36),
                            ("prime_grand_groupe", 0, 100)):
        if donnees.get(cle) is not None:
            valeur = int(donnees[cle])
            if not mini <= valeur <= maxi:
                return jsonify({"erreur": f"{cle} hors bornes ({mini}-{maxi})"}), 400
            modifications[cle] = valeur

    if isinstance(donnees.get("exclusions"), dict):
        modifications["exclusions"] = {
            cle: bool(v) for cle, v in donnees["exclusions"].items()
            if cle in config.EXCLUSIONS_ACTIVES}

    for cle in ("exclusions_perso", "exclusions_perso_souples"):
        if isinstance(donnees.get(cle), list):
            modifications[cle] = [
                str(t).strip() for t in donnees[cle] if str(t).strip()][:40]

    if isinstance(donnees.get("profil"), dict):
        profil = {}
        for cle, valeur in donnees["profil"].items():
            if cle not in config.DEFAUTS["profil"]:
                continue
            reference = config.DEFAUTS["profil"][cle]
            if isinstance(reference, int) and not isinstance(reference, bool):
                try:
                    profil[cle] = int(valeur)
                except (TypeError, ValueError):
                    return jsonify({"erreur": f"{cle} doit etre un nombre"}), 400
            else:
                profil[cle] = str(valeur).strip()[:400]
        # Teste seulement si le champ est envoye : l'interface poste le profil
        # entier, mais un appel partiel ne doit pas echouer sur un champ absent.
        if "nom" in profil and not profil["nom"]:
            return jsonify({"erreur": "le nom ne peut pas etre vide"}), 400
        if profil.get("email") and "@" not in profil["email"]:
            return jsonify({"erreur": "adresse email invalide"}), 400
        modifications["profil"] = profil

    # Adresse postale : reclamee par les formulaires des grands comptes, qui
    # refusent un code postal invalide. Distincte de l'adresse de reference
    # ci-dessus, qui ne sert qu'au calcul des distances.
    if isinstance(donnees.get("adresse_postale"), dict):
        postale = {}
        for cle, valeur in donnees["adresse_postale"].items():
            if cle in config.DEFAUTS["adresse_postale"]:
                postale[cle] = str(valeur).strip()[:120]
        code = postale.get("code_postal")
        if code and not re.fullmatch(r"[0-9]{5}", code):
            return jsonify({"erreur": "code postal invalide (5 chiffres)"}), 400
        modifications["adresse_postale"] = postale

    if isinstance(donnees.get("romes"), list):
        codes = []
        for code in donnees["romes"]:
            code = str(code).strip().upper()
            if not code:
                continue
            if not re.fullmatch(r"[A-Z][0-9]{4}", code):
                return jsonify({"erreur": f"code ROME invalide : {code}"}), 400
            if code not in codes:
                codes.append(code)
        if not codes:
            return jsonify({"erreur": "au moins un code ROME est necessaire"}), 400
        modifications["romes"] = codes

    if isinstance(donnees.get("mots_cles"), dict):
        mots = {}
        for mot, poids in donnees["mots_cles"].items():
            mot = texte.normalise(mot).strip()
            if not mot:
                continue
            try:
                poids = int(poids)
            except (TypeError, ValueError):
                return jsonify({"erreur": f"poids invalide pour {mot}"}), 400
            if not 1 <= poids <= 30:
                return jsonify({"erreur": f"poids hors bornes pour {mot} (1-30)"}), 400
            mots[mot] = poids
        if not mots:
            return jsonify({"erreur": "la liste de mots-cles ne peut pas etre vide"}), 400
        modifications["mots_cles"] = mots

    if isinstance(donnees.get("ecole_blocklist"), list):
        noms = []
        for nom in donnees["ecole_blocklist"]:
            nom = texte.normalise(nom).strip()
            if nom and nom not in noms:
                noms.append(nom)
        modifications["ecole_blocklist"] = noms

    parametres.enregistrer(modifications)
    etat = parametres.etat()
    etat["cv"] = _etat_cv()
    etat["jeton"] = _etat_jeton()
    etat["rescore_requis"] = bool(modifications)
    return jsonify(etat)


@app.route("/api/parametres/defaut/<cle>", methods=["POST"])
def api_defaut(cle):
    """Retablit une liste a sa valeur par defaut en la retirant de la surcouche."""
    if cle not in ("profil", "adresse_postale", "romes", "mots_cles",
                   "ecole_blocklist"):
        return jsonify({"erreur": f"liste inconnue : {cle}"}), 400
    parametres.reinitialiser(cle)
    etat = parametres.etat()
    etat["cv"] = _etat_cv()
    etat["jeton"] = _etat_jeton()
    return jsonify(etat)


@app.route("/api/comptes")
def api_comptes():
    """Etat des sessions de connexion enregistrees.

    Ne renvoie jamais le contenu des sessions : seulement leur presence, leur
    age et le nombre de cookies. Un fichier de session vaut un mot de passe.
    """
    from alternance.candidature import session as connecter_compte
    return jsonify([
        {"cle": cle, "libelle": site["libelle"], "role": site["role"],
         "url": site["url"], **connecter_compte.etat(cle)}
        for cle, site in connecter_compte.SITES.items()])


@app.route("/api/comptes/<cle>", methods=["DELETE"])
def api_deconnecter(cle):
    """Supprime la session locale. Ne deconnecte rien cote site."""
    from alternance.candidature import session as connecter_compte
    if cle not in connecter_compte.SITES:
        return jsonify({"erreur": "site inconnu"}), 400
    fichier = connecter_compte.chemin_session(cle)
    if fichier.exists():
        fichier.unlink()
    return jsonify({"ok": True, "cle": cle, **connecter_compte.etat(cle)})


@app.route("/api/integrations/outlook")
def api_outlook():
    """Etat de la boite universitaire. Ne renvoie aucun jeton."""
    from alternance.courrier import graph as graph_mail
    return jsonify(graph_mail.etat())


@app.route("/api/integrations/outlook", methods=["DELETE"])
def api_outlook_oublier():
    """Efface le cache local. Le consentement se retire cote Microsoft."""
    from alternance.courrier import graph as graph_mail
    graph_mail.oublier()
    return jsonify({"ok": True, **graph_mail.etat()})


@app.route("/api/parametres/impact", methods=["POST"])
def api_impact():
    """Que couperait cette configuration, sans rien enregistrer.

    Repond a la seule question qui compte avant de valider un terme : quelles
    offres deja collectees disparaitraient, et combien d'entre elles sont
    actuellement dans le vivier actionnable.
    """
    donnees = request.json or {}
    conn = db.connect()
    offres = [dict(r) for r in conn.execute(
        "SELECT intitule, description, statut, matching FROM offres "
        "WHERE genre != 'spontanee'")]
    conn.close()

    rapport = parametres.simuler(
        donnees.get("exclusions_perso_souples") or [],
        donnees.get("exclusions_perso") or [],
        donnees.get("exclusions") or {},
        offres)
    return jsonify({"analysees": len(offres), "impacts": rapport})


@app.route("/api/parametres/jeton", methods=["POST"])
def api_jeton():
    """Ecrit le jeton Claude dans .env. Il n'est jamais relu par l'interface.

    Un secret ne transite pas par un fichier de donnees : .env est le seul
    endroit, et il est exclu du git. L'API ne renvoie qu'une empreinte.
    """
    jeton = ((request.json or {}).get("jeton") or "").strip()
    if not jeton:
        return jsonify({"erreur": "jeton vide"}), 400
    if not jeton.startswith("sk-ant-oat01-"):
        return jsonify({"erreur": "format inattendu : un jeton "
                                  "`claude setup-token` commence par sk-ant-oat01-"}), 400

    env = BASE / ".env"
    lignes = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lignes = [l for l in lignes if not l.startswith("CLAUDE_CODE_OAUTH_TOKEN=")]
    lignes.append(f"CLAUDE_CODE_OAUTH_TOKEN={jeton}")
    env.write_text('\n'.join(lignes) + '\n', encoding="utf-8")
    return jsonify({"ok": True, "jeton": _etat_jeton()})


def _etat_cv():
    # Relu a chaque appel : chemins.CV est fige a l'import du module, or un
    # depot depuis l'interface change le fichier pendant que le serveur tourne.
    cv = chemins.trouver_cv()
    if not cv.exists():
        return {"present": False, "nom": None, "taille_ko": 0}
    return {"present": True, "nom": cv.name,
            "taille_ko": round(cv.stat().st_size / 1024)}


def _etat_jeton():
    """Presence et empreinte, jamais la valeur."""
    import os
    valeur = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or ""
    if not valeur:
        env = BASE / ".env"
        if env.exists():
            for ligne in env.read_text(encoding="utf-8").splitlines():
                if ligne.startswith("CLAUDE_CODE_OAUTH_TOKEN="):
                    valeur = ligne.split("=", 1)[1].strip()
    if not valeur:
        return {"present": False, "empreinte": None}
    return {"present": True, "empreinte": f"...{valeur[-6:]}", "longueur": len(valeur)}


@app.route("/api/cv", methods=["POST"])
def api_cv():
    """Remplace le CV de reference. L'ancien est archive, jamais ecrase."""
    fichier = request.files.get("fichier")
    if fichier is None or not fichier.filename:
        return jsonify({"erreur": "aucun fichier"}), 400
    if not fichier.filename.lower().endswith(".pdf"):
        return jsonify({"erreur": "le CV doit etre un PDF"}), 400

    chemins.DOSSIER_CV.mkdir(parents=True, exist_ok=True)

    # Les anciens CV sont archives PUIS retires du dossier : trouver_cv() prend
    # le PDF le plus recent, mais laisser trainer les precedents ferait porter
    # le choix sur une date de fichier, ce qui se retourne au premier
    # copier-coller. Un seul PDF dans le dossier, un seul CV possible.
    archives = BASE / "data" / "archives"
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    for ancien in chemins.DOSSIER_CV.glob("*.pdf"):
        archives.mkdir(parents=True, exist_ok=True)
        shutil.move(str(ancien), str(archives / f"{horodatage}_{ancien.name}"))

    # Le nom d'origine est conserve : il part en piece jointe chez le
    # recruteur, "cv.pdf" y ferait mauvais effet. secure_filename retire les
    # separateurs de chemin et les caracteres exotiques.
    cible = chemins.DOSSIER_CV / (secure_filename(fichier.filename) or "cv.pdf")
    fichier.save(str(cible))
    chemins.CV = cible
    return jsonify({
        "ok": True,
        "nom": cible.name,
        "taille_ko": round(cible.stat().st_size / 1024),
    })


# --------------------------------------------------------------------------
# Taches de fond
# --------------------------------------------------------------------------

@app.route("/api/tache", methods=["POST"])
def api_lancer_tache():
    donnees = request.json or {}
    tache_id, erreur = taches.lancer(donnees.get("type"), donnees)
    if erreur:
        return jsonify({"erreur": erreur}), 409
    return jsonify({"ok": True, "tache": tache_id})


@app.route("/api/tache")
def api_tache():
    conn = db.connect()
    r = conn.execute("SELECT * FROM taches ORDER BY id DESC LIMIT 1").fetchone()
    compte = {x["statut"]: x["n"] for x in conn.execute(
        "SELECT statut, COUNT(*) n FROM offres GROUP BY statut")}
    conn.close()
    return jsonify({
        "tache": dict(r) if r else None,
        "compte": {v["cle"]: compte.get(v["cle"], 0) for v in VUES},
    })


def servir(port=5000):
    """Demarre le serveur local.

    127.0.0.1 explicitement, jamais 0.0.0.0 : l'interface n'a aucune
    authentification et ne doit pas etre joignable depuis le reseau.
    """
    n = taches.purger_taches_orphelines()
    if n:
        print(f"{n} tache(s) interrompue(s) par un redemarrage, "
              "marquee(s) echouee(s)")
    print(f"Tableau de bord : http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", debug=False, port=port, threaded=True)


if __name__ == "__main__":
    servir()
