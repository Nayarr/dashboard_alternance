"""Vide le vivier pour repartir sur une collecte fraiche.

La base est sauvegardee au prealable dans data/archives/ par l'appelant.
Les tables sont videes, pas supprimees : le schema reste en place.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alternance import db  # noqa: E402

conn = db.init()
avant = conn.execute("SELECT COUNT(*) n FROM offres").fetchone()["n"]

for table in ("candidatures", "evenements", "offres", "runs"):
    conn.execute(f"DELETE FROM {table}")
conn.execute("DELETE FROM sqlite_sequence WHERE name IN "
             "('offres','candidatures','evenements','runs')")
conn.commit()
conn.execute("VACUUM")
conn.close()

print(f"{avant} offres supprimees, base prete pour une collecte fraiche")
