"""Parcours complet de l'application, sans rien envoyer ni rien ecrire.

    python outils/test_bout_en_bout.py
    python outils/test_bout_en_bout.py --sans-reseau   # ignore les collectes

Cinq etages sont verifies, dans l'ordre du pipeline :

    1. COLLECTE      chaque connecteur repond et produit des offres conformes
    2. SCORING       chaque offre traverse les filtres sans exception
    3. RECONNAISSANCE chaque canal sait dire ce que son formulaire accepte
    4. DEPOT         chaque canal se prepare a blanc, sans jamais envoyer
    5. INTERFACE     les routes repondent et rejettent les entrees invalides

Aucun --confirmer n'est passe nulle part, aucune ligne n'est ecrite en base,
aucun jeton Claude n'est consomme : les lettres deja redigees sont reutilisees.
"""

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alternance import chemins  # noqa: E402
from alternance import config  # noqa: E402
from alternance import db  # noqa: E402
from alternance import filtres as filters  # noqa: E402

# Champs qu'une offre doit porter pour traverser le pipeline sans surprise.
#
# distance_km n'en fait PAS partie : c'est une valeur derivee, recalculee par
# sourcing.enrichir a partir de latitude/longitude. Trois connecteurs la
# renseignent quand meme (apec, jobteaser, service_public), deux non (lba,
# wttj). Les deux fonctionnent, mais l'exiger ferait echouer des connecteurs
# corrects.
CHAMPS_REQUIS = ("uid", "source", "genre", "intitule", "entreprise", "lieu",
                 "description", "url_candidature", "contrat_type", "latitude",
                 "longitude")

resultats = []


def verifie(etage, libelle, fonction):
    """Execute une verification et retient son verdict."""
    debut = time.time()
    try:
        detail = fonction()
        etat = "ok"
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        etat = "ECHEC"
        if "--trace" in sys.argv:
            traceback.print_exc()
    duree = time.time() - debut
    resultats.append((etage, libelle, etat, detail, duree))
    marque = "  ok  " if etat == "ok" else " ECHEC"
    print(f"{marque} [{duree:5.1f}s] {libelle:34} {str(detail)[:60]}")
    return etat == "ok"


# --------------------------------------------------------------- 1. COLLECTE

def controle_offres(offres, source):
    """Une collecte est valable si ses offres portent tous les champs."""
    if not offres:
        return "aucune offre (source vide ou indisponible)"
    manquants = set()
    for o in offres[:20]:
        manquants |= {c for c in CHAMPS_REQUIS if c not in o}
    if manquants:
        raise AssertionError(f"champs absents : {sorted(manquants)}")
    sans_uid = sum(1 for o in offres if not o.get("uid"))
    if sans_uid:
        raise AssertionError(f"{sans_uid} offres sans uid (INSERT OR IGNORE les avalerait)")
    doublons = len(offres) - len({o["uid"] for o in offres})
    geo = sum(1 for o in offres if o.get("latitude"))
    return (f"{len(offres)} offres, {geo} geolocalisees, {doublons} uid en double")


def etage_collecte():
    from alternance.sources import apec, jobteaser, lba, service_public, wttj

    verifie("collecte", "wttj", lambda: controle_offres(wttj.collecte(), "wttj"))
    verifie("collecte", "apec", lambda: controle_offres(apec.collecter(), "apec"))
    verifie("collecte", "jobteaser",
            lambda: controle_offres(jobteaser.collecte(), "jobteaser"))
    verifie("collecte", "service_public",
            lambda: controle_offres(service_public.collecte(avec_description=False),
                                    "service_public"))
    verifie("collecte", "lba",
            lambda: controle_offres(lba.collecte(inclure_spontanees=True), "lba"))


# ---------------------------------------------------------------- 2. SCORING

