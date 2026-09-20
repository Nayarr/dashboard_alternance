# -*- coding: utf-8 -*-
"""Garde-fou du depot : rien de personnel ni de secret ne doit etre versionne.

    python outils/verifier_depot.py

Sort en code 1 a la premiere infraction. C'est ce que la CI execute sur chaque
proposition de modification, avant meme les tests : un CV ou un jeton pousse
par erreur ne se retire pas d'un historique public, il se revoque.

Le controle est structurel - noms de fichiers, formes de secrets, regles du
.gitignore - et non une liste de donnees personnelles. Ecrire ici l'adresse ou
le telephone a proteger reviendrait a les publier dans le fichier meme qui est
cense les garder hors du depot.
"""

import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# Fichiers qui ne doivent jamais etre suivis, par motif de chemin.
INTERDITS = [
    (r"^\.env$", "secrets reels ; seul .env.exemple est versionne"),
    (r"^token.*\.json$", "jeton d'authentification"),
    (r"^credentials.*\.json$", "identifiants de service"),
    (r"^identite_locale\.py$", "identite reelle"),
    (r"^prompts/systeme_lettre\.md$",
     "parcours et projets reels ; seul le .exemple.md est versionne"),
    (r"^templates/cv/.+", "CV, photo ou source LaTeX"),
    (r"^templates/dossier/.+", "dossier de motivation"),
    (r"^data/(?!$)", "base, sessions, profils de navigateur, reglages"),
    (r"^lettres/.+", "lettres redigees"),
    (r".*\.(db|sqlite3)$", "base de donnees"),
    (r".*\.(pem|key|p12|pfx)$", "cle privee"),
]
# Un .gitkeep garde un dossier vide : il ne porte rien.
TOLERES = re.compile(r"(^|/)\.gitkeep$")

# Formes de secrets reconnaissables, cherchees dans le contenu.
# .env.exemple porte volontairement une cle d'API partagee : il est exclu, la
# decision est documentee dans le README.
SECRETS = [
    (r"sk-ant-[a-z0-9-]{10,}", "jeton Anthropic"),
    (r"ghp_[A-Za-z0-9]{20,}", "jeton GitHub"),
    (r"AKIA[0-9A-Z]{16}", "cle AWS"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "cle privee"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "jeton Slack"),
]
EXCLUS_DU_SCAN = {".env.exemple"}

# Regles que .gitignore doit porter : sans elles, le prochain fichier depose
# au mauvais endroit partirait sans que personne ne le remarque.
REGLES_ATTENDUES = [".env", "data/", "lettres/", "prompts/systeme_lettre.md",
                    "templates/cv/", "templates/dossier/", "token"]


def suivis():
    """Ce qui est versionne, PLUS ce qui le serait au prochain `git add`.

    `git ls-files` seul ne voit que les fichiers deja suivis. Un fichier neuf
    echappait donc au controle tant qu'il n'etait pas stage : lance avant
    `git add`, le garde-fou disait « aucun secret », et la CI trouvait le
    probleme une fois le commit pousse. C'est exactement l'ordre inverse de
    celui qui sert a quelque chose.

    --others ajoute les fichiers non suivis, --exclude-standard retire ceux
    que le .gitignore couvre : il reste ce qui partirait vraiment.
    """
    sortie = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=BASE, capture_output=True, text=True, check=True)
    # --cached et --others peuvent nommer le meme chemin.
    return sorted({l.strip() for l in sortie.stdout.splitlines() if l.strip()})


def main():
    fichiers = suivis()
    problemes = []

    for chemin in fichiers:
        if TOLERES.search(chemin):
            continue
        for motif, raison in INTERDITS:
            if re.match(motif, chemin):
                problemes.append(f"{chemin} : {raison}")
                break

    for chemin in fichiers:
        if chemin in EXCLUS_DU_SCAN:
            continue
        f = BASE / chemin
        try:
            contenu = f.read_text(encoding="utf-8", errors="ignore")
        except (OSError, IsADirectoryError):
            continue
        for motif, quoi in SECRETS:
            trouve = re.search(motif, contenu)
            if trouve:
                problemes.append(
                    f"{chemin} : {quoi} en clair "
                    f"({trouve.group(0)[:12]}...)")

    gitignore = (BASE / ".gitignore")
    texte = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    for regle in REGLES_ATTENDUES:
        if regle not in texte:
            problemes.append(f".gitignore : regle manquante pour « {regle} »")

    if problemes:
        print("Le depot contient ce qui ne devrait pas y etre :\n")
        for p in problemes:
            print("  -", p)
        print(f"\n{len(problemes)} probleme(s). Voir la section "
              "« Donnees personnelles » du README.")
        return 1

    print(f"{len(fichiers)} fichiers verifies : aucun secret, "
          "aucune piece personnelle, .gitignore complet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
