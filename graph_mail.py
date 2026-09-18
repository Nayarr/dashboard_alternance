"""Envoi de mail via Microsoft Graph, depuis l'adresse universitaire.

Authentification par device code : aucun mot de passe n'est stocke, seulement un
jeton dans token_cache.json (exclu du git). Le jeton de rafraichissement evite de
se reconnecter a chaque envoi.

Premiere utilisation :
    python graph_mail.py --connexion
"""

import base64
import json
import os
from pathlib import Path

import msal
import requests

BASE = Path(__file__).parent
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
            "Aucun jeton valide en cache. Lancer : python graph_mail.py --connexion"
        )

    flux = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flux:
        raise RuntimeError(
            f"Device flow refuse : {flux.get('error_description', flux)}\n"
            "Verifier que 'Autoriser les flux de client public' est active dans "
            "Authentification, cote portail Entra."
        )

    print("\n" + "=" * 62)
    print(flux["message"])
    print("=" * 62 + "\n")

    res = app.acquire_token_by_device_flow(flux)
    if "access_token" not in res:
        raise RuntimeError(f"Authentification echouee : "
                           f"{res.get('error_description', res)}")
    _sauver(cache)
    return res["access_token"]


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
    token = jeton(interactif=interactif)
    moi = qui_suis_je(token)
    if moi:
        print(f"Connecte : {moi.get('displayName')} "
              f"<{moi.get('mail') or moi.get('userPrincipalName')}>")
    else:
        print(f"Jeton obtenu (identite non lisible, portee limitee a l'envoi) — "
              f"expediteur declare : {os.environ.get('GRAPH_EXPEDITEUR')}")
    print(f"Jeton en cache dans {CACHE.name}")