def etage_scoring(conn):
    sources = [r["source"] for r in conn.execute(
        "SELECT DISTINCT source FROM offres")]

    for source in sources:
        def scorer(source=source):
            lignes = conn.execute(
                "SELECT * FROM offres WHERE source = ? LIMIT 30", (source,)).fetchall()
            statuts = set()
            for ligne in lignes:
                o = dict(ligne)
                flag, raison = filters.detecte_ecole(
                    o["entreprise"], o["intitule"], o["description"])
                tech, raison_tech = filters.est_mission_technique(
                    o["intitule"], o["description"], o["genre"])
                score, detail = filters.score_offre(o)
                matching, _ = filters.pourcentage_matching(detail, o["genre"])
                statuts.add(filters.statut_initial(
                    score, flag, tech, filters.doute(o, raison, raison_tech),
                    filters.a_un_canal(o), matching))
                if not 0 <= matching <= 100:
                    raise AssertionError(f"matching hors bornes : {matching}")
            return f"{len(lignes)} offres, statuts : {sorted(statuts)}"
        verifie("scoring", source, scorer)

    # Les lignes sqlite3.Row doivent passer telles quelles
    ligne = conn.execute("SELECT * FROM offres LIMIT 1").fetchone()
    verifie("scoring", "sqlite3.Row accepte",
            lambda: f"est_stage={filters.est_stage(ligne)}, "
                    f"canal={filters.a_un_canal(ligne)}")


# --------------------------------------------------------- 3. RECONNAISSANCE

def etage_reconnaissance(conn):
    from alternance.candidature import reconnaissance as reco
    from playwright.sync_api import sync_playwright

    for source in reco.SOURCES:
        ligne = conn.execute(
            "SELECT id, entreprise, url_candidature FROM offres "
            "WHERE source = ? AND statut IN ('a_traiter','lettre_prete') LIMIT 1",
            (source,)).fetchone()
        if ligne is None:
            resultats.append(("reconnaissance", source, "ignore",
                              "aucune offre dans le vivier", 0))
            print(f"  --   [  0.0s] {source:34} aucune offre a inspecter")
            continue

        def inspecter(source=source, offre=dict(ligne)):
            session = config.BASE_DIR / "data" / "sessions" / f"{source}.json"
            with sync_playwright() as pw:
                nav = pw.chromium.launch(headless=True)
                ctx = nav.new_context(
                    storage_state=str(session) if session.exists() else None,
                    viewport={"width": 1440, "height": 950}, locale="fr-FR",
                    user_agent=reco.NAVIGATEUR)
                page = ctx.new_page()
                try:
                    releve, souci = reco.INSPECTEURS[source](page, offre)
                finally:
                    nav.close()
            if releve is None:
                return f"formulaire inaccessible ({souci})"
            return (f"texte={releve['lettre_texte']} "
                    f"fichier={releve['lettre_fichier']} zones={releve['zones']}")

        verifie("reconnaissance", source, inspecter)


# ------------------------------------------------------------------ 4. DEPOT

