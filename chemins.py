"""Chemins des pieces d'une candidature, calcules au meme endroit pour tous.

Historique du defaut corrige ici : le dossier de lettre etait indexe sur le seul
nom d'entreprise. Deux offres distinctes chez le meme employeur (Docaposte avait
un poste IA et un poste Java) partageaient donc le meme fichier, et la seconde
candidature reutilisait la lettre de la premiere. Le dossier est desormais
indexe sur l'identifiant de l'offre, qui est unique par definition.

Cette logique etait dupliquee dans generer_lettres, generer, postuler_lba,
postuler_lba et postuler_wttj : plusieurs definitions de slug() a maintenir en
parallele, donc cinq occasions de diverger.
"""

import re
import unicodedata
from pathlib import Path

BASE = Path(__file__).parent
LETTRES = BASE / "lettres"
DOSSIER_CV = BASE / "templates" / "cv"
DOSSIER_TYPE = BASE / "templates" / "dossier" / "dossier_base.docx"


def trouver_cv():
    """Le PDF depose dans templates/cv, quel que soit son nom.

    Le nom etait ecrit en dur dans cinq fichiers, ce qui rendait l'outil
    inutilisable par quelqu'un d'autre sans renommer son CV. Or ce nom part
    chez le recruteur en piece jointe : il doit rester celui du candidat.

    Le plus recent l'emporte, pour qu'un depot depuis l'interface prenne effet
    sans avoir a supprimer l'ancien. Aucun PDF present : on renvoie le chemin
    par defaut, qui n'existe pas, et les appelants testent .exists().
    """
    pdfs = sorted(DOSSIER_CV.glob("*.pdf"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    return pdfs[0] if pdfs else DOSSIER_CV / "cv.pdf"


CV = trouver_cv()


def slug(texte):
    """Minuscules sans accents, non alphanumeriques replies sur un underscore."""
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_") or "entreprise"


def dossier_candidature(offre, creer=False):
    """Repertoire des pieces d'UNE offre : <id>_<entreprise>.

    `offre` est une ligne sqlite3.Row ou un dict portant au moins id et
    entreprise.
    """
    chemin = LETTRES / f"{offre['id']}_{slug(offre['entreprise'])}"
    if creer:
        chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def lettre_txt(offre):
    return dossier_candidature(offre) / "lettre.txt"


def lettre_pdf(offre):
    return dossier_candidature(offre) / "lettre.pdf"


def lire_lettre(offre):
    """Texte de la lettre, ou None si elle n'a pas encore ete redigee."""
    fichier = lettre_txt(offre)
    return fichier.read_text(encoding="utf-8").strip() if fichier.exists() else None
