"""Le parcours du candidat : ce que le redacteur sait de ses experiences,
projets et competences. C'est sa seule source : ce qui n'y figure pas ne
sera pas ecrit.

Trois sources, par ordre de priorite :

  1. data/parcours.md, ecrit ou corrige dans la page Parametres ;
  2. prompts/systeme_lettre.md, l'ancienne methode, un fichier edite a la
     main. Respecte tant qu'il est rempli, pour ne rien casser chez qui s'en
     servait deja ;
  3. le CV depose, lu automatiquement.

Le parcours ne venait autrefois que de la deuxieme. Qui s'en tenait a
l'interface n'avait aucun moyen de le remplir, et aucune lettre n'etait
possible alors que son CV, deja depose, contenait exactement ces faits.
"""

import re

from alternance import chemins
from alternance import config

BASE = config.RACINE
# Sous data/ : personnel, exclu du git comme le reste des reglages.
FICHIER = BASE / "data" / "parcours.md"
SYSTEME = BASE / "prompts" / "systeme_lettre.md"
GABARIT = BASE / "prompts" / "systeme_lettre.exemple.md"
# Lignes du gabarit que personne ne garde en remplissant son parcours. La
# premiere est celle de l'ancien gabarit, encore recopie sur certains postes.
MARQUEURS_GABARIT = ("Prénom Nom, 20 ans.",
                     "Développement : langages et frameworks réellement pratiqués.")
# Prefixe reconnu par journal.expliquer : sans lui, l'interface affichait
# « Arret inattendu, sans message d'erreur » au-dessus du message lui-meme.
REFUS = "Lettres impossibles : "
# En dessous, le PDF est une image (scan, export aplati) : pypdf n'en tire
# que des bribes, et une lettre ecrite dessus inventerait le reste. Un CV
# d'une page en texte en donne plus de 1500.
CV_MINIMUM = 300
CV_MAXIMUM = 12000

DEBUT_SECTION = "# Le candidat"
FIN_SECTION = "# Comment écrire"

ENTETE_MANUEL = (
    "# Le candidat — son parcours, seule source de faits\n\n"
    "Ecrit par le candidat lui-meme. Experiences, projets, competences, "
    "langues : tout ce qui n'y figure pas n'existe pas pour toi. Pour "
    "l'identite, le contact et les dates, le bloc « Identité du candidat » "
    "fait foi.\n\n")
ENTETE_CV = (
    "# Le candidat — son CV, seule source de faits sur son parcours\n\n"
    "Texte extrait automatiquement du PDF de son CV. La mise en page est "
    "perdue : des colonnes peuvent se meler. Reconstitue le sens, n'ajoute "
    "rien. Experiences, projets, competences, langues : tout ce qui n'y "
    "figure pas n'existe pas pour toi. Pour l'identite, le contact et les "
    "dates, le bloc « Identité du candidat » fait foi.\n\n"
    "Les qualites que le CV revendique (rigueur, creativite...) ne se "
    "recopient pas : montre-les par un fait, ou tais-les.\n\n")


def manuel():
    """Le parcours saisi dans les Parametres, ou None."""
    if not FICHIER.exists():
        return None
    return FICHIER.read_text(encoding="utf-8").strip() or None


def historique():
    """systeme_lettre.md s'il a ete rempli, sinon None.

    Absent ou encore au gabarit, il ne compte pas.
    """
    if not SYSTEME.exists():
        return None
    texte = SYSTEME.read_text(encoding="utf-8")
    if any(m in texte for m in MARQUEURS_GABARIT):
        return None
    return texte


def section_candidat(prompt):
    """La partie parcours d'un prompt complet, sans les consignes d'ecriture.

    Sert a afficher un systeme_lettre.md historique dans la page Parametres :
    le candidat y corrige ses faits, pas les regles du redacteur.
    """
    debut = prompt.find(DEBUT_SECTION)
    fin = prompt.find(FIN_SECTION)
    if debut == -1 or fin <= debut:
        return prompt.strip()
    section = prompt[debut:fin]
    # Le titre de section est celui du gabarit, pas un fait du candidat.
    return section.split("\n", 1)[1].strip() if "\n" in section else ""


