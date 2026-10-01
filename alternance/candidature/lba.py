"""Candidature spontanee sur La Bonne Alternance, via le formulaire du site.

Le formulaire public ne demande ni compte ni CAPTCHA :
    applicant_last_name / applicant_first_name / applicant_email / applicant_phone
    applicant_inscription_formation (radio "Je suis deja inscrit(e) en formation")
    applicant_message (la lettre)  +  input[type=file] (le CV)
    bouton "J'envoie ma candidature spontanee"

Sans --confirmer, le script remplit tout, prend une capture et n'envoie pas.

    python cli.py postuler-lba --limite 3                # repetition a blanc
    python cli.py postuler-lba --limite 3 --confirmer    # envoi reel
    python cli.py postuler-lba --limite 20 --confirmer --headless
"""

import argparse
import re
import time
import unicodedata
from pathlib import Path

from playwright.sync_api import sync_playwright

from alternance import chemins
from alternance import config
from alternance import db
from alternance.candidature import confirmation

BASE = config.RACINE
LETTRES = BASE / "lettres"
CV = chemins.CV
CAPTURES = BASE / "data" / "captures"

PAUSE_ENTRE = 8          # secondes entre deux candidatures
BOUTON_OUVRIR = "button:has-text('Candidature simplifiée')"
BOUTON_ENVOYER = "button:has-text(\"J'envoie ma candidature\")"


def premier_visible(locator):
    """Le site duplique ses boutons dans un en-tete collant hors ecran :
    .first tombe sur la copie invisible et le clic expire."""
    for i in range(locator.count()):
        el = locator.nth(i)
        if el.is_visible():
            return el
    return None


def slug(texte):
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_") or "entreprise"


def lettre_de(offre):
    return chemins.lire_lettre(offre)


def postuler(page, offre, lettre, confirmer):
    """Remplit et, si confirmer, envoie. Retourne un libelle de resultat."""
    page.goto(offre["url_candidature"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)

    # Le menu de navigation s'ouvre parfois deplie et intercepte les clics
    fermer = premier_visible(page.locator("button:has-text('Fermer')"))
    if fermer:
        fermer.click()
        page.wait_for_timeout(400)

    ouvrir = premier_visible(page.locator(BOUTON_OUVRIR))
    if ouvrir is None:
        return "pas de formulaire sur la page"
    ouvrir.scroll_into_view_if_needed()
    ouvrir.click()
    page.wait_for_selector("#applicant_email", timeout=20000)

    nom_complet = config.PROFIL["nom"].split()
    page.fill("#applicant_first_name", nom_complet[0])
    page.fill("#applicant_last_name", " ".join(nom_complet[1:]))
    page.fill("#applicant_email", config.PROFIL["email"])
    page.fill("#applicant_phone", config.PROFIL["telephone_affiche"].replace(" ", ""))

    # Le candidat est deja inscrit en formation. Ce clic fait apparaitre
    # deux listes supplementaires, absentes du DOM avant lui.
    deja = page.get_by_text("Je suis déjà inscrit", exact=False).first
    if deja.count():
        deja.click()
        page.wait_for_timeout(900)

    # "Duree du contrat souhaitee" : optionnelle, mais la renseigner evite
    # qu'un recruteur ecarte le dossier faute d'information.
    for select in page.locator("select").all():
        if not select.is_visible():
            continue
        options = [o.strip() for o in select.locator("option").all_inner_texts()]
        if "12 mois" in options:
            select.select_option(label="12 mois")
            break

    page.fill("#applicant_message", lettre)
    page.set_input_files("input[type=file]", str(CV))

    CAPTURES.mkdir(parents=True, exist_ok=True)
    capture = CAPTURES / f"{offre['id']}_{slug(offre['entreprise'])}.png"
    page.screenshot(path=str(capture), full_page=True)

    if not confirmer:
        return f"rempli, non envoye (capture {capture.name})"

    bouton = premier_visible(page.locator(BOUTON_ENVOYER))
    if bouton is None:
        return "bouton d'envoi introuvable"
    bouton.scroll_into_view_if_needed()
    avant = confirmation.compter(page)
    bouton.click()
    if confirmation.attendre(page, avant):
        return "envoyee"
    apres = Path(str(capture).replace(".png", "_apres.png"))
    page.screenshot(path=str(apres))
    return f"a verifier : envoi clique, confirmation non detectee ({apres.name})"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=3)
    p.add_argument("--offre", type=int)
    p.add_argument("--confirmer", action="store_true")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    if not CV.exists():
        raise SystemExit(f"CV introuvable : {CV}")

    conn = db.connect()
    if args.offre:
        # Meme une offre designee a la main n'est pas renvoyee : sans ce
        # garde-fou, --offre --confirmer postulait une seconde fois.
        offres = conn.execute(
            "SELECT * FROM offres WHERE id = ? AND " + confirmation.JAMAIS_CANDIDATE,
            (args.offre,)).fetchall()
        if not offres:
            raise SystemExit(f"offre {args.offre} introuvable, ou candidature "
                             "deja deposee : rien n'est renvoye")
    else:
        offres = conn.execute(
            "SELECT * FROM offres WHERE source = 'lba' AND recipient_id IS NOT NULL "
            "AND statut = 'lettre_prete' AND " + confirmation.JAMAIS_CANDIDATE
            + " ORDER BY score DESC LIMIT ?",
            (args.limite,)).fetchall()

    if not offres:
        raise SystemExit("aucune offre avec lettre prete. Lancer : python cli.py lettres")

    mode = "ENVOI REEL" if args.confirmer else "REPETITION A BLANC"
    print(f"{mode} — {len(offres)} candidature(s)\n")

    envoyees = a_verifier = 0
    with sync_playwright() as pw:
        navigateur = pw.chromium.launch(headless=args.headless)
        contexte = navigateur.new_context(
            viewport={"width": 1400, "height": 1000},
            locale="fr-FR",
        )
        page = contexte.new_page()

        for i, o in enumerate(offres):
            nom = (o["entreprise"] or "?")[:28]
            lettre = lettre_de(o)
            if not lettre:
                print(f"  SAUTE #{o['id']:4} {nom:30} lettre absente")
                continue
            if not chemins.est_une_lettre(lettre):
                print(f"  SAUTE #{o['id']:4} {nom:30} le texte enregistre "
                      "n'est pas une lettre, a rediger")
                continue
            try:
                resultat = postuler(page, o, lettre, args.confirmer)
            except Exception as e:
                resultat = f"ERREUR {type(e).__name__}: {str(e)[:80]}"

            print(f"  #{o['id']:4} [{o['score']:3}] {nom:30} {resultat}")

            if resultat == "envoyee":
                confirmation.enregistrer_envoi(conn, o, "lba_formulaire", CV)
                envoyees += 1
            elif resultat.startswith("a verifier"):
                # Le formulaire est valide : l'offre ne doit plus jamais etre
                # reprise par un envoi, meme sans confirmation lue.
                confirmation.enregistrer_incertain(
                    conn, o, "lba_formulaire", CV, resultat.rsplit("(", 1)[-1][:-1])
                a_verifier += 1

            if i < len(offres) - 1:
                time.sleep(PAUSE_ENTRE)

        navigateur.close()

    print(f"\n{envoyees} candidature(s) reellement envoyee(s)")
    if a_verifier:
        print(f"{a_verifier} envoi(s) a verifier : formulaire valide, mais le "
              "site n'a pas affiche de confirmation. Onglet « Envoi a verifier ».")
    conn.close()


if __name__ == "__main__":
    main()
