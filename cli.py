# -*- coding: utf-8 -*-
"""Point d'entree unique de l'outil.

    python cli.py                      la liste des commandes
    python cli.py interface            ouvre le tableau de bord
    python cli.py collecte             interroge les cinq sources
    python cli.py lettres --limite 5   redige les lettres

Il y avait douze scripts a la racine, chacun avec ses propres options et sa
propre facon de s'appeler. Une seule porte d'entree evite d'avoir a retenir
lequel fait quoi, et donne un point unique ou les lister.

Les options n'ont pas change : tout ce qui suit le nom de la commande est
transmis tel quel au module concerne. `python cli.py lettres --limite 5
--force` fait exactement ce que faisait `python generer_lettres.py --limite 5
--force`.
"""

import importlib
import sys

# commande -> (module, fonction, resume affiche dans l'aide)
COMMANDES = {
    "interface":      ("alternance.interface.serveur", "servir",
                       "ouvre le tableau de bord sur 127.0.0.1:5000"),
    "collecte":       ("alternance.collecte", "main",
                       "interroge les sources, note et classe les offres"),
    "reconnaissance": ("alternance.candidature.reconnaissance", "main",
                       "releve ce que chaque formulaire accepte"),
    "lettres":        ("alternance.redaction.lettres", "main",
                       "redige les lettres des meilleures offres"),
    "pieces":         ("alternance.redaction.pieces", "main",
                       "fabrique les PDF joints a une candidature"),
    "postuler-lba":   ("alternance.candidature.lba", "main",
                       "depose une candidature sur La Bonne Alternance"),
    "postuler-wttj":  ("alternance.candidature.wttj", "main",
                       "depose une candidature sur Welcome to the Jungle"),
    "envoyer":        ("alternance.courrier.envoi", "main",
                       "envoie une candidature par email"),
    "connecter":      ("alternance.candidature.session", "main",
                       "ouvre un navigateur pour se connecter a un site"),
    "graph":          ("alternance.courrier.graph", "main",
                       "connecte la boite universitaire par code d'appareil"),
    "geocode":        ("alternance.geocode", "main",
                       "coordonnees d'une adresse"),
    "base":           ("outils.inspect_db", "main",
                       "etat de la base : repartition, rejets, motifs"),
}


def aide():
    print("Recherche d'alternance et de stage automatisee.\n")
    print("Usage : python cli.py <commande> [options]\n")
    largeur = max(len(c) for c in COMMANDES)
    for nom, (_, _, resume) in COMMANDES.items():
        print(f"  {nom:<{largeur}}  {resume}")
    print("\nLes options d'une commande s'obtiennent avec --help :")
    print("  python cli.py lettres --help")
    print("\nRien n'est envoye sans --confirmer.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        aide()
        return 0

    commande = sys.argv[1]
    if commande not in COMMANDES:
        print(f"Commande inconnue : {commande}\n")
        aide()
        return 2

    nom_module, fonction, _ = COMMANDES[commande]
    module = importlib.import_module(nom_module)

    # Le module lit sys.argv avec son propre argparse : on lui presente une
    # ligne de commande dont le nom de programme est « cli.py <commande> »,
    # pour que son --help et ses messages d'erreur collent a l'appel reel.
    # Aucune option n'a eu besoin d'etre redeclaree ici.
    sys.argv = [f"cli.py {commande}"] + sys.argv[2:]
    return getattr(module, fonction)() or 0


if __name__ == "__main__":
    sys.exit(main())
