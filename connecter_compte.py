"""Ouvre un navigateur pour se connecter a un site, et enregistre la session.

    python connecter_compte.py wttj

ce script ne demande jamais d'appuyer sur Entree, ce qui permet de le lancer
depuis l'interface web ou personne n'est devant un terminal.

Le signal de fin est la FERMETURE DE LA FENETRE par l'utilisateur. C'est le
seul indice fiable. La version precedente s'arretait des qu'un cookie
contenant "session" apparaissait : sur Welcome to the Jungle, wttj_api_session_key
et gb_session_id sont poses des la premiere visite, donc la connexion etait
declaree reussie avant meme la saisie des identifiants, et une session anonyme
ecrasait la bonne.

Comme la fermeture detruit le contexte avant qu'on puisse le lire, l'etat est
photographie toutes les deux secondes : c'est la derniere photo qui est
conservee.

Aucun mot de passe n'est lu, saisi ni stocke : la connexion se fait dans la
fenetre, par toi. Seuls les cookies resultants sont conserves, dans data/,
deja exclu du git.
"""

import argparse
import json
import urllib.parse
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).parent
SESSIONS = BASE / "data" / "sessions"

SITES = {
    "wttj": {
        "libelle": "Welcome to the Jungle",
        "url": "https://www.welcometothejungle.com/fr/authenticate/signin",
        "role": "obligatoire pour deposer une candidature WTTJ",
    },
    "apec": {
        "libelle": "Apec",
        # /candidat.html cache son formulaire derriere un depliant : le champ
        # mot de passe n'y est pas visible, donc pas detectable. mon-espace
        # affiche le formulaire directement quand on n'est pas connecte.
        "url": "https://www.apec.fr/candidat/mon-espace.html",
        "role": "descriptions completes et depot de candidature",
    },
    "jobteaser": {
        "libelle": "JobTeaser",
        # /fr/users/sign_in ne propose que le selecteur d'etablissement.
        # Cette entree redirige vers connect.jobteaser.com, leur
        # fournisseur d'identite, qui porte le formulaire email.
        "url": ("https://www.jobteaser.com/users/auth/connect"
                "?organization_domain=public&ui_locales=fr"),
        "role": "depot des candidatures simplifiees",
    },
}

DELAI_MAX = 600       # 10 minutes avant abandon
DELAI_MINIMAL = 20    # avant ce delai, aucune saisie n'a pu aboutir :
                      # sans ce plancher, la rotation d'un cookie
                      # analytique suffirait a declarer la connexion
PAS = 2

# Widgets d'identite tierce, bloques a la source.
#
# Welcome to the Jungle injecte le script Google Identity Services au
# chargement de sa page de connexion. Dans un navigateur pilote, ce widget
# ouvre et referme une fenetre en boucle sans que l'utilisateur ait clique
# quoi que ce soit. Les fournisseurs OAuth refusant de toute facon ce type de
# navigateur, ces widgets ne peuvent rien apporter ici : on les empeche de se
# charger. La connexion par email et mot de passe reste entiere.
DOMAINES_OAUTH = [
    "accounts.google.com",
    "apis.google.com",
    "gsi/client",
    "www.linkedin.com/oauth",
    "platform.linkedin.com",
    "connect.facebook.net",
    "www.facebook.com/v",
    "appleid.cdn-apple.com",
    "appleid.apple.com/auth",
    "login.microsoftonline.com",
]

# Ne jamais bloquer : ce sont les fournisseurs d'identite des sites eux-memes,
# pas des widgets tiers. Les couper empecherait toute connexion.
DOMAINES_PROPRES = [
    "connect.jobteaser.com",
]


def chemin_session(cle):
    return SESSIONS / f"{cle}.json"


def etat(cle):
    """Ce que l'interface affiche : presence, age, nombre de cookies."""
    fichier = chemin_session(cle)
    if not fichier.exists():
        return {"connecte": False}
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
        cookies = len(donnees.get("cookies") or [])
    except (json.JSONDecodeError, OSError):
        cookies = 0
    age = (time.time() - fichier.stat().st_mtime) / 86400
    return {"connecte": True, "cookies": cookies, "age_jours": round(age, 1)}


def _empreinte(contexte):
    """Nom -> valeur.

    Comparer les seuls noms ne suffit pas : en se connectant, Welcome to the
    Jungle ne cree pas de cookie, il change la VALEUR de wttj_api_session_key,
    qui existe deja pour un visiteur anonyme. La connexion passait donc
    inapercue.
    """
    return {c["name"]: c.get("value") for c in contexte.cookies()}


def _formulaire(page):
    """Un champ mot de passe est-il present et visible ?

    Sert de temoin : present avant la connexion, absent apres. C'est le seul
    signal disponible sans connaitre chaque site, et il ne se declenche pas
    sur une banniere de cookies ou une redirection interne.
    """
    try:
        return page.evaluate("""() => [...document.querySelectorAll(
            'input[type=password]')].some(i => i.offsetParent !== null)""")
    except Exception:
        return False


def _changements(avant, apres):
    """Cookies apparus ou dont la valeur a change."""
    return {nom for nom, valeur in apres.items() if avant.get(nom) != valeur}


