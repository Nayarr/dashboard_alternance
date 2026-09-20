"""Collecte des offres en apprentissage sur l'Apec.

L'Apec n'expose pas d'API publique documentee, mais son site interroge un
service JSON sans authentification : POST /cms/webservices/rechercheOffre.
C'est ce service qu'on utilise. Le robots.txt du domaine n'interdit rien.

Deux limites a connaitre, qui expliquent le peu de code ici :

1. Le service ne filtre pas par distance. On recupere donc TOUTES les offres
   en apprentissage de France (environ 370) et on filtre localement sur les
   coordonnees, que chaque resultat porte. C'est moins elegant qu'un filtre
   serveur, mais le volume le permet largement.

2. La description renvoyee est un resume tronque, environ 280 caracteres.
   Le texte complet vit derriere /cms/webservices/offre?numeroOffre=..., qui
   repond 401 sans session. Les offres Apec sont donc scorees sur un texte
   plus court que les autres sources : leur axe technique est structurellement
   desavantage. Une session Apec connectee depuis la page Parametres permettra
   de recuperer le texte entier.
"""

import hashlib
import time

import requests

from alternance import config
from alternance import filtres as filters

URL = "https://www.apec.fr/cms/webservices/rechercheOffre"

# Identifiants internes de l'Apec, releves dans les facettes du service.
CONTRAT_APPRENTISSAGE = 20053

ENTETES = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Referer": "https://www.apec.fr/candidat/recherche-emploi.html",
}

PAR_PAGE = 100
PAUSE = 0.4


def _page(debut):
    corps = {
        "typesContrat": [CONTRAT_APPRENTISSAGE],
        "sorts": [{"type": "DATE", "direction": "DESCENDING"}],
        "pagination": {"range": PAR_PAGE, "startIndex": debut},
        "activeFiltre": True,
    }
    reponse = requests.post(URL, json=corps, headers=ENTETES, timeout=30)
    reponse.raise_for_status()
    donnees = reponse.json()
    return donnees.get("totalCount") or 0, donnees.get("resultats") or []


def _lien(numero):
    return ("https://www.apec.fr/candidat/recherche-emploi.html"
            f"/emploi/detail-offre/{numero}")


def _coordonnees(brut):
    """Les coordonnees arrivent en chaines, et manquent sur les offres
    non localisables (teletravail total, poste itinerant)."""
    try:
        return float(brut["latitude"]), float(brut["longitude"])
    except (KeyError, TypeError, ValueError):
        return None, None


def _convertir(brut, lat, lon):
    numero = brut.get("numeroOffre")
    return {
        # uid est NOT NULL UNIQUE et l'insertion se fait en INSERT OR IGNORE :
        # l'oublier fait disparaitre toutes les lignes sans le moindre message.
        "uid": hashlib.sha1(f"apec|{numero}".encode()).hexdigest()[:16],
        "source": "apec",
        "source_id": str(numero),
        "genre": "offre",
        "intitule": (brut.get("intitule") or "").strip(),
        "entreprise": (brut.get("nomCommercial") or "").strip(),
        "lieu": (brut.get("lieuTexte") or "").strip(),
        "description": (brut.get("texteOffre") or "").strip(),
        "url_offre": _lien(numero),
        "url_candidature": _lien(numero),
        "logo_url": brut.get("urlLogo") or None,
        "contrat_type": "apprentissage",
        "contrat_duree": None,
        # secteurActivite est un identifiant numerique interne, pas un
        # libelle : inutilisable tel quel pour le scoring par NAF.
        "naf": None,
        "taille": None,
        "latitude": lat,
        "longitude": lon,
        "distance_km": filters.distance_km(lat, lon),
        "date_publication": brut.get("datePublication"),
        "contact_email": None,
        "recipient_id": None,
    }


def collecter(rayon_km=None, verbeux=True):
    """Retourne les offres en apprentissage situees dans le rayon configure."""
    rayon = rayon_km or config.RAYON_KM

    total, brutes = _page(0)
    while len(brutes) < total:
        time.sleep(PAUSE)
        _, lot = _page(len(brutes))
        if not lot:
            break
        brutes += lot

    offres = []
    sans_position = 0
    for brut in brutes:
        lat, lon = _coordonnees(brut)
        if lat is None:
            sans_position += 1
            continue
        distance = filters.distance_km(lat, lon)
        if distance is None or distance > rayon:
            continue
        offres.append(_convertir(brut, lat, lon))

    if verbeux:
        print(f"APEC : {len(brutes)} offres en apprentissage, "
              f"{len(offres)} a moins de {rayon} km "
              f"({sans_position} sans localisation)")
    return offres


if __name__ == "__main__":
    for offre in collecter()[:10]:
        print(f"  {offre['distance_km']:5.1f} km  {offre['intitule'][:52]:54} "
              f"{offre['entreprise'][:24]}")
