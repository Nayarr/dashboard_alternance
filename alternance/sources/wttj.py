"""Source Welcome to the Jungle.

Le site est une SPA : aucune offre n'est rendue cote serveur. Son front interroge
un index Algolia avec une cle de recherche publique, embarquee dans le bundle JS.
On utilise le meme point d'entree : JSON structure, pas de parsing HTML fragile,
et une charge tres inferieure a celle d'un rendu de page complet.

Volume vise : une recherche d'alternance sur une region, soit quelques
centaines d'offres. Cadence volontairement lente.
"""

import hashlib
import json
import time

import requests

from alternance import config

APP_ID = "CSEKHVMS53"
API_KEY = "4bd8f6215d0cc52b26430765769e65a0"   # cle publique search-only du front
INDEX = "wk_cms_jobs_production"
URL = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/{INDEX}/query"

HEADERS = {
    "x-algolia-api-key": API_KEY,
    "x-algolia-application-id": APP_ID,
    "content-type": "application/x-www-form-urlencoded",
    "referer": "https://www.welcometothejungle.com/",
}

REQUETES = [
    "developpeur", "developpement web", "fullstack", "back-end", "front-end",
    "python", "php symfony", "javascript", "administrateur systeme",
    "devops", "automatisation", "logiciel",
]

# Seules les publications portees par le site WTTJ ont une URL publique
# de la forme /fr/companies/{org}/jobs/{slug}. Les autres vivent sur des
# sites carriere en marque blanche dont le domaine n'est pas devinable.
SITE_WTTJ = "wttj_fr"

HITS_PAR_PAGE = 50
MAX_PAGES = 4
PAUSE = 1.2


def _uid(entreprise, intitule, lieu):
    brut = f"wttj|{(entreprise or '').lower()}|{(intitule or '').lower()}|{(lieu or '').lower()}"
    return hashlib.sha1(brut.encode()).hexdigest()[:16]


def _filtre_contrat():
    """Filtre Algolia sur la nature du contrat, selon les reglages.

    APPRENTICESHIP couvre l'alternance, INTERNSHIP les stages. Les deux
    peuvent etre cumules : Algolia accepte un OU entre parentheses.
    """
    natures = []
    if config.RECHERCHE_ALTERNANCE:
        natures.append("contract_type:APPRENTICESHIP")
    if config.RECHERCHE_STAGES:
        natures.append("contract_type:INTERNSHIP")
    if not natures:
        raise ValueError("ni alternance ni stage demandes : rien a collecter")
    return "(" + " OR ".join(natures) + ")" if len(natures) > 1 else natures[0]


def _requete(query, page):
    params = (
        f"query={requests.utils.quote(query)}"
        f"&hitsPerPage={HITS_PAR_PAGE}&page={page}"
        f"&filters={requests.utils.quote(_filtre_contrat())}"
        f"&aroundLatLng={config.ORIGINE[0]},{config.ORIGINE[1]}"
        f"&aroundRadius={int(config.RAYON_KM * 1000)}"
    )
    r = requests.post(URL, headers=HEADERS, data=json.dumps({"params": params}),
                      timeout=45)
    r.raise_for_status()
    return r.json()


def _map(h):
    org = h.get("organization") or {}
    offices = h.get("offices") or [{}]
    bureau = offices[0] if offices else {}
    geo = (h.get("_geoloc") or [{}])
    geo = geo[0] if isinstance(geo, list) and geo else {}

    entreprise = org.get("name") or ""
    ville = bureau.get("city") or ""
    dept = bureau.get("district") or bureau.get("state") or ""
    lieu = ", ".join(x for x in (ville, dept) if x)

    taille = org.get("size")
    if isinstance(taille, dict):
        taille = taille.get("fr")

    # L'index ne porte pas la description complete : on garde ce qui est
    # exploitable pour le scoring et le filtre mission.
    description = " ".join(filter(None, [
        h.get("profile") or "",
        (org.get("descriptions") or {}).get("fr") or "",
        ((h.get("profession") or {}).get("name") or {}).get("fr") or "",
    ]))

    url = None
    if org.get("slug") and h.get("slug"):
        url = ("https://www.welcometothejungle.com/fr/companies/"
               f"{org['slug']}/jobs/{h['slug']}")

    duree = h.get("contract_duration_maximum") or h.get("contract_duration_minimum")

    # WTTJ exprime ses durees en mois pour les deux natures. Le scoring des
    # stages raisonne en semaines : on convertit ici plutot que de melanger
    # deux unites dans la meme colonne de la base.
    est_stage = (h.get("contract_type") or "").upper() == "INTERNSHIP"
    if est_stage and duree:
        duree = int(round(duree * 4.35))

    return {
        "uid": _uid(entreprise, h.get("name"), lieu),
        "source": "wttj",
        # Reference de l'offre, pas objectID de la publication : WTTJ
        # rediffuse la meme offre sur plusieurs sites, chacun avec son
        # propre objectID mais une reference commune.
        "source_id": h.get("reference") or h.get("objectID"),
        "partner_label": "Welcome to the Jungle",
        "genre": "offre",
        "entreprise": entreprise,
        "siret": None,
        "taille": taille,
        "naf": ", ".join(h.get("sectors_name") or []) if h.get("sectors_name") else None,
        "site_web": None,
        # WTTJ expose un CDN de logos ; LBA n'a pas d'equivalent.
        "logo_url": ((org.get("logo") or {}).get("url") or None),
        "intitule": h.get("name"),
        "description": description.strip() or None,
        "url_offre": url,
        "url_candidature": url,
        "recipient_id": None,
        "contact_telephone": None,
        "lieu": lieu,
        "latitude": geo.get("lat"),
        "longitude": geo.get("lng"),
        "contrat_type": "Stage" if est_stage else "Apprentissage",
        "contrat_duree": duree,
        "date_publication": h.get("published_at"),
    }


def collecte():
    vus = set()
    resultats = []
    compteur = {"hors_wttj": 0}

    for query in REQUETES:
        avant = len(resultats)
        for page in range(MAX_PAGES):
            data = _requete(query, page)
            hits = data.get("hits", [])
            for h in hits:
                # Identite de l'OFFRE : sans ca, la meme offre entre autant de
                # fois qu'elle compte de sites diffuseurs.
                cle = h.get("reference") or h.get("objectID")
                if cle in vus:
                    continue

                # Une publication hors wttj_fr n'a pas d'URL constructible :
                # elle produirait un 404 au moment de postuler.
                if (h.get("website") or {}).get("reference") != SITE_WTTJ:
                    compteur["hors_wttj"] += 1
                    continue

                vus.add(cle)
                resultats.append(_map(h))
            if page + 1 >= data.get("nbPages", 0):
                break
            time.sleep(PAUSE)
        print(f"  '{query}': +{len(resultats) - avant} (total {len(resultats)})")
        time.sleep(PAUSE)

    if compteur["hors_wttj"]:
        print(f"  {compteur['hors_wttj']} publication(s) ignoree(s) : site en "
              f"marque blanche, URL non constructible")
    return resultats