def main():
    parseur = argparse.ArgumentParser()
    parseur.add_argument("site", choices=sorted(SITES))
    parseur.add_argument("--url", help="remplace l'URL de connexion par defaut")
    arguments = parseur.parse_args()

    site = SITES[arguments.site]
    fichier = chemin_session(arguments.site)
    provisoire = fichier.with_suffix(".encours")
    SESSIONS.mkdir(parents=True, exist_ok=True)

    print(f"# Connexion a {site['libelle']}")
    print("# Une fenetre vient de s'ouvrir.")
    print("# 1. Connecte-toi avec EMAIL + MOT DE PASSE")
    print("#    Pas avec Google ni LinkedIn : ces fournisseurs refusent les")
    print("#    navigateurs pilotes, leur fenetre s'ouvre et se referme en boucle.")
    print("# 2. La connexion est detectee automatiquement.")
    print("#    Tu peux aussi fermer la fenetre toi-meme une fois connecte.")

    with sync_playwright() as pw:
        # Contexte PERSISTANT plutot que launch() + new_context().
        #
        # La forme classique cree deux choses : le navigateur, qui ouvre sa
        # propre fenetre par defaut, puis un contexte isole qui en ouvre une
        # seconde. Sur Windows la premiere apparait et se referme aussitot,
        # ce qui donne l'impression d'un onglet qui surgit puis disparait.
        # Retirer --start-maximized n'y changeait rien : les deux fenetres
        # viennent de la structure, pas des arguments.
        #
        # Un contexte persistant n'a qu'un seul processus et une seule fenetre.
        # Effet de bord utile : le profil survit entre deux lancements, donc
        # une reconnexion ne repart pas de zero.
        profil = BASE / "data" / "profils" / arguments.site
        profil.mkdir(parents=True, exist_ok=True)
        contexte = pw.chromium.launch_persistent_context(
            str(profil), headless=False,
            viewport={"width": 1440, "height": 900}, locale="fr-FR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"))
        navigateur = contexte

        def filtrer(route):
            url = route.request.url
            if any(propre in url for propre in DOMAINES_PROPRES):
                return route.continue_()
            if any(domaine in url for domaine in DOMAINES_OAUTH):
                return route.abort()
            return route.continue_()

        contexte.route("**/*", filtrer)

        # Le contexte persistant ouvre deja un onglet : le reutiliser, sinon on
        # se retrouve avec un about:blank orphelin a cote.
        page = contexte.pages[0] if contexte.pages else contexte.new_page()
        page.goto(arguments.url or site["url"],
                  wait_until="domcontentloaded", timeout=60000)

        page.wait_for_timeout(4000)
        depart = _empreinte(contexte)
        url_depart = page.url
        formulaire_present = _formulaire(page)
        print(f"# {len(depart)} cookies anonymes au chargement")
        if not formulaire_present:
            print("# ATTENTION : aucun champ mot de passe sur cette page.")
            print("# La detection automatique sera moins sure : ferme la fenetre")
            print("# toi-meme une fois connecte.")
        print("# En attente de ta connexion...")

        ecoule = 0
        modifies = set()
        ferme = False
        stable = 0
        while ecoule < DELAI_MAX:
            time.sleep(PAS)
            ecoule += PAS

            if page.is_closed() or not contexte.pages:
                print("# fenetre fermee")
                ferme = True
                break

            try:
                contexte.storage_state(path=str(provisoire))
                modifies = _changements(depart, _empreinte(contexte))
                url_courante = page.url
            except Exception:
                break

            # Le signal, c'est la DISPARITION DU FORMULAIRE : un champ mot de
            # passe visible au depart qui n'existe plus signifie que le site a
            # remplace l'ecran de connexion par l'espace personnel.
            #
            # La version precedente se contentait d'un changement de cookies et
            # d'URL. Sur l'Apec, la banniere de consentement modifie des cookies
            # et une redirection interne change l'URL : une connexion inexistante
            # a ete declaree reussie, et la session anonyme enregistree.
            hote_attendu = urllib.parse.urlparse(url_depart).netloc
            sur_le_site = urllib.parse.urlparse(url_courante).netloc.endswith(
                hote_attendu.split(".")[-2] + "." + hote_attendu.split(".")[-1])
            connecte = (formulaire_present and not _formulaire(page)) if formulaire_present else False

            if ecoule >= DELAI_MINIMAL and modifies and sur_le_site and connecte:
                stable += 1
                if stable >= 2:
                    print(f"# connexion detectee ({len(modifies)} cookies modifies)")
                    time.sleep(2)
                    contexte.storage_state(path=str(provisoire))
                    modifies = _changements(depart, _empreinte(contexte))
                    break
            else:
                stable = 0

            if ecoule % 30 == 0:
                print(f"# en attente ({ecoule}s, {len(modifies)} cookies modifies)")

        if not ferme:
            try:
                contexte.storage_state(path=str(provisoire))
                modifies = _changements(depart, _empreinte(contexte))
            except Exception:
                pass
        try:
            navigateur.close()
        except Exception:
            pass

    if not provisoire.exists():
        print("# ECHEC : rien n'a pu etre enregistre")
        sys.exit(1)

    if ecoule >= DELAI_MAX:
        provisoire.unlink(missing_ok=True)
        print("# ECHEC : delai depasse sans fermeture de la fenetre")
        sys.exit(1)

    # Aucun cookie apparu apres le chargement : la connexion n'a pas eu lieu.
    # On refuse d'ecraser la session existante, qui elle fonctionne peut-etre.
    # C'est exactement l'accident survenu avec la detection precedente.
    if not modifies:
        provisoire.unlink(missing_ok=True)
        print("# ECHEC : aucun cookie n'a change depuis le chargement de la page.")
        print("# La connexion n'a pas abouti, la session existante est intacte.")
        sys.exit(1)

    if fichier.exists():
        shutil.copy2(fichier, fichier.with_suffix(".precedent"))

    provisoire.replace(fichier)
    total = len(json.loads(fichier.read_text(encoding="utf-8")).get("cookies") or [])
    print(f"# OK session enregistree : {total} cookies, "
          f"{len(modifies)} modifies par la connexion")


if __name__ == "__main__":
    main()
