"""Source La Bonne Alternance (API Apprentissage - mission-apprentissage.beta.gouv.fr).

GET /api/job/v1/search renvoie deux gisements :
  - jobs       : offres publiees (agrege France Travail, Hellowork, etc.)
  - recruiters : entreprises susceptibles de recruter, sans offre publiee
                 -> candidature spontanee
Rate limit : 60 appels / minute.
"""

import hashlib
import html
import os
import re
import time

import requests

import config

BASE = "https://api.apprentissage.beta.gouv.fr/api"
SEARCH = f"{BASE}/job/v1/search"
APPLY = f"{BASE}/job/v1/apply"


def _headers():
    key = os.environ.get("LBA_API_KEY")
    if not key:
        raise RuntimeError("LBA_API_KEY absente du .env")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _uid(source, entreprise, intitule, lieu):
    brut = f"{source}|{(entreprise or '').lower()}|{(intitule or '').lower()}|{(lieu or '').lower()}"
    return hashlib.sha1(brut.encode()).hexdigest()[:16]


def _propre(texte):
    """Decode les entites HTML et normalise les blancs."""
    if not texte:
        return texte
    texte = html.unescape(texte)
    texte = re.sub(r"<[^>]+>", " ", texte)
    return re.sub(r"[ \t]{2,}", " ", texte).strip()


def _nom_entreprise(workplace, description=""):
    nom = (workplace.get("name")
           or workplace.get("brand")
           or workplace.get("legal_name"))
    if nom:
        return _propre(nom)
    # Certaines offres France Travail relayees n'ont pas de nom : on tente la
    # premiere entite nommee de la description, sinon on marque explicitement.
    if description:
        m = re.match(r"\s*([A-ZÉÈÀÂÎÔÛ][\w'&.-]*(?:\s+[A-ZÉÈÀÂÎÔÛ][\w'&.-]*){0,3})",
                     _propre(description))
        if m and len(m.group(1)) > 2:
            return m.group(1).strip()
    return "(non communique)"


def _map_job(j):
    wp = j.get("workplace") or {}
    ap = j.get("apply") or {}
    ct = j.get("contract") or {}
    of = j.get("offer") or {}
    ident = j.get("identifier") or {}
    loc = wp.get("location") or {}
    coords = ((loc.get("geopoint") or {}).get("coordinates") or [None, None])
    domain = wp.get("domain") or {}
    naf = domain.get("naf") or {}

    description = _propre(of.get("description")) or ""
    entreprise = _nom_entreprise(wp, wp.get("description") or description)
    lieu = _propre(loc.get("address")) or ""
    types = ct.get("type") or []
    titre = _propre(of.get("title"))

    return {
        "uid": _uid("lba", entreprise, titre, lieu),
        "source": "lba",
        "source_id": ident.get("id"),
        "partner_label": ident.get("partner_label"),
        "genre": "offre",
        "entreprise": entreprise,
        "siret": wp.get("siret"),
        "taille": wp.get("size"),
        "naf": naf.get("label") if isinstance(naf, dict) else None,
        "site_web": wp.get("website"),
        "logo_url": None,   # LBA n'expose pas de logo
        "intitule": titre,
        "description": description,
        "url_offre": ap.get("url"),
        "url_candidature": ap.get("url"),
        "recipient_id": ap.get("recipient_id"),
        "contact_telephone": ap.get("phone"),
        "lieu": lieu,
        "latitude": coords[1],
        "longitude": coords[0],
        "contrat_type": ", ".join(types) if types else None,
        "contrat_duree": ct.get("duration"),
        "date_publication": (of.get("publication") or {}).get("creation")
        if isinstance(of.get("publication"), dict) else None,
    }


def _map_recruiter(r):
    wp = r.get("workplace") or {}
    ap = r.get("apply") or {}
    ident = r.get("identifier") or {}
    loc = wp.get("location") or {}
    coords = ((loc.get("geopoint") or {}).get("coordinates") or [None, None])
    domain = wp.get("domain") or {}
    naf = domain.get("naf") or {}

    entreprise = _nom_entreprise(wp)
    lieu = _propre(loc.get("address")) or ""
    secteur = _propre(naf.get("label")) if isinstance(naf, dict) else None

    return {
        "uid": _uid("lba_spont", entreprise, wp.get("siret"), lieu),
        "source": "lba",
        "source_id": ident.get("id"),
        "partner_label": "LBA recruteur",
        "genre": "spontanee",
        "entreprise": entreprise,
        "siret": wp.get("siret"),
        "taille": wp.get("size"),
        "naf": secteur,
        "site_web": wp.get("website"),
        "logo_url": None,   # LBA n'expose pas de logo
        "intitule": f"Candidature spontanée - {secteur or 'informatique'}",
        "description": wp.get("description") or secteur or "",
        "url_offre": ap.get("url"),
        "url_candidature": ap.get("url"),
        "recipient_id": ap.get("recipient_id"),
        "contact_telephone": ap.get("phone"),
        "lieu": lieu,
        "latitude": coords[1],
        "longitude": coords[0],
        "contrat_type": "Apprentissage",
        "contrat_duree": None,
        "date_publication": None,
    }


def collecte(romes=None, radius=None, inclure_spontanees=True):
    """Interroge l'API pour chaque code ROME et retourne des offres normalisees."""
    romes = romes or config.ROMES
    radius = radius or config.RAYON_KM
    lat, lon = config.ORIGINE
    resultats = []

    for rome in romes:
        params = {
            "romes": rome,
            "latitude": lat,
            "longitude": lon,
            "radius": radius,
        }
        r = requests.get(SEARCH, params=params, headers=_headers(), timeout=60)
        if r.status_code == 429:
            attente = int(r.headers.get("retry-after", 60))
            print(f"  rate limit atteint, pause {attente}s")
            time.sleep(attente)
            r = requests.get(SEARCH, params=params, headers=_headers(), timeout=60)
        r.raise_for_status()
        data = r.json()

        jobs = [_map_job(j) for j in data.get("jobs", [])]
        recruiters = [_map_recruiter(x) for x in data.get("recruiters", [])] \
            if inclure_spontanees else []
        resultats += jobs + recruiters
        print(f"  ROME {rome}: {len(jobs)} offres, {len(recruiters)} recruteurs")
        time.sleep(1.1)  # 60 appels/min

    return resultats
