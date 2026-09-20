"""Geocodage d'une adresse via l'API Adresse (api-adresse.data.gouv.fr).

Officielle, gratuite, sans cle. Sert a fixer ORIGINE dans config.py.

    python cli.py geocode "12 rue de la Paix, 75002 Paris"
"""

import sys

import requests

API = "https://api-adresse.data.gouv.fr/search/"


def geocode(adresse, limit=3):
    r = requests.get(API, params={"q": adresse, "limit": limit}, timeout=30)
    r.raise_for_status()
    return [
        {
            "label": f["properties"]["label"],
            "score": f["properties"]["score"],
            "lat": f["geometry"]["coordinates"][1],
            "lon": f["geometry"]["coordinates"][0],
        }
        for f in r.json().get("features", [])
    ]


def main():
    from alternance import config

    adresse = " ".join(sys.argv[1:]) or config.ADRESSE_REFERENCE
    resultats = geocode(adresse)
    if not resultats:
        print("Aucun resultat")
        raise SystemExit(1)

    for x in resultats:
        print(f"{x['label']:60} score={x['score']:.3f}  {x['lat']}, {x['lon']}")

    best = resultats[0]
    print(f"\nPour config.py :\n"
          f'ADRESSE_REFERENCE = "{adresse}"\n'
          f"ORIGINE = ({best['lat']}, {best['lon']})")


if __name__ == "__main__":
    main()
