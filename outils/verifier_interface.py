# -*- coding: utf-8 -*-
"""Coherence entre app.js, index.html et les routes du serveur.

    python outils/verifier_interface.py

Trois erreurs silencieuses que rien d'autre n'attrape, parce qu'elles ne font
pas planter le serveur :

    - `$("#quelque-chose")` sur un identifiant qui n'existe nulle part rend
      `null`, et la ligne suivante leve dans la console que personne ne lit ;
    - un appel a une route jamais declaree renvoie la page d'accueil ou un
      404, sans que l'interface le signale ;
    - une vue presente dans la navigation mais refusee par l'API donne un
      onglet mort.

Sort en code 1 a la premiere incoherence.
"""

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INTERFACE = BASE / "alternance" / "interface"
JS = (INTERFACE / "statique" / "app.js").read_text(encoding="utf-8")
HTML = (INTERFACE / "statique" / "index.html").read_text(encoding="utf-8")
PY = (INTERFACE / "serveur.py").read_text(encoding="utf-8")


def identifiants_disponibles():
    """Ceux du HTML, plus ceux que le JS fabrique lui-meme.

    Les blocs poses par innerHTML - la carte d'un compte, le detail d'une
    offre - n'existent pas dans index.html et sont pourtant legitimes.
    """
    ids = set(re.findall(r'id="([^"{}$]+)"', HTML))
    ids |= set(re.findall(r'id="([^"{}$]+)"', JS))
    return ids


def identifiants_cites():
    return (set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', JS))
            | set(re.findall(r'querySelector\("#([A-Za-z0-9_-]+)"\)', JS)))


def routes_declarees():
    return set(re.findall(r'@app\.route\("([^"]+)"', PY))


def routes_appelees():
    chemins = set(re.findall(r'api\(\s*[`"\']([^`"\'?]+)', JS))
    chemins |= set(re.findall(r'fetch\(\s*[`"\']([^`"\'?]+)', JS))
    return {c for c in chemins if c.startswith("/")}


def route_couverte(appel, declarees):
    # Les gabarits JS (`/api/offre/${id}/statut`) deviennent des jokers, tout
    # comme les convertisseurs Flask (<int:offre_id>).
    concret = re.sub(r"\$\{[^}]+\}", "X", appel).rstrip("/")
    for r in declarees:
        motif = re.sub(r"<[^>]+>", "[^/]+", r).rstrip("/")
        if re.fullmatch(motif, concret):
            return True
    return False


def main():
    problemes = []

    disponibles = identifiants_disponibles()
    for cible in sorted(identifiants_cites() - disponibles):
        problemes.append(
            f"app.js interroge #{cible}, absent du HTML et jamais cree")

    declarees = routes_declarees()
    for appel in sorted(routes_appelees()):
        if not route_couverte(appel, declarees):
            problemes.append(f"app.js appelle {appel}, route non declaree")

    # Les statuts cites par le JS - vues de rebut, suites du pipeline -
    # doivent exister cote serveur. Une faute de frappe dans REBUTS retire
    # silencieusement un bouton, sans erreur nulle part.
    #
    # La liste est lue dans le source et non importee : importer le serveur
    # tirerait Flask, et ce controle doit rester purement statique. Il tourne
    # en CI dans un job sans dependances installees, expres, pour qu'une
    # incoherence d'interface se voie en quelques secondes.
    bloc_vues = re.search(r"^VUES = \[(.*?)^\]", PY, re.S | re.M)
    if not bloc_vues:
        problemes.append("liste VUES introuvable dans le serveur")
        connus = set()
    else:
        connus = set(re.findall(r'"cle":\s*"([a-z_]+)"', bloc_vues.group(1)))

    bloc_rebuts = re.search(r"const REBUTS = \[([^\]]*)\]", JS)
    cites = set(re.findall(r'"([a-z_]+)"', bloc_rebuts.group(1))) if bloc_rebuts else set()

    bloc_suites = re.search(r"const SUITES = \{(.*?)\n\};", JS, re.S)
    if bloc_suites:
        cites |= set(re.findall(r"^  ([a-z_]+):", bloc_suites.group(1), re.M))
        cites |= set(re.findall(r'statut: "([a-z_]+)"', bloc_suites.group(1)))

    for statut in sorted(cites - connus):
        problemes.append(f"app.js cite le statut « {statut} », inconnu du serveur")

    if problemes:
        print("Incoherences dans l'interface :\n")
        for p in problemes:
            print("  -", p)
        return 1

    print(f"{len(identifiants_cites())} identifiants et "
          f"{len(routes_appelees())} routes verifies : coherent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
