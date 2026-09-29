"""Generation des lettres de motivation via Claude Code en mode headless.

Le token `claude setup-token` du .env permet d'appeler Claude Code sans session
interactive : c'est le mecanisme officiel prevu pour un abonnement.

    python cli.py lettres --limite 5          # les 5 meilleurs scores
    python cli.py lettres --offre 59          # une offre precise
    python cli.py lettres --limite 50 --force # regenere meme si deja ecrite
"""

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from alternance import chemins
from alternance import config
from alternance import db

BASE = config.RACINE
LETTRES = BASE / "lettres"
# Deux sources, chacune pour ce qu'elle sait porter :
#
#   - l'identite, la formation, le contact, le rythme et les dates viennent de
#     la page Parametres (config.PROFIL). La page annonce que ces valeurs
#     « partent dans les lettres » : c'etait faux, la redaction ne les lisait
#     jamais. Qui installait l'outil et remplissait l'interface obtenait des
#     lettres signees « Prenom Nom », ou un refus de Claude ;
#   - le parcours (experiences, projets, competences) vient du CV depose en
#     haut de la page, ou de prompts/systeme_lettre.md pour qui l'a rempli.
#
# Le parcours ne venait que de systeme_lettre.md, un fichier a recopier et a
# editer a la main. Personne qui s'en tient a l'interface ne le fait : pour
# eux, aucune lettre n'etait possible, et le message leur demandait d'ouvrir
# un fichier qu'ils ne sauraient pas trouver. Le CV, lui, est deja depose
# depuis l'interface, et il contient exactement ces faits.
#
# systeme_lettre.md garde la priorite quand il est rempli : il est plus
# precis qu'un PDF dont la mise en page est perdue a l'extraction.
SYSTEME = BASE / "prompts" / "systeme_lettre.md"
GABARIT = BASE / "prompts" / "systeme_lettre.exemple.md"
# Lignes du gabarit que personne ne garde en remplissant son parcours. La
# premiere est celle de l'ancien gabarit, encore recopie sur certains postes.
MARQUEURS_GABARIT = ("Prénom Nom, 20 ans.",
                     "Développement : langages et frameworks réellement pratiqués.")
# Prefixe reconnu par journal.expliquer : sans lui, l'interface affichait
# « Arret inattendu, sans message d'erreur » au-dessus du message lui-meme.
REFUS = "Lettres impossibles : "
TIMEOUT = 300
# En dessous, le PDF est une image (scan, export aplati) : pypdf n'en tire
# que des bribes, et une lettre ecrite dessus inventerait le reste. Un CV
# d'une page en texte en donne plus de 1500.
CV_MINIMUM = 300
CV_MAXIMUM = 12000

# Champs du profil repris dans les lettres, dans l'ordre ou ils se lisent.
# L'adresse postale et les liens de signature n'y ont pas leur place : le
# prompt interdit tout en-tete.
CHAMPS_IDENTITE = [
    ("nom", "Nom (signature)"),
    ("titre", "Accroche"),
    ("formation", "Formation"),
    ("etablissement", "Etablissement"),
    ("ville", "Ville de residence"),
    ("email", "Email"),
    ("telephone_affiche", "Telephone"),
    ("debut", "Debut possible"),
    ("disponibilite", "Disponibilite"),
    ("fin", "Fin de formation"),
    ("rythme", "Rythme d'alternance"),
    ("duree_mois", "Duree de contrat recherchee (mois)"),
    ("duree_negociable_jusqu_a", "Duree acceptable jusqu'a (mois)"),
    ("poursuite_etudes", "Poursuite d'etudes"),
]


def bloc_identite():
    """Le profil saisi dans la page Parametres, tel que le redacteur le lit."""
    lignes = ["# Identité du candidat",
              "",
              "Saisie par le candidat dans l'outil. Ces valeurs font foi : si "
              "la suite du prompt en donne d'autres, ce sont celles-ci qui "
              "comptent.",
              ""]
    for cle, libelle in CHAMPS_IDENTITE:
        valeur = config.PROFIL.get(cle)
        if valeur not in (None, ""):
            lignes.append(f"- {libelle} : {valeur}")
    return "\n".join(lignes)


