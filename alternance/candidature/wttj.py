"""Candidature sur Welcome to the Jungle, via son formulaire interne.

Environ 60 % des offres WTTJ sont portees par leur propre ATS ("Welcome Kit").
Les autres redirigent vers l'ATS de l'employeur (Taleez, Thales, Docaposte...)
et sortent du perimetre de ce script : elles sont marquees ats_externe pour un
depot manuel, plutot que tentees en vain.

Le formulaire exige une session connectee, capturee une fois par
la commande connecter, et relue ici. Aucun mot de passe n'est manipule.

Champs releves sur le formulaire :
    firstname*  lastname*  email  phone*  location  subtitle*
    resume* (fichier)  media.website  media.linkedin  media.twitter
    cover_letter (textarea)  consent* (case, generalement deja cochee)

Sans --confirmer, le script remplit tout, capture l'ecran et n'envoie rien.

    python cli.py postuler-wttj --limite 3
    python cli.py postuler-wttj --limite 10 --confirmer
"""

import argparse
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from alternance import chemins
from alternance import config
from alternance import db
from alternance.candidature import cadence
from alternance.candidature import confirmation

BASE = config.RACINE
LETTRES = BASE / "lettres"
CV = chemins.CV
SESSION = BASE / "data" / "sessions" / "wttj.json"
CAPTURES = BASE / "data" / "captures"

HOTE_WTTJ = "welcometothejungle.com"
# Delai entre deux actions du navigateur, en millisecondes. Sans lui, six
# champs, le CV et le clic d'envoi partaient en moins de deux secondes. Le
# rythme entre deux candidatures, lui, est tenu par le module cadence.
LENTEUR_MS = 250


def slug(texte):
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_") or "entreprise"


def lettre_de(offre):
    return chemins.lire_lettre(offre)


def premier_visible(locator):
    """WTTJ duplique ses boutons (en-tete collant, pied de page) : .first tombe
    souvent sur une copie hors ecran dont le clic expire au bout de 30 s."""
    for i in range(locator.count()):
        el = locator.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


def remplir_si_vide(page, selecteur, valeur):
    """Le formulaire est pre-rempli depuis le profil WTTJ. On ne renseigne que
    les champs vides : le profil local, tenu a jour, fait autorite."""
    champ = premier_visible(page.locator(selecteur))
    if champ is None:
        return False
    try:
        if (champ.input_value() or "").strip():
            return True
        champ.fill(valeur)
        return True
    except Exception:
        return False


def refuser_cookies(page):
    """Ferme le bandeau Axeptio en refusant les cookies non essentiels.

    Le bandeau flotte au-dessus du formulaire et intercepte le clic sur le
    bouton d'envoi. On choisit "Non merci", l'option la plus protectrice, pas
    "OK pour moi".
    """
    for libelle in ("Non merci", "Refuser", "Tout refuser", "Continuer sans accepter"):
        bouton = premier_visible(page.locator(f"button:has-text('{libelle}')"))
        if bouton is not None:
            try:
                bouton.click()
                page.wait_for_timeout(600)
                return True
            except Exception:
                continue
    return False


