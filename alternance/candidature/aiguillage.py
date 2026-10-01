"""Envoie les candidatures pretes, chacune par le site dont vient son offre.

    python cli.py postuler --limite 5              repetition a blanc
    python cli.py postuler --limite 5 --confirmer  envoi reel

Le bouton « Envoyer les candidatures » ne lancait que l'envoi La Bonne
Alternance. Une lettre prete sur une offre Welcome to the Jungle n'etait
jamais envoyee, et quand aucune offre LBA n'etait prete, la tache echouait
sur « aucune offre avec lettre prete » alors que la vue en affichait
plusieurs.

L'outil ne sait deposer une candidature que sur deux sites :

    - La Bonne Alternance, quand l'offre porte un destinataire
      (recipient_id). Les offres relayees depuis France Travail n'en ont
      pas : le formulaire LBA ne les accepte pas ;
    - Welcome to the Jungle, avec une session ouverte depuis les Parametres.

Les autres sources (JobTeaser, Apec, Choisir le service public) n'ont pas
de depot automatique : la candidature se fait sur le site, depuis le lien de
l'offre, puis « Marquer envoyee ». Elles sont annoncees, jamais passees sous
silence.
"""

import argparse
import sys

from alternance import db
from alternance.candidature import cadence
from alternance.candidature import confirmation

# Ordre d'envoi, et module de chaque canal. Le module garde ses propres
# options et son propre affichage : on l'appelle exactement comme la ligne
# de commande le ferait.
CANAUX = [
    ("lba", "La Bonne Alternance", "alternance.candidature.lba"),
    ("wttj", "Welcome to the Jungle", "alternance.candidature.wttj"),
]
# Memes criteres que les requetes de lba.py et wttj.py : un ecart ici
# annoncerait une candidature que le canal ne trouverait pas.
CONDITIONS = {
    "lba": "source = 'lba' AND recipient_id IS NOT NULL AND "
           + confirmation.JAMAIS_CANDIDATE,
    "wttj": "source = 'wttj' AND " + confirmation.JAMAIS_CANDIDATE,
}
LIBELLES_SOURCES = {
    "lba": "La Bonne Alternance (offre relayee, sans formulaire)",
    "jobteaser": "JobTeaser",
    "apec": "Apec",
    "service_public": "Choisir le service public",
    "france_travail": "France Travail",
}


def repartition(conn):
    """Combien de lettres pretes chaque canal peut envoyer, et le reste.

    {"canaux": {"lba": 2, "wttj": 1}, "manuelles": {"jobteaser": 1}}
    """
    canaux = {}
    for cle, _, _ in CANAUX:
        canaux[cle] = conn.execute(
            f"SELECT COUNT(*) FROM offres WHERE statut = 'lettre_prete' "
            f"AND {CONDITIONS[cle]}").fetchone()[0]
    automatiques = " OR ".join(f"({c})" for c in CONDITIONS.values())
    manuelles = {}
    for r in conn.execute(
            "SELECT source, COUNT(*) FROM offres WHERE statut = 'lettre_prete' "
            f"AND NOT ({automatiques}) GROUP BY source"):
        manuelles[r[0]] = r[1]
    return {"canaux": canaux, "manuelles": manuelles}


def decrire_manuelles(manuelles):
    return ", ".join(f"{n} {LIBELLES_SOURCES.get(s, s)}"
                     for s, n in sorted(manuelles.items()))


def lancer_canal(module, arguments):
    """Execute le main() d'un canal comme en ligne de commande.

    Renvoie True si le canal s'est termine normalement. Un canal en echec
    n'empeche pas le suivant : une session WTTJ expiree ne doit pas bloquer
    les candidatures LBA.
    """
    import importlib
    argv = sys.argv
    sys.argv = [module] + arguments
    try:
        importlib.import_module(module).main()
        return True
    except SystemExit as e:
        if e.code in (None, 0):
            return True
        print(f"  ECHEC du canal : {e.code}" if isinstance(e.code, str)
              else f"  ECHEC du canal (code {e.code})")
        return False
    except Exception as e:
        print(f"  ECHEC du canal : {type(e).__name__}: {e}")
        return False
    finally:
        sys.argv = argv
        sys.stdout.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=5,
                   help="nombre maximal de candidatures, tous canaux confondus")
    p.add_argument("--confirmer", action="store_true",
                   help="valide reellement les formulaires")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()

    conn = db.connect()
    etat = repartition(conn)
    conn.close()

    if etat["manuelles"]:
        print(f"Sans depot automatique : {decrire_manuelles(etat['manuelles'])}. "
              "Postuler depuis le lien de l'offre, puis « Marquer envoyee ».\n")

    total = sum(etat["canaux"].values())
    if not total:
        # Pas une erreur : il n'y a simplement rien que l'outil sache
        # envoyer. La tache se termine normalement, sur une phrase qui le dit.
        print("Aucune candidature a envoyer automatiquement."
              + (" Les lettres pretes concernent des offres a deposer a la main."
                 if etat["manuelles"] else " Generer les lettres d'abord."))
        return

    reste = args.limite
    echecs = []
    for cle, nom, module in CANAUX:
        n = min(etat["canaux"][cle], reste)
        if not n:
            continue
        # En pause, le canal n'est pas tente : ses candidatures attendent la
        # reprise, et les autres canaux partent quand meme.
        fin = cadence.reprise(cle)
        if fin:
            print(f"--- {nom} : {n} candidature(s) reportee(s). "
                  + cadence.message_pause(cle, fin) + "\n")
            continue
        print(f"--- {nom} : {n} candidature(s)")
        arguments = ["--limite", str(n)]
        if args.confirmer:
            arguments.append("--confirmer")
        if args.headless:
            arguments.append("--headless")
        if not lancer_canal(module, arguments):
            echecs.append(nom)
        reste -= n
        print()
        if reste <= 0:
            break

    if echecs:
        sys.exit("Echec sur : " + ", ".join(echecs)
                 + ". Le detail est au-dessus.")


if __name__ == "__main__":
    main()