def parcours_manuel():
    """Le contenu de systeme_lettre.md s'il a ete rempli, sinon None.

    Absent ou encore au gabarit, il ne compte pas : le CV prend le relais.
    """
    if not SYSTEME.exists():
        return None
    texte = SYSTEME.read_text(encoding="utf-8")
    if any(m in texte for m in MARQUEURS_GABARIT):
        return None
    return texte


def texte_du_cv():
    """Le texte du CV depose, ou une erreur qui dit quoi deposer.

    Relu a chaque fois : chemins.CV est fige a l'import, or le CV peut etre
    remplace depuis l'interface pendant que le serveur tourne.
    """
    cv = chemins.trouver_cv()
    if not cv.exists():
        raise RuntimeError(
            REFUS + "aucun CV depose. Le deposer dans le cadre en haut de la "
            "page : c'est de lui que le redacteur tire experiences, projets "
            "et competences.")
    try:
        import logging
        from pypdf import PdfReader
        # pypdf avertit sur stderr pour chaque ecart de format, et la tache
        # l'afficherait dans le journal de l'interface comme une erreur.
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        pages = PdfReader(str(cv)).pages
        texte = "\n".join((p.extract_text() or "") for p in pages)
    except Exception as e:
        raise RuntimeError(
            REFUS + f"le CV {cv.name} n'a pas pu etre lu ({e}). Le deposer "
            "a nouveau, exporte en PDF depuis Word, Canva ou LaTeX.") from None
    texte = re.sub(r"[ \t]+", " ", texte).strip()
    if len(texte) < CV_MINIMUM:
        raise RuntimeError(
            REFUS + f"le CV {cv.name} ne contient presque pas de texte "
            f"lisible ({len(texte)} caracteres) : c'est sans doute une image "
            "ou un scan. L'exporter en PDF depuis l'outil qui a servi a le "
            "creer, sans l'aplatir, puis le deposer a nouveau.")
    return cv, texte[:CV_MAXIMUM]


def parcours_depuis_le_cv():
    """Le gabarit, dont la section candidat est remplacee par le CV.

    Le reste du gabarit - comment ecrire, interdits, format de sortie - est
    generique et s'applique tel quel.
    """
    cv, texte = texte_du_cv()
    gabarit = GABARIT.read_text(encoding="utf-8")
    gabarit = re.sub(r"<!--.*?-->\s*", "", gabarit, flags=re.S)
    section = (
        "# Le candidat — son CV, seule source de faits sur son parcours\n\n"
        "Texte extrait automatiquement du PDF de son CV. La mise en page est "
        "perdue : des colonnes peuvent se meler, des puces apparaitre comme "
        "des fleches. Reconstitue le sens, n'ajoute rien. Experiences, "
        "projets, competences, langues : tout ce qui n'y figure pas n'existe "
        "pas pour toi. Pour l'identite, le contact et les dates, le bloc "
        "« Identité du candidat » fait foi.\n\n"
        "Les qualites que le CV revendique (rigueur, creativite...) ne se "
        "recopient pas : montre-les par un fait, ou tais-les.\n\n"
        f"<cv fichier=\"{cv.name}\">\n{texte}\n</cv>\n\n")
    debut = gabarit.find("# Le candidat")
    fin = gabarit.find("# Comment écrire")
    if debut == -1 or fin == -1:
        # Gabarit reformule : mieux vaut un prompt un peu redondant qu'une
        # section candidat ecrasee sans le savoir.
        return gabarit + "\n\n" + section
    return gabarit[:debut] + section + gabarit[fin:]