def postuler(page, offre, lettre, confirmer):
    """Retourne (issue, detail). N'envoie que si confirmer est vrai."""
    reponse = page.goto(offre["url_candidature"], wait_until="domcontentloaded",
                        timeout=60000)
    page.wait_for_timeout(2200)
    if cadence.page_limitee(page, reponse.status if reponse else None):
        return "limite", "le site signale trop de requetes"
    refuser_cookies(page)

    bouton = premier_visible(page.locator(
        "a:has-text('Postuler'), button:has-text('Postuler')"))
    if bouton is None:
        return "externe", "aucun bouton Postuler"

    # Une offre portee par un ATS tiers expose un lien absolu hors domaine :
    # on le detecte avant de cliquer, pour ne pas quitter le site pour rien.
    href = bouton.get_attribute("href") or ""
    if href.startswith("http") and HOTE_WTTJ not in urlparse(href).netloc:
        return "externe", "redirige vers " + urlparse(href).netloc

    bouton.click()
    page.wait_for_timeout(3500)

    if "authenticate" in page.url or "signin" in page.url:
        return "erreur", "session expiree, relancer : python cli.py connecter wttj"

    try:
        page.wait_for_selector("input[name='firstname']", timeout=25000)
    except PWTimeout:
        # On a quitte le domaine : la redirection est averee.
        if HOTE_WTTJ not in urlparse(page.url).netloc:
            return "externe", "redirige vers " + urlparse(page.url).netloc
        if cadence.page_limitee(page):
            return "limite", "le site signale trop de requetes"
        # Sinon on est reste sur WTTJ sans voir le formulaire : lenteur,
        # bandeau de consentement, modale non ouverte, ou limitation muette.
        # Rien ne prouve que l'offre soit portee par un ATS tiers, donc on ne
        # la reclasse pas ; deux de suite font conclure a une limitation.
        return "absent", "formulaire non apparu sur WTTJ (reessayer)"

    nom = config.PROFIL["nom"].split()
    remplir_si_vide(page, "input[name='firstname']", nom[0])
    remplir_si_vide(page, "input[name='lastname']", " ".join(nom[1:]))
    remplir_si_vide(page, "input[name='email']", config.PROFIL["email"])
    remplir_si_vide(page, "input[name='phone']",
                    config.PROFIL["telephone_affiche"].replace(" ", ""))
    remplir_si_vide(page, "input[name='location']",
                    config.PROFIL["ville"] + ", France")
    # Facultatifs des deux cotes : le formulaire les accepte vides, et le
    # profil peut ne pas les renseigner. Les remplir avec une chaine vide
    # ecraserait ce que WTTJ a deja pre-rempli depuis le compte.
    if config.PROFIL.get("titre"):
        remplir_si_vide(page, "input[name='subtitle']", config.PROFIL["titre"])
    if config.PROFIL.get("linkedin"):
        remplir_si_vide(page, "input[name='media.linkedin']",
                        config.PROFIL["linkedin"])

    # Le CV est obligatoire et n'est jamais pre-rempli par le profil.
    # L'input natif est masque derriere une zone de depot stylee : on ne peut
    # donc PAS exiger sa visibilite. set_input_files fonctionne sur un input
    # cache, c'est le cas nominal sur la plupart des ATS.
    fichier = page.locator("input[name='resume']")
    if fichier.count() == 0:
        fichier = page.locator("input[type='file'][accept*='pdf']")
    if fichier.count() == 0:
        return "erreur", "champ CV introuvable"
    fichier.first.set_input_files(str(CV))
    page.wait_for_timeout(1800)

    lettre_champ = premier_visible(page.locator("textarea[name='cover_letter']"))
    if lettre_champ is not None:
        lettre_champ.fill(lettre)

    # Consentement RGPD : case obligatoire, deja active par defaut.
    consent = premier_visible(page.locator("input[name='consent']"))
    if consent is not None and not consent.is_checked():
        consent.check()

    # Le bandeau peut se rafficher au changement de vue : on repasse dessus
    # juste avant la capture et l'envoi.
    refuser_cookies(page)

    CAPTURES.mkdir(parents=True, exist_ok=True)
    capture = CAPTURES / ("wttj_" + str(offre["id"]) + "_" + slug(offre["entreprise"]) + ".png")
    page.screenshot(path=str(capture), full_page=True)

    if not confirmer:
        return "blanc", "rempli, non envoye (" + capture.name + ")"

    # Libelle reel du bouton : "J'envoie ma candidature !". On matche sur une
    # sous-chaine sans apostrophe, celle du site etant une apostrophe courbe.
    envoi = premier_visible(page.locator(
        "button:has-text('envoie ma candidature'), button[type='submit'], "
        "button:has-text('Envoyer')"))
    if envoi is None:
        return "erreur", "bouton d'envoi introuvable"
    envoi.scroll_into_view_if_needed()
    avant = confirmation.compter(page)
    envoi.click()

    if confirmation.attendre(page, avant):
        return "envoyee", "envoyee"
    apres = Path(str(capture).replace(".png", "_apres.png"))
    page.screenshot(path=str(apres))
    return "incertain", "a verifier : envoi clique, confirmation non detectee (" \
        + apres.name + ")"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=3)
    p.add_argument("--offre", type=int)
    p.add_argument("--confirmer", action="store_true")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    if not SESSION.exists():
        raise SystemExit("session absente : " + str(SESSION)
                         + "\nLancer : python cli.py connecter wttj")
    if not CV.exists():
        raise SystemExit("CV introuvable : " + str(CV))
    try:
        cadence.verifier("wttj")
    except cadence.SiteEnPause as e:
        raise SystemExit(str(e))

    conn = db.connect()
    if args.offre:
        # Meme une offre designee a la main n'est pas renvoyee.
        offres = conn.execute(
            "SELECT * FROM offres WHERE id = ? AND " + confirmation.JAMAIS_CANDIDATE,
            (args.offre,)).fetchall()
        if not offres:
            raise SystemExit("offre " + str(args.offre) + " introuvable, ou "
                             "candidature deja deposee : rien n'est renvoye")
    else:
        offres = conn.execute(
            "SELECT * FROM offres WHERE source = 'wttj' AND statut = 'lettre_prete' "
            "AND " + confirmation.JAMAIS_CANDIDATE
            + " ORDER BY matching DESC, score DESC LIMIT ?", (args.limite,)).fetchall()

    if not offres:
        raise SystemExit("aucune offre WTTJ avec lettre prete. "
                         "Lancer d'abord : python cli.py lettres")

    mode = "ENVOI REEL" if args.confirmer else "REPETITION A BLANC"
    print(mode + " - " + str(len(offres)) + " candidature(s)\n")

    compteurs = {"envoyee": 0, "externe": 0, "erreur": 0, "blanc": 0,
                 "incertain": 0, "absent": 0}
    surveillance = cadence.Surveillance("wttj")
    arret = None

    with sync_playwright() as pw:
        navigateur = pw.chromium.launch(headless=args.headless,
                                        slow_mo=LENTEUR_MS)
        contexte = navigateur.new_context(
            storage_state=str(SESSION), locale="fr-FR",
            viewport={"width": 1400, "height": 1000},
        )
        page = contexte.new_page()

        for i, o in enumerate(offres):
            nom = (o["entreprise"] or "?")[:26]
            lettre = lettre_de(o)
            if not lettre:
                print("  SAUTE  #" + str(o["id"]) + " " + nom + " : lettre absente")
                continue
            if not chemins.est_une_lettre(lettre):
                print("  SAUTE  #" + str(o["id"]) + " " + nom
                      + " : le texte enregistre n'est pas une lettre, a rediger")
                continue
            try:
                cadence.attendre("wttj")
                issue, detail = postuler(page, o, lettre, args.confirmer)
                # Le site limite : on s'arrete. Continuer prolonge la
                # suspension, et chaque offre suivante echouerait de toute
                # facon.
                if issue == "limite":
                    surveillance.limite(detail)
                elif issue == "absent":
                    surveillance.echec(detail)
                elif issue != "erreur":
                    surveillance.succes()
            except cadence.SiteEnPause as e:
                arret = str(e)
                print("  ARRET  " + arret)
                break
            except Exception as e:
                issue, detail = "erreur", type(e).__name__ + ": " + str(e)[:70]

            compteurs[issue] = compteurs.get(issue, 0) + 1
            print(f"  #{o['id']:4} [{o['matching']:3}%] {nom:28} {detail}")

            if issue == "externe":
                # L'URL et les pieces sont pretes : seul le depot reste manuel.
                conn.execute("UPDATE offres SET statut = 'ats_externe' WHERE id = ?",
                             (o["id"],))
                db.log(conn, o["id"], "wttj:externe", detail)
                conn.commit()

            if issue == "envoyee":
                confirmation.enregistrer_envoi(conn, o, "wttj_formulaire", CV)
            elif issue == "incertain":
                # Le formulaire est valide : l'offre ne doit plus jamais etre
                # reprise par un envoi, meme sans confirmation lue.
                confirmation.enregistrer_incertain(
                    conn, o, "wttj_formulaire", CV, detail.rsplit("(", 1)[-1][:-1])

        navigateur.close()

    print("\n  envoyees         : " + str(compteurs["envoyee"]))
    print("  ATS externe      : " + str(compteurs["externe"]) + " (depot manuel)")
    print("  remplies a blanc : " + str(compteurs["blanc"]))
    print("  a verifier       : " + str(compteurs["incertain"])
          + " (formulaire valide, confirmation non lue)")
    print("  erreurs          : " + str(compteurs["erreur"]))
    print("  formulaire absent: " + str(compteurs["absent"]))
    conn.close()

    if arret:
        raise SystemExit(arret)


if __name__ == "__main__":
    main()
