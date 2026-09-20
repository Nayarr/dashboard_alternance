"""Envoi de mail via Microsoft Graph, depuis l'adresse universitaire.

Authentification par device code : aucun mot de passe n'est stocke, seulement un
jeton dans token_cache.json (exclu du git). Le jeton de rafraichissement evite de
se reconnecter a chaque envoi.

Premiere utilisation :
    python cli.py graph --connexion
"""

import base64
import json
import os
import time
from pathlib import Path

import msal
import requests

BASE = Path(__file__).resolve().parent.parent.parent
CACHE = BASE / "token_cache.json"
# User.Read sert uniquement a confirmer sur quel compte on est connecte : sans
# lui, le jeton Mail.Send seul renvoie 403 sur /me.
SCOPES = ["Mail.Send", "User.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"


def _application():
    cache = msal.SerializableTokenCache()
    if CACHE.exists():
        cache.deserialize(CACHE.read_text(encoding="utf-8"))

    app = msal.PublicClientApplication(
        os.environ["GRAPH_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}",
        token_cache=cache,
    )
    return app, cache


def _sauver(cache):
    if cache.has_state_changed:
        CACHE.write_text(cache.serialize(), encoding="utf-8")


def jeton(interactif=True):
    """Retourne un access token, en reutilisant le cache si possible."""
    app, cache = _application()

    comptes = app.get_accounts()
    if comptes:
        res = app.acquire_token_silent(SCOPES, account=comptes[0])
        if res and "access_token" in res:
            _sauver(cache)
            return res["access_token"]

    if not interactif:
        raise RuntimeError(
            "Aucun jeton valide en cache. Lancer : python cli.py graph --connexion"
        )

    flux = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flux:
        raise RuntimeError(
            f"Device flow refuse : {flux.get('error_description', flux)}\n"
            "Verifier que 'Autoriser les flux de client public' est active dans "
            "Authentification, cote portail Entra."
        )

    # Ligne lisible par une machine, en plus du message pour un humain :
    # l'interface web lance ce script en tache de fond et doit pouvoir extraire
    # le code de son journal pour l'afficher. Sans elle, il faudrait analyser
    # une phrase en anglais dont le libelle depend du tenant.
    print(f"# DEVICE_CODE {flux['user_code']} "
          f"{flux.get('verification_uri', 'https://microsoft.com/devicelogin')}")
    print("=" * 62)
    print(flux["message"])
    print("=" * 62)

    res = app.acquire_token_by_device_flow(flux)
    if "access_token" not in res:
        raise RuntimeError(f"Authentification echouee : "
                           f"{res.get('error_description', res)}")
    _sauver(cache)
    return res["access_token"]


def etat():
    """Ce que l'interface affiche. Ne lit aucun jeton, ne fait aucun appel reseau.

    `configure` distingue deux absences qui n'appellent pas la meme reponse :
    pas d'application declaree cote Entra, ou application declaree mais compte
    jamais connecte.
    """
    configure = bool(os.environ.get("GRAPH_CLIENT_ID")
                     and os.environ.get("GRAPH_TENANT_ID"))
    if not configure or not CACHE.exists():
        return {"connecte": False, "compte": None, "configure": configure}

    try:
        app, _ = _application()
        comptes = app.get_accounts()
    except Exception:
        comptes = []

    if not comptes:
        return {"connecte": False, "compte": None, "configure": True}

    age = (time.time() - CACHE.stat().st_mtime) / 86400
    return {"connecte": True, "configure": True,
            "compte": comptes[0].get("username"),
            "age_jours": round(age, 1)}


def oublier():
    """Efface le cache local. Ne revoque rien cote Microsoft.

    Le consentement se retire sur myapps.microsoft.com : dit explicitement
    plutot que laisse croire qu'un bouton local suffit.
    """
    CACHE.unlink(missing_ok=True)
    return True


def qui_suis_je(token):
    """Identite du compte connecte. Renvoie None si le jeton ne le permet pas :
    c'est une confirmation de confort, jamais un bloquant pour l'envoi."""
    r = requests.get(f"{GRAPH}/me", headers={"Authorization": f"Bearer {token}"},
                     timeout=30)
    if r.status_code == 403:
        return None
    r.raise_for_status()
    return r.json()


def envoyer(destinataire, objet, corps, pieces=(), reply_to=None,
            enregistrer_dans_envoyes=True):
    """Envoie un mail. `pieces` est une liste de Path vers des fichiers."""
    token = jeton(interactif=False)

    jointes = []
    for chemin in pieces:
        chemin = Path(chemin)
        jointes.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": chemin.name,
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(chemin.read_bytes()).decode(),
        })

    message = {
        "subject": objet,
        "body": {"contentType": "Text", "content": corps},
        "toRecipients": [{"emailAddress": {"address": destinataire}}],
    }
    if jointes:
        message["attachments"] = jointes
    if reply_to:
        message["replyTo"] = [{"emailAddress": {"address": reply_to}}]

    r = requests.post(
        f"{GRAPH}/me/sendMail",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        data=json.dumps({"message": message,
                         "saveToSentItems": enregistrer_dans_envoyes}),
        timeout=120,
    )
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Graph a refuse l'envoi ({r.status_code}) : {r.text[:400]}")
    return True


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")

    interactif = "--connexion" in sys.argv

    manquantes = [v for v in ("GRAPH_CLIENT_ID", "GRAPH_TENANT_ID")
                  if not os.environ.get(v)]
    if manquantes:
        sys.exit(f"{' et '.join(manquantes)} absent(es) du .env. Voir la "
                 "section \"Envoyer par email\" du README.")

    # Sans --connexion, ce script sert a repondre a une seule question : quel
    # compte est connecte. Une pile d'appels Python n'y repond pas.
    try:
        token = jeton(interactif=interactif)
    except RuntimeError as e:
        sys.exit(str(e))

    moi = qui_suis_je(token)
    if moi:
        print(f"Connecte : {moi.get('displayName')} "
              f"<{moi.get('mail') or moi.get('userPrincipalName')}>")
    else:
        print(f"Jeton obtenu (identite non lisible, portee limitee a l'envoi) — "
              f"expediteur declare : {os.environ.get('GRAPH_EXPEDITEUR')}")
    print(f"Jeton en cache dans {CACHE.name}")
    print("# OK compte connecte")