def prompt_systeme():
    """Identite + parcours, ou une erreur qui dit quoi faire.

    Verifie avant tout appel : sans ces faits, chaque lettre couterait un
    appel pour un refus.
    """
    defaut = config.DEFAUTS["profil"]
    if any(config.PROFIL.get(c) == defaut[c] for c in ("nom", "email")):
        raise RuntimeError(
            REFUS + "le profil porte encore les valeurs d'exemple. Page "
            "Parametres, bloc « Profil » : renseigner au moins le nom et "
            "l'email, puis enregistrer.")
    parcours = parcours_manuel() or parcours_depuis_le_cv()
    return bloc_identite() + "\n\n" + parcours


def purger_lettres_invalides(conn):
    """Remet a rediger les offres dont la « lettre » n'en est pas une.

    Avant le controle d'ouverture, un refus de Claude long de plus de 120
    mots etait enregistre comme lettre, et l'offre passait en « lettre
    prete ». Ce controle empeche d'en produire de nouveaux, pas d'effacer
    ceux qui sont deja sur disque - et le bouton « Envoyer les
    candidatures » les aurait colles dans le formulaire du recruteur.

    Le fichier est renomme et non supprime : il reste lisible pour qui veut
    comprendre ce qui s'est passe.
    """
    remises = 0
    for o in conn.execute("SELECT id, entreprise FROM offres "
                          "WHERE statut = 'lettre_prete'").fetchall():
        fichier = chemins.lettre_txt(o)
        texte = chemins.lire_lettre(o)
        if chemins.est_une_lettre(texte):
            continue
        if fichier.exists():
            fichier.replace(fichier.with_name("lettre.rejetee.txt"))
        conn.execute("UPDATE offres SET statut = 'a_traiter' WHERE id = ?",
                     (o["id"],))
        db.log(conn, o["id"], "lettre:rejetee",
               "le texte enregistre n'etait pas une lettre")
        remises += 1
    if remises:
        conn.commit()
    return remises


def slug(texte):
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9]+", "_", texte).strip("_")
    return texte or "entreprise"


def contexte_offre(o):
    """Ce que Claude doit savoir de l'offre, sans bruit."""
    lignes = [f"Entreprise : {o['entreprise'] or 'non communiquee'}"]
    if o["naf"]:
        lignes.append(f"Secteur : {o['naf']}")
    if o["taille"]:
        lignes.append(f"Effectif : {o['taille']}")
    if o["lieu"]:
        d = f" (a {o['distance_km']} km du domicile)" if o["distance_km"] else ""
        lignes.append(f"Lieu : {o['lieu']}{d}")
    if o["contrat_duree"]:
        lignes.append(f"Duree annoncee : {o['contrat_duree']} mois")

    if o["genre"] == "spontanee":
        lignes.append(
            "\nIl s'agit d'une CANDIDATURE SPONTANEE : aucune offre n'est publiee. "
            "Le 'Vous' doit donc porter sur le metier et le secteur de l'entreprise, "
            "pas sur des missions precises. Sois concret sur ce qu'il peut leur "
            "apporter compte tenu de leur activite."
        )
    else:
        lignes.append("\nIntitule du poste : " + (o["intitule"] or ""))
        lignes.append("\nTexte de l'annonce :\n" + (o["description"] or "")[:6000])
    return "\n".join(lignes)


