"""Rythme des interactions avec un site, partage entre toutes les taches.

Welcome to the Jungle suspend les interactions d'un compte pendant 20 a 30
minutes quand il ouvre trop de formulaires trop vite. Deux choses le
provoquaient :

  - la reconnaissance ouvrait un formulaire toutes les huit secondes
    environ, jusqu'a quarante d'affilee, avec le compte connecte ;
  - une fois la limite atteinte, rien ne s'en apercevait : chaque offre
    suivante echouait en quelques secondes sur « formulaire non apparu », et
    la boucle continuait de solliciter le site, ce qui prolonge la sanction.

Ce module tient, pour chaque site, l'heure de la derniere ouverture de
formulaire et une eventuelle pause. L'etat vit dans data/cadence.json et non
en memoire : la reconnaissance puis l'envoi, lances l'un apres l'autre depuis
l'interface, sont deux processus distincts et doivent partager le meme
rythme.

Le but est de rester sous la limite du site et de s'arreter des qu'il la
signale, pas de la contourner : aucune tentative n'est faite pendant une
pause.
"""

import json
import re
import time
from datetime import datetime, timedelta

from alternance import config

FICHIER = config.RACINE / "data" / "cadence.json"

# Secondes minimales entre deux ouvertures de formulaire sur un meme site.
# WTTJ ne publie aucun seuil : 45 s garde un rythme qu'aucune personne ne
# depasserait en postulant a la main. LBA n'a jamais bloque a 8 s.
INTERVALLES = {"wttj": 45, "lba": 8}
# Duree de la pause posee quand le site signale qu'il limite. Au-dessus de la
# fourchette observee (20 a 30 min) : reprendre trop tot relance la sanction.
PAUSES_MINUTES = {"wttj": 35, "lba": 15}
# Echecs « formulaire absent » consecutifs a partir desquels on conclut a une
# limitation plutot qu'a une offre isolee en panne.
ECHECS_AVANT_PAUSE = 2

NOMS = {"wttj": "Welcome to the Jungle", "lba": "La Bonne Alternance"}

# Ce qu'une page affiche quand le site limite les requetes.
SIGNES_DE_LIMITE = re.compile(
    r"too many requests|trop de (?:requ[eê]tes|tentatives)|rate.?limit|"
    r"r[eé]essayez (?:plus tard|dans quelques minutes)|try again later",
    re.I)


class SiteEnPause(Exception):
    """Le site a signale une limite : aucune interaction avant la reprise."""


def _lire():
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ecrire(etat):
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(etat, indent=2), encoding="utf-8")


def reprise(site):
    """Heure de reprise si le site est en pause, sinon None."""
    jusqu_a = _lire().get(site, {}).get("pause_jusqu_a")
    if not jusqu_a:
        return None
    fin = datetime.fromisoformat(jusqu_a)
    return fin if fin > datetime.now() else None


def message_pause(site, fin):
    return (f"{NOMS.get(site, site)} limite les interactions : reprise "
            f"possible apres {fin:%H:%M}. Rien n'a ete tente.")


def verifier(site):
    """Leve SiteEnPause si le site est en pause."""
    fin = reprise(site)
    if fin:
        raise SiteEnPause(message_pause(site, fin))


def attendre(site, dormir=time.sleep):
    """Respecte l'intervalle depuis la derniere ouverture, puis la note.

    A appeler juste avant d'ouvrir un formulaire. Leve SiteEnPause si une
    pause est en cours.
    """
    verifier(site)
    etat = _lire()
    derniere = etat.get(site, {}).get("derniere")
    if derniere:
        ecoule = (datetime.now() - datetime.fromisoformat(derniere)).total_seconds()
        reste = INTERVALLES.get(site, 0) - ecoule
        if reste > 0:
            if reste >= 5:
                print(f"  pause {int(reste)} s (cadence {NOMS.get(site, site)})",
                      flush=True)
            dormir(reste)
    etat = _lire()
    etat.setdefault(site, {})["derniere"] = datetime.now().isoformat(
        timespec="seconds")
    _ecrire(etat)


def poser_pause(site, motif):
    """Le site limite : plus aucune interaction avant la fin de la pause."""
    fin = datetime.now() + timedelta(minutes=PAUSES_MINUTES.get(site, 30))
    etat = _lire()
    etat.setdefault(site, {}).update({
        "pause_jusqu_a": fin.isoformat(timespec="seconds"), "motif": motif})
    _ecrire(etat)
    return fin


def page_limitee(page, statut=None):
    """Vrai si la page ou sa reponse HTTP signale une limitation."""
    if statut == 429:
        return True
    try:
        texte = page.inner_text("body", timeout=3000)[:5000]
    except Exception:
        return False
    return bool(SIGNES_DE_LIMITE.search(texte))


class Surveillance:
    """Compte les echecs d'ouverture consecutifs sur un site.

    Un formulaire qui n'apparait pas peut venir d'une offre isolee. Deux de
    suite, sur un site qui en affichait juste avant, signalent une limitation :
    on s'arrete au lieu d'essayer les offres suivantes une a une.
    """

    def __init__(self, site):
        self.site = site
        self.echecs = 0

    def succes(self):
        self.echecs = 0

    def echec(self, motif):
        """Note un echec ; leve SiteEnPause si la limite est probable."""
        self.echecs += 1
        if self.echecs >= ECHECS_AVANT_PAUSE:
            fin = poser_pause(self.site, motif)
            raise SiteEnPause(
                f"{NOMS.get(self.site, self.site)} ne repond plus normalement "
                f"({self.echecs} formulaires de suite sans reponse) : arret, "
                f"pas de nouvelle tentative avant {fin:%H:%M}.")

    def limite(self, motif):
        """Le site a dit explicitement qu'il limite."""
        fin = poser_pause(self.site, motif)
        raise SiteEnPause(message_pause(self.site, fin))
