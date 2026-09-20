"""Audit du lot Welcome to the Jungle : verifier que le filtre ne jette rien de bon."""

import json

from alternance import db

conn = db.connect()

print("### Recalees dont l'intitule contient un mot de dev (faux positifs ?)")
rows = conn.execute(
    "SELECT score, entreprise, intitule, score_detail FROM offres "
    "WHERE source='wttj' AND statut='hors_cible' "
    "AND (lower(intitule) LIKE '%dévelop%' OR lower(intitule) LIKE '%develop%' "
    "     OR lower(intitule) LIKE '%stack%' OR lower(intitule) LIKE '%logiciel%') "
    "ORDER BY score DESC"
).fetchall()
for r in rows:
    raison = json.loads(r["score_detail"]).get("mission_technique", "") if r["score_detail"] else ""
    print(f"[{r['score']:4d}] {(r['entreprise'] or '')[:26]:28} {(r['intitule'] or '')[:52]:54} {raison[:34]}")
print(f"  -> {len(rows)} cas\n")

print("### Entreprises WTTJ suspectes d'etre des ecoles mais non taguees")
rows = conn.execute(
    "SELECT DISTINCT entreprise, intitule, statut FROM offres WHERE source='wttj' "
    "AND flag_ecole=0 AND ("
    "  lower(entreprise) LIKE '%campus%' OR lower(entreprise) LIKE '%school%' "
    "  OR lower(entreprise) LIKE '%ecole%' OR lower(entreprise) LIKE '%académ%' "
    "  OR lower(entreprise) LIKE '%formation%' OR lower(entreprise) LIKE '%hack%')"
).fetchall()
for r in rows:
    print(f"  {(r['entreprise'] or '')[:30]:32} {(r['intitule'] or '')[:46]:48} [{r['statut']}]")
print(f"  -> {len(rows)} cas\n")

print("### Repartition du lot WTTJ")
for r in conn.execute(
    "SELECT statut, COUNT(*) n FROM offres WHERE source='wttj' GROUP BY statut ORDER BY n DESC"
):
    print(f"  {r['statut']:12} {r['n']:4}")

conn.close()
