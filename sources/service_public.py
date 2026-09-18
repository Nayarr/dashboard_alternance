"""Collecte des offres publiees sur choisirleservicepublic.gouv.fr.

Le portail de l'emploi public : ministeres, collectivites, etablissements.
Ces employeurs encadrent serieusement un alternant et pesent sur un CV junior,
mais ils n'apparaissent sur aucune des autres sources.

Pas d'API : le site est un WordPress rendu cote serveur, les offres sont dans
le HTML. Son robots.txt n'interdit que /wp-admin/ et les PDF d'offres, la
section /nos-offres/ est libre d'acces.

Deux limites assumees :

1. Aucun filtre "apprentissage" ou "stage" n'existe sur le site : ses filtres
   portent sur le statut (titulaire, contractuel), pas sur la nature du
   contrat. On interroge par mots-cles, puis on ECARTE ici tout ce dont la
   nature n'est pas etablie. Ce tri ne peut pas etre delegue a filters.py :
   un contrat_type absent y est lu comme une alternance, et un poste
   permanent de lead developpeur entrait dans le vivier a 75 %.

2. Les offres ne portent pas de coordonnees, seulement un departement. On
   geocode le libelle, comme pour France Travail et JobTeaser.
"""

import hashlib
import re
import time

import requests
from bs4 import BeautifulSoup

import config
import filters
import geocode

BASE = "https://choisirleservicepublic.gouv.fr"

# Recherches lancees, par nature de contrat. Sans filtre de contrat sur le
# site, le mot-cle est le seul levier : chercher des stages avec des requetes
# qui ne parlent que d'alternance ne ramene rien.
RECHERCHES_PAR_NATURE = {
    "alternance": [
        "alternance informatique",
        "apprentissage developpeur",
        "alternance developpeur",
        "apprenti informatique",
    ],
    "stage": [
        "stage informatique",
        "stage developpeur",
        "stagiaire developpement",
    ],
}

ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

PAGES_MAX = 3         # 20 offres par page
PAUSE = 2.0           # les pages pesent 4 Mo : on ne martele pas

_CACHE_GEO = {}
DEPARTEMENT = re.compile(r"\(([0-9AB]{2,3})\)")


def _coordonnees(lieu):
    """Geocode le libelle de localisation, du type 'Haute Garonne (31)'."""
    ville = re.sub(r"\s*\([0-9AB]{2,3}\)\s*", "", lieu or "").strip()
    if not ville:
        return None, None
    if ville not in _CACHE_GEO:
        try:
            r = geocode.geocode(ville, limit=1)
            _CACHE_GEO[ville] = (r[0]["lat"], r[0]["lon"]) if r else (None, None)
        except Exception:
            _CACHE_GEO[ville] = (None, None)
        time.sleep(0.2)
    return _CACHE_GEO[ville]


def _champ(texte, etiquette):
    """Extrait 'Employeur : X' du bloc de texte d'une carte."""
    trouve = re.search(rf"{etiquette}\s*:\s*(.+?)(?:\s{{2,}}|$|Localisation|Employeur|"
                       r"Fonction publique|En ligne depuis)", texte)
    return trouve.group(1).strip() if trouve else ""


NATURE_ALTERNANCE = re.compile(r"alternan|apprenti", re.I)
NATURE_STAGE = re.compile(r"stage|stagiaire", re.I)


def _nature(texte):
    """Nature du contrat, deduite du texte de la carte.

    Le site n'a aucun filtre de contrat : la recherche par mot-cle ramene
    autant de postes permanents que d'alternances. Etiqueter le tout
    "alternance" serait une affirmation sans preuve, et ferait passer des
    postes de lead developpeur senior pour des offres d'apprentissage.
    Une offre dont rien n'indique la nature retourne None : elle sera notee
    sans prime de contrat, et restera visible pour un examen a la main.
    """
    if NATURE_ALTERNANCE.search(texte):
        return "alternance"
    if NATURE_STAGE.search(texte):
        return "Stage"
    return None


def _carte(lien, bloc):
    url = lien.get("href") or ""
    if "/offre-emploi/" not in url:
        return None
    texte = re.sub(r"\s+", " ", bloc.get_text(" ", strip=True))

    lieu = _champ(texte, "Localisation")
    employeur = _champ(texte, "Employeur")
    lat, lon = _coordonnees(lieu)

    # L'intitule est le premier segment, avant la premiere etiquette
    intitule = re.split(r"\s(?:Num[ée]rique|Localisation|Employeur|Fonction publique)\s",
                        texte)[0].strip()

    return {
        "uid": hashlib.sha1(url.encode()).hexdigest()[:16],
        "source": "service_public",
        "source_id": url.rstrip("/").split("/")[-1][:80],
        "genre": "offre",
        "intitule": intitule[:200],
        "entreprise": employeur[:120],
        "lieu": lieu,
        # La page de liste ne donne pas le texte de l'annonce. Le titre suffit
        # au portillon technique ; la fiche complete reste a ouvrir a la main.
        "description": "",
        "url_offre": url,
        "url_candidature": url,
        "logo_url": None,
        "contrat_type": _nature(intitule + " " + texte),
        "contrat_duree": None,
        "naf": None,
        "taille": None,
        "latitude": lat,
        "longitude": lon,
        "distance_km": filters.distance_km(lat, lon),
        "contact_email": None,
        "recipient_id": None,
    }


