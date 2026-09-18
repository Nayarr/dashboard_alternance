"""Collecte des offres en alternance sur JobTeaser.

Les offres sont publiques : aucun compte n'est necessaire pour les lire. Le
compte ne sert qu'a postuler, notamment via le bouton "Candidature simplifiee"
que porte une bonne partie des annonces.

Deux contraintes dictent la forme de ce connecteur.

1. Le robots.txt de JobTeaser autorise `*/job-search/*` mais interdit toute URL
   a parametres (`/*?*`). La liste filtrable, qui compte plus de 30 000 offres,
   passe par des parametres de requete : elle est donc hors limites. On passe
   par les pages d'atterrissage a chemin fixe, explicitement autorisees, une
   par theme et par ville.

2. Les fiches de detail sont inaccessibles en lot. La PREMIERE repond
   normalement dans un navigateur, les suivantes renvoient un 403 Cloudflare
   ("Un instant...") qui ne se resout pas, y compris avec 15 s entre chaque
   fiche et 9 s d'attente. Mesure anti-robot deliberee : on s'arrete la.

   Consequence : les offres JobTeaser arrivent SANS description et sont scorees
   sur leur seul intitule. La fonction enrichir() ci-dessous reste utilisable a
   l'unite (une fiche a la fois, sur demande), mais collecte() ne l'appelle pas
   par defaut : 77 fiches produiraient 76 echecs.
"""

import hashlib
import html
import re
import time

import requests
from bs4 import BeautifulSoup

import config
import filters
import geocode

BASE = "https://www.jobteaser.com"

# Pages d'atterrissage valides, verifiees une a une. Les themes absents de
# cette liste renvoient 404 : JobTeaser ne genere ces pages que pour les
# combinaisons qui ont assez d'offres.
PAGES = [
    "alternance-informatique-paris",
    "alternance-gestion-projet-it-paris",
    "alternance-data-paris",
    "alternance-telecoms-paris",
    "alternance-reseaux-paris",
    "alternance-web-paris",
    "alternance-conseil-paris",
]

ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

PAUSE = 1.5           # une page toutes les 1,5 s : lent, volontairement
MOIS = re.compile(r"(\d+)\s*(?:a|à)?\s*(\d+)?\s*mois")

_CACHE_GEO = {}


def _coordonnees(lieu):
    """Geocode la commune, en memorisant : les memes villes reviennent."""
    ville = (lieu or "").split(",")[0].strip()
    if not ville:
        return None, None
    if ville not in _CACHE_GEO:
        try:
            resultats = geocode.geocode(ville, limit=1)
        except Exception as e:
            # L'API Adresse tombe regulierement. Une panne ne doit pas vider la
            # collecte en silence : l'offre est conservee sans distance.
            print(f"  geocodage indisponible pour {ville} : {type(e).__name__}")
            resultats = []
        _CACHE_GEO[ville] = ((resultats[0]["lat"], resultats[0]["lon"])
                             if resultats else (None, None))
        time.sleep(0.2)
    return _CACHE_GEO[ville]


def _duree(texte):
    """"Alternance 12 a 24 mois" -> 24. On retient la borne haute : c'est elle
    qui determine si le contrat depasse ce que le candidat peut engager."""
    trouve = MOIS.search(texte or "")
    if not trouve:
        return None
    haute = trouve.group(2) or trouve.group(1)
    try:
        return int(haute)
    except ValueError:
        return None


def _carte(carte):
    """Extrait une offre d'une carte de liste.

    Les classes CSS sont hachees par le bundler et changent a chaque
    deploiement. On s'accroche aux attributs data-testid, qui sont stables et
    decrivent le contenu : jobad-card-location, -contract, -company-name, et
    -internal, qui marque les offres a candidature simplifiee (JobTeaser gere
    le depot lui-meme au lieu de rediriger vers le site de l'entreprise).
    """
    lien = carte.select_one('a[href^="/fr/job-offers/"]')
    if lien is None:
        return None
    identifiant = re.search(r"/fr/job-offers/([0-9a-f-]{36})", lien.get("href") or "")
    if not identifiant:
        return None

    def champ(testid):
        element = carte.select_one(f'[data-testid="{testid}"]')
        return element.get_text(" ", strip=True) if element else ""

    lieu = champ("jobad-card-location")
    contrat = champ("jobad-card-contract")
    lat, lon = _coordonnees(lieu)

    return {
        "uid": hashlib.sha1(f"jobteaser|{identifiant.group(1)}".encode()).hexdigest()[:16],
        "source": "jobteaser",
        "source_id": identifiant.group(1),
        "genre": "offre",
        "intitule": lien.get_text(" ", strip=True),
        "entreprise": champ("jobad-card-company-name"),
        "lieu": lieu,
        # Pas de description : les fiches de detail ne sont pas ouvertes.
        "description": "",
        "url_offre": BASE + lien.get("href"),
        "url_candidature": BASE + lien.get("href"),
        "logo_url": _logo(carte),
        "contrat_type": "alternance",
        "contrat_duree": _duree(contrat),
        "naf": None,
        "taille": None,
        "latitude": lat,
        "longitude": lon,
        "distance_km": filters.distance_km(lat, lon),
        "contact_email": None,
        "recipient_id": None,
        # Dit si le depot pourra etre automatise ou s'il faudra passer par le
        # site de l'entreprise.
        "notes": ("candidature_simplifiee"
                  if carte.select_one('[data-testid="jobad-card-internal"]') else None),
    }