def etage_depot(conn):
    # --- LBA : formulaire public, rempli sans etre envoye -------------------
    def lba():
        import subprocess
        r = subprocess.run(
            [sys.executable, "cli.py", "postuler-lba", "--limite", "1", "--headless"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(config.BASE_DIR), timeout=300)
        if "reellement envoyee" not in r.stdout:
            raise AssertionError((r.stdout + r.stderr)[-200:])
        ligne = [l for l in r.stdout.splitlines() if "rempli" in l or "ECHEC" in l]
        return ligne[0].strip()[:70] if ligne else "aucune offre a traiter"
    verifie("depot", "lba (repetition a blanc)", lba)

    # --- WTTJ : formulaire interne, session requise -------------------------
    def wttj():
        import subprocess
        r = subprocess.run(
            [sys.executable, "postuler_wttj.py", "--limite", "1", "--headless"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(config.BASE_DIR), timeout=400)
        if "envoyees" not in r.stdout:
            raise AssertionError((r.stdout + r.stderr)[-200:])
        ligne = [l for l in r.stdout.splitlines() if "rempli" in l or "externe" in l]
        return ligne[0].strip()[:70] if ligne else "aucune offre a traiter"
    verifie("depot", "wttj (repetition a blanc)", wttj)

    # --- Email : canal du service public ------------------------------------
    def courriel():
        from alternance.courrier import envoi as envoyer
        ligne = conn.execute(
            "SELECT * FROM offres WHERE contact_email IS NOT NULL "
            "AND id IN (SELECT id FROM offres) ORDER BY matching DESC").fetchall()
        candidates = [dict(r) for r in ligne
                      if chemins.lettre_pdf(dict(r)).exists()]
        if not candidates:
            return "aucune offre avec adresse ET pieces generees"
        o = candidates[0]
        dossier = chemins.dossier_candidature(o)
        pieces = [dossier / n for n in envoyer.PIECES]
        manquantes = [p.name for p in pieces if not p.exists()]
        if manquantes:
            raise AssertionError(f"pieces manquantes : {manquantes}")
        objet = envoyer.objet_mail(o)
        corps = envoyer.corps_mail(o, envoyer.lire_lettre(dossier))
        if not objet or len(corps) < 100:
            raise AssertionError("objet ou corps vide")
        poids = sum(p.stat().st_size for p in pieces) // 1024
        return f"#{o['id']} -> {o['contact_email']}, {poids} Ko, apercu seul"
    verifie("depot", "email (service public)", courriel)


# -------------------------------------------------------------- 5. INTERFACE

def etage_interface():
    from alternance.interface import serveur as dashboard
    c = dashboard.app.test_client()

    def lectures():
        codes = {}
        for vue in dashboard.VUES:
            r = c.get(f"/api/offres?statut={vue['cle']}")
            codes[vue["cle"]] = r.status_code
        mauvais = {k: v for k, v in codes.items() if v != 200}
        if mauvais:
            raise AssertionError(f"vues en erreur : {mauvais}")
        return f"{len(codes)} vues, toutes en 200"
    verifie("interface", "vues d'offres", lectures)

    def contexte():
        for url in ("/api/contexte", "/api/parametres", "/api/comptes", "/api/tache"):
            if c.get(url).status_code != 200:
                raise AssertionError(f"{url} en erreur")
        return "contexte, parametres, comptes, tache"
    verifie("interface", "routes de service", contexte)

    def rejets():
        cas = [
            (c.post("/api/offre/999999/statut", json={"statut": "a_traiter"}), 404),
            (c.post("/api/offre/1/statut", json={"statut": "xxx"}), 400),
            (c.post("/api/parametres", json={"seuil_matching": 500}), 400),
            (c.post("/api/parametres", json={"romes": ["ZZ"]}), 400),
            (c.post("/api/parametres/jeton", json={"jeton": "bidon"}), 400),
            (c.get("/api/offres?statut=inexistant"), 400),
        ]
        faux = [f"attendu {attendu} recu {r.status_code}"
                for r, attendu in cas if r.status_code != attendu]
        if faux:
            raise AssertionError(faux)
        return f"{len(cas)} entrees invalides rejetees correctement"
    verifie("interface", "entrees invalides", rejets)


# ------------------------------------------------------------------- rapport

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sans-reseau", action="store_true",
                   help="ignore les collectes et la reconnaissance")
    p.add_argument("--trace", action="store_true")
    args = p.parse_args()

    conn = db.connect()
    print("=" * 78)
    print("PARCOURS COMPLET — DRY RUN, aucun envoi, aucune ecriture")
    print("=" * 78)

    if not args.sans_reseau:
        print("\n--- 1. COLLECTE ---")
        etage_collecte()

    print("\n--- 2. SCORING ---")
    etage_scoring(conn)

    if not args.sans_reseau:
        print("\n--- 3. RECONNAISSANCE ---")
        etage_reconnaissance(conn)

        print("\n--- 4. DEPOT ---")
        etage_depot(conn)

    print("\n--- 5. INTERFACE ---")
    etage_interface()

    print("\n" + "=" * 78)
    echecs = [r for r in resultats if r[2] == "ECHEC"]
    ignores = [r for r in resultats if r[2] == "ignore"]
    print(f"{len(resultats)} verifications | {len(echecs)} echec(s) | "
          f"{len(ignores)} ignoree(s) | {sum(r[4] for r in resultats):.0f}s")
    for etage, libelle, _e, detail, _d in echecs:
        print(f"  ECHEC {etage}/{libelle} : {str(detail)[:90]}")
    conn.close()
    sys.exit(1 if echecs else 0)


if __name__ == "__main__":
    main()
