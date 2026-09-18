"""Schema SQLite et acces base. Source de verite du suivi de candidatures."""

import json
import sqlite3
from datetime import datetime

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS offres (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    uid               TEXT UNIQUE NOT NULL,
    source            TEXT NOT NULL,
    source_id         TEXT,
    partner_label     TEXT,
    genre             TEXT NOT NULL DEFAULT 'offre',

    entreprise        TEXT,
    siret             TEXT,
    taille            TEXT,
    naf               TEXT,
    site_web          TEXT,
    -- URL du logo quand la source en fournit un (WTTJ). LBA n'en a pas :
    -- l'interface genere alors un monogramme, plutot que d'appeler un
    -- service de favicons tiers qui recevrait la liste des cibles.
    logo_url          TEXT,

    intitule          TEXT,
    description       TEXT,
    url_offre         TEXT,
    url_candidature   TEXT,
    recipient_id      TEXT,
    contact_email     TEXT,
    contact_telephone TEXT,

    lieu              TEXT,
    latitude          REAL,
    longitude         REAL,
    distance_km       REAL,

    contrat_type      TEXT,
    contrat_duree     INTEGER,
    date_publication  TEXT,
    date_collecte     TEXT NOT NULL,

    score             INTEGER DEFAULT 0,
    -- Adequation 0-100 derivee de score_detail par filters.pourcentage_matching.
    -- Le score brut reste stocke pour l'audit, mais c'est ce pourcentage qui
    -- est affiche : un score de 220 n'a pas de referentiel lisible.
    matching          INTEGER DEFAULT 0,

    -- Empreinte entreprise+intitule, commune a toutes les sources. Sert a
    -- reperer la meme offre publiee sur deux sites : uid, lui, contient la
    -- source et ne peut donc pas les rapprocher.
    empreinte         TEXT,

    -- Pose a 1 quand l'offre est recuperee a la main depuis l'interface. Un
    -- rescore respecte ce verrou : sans lui, le filtre qui avait ecarte
    -- l'offre la reecarterait au calcul suivant.
    verrou_manuel     INTEGER DEFAULT 0,
    score_detail      TEXT,
    flag_ecole        INTEGER DEFAULT 0,
    flag_ecole_raison TEXT,

    statut            TEXT NOT NULL DEFAULT 'a_traiter',
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_offres_statut ON offres(statut);
CREATE INDEX IF NOT EXISTS idx_offres_score  ON offres(score DESC);
CREATE INDEX IF NOT EXISTS idx_offres_matching ON offres(matching DESC);
CREATE INDEX IF NOT EXISTS idx_offres_ecole  ON offres(flag_ecole);
CREATE INDEX IF NOT EXISTS idx_offres_entreprise ON offres(entreprise);

CREATE TABLE IF NOT EXISTS candidatures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    offre_id            INTEGER NOT NULL REFERENCES offres(id),
    canal               TEXT,
    lettre_path         TEXT,
    cv_path             TEXT,
    dossier_path        TEXT,
    recommandation      TEXT,
    date_preparation    TEXT,
    date_envoi          TEXT,
    statut              TEXT NOT NULL DEFAULT 'preparee',
    nb_relances         INTEGER DEFAULT 0,
    date_relance_prevue TEXT,
    date_reponse        TEXT,
    type_reponse        TEXT,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_cand_statut  ON candidatures(statut);
CREATE INDEX IF NOT EXISTS idx_cand_relance ON candidatures(date_relance_prevue);

CREATE TABLE IF NOT EXISTS evenements (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    offre_id  INTEGER REFERENCES offres(id),
    date      TEXT NOT NULL,
    type      TEXT NOT NULL,
    detail    TEXT
);

-- Taches de fond. Une collecte dure 3 min, une generation de lettres 14 :
-- impossible de les tenir dans une requete HTTP. L'interface lance la tache
-- puis interroge sa progression.
CREATE TABLE IF NOT EXISTS taches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT NOT NULL,      -- collecte | lettres | candidatures
    statut       TEXT NOT NULL,      -- en_cours | terminee | echouee | annulee
    parametres   TEXT,               -- JSON
    progression  INTEGER DEFAULT 0,
    total        INTEGER DEFAULT 0,
    message      TEXT,
    journal      TEXT,
    debut        TEXT NOT NULL,
    fin          TEXT
);