def _logo(carte):
    image = carte.select_one('[data-testid="jobad-card-company-logo"] img')
    if image is None:
        image = carte.select_one('[data-testid="jobad-card-company-logo"]')
    source = (image.get("src") if image else None) or ""
    return source if source.startswith("http") else None


def _page(chemin):
    reponse = requests.get(f"{BASE}/fr/job-search/{chemin}", headers=ENTETES, timeout=30)
    if reponse.status_code != 200:
        print(f"  {chemin} : HTTP {reponse.status_code}, ignoree")
        return []

    soup = BeautifulSoup(reponse.text, "html.parser")
    offres = []
    for carte in soup.select('[data-testid="jobad-card"]'):
        offre = _carte(carte)
        if offre:
            offres.append(offre)
    return offres


def _texte_html(brut):
    """Le JSON-LD contient du HTML : on le rend lisible pour le scoring."""
    if not brut:
        return ""
    texte = re.sub(r"<br\s*/?>", "\n", brut)
    texte = re.sub(r"</(p|div|li|h[1-6])>", "\n", texte)
    texte = re.sub(r"<[^>]+>", " ", texte)
    texte = html.unescape(texte)
    return re.sub(r"[ \t]+", " ", texte).strip()


def enrichir(offres, pause=2.0, verbeux=True):
    """Remplit la description de chaque offre en ouvrant sa fiche.

    Ne fonctionne que sur la premiere fiche d'une session : JobTeaser oppose un
    403 Cloudflare aux suivantes. Conservee parce qu'elle reste utile a
    l'unite, sur une offre precise qu'on veut examiner. Ne pas l'appeler sur
    une liste entiere.
    """
    from playwright.sync_api import sync_playwright

    reussites = 0
    with sync_playwright() as pw:
        navigateur = pw.chromium.launch(headless=True)
        contexte = navigateur.new_context(locale="fr-FR",
                                          user_agent=ENTETES["User-Agent"])
        page = contexte.new_page()
        for rang, offre in enumerate(offres, 1):
            try:
                page.goto(offre["url_offre"], wait_until="domcontentloaded",
                          timeout=40000)
                page.wait_for_timeout(1200)
                fiche = page.evaluate("""() => {
                    for (const s of document.querySelectorAll(
                            'script[type="application/ld+json"]')) {
                        try {
                            const d = JSON.parse(s.textContent);
                            if (d['@type'] === 'JobPosting') return d;
                        } catch (e) {}
                    }
                    return null;
                }""")
            except Exception as e:
                if verbeux:
                    print(f"  [{rang}/{len(offres)}] echec : {type(e).__name__}")
                fiche = None

            if fiche:
                offre["description"] = _texte_html(fiche.get("description"))
                if not offre.get("date_publication"):
                    offre["date_publication"] = fiche.get("datePosted")
                if fiche.get("description"):
                    reussites += 1

            if verbeux and rang % 10 == 0:
                print(f"  {rang}/{len(offres)} fiches lues")
            time.sleep(pause)

        navigateur.close()

    if verbeux:
        moyenne = (sum(len(o["description"]) for o in offres)
                   // max(1, len(offres)))
        print(f"  descriptions recuperees : {reussites}/{len(offres)}, "
              f"{moyenne} caracteres en moyenne")
    return offres


def collecte(rayon_km=None, avec_description=False):
    rayon = rayon_km or config.RAYON_KM
    vues = {}
    for chemin in PAGES:
        lot = _page(chemin)
        nouvelles = sum(1 for o in lot if o["uid"] not in vues)
        for o in lot:
            vues.setdefault(o["uid"], o)
        print(f"  {chemin:38} {len(lot):3} offres, {nouvelles:3} nouvelles")
        time.sleep(PAUSE)

    # On n'ecarte que ce qui est prouve trop loin. Une offre sans coordonnees
    # est conservee : elle sera simplement notee 0 sur l'axe distance, ce qui
    # vaut mieux que de la perdre parce que le geocodeur etait en panne.
    dans_rayon = [o for o in vues.values()
                  if o["distance_km"] is None or o["distance_km"] <= rayon]
    sans_distance = sum(1 for o in dans_rayon if o["distance_km"] is None)
    simplifiees = sum(1 for o in dans_rayon if o["notes"] == "candidature_simplifiee")
    print(f"JobTeaser : {len(vues)} offres uniques, {len(dans_rayon)} retenues "
          f"(<= {rayon} km, {sans_distance} sans coordonnees), "
          f"dont {simplifiees} en candidature simplifiee")

    if avec_description and dans_rayon:
        print(f"  lecture des {len(dans_rayon)} fiches...")
        enrichir(dans_rayon)
    return dans_rayon


if __name__ == "__main__":
    for offre in collecte()[:12]:
        marque = "*" if offre["notes"] else " "
        distance = (f"{offre['distance_km']:5.1f} km" if offre["distance_km"] is not None
                    else "   ? km")
        print(f" {marque} {distance}  {offre['intitule'][:46]:48} "
              f"{offre['entreprise'][:22]}")
