"""Etat d'une candidature apres envoi : statut, canal, relance, journal."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402

offre_id = int(sys.argv[1]) if len(sys.argv) > 1 else 925
conn = db.connect()

r = conn.execute(
    "SELECT o.id, o.entreprise, o.statut, o.contact_email, c.canal, "
    "c.date_envoi, c.date_relance_prevue, c.statut AS statut_cand "
    "FROM candidatures c JOIN offres o ON o.id = c.offre_id "
    "WHERE c.offre_id = ?", (offre_id,)
).fetchone()

if r is None:
    print(f"aucune candidature enregistree pour l'offre {offre_id}")
else:
    print(f"Offre #{r['id']} — {r['entreprise']}")
    print(f"  statut offre    : {r['statut']}")
    print(f"  statut envoi    : {r['statut_cand']}")
    print(f"  canal           : {r['canal']}")
    print(f"  destinataire    : {r['contact_email']}")
    print(f"  envoye le       : {r['date_envoi']}")
    print(f"  relance prevue  : {r['date_relance_prevue']}")

print("\nDerniers evenements :")
for e in conn.execute(
    "SELECT date, type, detail FROM evenements ORDER BY id DESC LIMIT 5"
):
    print(f"  {e['date']}  {e['type']:16} {e['detail']}")

conn.close()