CREATE INDEX IF NOT EXISTS idx_taches_statut ON taches(statut);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    source        TEXT,
    nb_collectees INTEGER,
    nb_nouvelles  INTEGER,
    nb_ecoles     INTEGER,
    nb_retenues   INTEGER,
    detail        TEXT
);
"""

# Statuts d'une offre, dans l'ordre du cycle de vie
STATUTS = [
    "a_valider", "a_traiter", "ecarte", "ecole", "hors_cible", "sans_canal", "ats_externe", "lettre_prete",
    "envoyee", "entretien", "refus", "signee",
]

# Statuts poses par une decision humaine : jamais ecrases par un --rescore
# ats_externe y figure : une redirection vers le site de l'employeur est un
# fait constate sur le formulaire, pas une deduction du score. Un rescore ne
# doit pas la remettre en question, sinon l'offre revient dans le vivier a
# chaque recalcul alors qu'elle n'est pas automatisable.
STATUTS_FIGES = {"lettre_prete", "envoyee", "entretien", "refus", "ats_externe",
                 "signee", "valide_manuel", "rejete_manuel"}


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout : le dashboard garde la base ouverte pendant qu'un script de
    # collecte ou de reconnaissance ecrit. Sans attente, l'ecriture echouait
    # sur "database is locked" et le travail etait perdu.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


# Colonnes ajoutees apres la mise en service. CREATE TABLE IF NOT EXISTS ne les
# pose pas sur une base existante : il faut les ajouter une par une.
COLONNES_TARDIVES = [
    ("empreinte", "TEXT"),
    ("verrou_manuel", "INTEGER DEFAULT 0"),
    # Relevees par reconnaissance.py. NULL signifie "pas encore inspecte",
    # a ne pas confondre avec 0 qui signifie "le formulaire n'en veut pas".
    ("lettre_texte", "INTEGER"),
    ("lettre_fichier", "INTEGER"),
]


def migrer(conn):
    existantes = {r["name"] for r in conn.execute("PRAGMA table_info(offres)")}
    for nom, type_sql in COLONNES_TARDIVES:
        if nom not in existantes:
            conn.execute(f"ALTER TABLE offres ADD COLUMN {nom} {type_sql}")
    # Pose apres la migration : l'index ne peut pas preceder sa colonne.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_offres_empreinte "
                 "ON offres(empreinte)")
    conn.commit()


def init():
    conn = connect()
    conn.executescript(SCHEMA)
    migrer(conn)
    conn.commit()
    return conn


def empreinte(entreprise, intitule):
    """Cle de rapprochement entre sources : employeur + intitule, normalises.

    Volontairement grossiere. Deux annonces du meme poste sur deux sites ne
    partagent ni identifiant ni mise en forme : seuls le nom de l'employeur et
    l'intitule se ressemblent assez pour servir de reperes.
    """
    import re
    import texte
    propre = lambda t: re.sub(r"[^a-z0-9]+", " ", texte.normalise(t)).strip()
    nom = propre(entreprise)
    titre = propre(intitule)
    if not nom or not titre:
        return None          # sans les deux, le rapprochement n'a pas de sens
    return f"{nom}|{titre[:60]}"


def upsert_offre(conn, offre):
    """Insere une offre si son uid est inconnu. Retourne True si nouvelle."""
    offre = dict(offre)
    offre.setdefault("empreinte",
                     empreinte(offre.get("entreprise"), offre.get("intitule")))
    offre["date_collecte"] = datetime.now().isoformat(timespec="seconds")
    if isinstance(offre.get("score_detail"), (dict, list)):
        offre["score_detail"] = json.dumps(offre["score_detail"], ensure_ascii=False)

    colonnes = ", ".join(offre)
    placeholders = ", ".join(f":{c}" for c in offre)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO offres ({colonnes}) VALUES ({placeholders})", offre
    )
    return cur.rowcount > 0


def doublon_existant(conn, offre):
    """L'offre est-elle deja en base sous une autre source ?

    Retourne la ligne deja presente, ou None. Le rapprochement se fait sur
    l'empreinte entreprise+intitule : deux sites qui publient la meme annonce
    ne partagent aucun identifiant, seuls ces deux champs se ressemblent.

    On ne compare pas les offres d'une meme source entre elles : leur uid s'en
    charge deja, et deux postes distincts peuvent legitimement porter le meme
    intitule chez le meme employeur.
    """
    cle = offre.get("empreinte") or empreinte(offre.get("entreprise"),
                                              offre.get("intitule"))
    if not cle:
        return None
    return conn.execute(
        "SELECT id, source, statut FROM offres WHERE empreinte = ? AND source != ? "
        "LIMIT 1", (cle, offre.get("source"))).fetchone()


def log(conn, offre_id, type_, detail=""):
    conn.execute(
        "INSERT INTO evenements (offre_id, date, type, detail) VALUES (?, ?, ?, ?)",
        (offre_id, datetime.now().isoformat(timespec="seconds"), type_, detail),
    )


def stats(conn):
    rows = conn.execute(
        "SELECT statut, COUNT(*) n FROM offres GROUP BY statut ORDER BY n DESC"
    ).fetchall()
    return {r["statut"]: r["n"] for r in rows}