def _page(recherche, numero):
    chemin = f"/nos-offres/filtres/mot-cles/{requests.utils.quote(recherche)}/"
    if numero > 1:
        chemin += f"page/{numero}/"
    reponse = requests.get(BASE + chemin, headers=ENTETES, timeout=45)
    if reponse.status_code != 200:
        return []

    soup = BeautifulSoup(reponse.text, "html.parser")
    offres, vus = [], set()
    for lien in soup.select('a[href*="/offre-emploi/"]'):
        url = lien.get("href") or ""
        if url in vus:
            continue
        vus.add(url)
        bloc = lien.find_parent(["article", "li"]) or lien.parent
        offre = _carte(lien, bloc)
        if offre and offre["intitule"]:
            offres.append(offre)
    return offres


# Adresses de service, a ecarter : elles ne recrutent pas.
EMAILS_IGNORES = ("webmaster", "contact@", "noreply", "no-reply", "support",
                  "rgpd", "dpo@", "presse")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")


def _email_recruteur(texte):
    """Adresse a qui envoyer la candidature.

    Le portail affiche un bouton "Postuler par mail" et donne l'adresse en
    clair dans l'annonce : c'est le seul canal, il n'y a pas de formulaire.
    On prend la premiere adresse qui ne soit pas une boite de service.
    """
    for adresse in EMAIL.findall(texte or ""):
        bas = adresse.lower()
        if any(ignore in bas for ignore in EMAILS_IGNORES):
            continue
        return adresse
    return None


def _description(url):
    """Texte de l'annonce, lu sur sa fiche.

    Les pages de liste n'en donnent aucun, ce qui laisse le portillon technique
    juger sur le seul intitule : deux vraies alternances de developpement se
    retrouvaient a 19 % et 57 %. /offre-emploi/ est autorise par le robots.txt,
    seuls les PDF d'offres sont interdits.
    """
    try:
        r = requests.get(url, headers=ENTETES, timeout=40)
        if r.status_code != 200:
            return "", None
    except Exception:
        return "", None
    soup = BeautifulSoup(r.text, "html.parser")
    for balise in soup(["script", "style", "nav", "header", "footer"]):
        balise.decompose()
    corps = soup.select_one("main") or soup.body
    if corps is None:
        return "", None
    texte = re.sub(r"\s+", " ", corps.get_text(" ", strip=True))
    return texte[:6000], _email_recruteur(texte)


def enrichir(offres, verbeux=True):
    """Complete les descriptions des seules offres en alternance ou en stage.

    Appelee apres le tri sur la nature : seules les offres en alternance ou en
    stage arrivent ici, soit environ 38 sur les 91 retenues geographiquement.
    Ouvrir les 91 fiches couterait trois fois plus de temps pour aucun gain.
    """
    cibles = offres
    for rang, offre in enumerate(cibles, 1):
        offre["description"], offre["contact_email"] = _description(offre["url_offre"])
        if verbeux and rang % 10 == 0:
            print(f"  {rang}/{len(cibles)} fiches lues")
        time.sleep(PAUSE)
    if verbeux:
        moyenne = sum(len(o["description"]) for o in cibles) // max(1, len(cibles))
        avec_mail = sum(1 for o in cibles if o["contact_email"])
        print(f"  {len(cibles)} fiches lues, {moyenne} caracteres en moyenne, "
              f"{avec_mail} avec une adresse de candidature")
    return offres


def collecte(rayon_km=None, avec_description=True):
    rayon = rayon_km or config.RAYON_KM
    recherches = []
    if config.RECHERCHE_ALTERNANCE:
        recherches += RECHERCHES_PAR_NATURE["alternance"]
    if config.RECHERCHE_STAGES:
        recherches += RECHERCHES_PAR_NATURE["stage"]
    if not recherches:
        print("Service public : ni alternance ni stage demandes")
        return []

    vues = {}
    for recherche in recherches:
        avant = len(vues)
        for numero in range(1, PAGES_MAX + 1):
            lot = _page(recherche, numero)
            if not lot:
                break
            for o in lot:
                vues.setdefault(o["uid"], o)
            time.sleep(PAUSE)
        print(f"  {recherche:30} {len(vues) - avant:3} nouvelles")

    # Comme ailleurs : on n'ecarte que ce qui est prouve trop loin, une offre
    # sans coordonnees est conservee plutot que perdue sur une panne du
    # geocodeur.
    dans_rayon = [o for o in vues.values()
                  if o["distance_km"] is None or o["distance_km"] <= rayon]

    # Le portail n'a aucun filtre de contrat : la recherche par mot-cle ramene
    # autant de postes permanents que d'alternances. Les autres sources
    # renseignent toujours contrat_type, si bien qu'une valeur absente est lue
    # ailleurs comme "alternance" par defaut : un poste de lead developpeur
    # senior entrait alors dans le vivier a 75 %. On ne garde donc que ce dont
    # la nature est etablie.
    # On s'aligne aussi sur les natures effectivement recherchees. Le scoring
    # les rejetterait de toute facon, mais pas avant qu'on ait lu leur fiche :
    # autant ne pas ouvrir 20 pages de stages quand seule l'alternance est
    # cochee.
    voulues = set()
    if config.RECHERCHE_ALTERNANCE:
        voulues.add("alternance")
    if config.RECHERCHE_STAGES:
        voulues.add("Stage")

    retenues = [o for o in dans_rayon if o["contrat_type"] in voulues]
    ecartees = len(dans_rayon) - len(retenues)
    print(f"Service public : {len(vues)} offres uniques, {len(dans_rayon)} "
          f"a moins de {rayon} km, {len(retenues)} en alternance ou stage "
          f"({ecartees} postes permanents ecartes)")
    if avec_description and retenues:
        enrichir(retenues)
    return retenues


if __name__ == "__main__":
    for offre in collecte()[:12]:
        distance = (f"{offre['distance_km']:5.1f} km" if offre["distance_km"] is not None
                    else "   ? km")
        print(f"  {distance}  {offre['intitule'][:46]:48} {offre['entreprise'][:26]}")
