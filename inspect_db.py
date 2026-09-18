"""Inspection rapide de la base : ecoles detectees, ecartees, repartition."""

import sys

import db

conn = db.connect()
quoi = sys.argv[1] if len(sys.argv) > 1 else "ecole"

if quoi == "ecole":
    print("--- Detectees comme organismes de formation ---")
    for r in conn.execute(
        "SELECT entreprise, intitule, flag_ecole_raison FROM offres WHERE flag_ecole=1"
    ):
        print(f"{(r['entreprise'] or '')[:38]:40} | {(r['flag_ecole_raison'] or '')[:78]}")

elif quoi == "ecarte":
    print("--- Ecartees par le score ---")
    for r in conn.execute(
        "SELECT score, entreprise, intitule FROM offres WHERE statut='ecarte' "
        "ORDER BY score DESC"
    ):
        print(f"{r['score']:5d}  {(r['entreprise'] or '')[:32]:34} {(r['intitule'] or '')[:58]}")

elif quoi == "offres":
    print("--- Offres publiees retenues (hors spontanees) ---")
    for r in conn.execute(
        "SELECT score, entreprise, intitule, distance_km FROM offres "
        "WHERE statut='a_traiter' AND genre='offre' ORDER BY score DESC"
    ):
        d = f"{r['distance_km']}km" if r["distance_km"] is not None else "?"
        print(f"{r['score']:5d}  {(r['entreprise'] or '')[:30]:32} "
              f"{(r['intitule'] or '')[:52]:54} {d}")

elif quoi == "horscible":
    print("--- Ecartees : mission non technique ---")
    for r in conn.execute(
        "SELECT score, entreprise, intitule, score_detail FROM offres "
        "WHERE statut='hors_cible' ORDER BY score DESC"
    ):
        raison = ""
        if r["score_detail"]:
            import json
            raison = json.loads(r["score_detail"]).get("mission_technique", "")
        print(f"{r['score']:5d}  {(r['entreprise'] or '')[:26]:28} "
              f"{(r['intitule'] or '')[:48]:50} {raison[:32]}")

elif quoi == "rejets":
    import json as _json
    print("=" * 100)
    print("TOUT CE QUI EST ECARTE - a relire pour ajuster les filtres")
    print("=" * 100)
    for statut, libelle in [
        ("hors_cible", "MISSION NON TECHNIQUE (veto sur le titre)"),
        ("ecarte", "SCORE INSUFFISANT (seuil 25)"),
        ("ecole", "ORGANISME DE FORMATION"),
    ]:
        rows = conn.execute(
            "SELECT score, entreprise, intitule, lieu, distance_km, genre, "
            "score_detail, flag_ecole_raison FROM offres WHERE statut=? "
            "ORDER BY score DESC", (statut,)
        ).fetchall()
        print(f"\n### {libelle} — {len(rows)} offres\n")
        for r in rows:
            d = f"{r['distance_km']}km" if r["distance_km"] is not None else "?"
            print(f"[{r['score']:4d}] {r['entreprise'] or '?'}  ({d}, {r['genre']})")
            print(f"       {r['intitule'] or ''}")
            if statut == "ecole":
                print(f"       -> {r['flag_ecole_raison']}")
            elif r["score_detail"]:
                det = _json.loads(r["score_detail"])
                if statut == "hors_cible":
                    print(f"       -> {det.get('mission_technique', '')}")
                else:
                    print(f"       -> mots-cles={det.get('mots_cles')} "
                          f"negatifs={det.get('negatifs')} "
                          f"prox={det.get('proximite')} duree={det.get('duree')} "
                          f"naf={det.get('secteur_naf')}")
                    if det.get("negatifs_trouves"):
                        print(f"          penalise par : {det['negatifs_trouves']}")
            print()

elif quoi == "partenaires":
    print("--- Partenaires deja agreges par La Bonne Alternance ---")
    for r in conn.execute(
        "SELECT partner_label, COUNT(*) n FROM offres GROUP BY partner_label "
        "ORDER BY n DESC"
    ):
        print(f"  {(r['partner_label'] or '(aucun)'):24} {r['n']:4}")

elif quoi == "resume":
    print("Statuts :", db.stats(conn))
    for r in conn.execute(
        "SELECT genre, COUNT(*) n, ROUND(AVG(score)) moy FROM offres GROUP BY genre"
    ):
        print(f"  {r['genre']:12} {r['n']:4} offres, score moyen {r['moy']}")

conn.close()
