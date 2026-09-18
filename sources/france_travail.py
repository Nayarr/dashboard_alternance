"""Source France Travail (API Offres d'emploi v2).

Complement de LBA : LBA agrege deja une partie des offres France Travail, mais
l'API directe donne acces a l'ensemble du stock et a des filtres plus fins.

Necessite que l'application soit souscrite a l'API "Offres d'emploi v2" sur
francetravail.io. Tant que ce n'est pas le cas, l'auth renvoie invalid_client.
"""

import hashlib
import os
import re
import time

import requests

import config

# France Travail place parfois une phrase entiere dans contact.courriel :
# "Pour postuler, utiliser le lien suivant : https://..." . Sans validation,
# ce texte est pris pour une adresse et l'offre parait candidatable par mail.
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)


def _email_valide(valeur):
    valeur = (valeur or "").strip()
    return valeur if EMAIL.match(valeur) else None

TOKEN_URL = ("https://entreprise.francetravail.fr/connexion/oauth2/access_token"
             "?realm=%2Fpartenaire")
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# Le filtre alternance passe par "natureContrat", PAS par "typeContrat" :
# typeContrat n'accepte que CDI/CDD/MIS... et renvoie 400 sur E2.
#   E2 = contrat d'apprentissage
#   FS = contrat de professionnalisation
# Les valeurs sont interrogees une par une, la forme "E2,FS" n'est pas garantie.
NATURES_CONTRAT = ["E2", "FS"]

_token = {"valeur": None, "expire_a": 0}


def _access_token():
    if _token["valeur"] and time.time() < _token["expire_a"] - 60:
        return _token["valeur"]

    cid = os.environ.get("FT_CLIENT_ID")
    secret = os.environ.get("FT_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("FT_CLIENT_ID / FT_CLIENT_SECRET absents du .env")

    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": cid,
            "client_secret": secret,
            "scope": "api_offresdemploiv2 o2dsoffre",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"Auth France Travail refusee ({r.status_code}) : {r.text[:200]}\n"
            "Verifier que l'application est bien souscrite a l'API "
            "'Offres d'emploi v2' sur francetravail.io."
        )
    data = r.json()
    _token["valeur"] = data["access_token"]
    _token["expire_a"] = time.time() + data.get("expires_in", 1500)
    return _token["valeur"]


def _uid(entreprise, intitule, lieu):
    brut = f"ft|{(entreprise or '').lower()}|{(intitule or '').lower()}|{(lieu or '').lower()}"
    return hashlib.sha1(brut.encode()).hexdigest()[:16]


_CACHE_GEO = {}


def _position(lieu, libelle):
    """Coordonnees de l'offre, geocodees si l'API n'en fournit pas.

    France Travail expose des champs latitude/longitude mais les laisse vides
    sur la quasi-totalite des annonces. Sans coordonnees, l'axe proximite vaut
    zero, soit 15 % de l'adequation perdus : aucune offre ne franchissait le
    seuil alors que la plupart sont dans Paris intra-muros. On retombe donc sur
    le libelle, du type "75 - Paris 9", geocode via l'API Adresse.
    """
    if lieu.get("latitude") and lieu.get("longitude"):
        return {"latitude": float(lieu["latitude"]),
                "longitude": float(lieu["longitude"])}

    ville = re.sub(r"^\s*\d+\s*-\s*", "", libelle or "").strip()
    if not ville:
        return {"latitude": None, "longitude": None}

    if ville not in _CACHE_GEO:
        import geocode
        try:
            r = geocode.geocode(ville, limit=1)
            _CACHE_GEO[ville] = ((r[0]["lat"], r[0]["lon"]) if r else (None, None))
        except Exception:
            # Une panne du geocodeur ne doit pas vider la collecte : l'offre
            # est conservee, simplement sans note de proximite.
            _CACHE_GEO[ville] = (None, None)
        time.sleep(0.2)

    lat, lon = _CACHE_GEO[ville]
    return {"latitude": lat, "longitude": lon}


def _map(o):
    ent = o.get("entreprise") or {}
    lieu = o.get("lieuTravail") or {}
    contact = o.get("contact") or {}
    entreprise = ent.get("nom") or ""
    libelle = lieu.get("libelle") or ""

    duree = None
    tec = (o.get("typeContratLibelle") or "") + " " + (o.get("dureeTravailLibelle") or "")
    for n in (12, 24, 36):
        if f"{n} mois" in tec.lower():
            duree = n
            break

    return {
        "uid": _uid(entreprise, o.get("intitule"), libelle),
        "source": "france_travail",
        "source_id": o.get("id"),
        "partner_label": "France Travail",
        "genre": "offre",
        "entreprise": entreprise,
        "siret": None,
        "taille": o.get("trancheEffectifEtab"),
        "naf": o.get("secteurActiviteLibelle"),
        "site_web": ent.get("url"),
        "intitule": o.get("intitule"),
        "description": o.get("description"),
        "url_offre": (o.get("origineOffre") or {}).get("urlOrigine"),
        "url_candidature": (o.get("origineOffre") or {}).get("urlOrigine"),
        "recipient_id": None,
        "contact_email": _email_valide(contact.get("courriel")),
        "contact_telephone": contact.get("telephone"),
        "lieu": libelle,
        **_position(lieu, libelle),
        "contrat_type": o.get("typeContratLibelle"),
        "contrat_duree": duree,
        "date_publication": o.get("dateCreation"),
    }


def collecte(mots_cles=("developpeur", "developpement web", "python", "automatisation"),
             departements=None):
    departements = departements or config.DEPARTEMENTS
    token = _access_token()
    vus = set()
    resultats = []

    for mot in mots_cles:
        avant = len(resultats)
        for dep in departements:
            for nature in NATURES_CONTRAT:
                params = {
                    "motsCles": mot,
                    "natureContrat": nature,
                    "departement": dep,
                    "range": "0-149",
                }
                r = requests.get(
                    SEARCH_URL, params=params,
                    headers={"Authorization": f"Bearer {token}"}, timeout=45,
                )
                if r.status_code == 204:      # aucun resultat
                    continue
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                if r.status_code == 400:
                    print(f"    400 sur {dep}/{nature}: {r.text[:120]}")
                    continue
                r.raise_for_status()
                for o in r.json().get("resultats", []):
                    if o.get("id") in vus:
                        continue
                    vus.add(o.get("id"))
                    resultats.append(_map(o))
                time.sleep(0.4)
        print(f"  '{mot}': +{len(resultats) - avant} (total {len(resultats)})")

    return resultats