def nettoyer_cv(texte):
    """Rend l'extraction lisible dans une zone de texte.

    Les puces des modeles de CV ressortent en fleches isolees, et les
    espacements en suites de blancs.
    """
    lignes = []
    for ligne in texte.splitlines():
        ligne = re.sub(r"[ \t]+", " ", ligne.replace("→", "")).strip()
        if ligne:
            lignes.append(ligne)
    return "\n".join(lignes)


def texte_du_cv():
    """(fichier, texte) du CV depose, ou une erreur qui dit quoi deposer.

    Relu a chaque fois : chemins.CV est fige a l'import, or le CV peut etre
    remplace depuis l'interface pendant que le serveur tourne.
    """
    cv = chemins.trouver_cv()
    if not cv.exists():
        raise RuntimeError(
            REFUS + "aucun CV depose, et aucun parcours saisi. Deposer son CV "
            "dans la page Parametres : le parcours s'en remplit tout seul.")
    try:
        import logging
        from pypdf import PdfReader
        # pypdf avertit sur stderr pour chaque ecart de format, et la tache
        # l'afficherait dans le journal de l'interface comme une erreur.
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        pages = PdfReader(str(cv)).pages
        texte = "\n".join((p.extract_text() or "") for p in pages)
    except Exception as e:
        raise RuntimeError(
            REFUS + f"le CV {cv.name} n'a pas pu etre lu ({e}). Le deposer "
            "a nouveau, exporte en PDF depuis Word, Canva ou LaTeX, ou "
            "ecrire son parcours a la main dans la page Parametres.") from None
    texte = nettoyer_cv(texte)
    if len(texte) < CV_MINIMUM:
        raise RuntimeError(
            REFUS + f"le CV {cv.name} ne contient presque pas de texte "
            f"lisible ({len(texte)} caracteres) : c'est sans doute une image "
            "ou un scan. L'exporter en PDF depuis l'outil qui a servi a le "
            "creer, ou ecrire son parcours a la main dans la page "
            "Parametres.")
    return cv, texte[:CV_MAXIMUM]


def lire():
    """Ce que la page Parametres affiche : le texte et d'ou il vient."""
    cv = chemins.trouver_cv()
    etat = {"texte": "", "source": "aucun", "erreur": None,
            "cv": cv.name if cv.exists() else None}
    texte = manuel()
    if texte:
        return dict(etat, texte=texte, source="manuel")
    texte = historique()
    if texte:
        return dict(etat, texte=section_candidat(texte), source="fichier")
    try:
        _, texte = texte_du_cv()
    except RuntimeError as e:
        return dict(etat, erreur=str(e).removeprefix(REFUS))
    return dict(etat, texte=texte, source="cv")


def enregistrer(texte):
    """Ecrit le parcours saisi. Vide, il rend la main au CV."""
    texte = (texte or "").strip()
    if not texte:
        return oublier()
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(texte + "\n", encoding="utf-8")


def oublier():
    """Revient au CV. La saisie est mise de cote, pas supprimee."""
    if FICHIER.exists():
        FICHIER.replace(FICHIER.with_name("parcours.precedent.md"))


def avec_gabarit(section):
    """Le gabarit, dont la section candidat est remplacee par `section`.

    Le reste - comment ecrire, interdits, format de sortie - est generique
    et s'applique tel quel.
    """
    gabarit = GABARIT.read_text(encoding="utf-8")
    gabarit = re.sub(r"<!--.*?-->\s*", "", gabarit, flags=re.S)
    debut = gabarit.find(DEBUT_SECTION)
    fin = gabarit.find(FIN_SECTION)
    if debut == -1 or fin == -1:
        # Gabarit reformule : mieux vaut un prompt un peu redondant qu'une
        # section candidat ecrasee sans le savoir.
        return gabarit + "\n\n" + section
    return gabarit[:debut] + section + "\n\n" + gabarit[fin:]


def prompt():
    """Parcours et consignes d'ecriture, ou une erreur qui dit quoi faire."""
    texte = manuel()
    if texte:
        return avec_gabarit(ENTETE_MANUEL + texte)
    texte = historique()
    if texte:
        return texte
    cv, texte = texte_du_cv()
    return avec_gabarit(ENTETE_CV + f"<cv fichier=\"{cv.name}\">\n{texte}\n</cv>")
