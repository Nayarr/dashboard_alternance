# -*- coding: utf-8 -*-
"""Schema, migrations et chemins des pieces.

Deux pannes reelles sont gelees ici : une installation neuve qui n'avait
aucune table, et une base anterieure a l'ajout d'une colonne.
"""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from alternance import chemins
from alternance import db


class BaseTemporaire(unittest.TestCase):
    """Chaque test travaille sur sa propre base, jamais sur celle du projet."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._chemin_initial = db.DB_PATH
        db.DB_PATH = self.dossier / "test.db"
        db._schema_verifie = False

    def tearDown(self):
        db.DB_PATH = self._chemin_initial
        db._schema_verifie = False
        shutil.rmtree(self.dossier, ignore_errors=True)


class TestInstallationNeuve(BaseTemporaire):
    def test_connect_cree_le_schema(self):
        """`python dashboard.py` avant toute collecte donnait
        "no such table: offres" : la moitie des points d'entree appelaient
        connect() sans jamais passer par init()."""
        conn = db.connect()
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        for attendue in ("offres", "candidatures", "evenements", "runs", "taches"):
            self.assertIn(attendue, tables)

    def test_colonnes_tardives_presentes(self):
        conn = db.connect()
        colonnes = {r["name"] for r in conn.execute("PRAGMA table_info(offres)")}
        conn.close()
        for nom, _type in db.COLONNES_TARDIVES:
            self.assertIn(nom, colonnes, f"{nom} absente d'une base neuve")

    def test_url_ats_inscriptible(self):
        """reconnaissance.py s'arretait sur "no such column: url_ats" des la
        premiere offre redirigee vers l'ATS d'un employeur."""
        conn = db.connect()
        conn.execute(
            "INSERT INTO offres (uid, source, entreprise, statut, date_collecte) "
            "VALUES ('u1', 'wttj', 'Test', 'a_traiter', datetime('now'))")
        conn.execute("UPDATE offres SET statut='ats_externe', url_ats=? "
                     "WHERE uid='u1'", ("recrute.exemple.com",))
        self.assertEqual(
            conn.execute("SELECT url_ats FROM offres WHERE uid='u1'")
                .fetchone()["url_ats"], "recrute.exemple.com")
        conn.close()


class TestMigration(BaseTemporaire):
    def test_base_anterieure_reparee_a_l_ouverture(self):
        """Une base creee avant l'ajout d'une colonne doit se completer seule :
        personne ne doit avoir a supprimer sa base ni a recollecter."""
        brute = sqlite3.connect(db.DB_PATH)
        brute.executescript(db.SCHEMA)      # SCHEMA seul : sans les tardives
        brute.commit()
        avant = {r[1] for r in brute.execute("PRAGMA table_info(offres)")}
        brute.close()
        self.assertNotIn("url_ats", avant)

        conn = db.connect()
        apres = {r["name"] for r in conn.execute("PRAGMA table_info(offres)")}
        conn.close()
        self.assertIn("url_ats", apres)


class TestEmpreinte(unittest.TestCase):
    """Le dedoublonnage entre sources repose dessus."""

    def test_insensible_a_la_casse_et_aux_espaces(self):
        self.assertEqual(db.empreinte("Docaposte", "Dev Python"),
                         db.empreinte("  DOCAPOSTE ", "dev   python "))

    def test_distingue_deux_postes_du_meme_employeur(self):
        self.assertNotEqual(db.empreinte("Docaposte", "Dev Python"),
                            db.empreinte("Docaposte", "Dev Java"))


class TestChemins(unittest.TestCase):
    def test_dossier_indexe_par_offre_et_non_par_entreprise(self):
        """Deux postes chez le meme employeur partageaient un dossier, donc
        une lettre : la seconde candidature partait avec celle de la premiere."""
        a = chemins.dossier_candidature({"id": 1, "entreprise": "Docaposte"})
        b = chemins.dossier_candidature({"id": 2, "entreprise": "Docaposte"})
        self.assertNotEqual(a, b)

    def test_slug_sans_accent_ni_ponctuation(self):
        self.assertEqual(chemins.slug("Écoles & Cie / Paris"), "ecoles_cie_paris")

    def test_slug_ne_rend_jamais_une_chaine_vide(self):
        self.assertTrue(chemins.slug("///"))
        self.assertTrue(chemins.slug(None))

    def test_cv_trouve_quel_que_soit_son_nom(self):
        """Le nom du CV etait code en dur dans cinq fichiers : l'outil etait
        inutilisable sans renommer son propre PDF."""
        dossier = Path(tempfile.mkdtemp())
        initial = chemins.DOSSIER_CV
        try:
            chemins.DOSSIER_CV = dossier
            self.assertFalse(chemins.trouver_cv().exists())
            (dossier / "CV_Untel.pdf").write_bytes(b"%PDF-1.4")
            trouve = chemins.trouver_cv()
            self.assertEqual(trouve.name, "CV_Untel.pdf")
        finally:
            chemins.DOSSIER_CV = initial
            shutil.rmtree(dossier, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
