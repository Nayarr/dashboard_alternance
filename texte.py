"""Normalisation de texte, partagee par le scoring et les parametres.

Isolee dans son propre module parce que `config` ne peut pas importer
`filters` (qui l'importe deja) alors que les deux ont besoin de la meme
regle : minuscules sans accents, pour que les motifs n'aient jamais a gerer
les deux graphies.
"""

import unicodedata


def normalise(texte):
    if not texte:
        return ""
    texte = unicodedata.normalize("NFD", str(texte).lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")