def nature_contrat(o):
    """Ligne d'en-tete qui dit au redacteur de quoi il s'agit.

    Sans elle, toute lettre parlait de rythme d'alternance, y compris pour un
    stage — ce qui se voit immediatement a la lecture.
    """
    from alternance import filtres as filters
    # Les offres arrivent en sqlite3.Row, qui n'expose pas .get() : filters
    # travaille sur des dictionnaires. Sans cette conversion, la generation
    # echouait pour TOUTES les offres, pas seulement les stages.
    o = dict(o)
    if not filters.est_stage(o):
        # Le rythme vient du profil : ecrit en dur, il contredisait celui
        # que le candidat avait saisi dans la page Parametres.
        rythme = config.PROFIL.get("rythme") or "voir l'identite du candidat"
        return (f"NATURE : ALTERNANCE, rythme {rythme}. "
                "Ne parle pas de duree de stage.")

    cible = config.STAGE_DUREE_SEMAINES
    base = (f"NATURE : STAGE de {cible} semaines, a temps plein. "
            "Ne parle pas de rythme d'alternance.")

    duree = o.get("contrat_duree")
    if duree is None:
        # Pres de la moitie des annonces de stage n'indiquent aucune duree.
        # La lettre doit alors poser le besoin explicitement, sinon le
        # recruteur decouvre la contrainte au premier echange.
        return (base + f" L'annonce n'indique AUCUNE duree : formule clairement "
                f"que le stage recherche dure {cible} semaines, en une phrase "
                "simple, sans en faire un point de blocage.")
    if duree > cible + config.STAGE_ECART_LONG:
        return (base + f" L'annonce annonce {duree} semaines, plus que les "
                f"{cible} necessaires : dis en une phrase que la duree requise "
                f"est de {cible} semaines et que le calendrier reste a caler "
                "ensemble. Pas de justification longue.")
    return base + " La duree annoncee correspond : ne reviens pas dessus."


# Consigne ajoutee au prompt systeme quand la relecture est active. Elle est
# ici et non dans systeme_lettre.md parce que ce fichier-la est personnel et
# recopie depuis un .exemple : une consigne technique n'a pas a dependre du
# fait que quelqu'un ait pense a la reporter.
RELECTURE = """
Avant de rediger, invoque le skill lettre-motivation et applique sa methode.
Une fois la lettre ecrite, invoque humanizer-fr puis lettre-motivation-anti-ia
et corrige le texte selon leurs retours. Ne renvoie que la lettre finale, sans
commentaire sur les corrections apportees."""


def appeler_claude(contexte, nature=None):
    env = dict(os.environ)
    token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        sys.exit("CLAUDE_CODE_OAUTH_TOKEN absent du .env")

    prompt = (
        "Redige la lettre de motivation correspondant a cette candidature.\n\n"
        + ((nature + "\n\n") if nature else "")
        + contexte
    )
    systeme = prompt_systeme()
    if config.LETTRE_RELECTURE:
        systeme += "\n" + RELECTURE

    try:
        resultat = subprocess.run(
            ["claude", "-p", prompt,
             "--append-system-prompt", systeme,
             # "Skill" et pas "" : --allowedTools est une liste d'outils
             # autorises SANS demande de permission, pas une restriction de ce
             # qui existe. Avec une liste vide, le Skill tool restait present
             # mais toute invocation attendait une approbation que personne ne
             # peut donner en mode headless. Les skills etaient donc inertes.
             "--allowedTools", "Skill"],
            capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=TIMEOUT, cwd=str(BASE),
        )
    except FileNotFoundError:
        # Sans ce rattrapage, l'interface affichait « FileNotFoundError:
        # [WinError 2] Le fichier specifie est introuvable » : exact, et
        # parfaitement muet sur le fichier en question. Le message doit nommer
        # ce qui manque et dire comment l'obtenir.
        raise RuntimeError(
            "La commande `claude` est introuvable. Les lettres sont redigees "
            "par Claude Code : l'installer avec "
            "`npm install -g @anthropic-ai/claude-code`, puis produire un "
            "jeton avec `claude setup-token`. Le reste de l'outil fonctionne "
            "sans lui.") from None
    if resultat.returncode != 0:
        raise RuntimeError((resultat.stderr or resultat.stdout)[:400])
    return resultat.stdout.strip()


