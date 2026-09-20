# -*- coding: utf-8 -*-
"""Verifie qu'une description de proposition suit le gabarit.

    python outils/verifier_pr.py             # lit la description sur stdin
    python outils/verifier_pr.py fichier.md

Le gabarit vit dans .github/pull_request_template.md. Les quatre titres
attendus y sont definis une seule fois, ici : un gabarit que personne ne
verifie se vide en trois semaines.

Ce qui est refuse :
    - un titre manquant
    - une section vide, ou reduite aux commentaires d'aide du gabarit
    - une description qui n'est que le gabarit recopie sans etre rempli

Ce qui n'est pas verifie : la qualite de ce qui est ecrit. Aucun script ne
sait faire la difference entre une explication et une phrase de remplissage.
"""

import re
import sys
from pathlib import Path

SECTIONS = [
    ("Ce que ça change", 40),
    ("Pourquoi", 40),
    ("Comment c'est vérifié", 30),
    ("Risques et limites", 10),
]


def _sans_commentaires(texte):
    return re.sub(r"<!--.*?-->", "", texte, flags=re.S)


def _normalise_titre(t):
    """Compare sans accents ni casse : « verifie » doit passer aussi."""
    remplacements = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    return t.lower().translate(remplacements).strip()


def verifier(description):
    problemes = []
    texte = _sans_commentaires(description or "")

    # La checklist du pied est separee par une ligne horizontale. Sans cette
    # coupe, ses lignes repliees tombaient dans la derniere section et la
    # faisaient passer pour remplie.
    coupe = re.search(r"^\s*-{3,}\s*$", texte, flags=re.M)
    if coupe:
        texte = texte[:coupe.start()]

    if not texte.strip():
        return ["la description est vide : le gabarit "
                ".github/pull_request_template.md est a remplir"]

    # Decoupe sur les titres de niveau 2.
    blocs = {}
    courant = None
    for ligne in texte.splitlines():
        titre = re.match(r"^\s*##\s+(.+?)\s*$", ligne)
        if titre:
            courant = _normalise_titre(titre.group(1))
            blocs[courant] = []
        elif courant:
            blocs[courant].append(ligne)

    for attendu, mini in SECTIONS:
        cle = _normalise_titre(attendu)
        if cle not in blocs:
            problemes.append(f"section manquante : « ## {attendu} »")
            continue
        corps = "\n".join(blocs[cle]).strip()
        # Une ligne de separation ou une case a cocher ne compte pas comme
        # du contenu : on ne garde que la prose.
        corps = re.sub(r"^\s*(-\s*\[[ x]\].*|---+)\s*$", "", corps,
                       flags=re.M).strip()
        if len(corps) < mini:
            problemes.append(
                f"section « {attendu} » vide ou trop courte "
                f"({len(corps)} caracteres, {mini} attendus)")

    return problemes


def main():
    if len(sys.argv) > 1:
        description = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        description = sys.stdin.read()

    problemes = verifier(description)
    if problemes:
        print("La description ne suit pas le gabarit :\n")
        for p in problemes:
            print("  -", p)
        print("\nGabarit : .github/pull_request_template.md")
        return 1

    print("Description conforme au gabarit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
