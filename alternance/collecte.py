"""Orchestrateur de collecte : interroge les sources, score, filtre, stocke.

    python cli.py collecte              # toutes les sources disponibles
    python cli.py collecte --source lba
    python cli.py collecte --no-spontanees
"""

import argparse
import json
from collections import Counter
from datetime import datetime

from alternance import config  # noqa: F401  (charge le .env)
from alternance import db
from alternance import filtres as filters
from alternance.sources import apec, france_travail, jobteaser, lba, service_public, wttj


def enrichir(offres):
    """Calcule distance, score et flag ecole. Modifie les dicts en place."""
    compteur = Counter(o.get("entreprise") for o in offres if o.get("entreprise"))

    for o in offres:
        o["distance_km"] = filters.distance_km(o.get("latitude"), o.get("longitude"))
        flag, raison = filters.detecte_ecole(
            o.get("entreprise"), o.get("intitule"), o.get("description"), compteur
        )
        o["flag_ecole"] = flag
        o["flag_ecole_raison"] = raison or None
        tech, raison_tech = filters.est_mission_technique(
            o.get("intitule"), o.get("description"), o.get("genre", "offre")
        )
        score, detail = filters.score_offre(o)
        detail["mission_technique"] = raison_tech
        o["score"] = score

        raison_doute = filters.doute(o, raison, raison_tech)
        detail["doute"] = raison_doute

        # Le score brut sert au tri interne ; le pourcentage est ce que
        # l'utilisateur lit. Les deux sont conserves : le premier permet
        # d'auditer, le second d'arbitrer.
        matching, ventilation = filters.pourcentage_matching(
            detail, o.get("genre", "offre"))
        detail["ventilation"] = ventilation
        o["matching"] = matching
        o["score_detail"] = detail
        o["statut"] = filters.statut_initial(
            score, flag, tech, raison_doute, filters.a_un_canal(o), matching)
    return offres


def collecter(sources, inclure_spontanees=True):
    brut = []
    for nom in sources:
        print(f"\n[{nom}]")
        try:
            if nom == "lba":
                brut += lba.collecte(inclure_spontanees=inclure_spontanees)
            elif nom == "france_travail":
                brut += france_travail.collecte()
            elif nom == "wttj":
                brut += wttj.collecte()
            elif nom == "apec":
                brut += apec.collecter()
            elif nom == "jobteaser":
                brut += jobteaser.collecte()
            elif nom == "service_public":
                brut += service_public.collecte()
        except Exception as e:
            print(f"  ECHEC {nom}: {e}")
    return brut


def rescore(conn):
    """Recalcule score et flag ecole sur toute la base, sans rien recollecter.

    A lancer apres chaque ajustement des criteres. Les offres deja traitees
    (envoyee, entretien...) gardent leur statut : seul le score est mis a jour.
    """
    lignes = conn.execute("SELECT * FROM offres").fetchall()
    offres = [dict(r) for r in lignes]
    enrichir(offres)

    figes = db.STATUTS_FIGES
    verrous = {r["id"] for r in lignes if (r["verrou_manuel"] or 0)}
    for o in offres:
        statut = o["statut"]
        ancien = next(r["statut"] for r in lignes if r["id"] == o["id"])
        # Une offre recuperee a la main garde son statut : c'est une decision
        # humaine, et la rejouer reviendrait a la reecarter aussitot par le
        # filtre qui l'avait sortie.
        if ancien in figes or o["id"] in verrous:
            statut = ancien
        conn.execute(
            "UPDATE offres SET score=?, matching=?, score_detail=?, flag_ecole=?, "
            "flag_ecole_raison=?, distance_km=?, statut=? WHERE id=?",
            (o["score"], o["matching"], json.dumps(o["score_detail"], ensure_ascii=False),
             o["flag_ecole"], o["flag_ecole_raison"], o["distance_km"],
             statut, o["id"]),
        )
    conn.commit()
    print(f"{len(offres)} offres rescorees")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", action="append", dest="sources",
                   choices=["lba", "france_travail", "wttj", "apec", "jobteaser",
                            "service_public"])
    p.add_argument("--no-spontanees", action="store_true")
    p.add_argument("--rescore", action="store_true",
                   help="recalcule scores et filtres sur la base existante")
    args = p.parse_args()
    # France Travail est exclu par defaut : son bouton "Postuler" ouvre un
    # menu "Choisissez le partenaire" qui redirige vers directemploi,
    # makesense, jobaffinity, meteojob... Aucun parcours unique possible.
    # Le connecteur reste disponible via --source france_travail.
    sources = args.sources or ["lba", "wttj", "apec", "jobteaser",
                               "service_public"]

    conn = db.init()

    if args.rescore:
        rescore(conn)
        print(f"\nEtat de la base : {db.stats(conn)}")
        conn.close()
        return

    offres = collecter(sources, inclure_spontanees=not args.no_spontanees)
    print(f"\n{len(offres)} entrees collectees (doublons inclus)")

    enrichir(offres)

    nouvelles = ecoles = retenues = doublons = 0
    for o in offres:
        # Une offre deja presente sous une autre source n'est pas rejetee en
        # silence : on la compte et on la signale, pour que le total colle.
        jumelle = db.doublon_existant(conn, o)
        if jumelle is not None:
            doublons += 1
            db.log(conn, jumelle["id"], "doublon",
                   f"egalement publiee sur {o['source']}")
            continue
        if db.upsert_offre(conn, o):
            nouvelles += 1
            if o["flag_ecole"]:
                ecoles += 1
            elif o["statut"] == "a_traiter":
                retenues += 1
    conn.commit()

    conn.execute(
        "INSERT INTO runs (date, source, nb_collectees, nb_nouvelles, nb_ecoles, "
        "nb_retenues, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), ",".join(sources),
         len(offres), nouvelles, ecoles, retenues,
         json.dumps({"spontanees": not args.no_spontanees})),
    )
    conn.commit()

    print(f"\n  nouvelles      : {nouvelles}")
    print(f"  doublons       : {doublons} (deja presentes via une autre source)")
    print(f"  ecartees ecole : {ecoles}")
    print(f"  retenues       : {retenues}")
    print(f"\nEtat de la base : {db.stats(conn)}")

    top = conn.execute(
        "SELECT score, entreprise, intitule, lieu, distance_km FROM offres "
        "WHERE statut = 'a_traiter' ORDER BY score DESC LIMIT 15"
    ).fetchall()
    if top:
        print("\nMeilleures offres a traiter :")
        for r in top:
            d = f"{r['distance_km']}km" if r["distance_km"] is not None else "?"
            print(f"  {r['score']:4d}  {(r['entreprise'] or '?')[:28]:28} "
                  f"{(r['intitule'] or '')[:52]:52} {d}")
    conn.close()


if __name__ == "__main__":
    main()