def nettoyer(texte):
    """Retire les residus de formatage et les caracteres typographiques IA."""
    texte = re.sub(r"^```[a-z]*\n|\n```$", "", texte.strip())
    for mauvais, bon in [("—", ", "), ("–", ", "), ("’", "'"),
                         ("‘", "'"), ("“", '"'), ("”", '"'),
                         ("…", "..."), (" ", " "), (" ", " ")]:
        texte = texte.replace(mauvais, bon)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def generer(conn, o, force=False):
    # Chemin indexe sur l'offre et non sur l'entreprise : deux postes chez un
    # meme employeur doivent avoir deux lettres distinctes.
    chemins.dossier_candidature(o, creer=True)
    fichier = chemins.lettre_txt(o)

    if fichier.exists() and not force:
        return fichier, "deja_ecrite"

    texte = nettoyer(appeler_claude(contexte_offre(o), nature_contrat(o)))
    # Le prompt impose d'ouvrir sur « Madame, Monsieur, ». Un texte qui
    # commence autrement n'est pas une lettre : un refus, une question, un
    # « Voici la lettre : ». Le compte de mots seul ne les arretait pas.
    if not chemins.est_une_lettre(texte):
        debut = " ".join(texte.split()[:12])
        raise RuntimeError(f"pas une lettre, rien n'est enregistre : {debut}...")
    mots = len(texte.split())
    if mots < 120:
        raise RuntimeError(f"lettre anormalement courte ({mots} mots)")

    fichier.write_text(texte + "\n", encoding="utf-8")
    conn.execute("UPDATE offres SET statut = 'lettre_prete' WHERE id = ?", (o["id"],))
    db.log(conn, o["id"], "lettre:generee", f"{mots} mots -> {fichier.name}")
    conn.commit()
    return fichier, f"{mots} mots"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=5)
    p.add_argument("--offre", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--sans-relecture", action="store_true",
                   help="ignore les skills de relecture, environ 8 fois moins "
                        "de jetons et 4 fois plus rapide")
    args = p.parse_args()

    # Une fois pour toutes, avant la boucle : sinon la meme cause s'affiche
    # en autant d'echecs qu'il y a d'offres.
    try:
        prompt_systeme()
    except RuntimeError as e:
        sys.exit(str(e))

    if args.sans_relecture:
        config.LETTRE_RELECTURE = False
    if config.LETTRE_RELECTURE:
        print("relecture par les skills active "
              "(--sans-relecture pour l'ignorer)\n")

    conn = db.connect()
    remises = purger_lettres_invalides(conn)
    if remises:
        print(f"{remises} lettre(s) enregistree(s) qui n'en etai(en)t pas : "
              "offre(s) remise(s) a rediger\n")
    if args.offre:
        offres = conn.execute("SELECT * FROM offres WHERE id = ?",
                              (args.offre,)).fetchall()
    else:
        # Une offre dont la reconnaissance a montre qu'elle n'accepte ni zone
        # de texte ni piece jointe n'a pas besoin de lettre : la rediger
        # couterait 65 000 jetons pour un fichier que personne ne lira.
        # NULL signifie "pas encore inspectee" : on la traite normalement.
        offres = conn.execute(
            "SELECT * FROM offres WHERE statut = 'a_traiter' "
            "AND NOT (COALESCE(lettre_texte, 1) = 0 AND COALESCE(lettre_fichier, 1) = 0) "
            "ORDER BY score DESC LIMIT ?", (args.limite,)).fetchall()

        ignorees = conn.execute(
            "SELECT COUNT(*) c FROM offres WHERE statut = 'a_traiter' "
            "AND lettre_texte = 0 AND lettre_fichier = 0").fetchone()[0]
        if ignorees:
            print(f"{ignorees} offre(s) ignoree(s) : leur formulaire n'accepte "
                  "aucune lettre" + '\n')

    print(f"{len(offres)} lettre(s) a produire\n")
    ok = echecs = 0
    for o in offres:
        nom = (o["entreprise"] or "?")[:30]
        try:
            fichier, info = generer(conn, o, args.force)
            print(f"  OK   #{o['id']:4} [{o['score']:3}] {nom:32} {info}")
            ok += 1
        except Exception as e:
            print(f"  ECHEC #{o['id']:4} {nom:32} {str(e)[:90]}")
            echecs += 1

    print(f"\n{ok} lettre(s) ecrite(s), {echecs} echec(s)")
    conn.close()


if __name__ == "__main__":
    main()
