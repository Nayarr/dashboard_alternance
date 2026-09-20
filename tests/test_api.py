# -*- coding: utf-8 -*-
"""API HTTP du tableau de bord.

Le client de test Flask suffit : aucun serveur n'est lance, aucun appel reseau
n'est emis. Les tests ecrivent dans une base temporaire.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import db


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier = Path(tempfile.mkdtemp())
        cls._chemin_initial = db.DB_PATH
        db.DB_PATH = cls.dossier / "test.db"
        db._schema_verifie = False

        import dashboard
        import parametres
        cls.dashboard = dashboard
        cls.client = dashboard.app.test_client()

        # La surcouche est redirigee elle aussi : un test qui enregistre des
        # reglages ne doit pas ecraser ceux de la personne qui lance la suite.
        cls._parametres = parametres
        cls._fichier_initial = parametres.FICHIER
        parametres.FICHIER = cls.dossier / "parametres.json"

        conn = db.connect()
        conn.execute(
            "INSERT INTO offres (uid, source, entreprise, intitule, statut, "
            "date_collecte, score, matching) VALUES "
            "('u1','lba','Exemple SA','Developpeur Python','a_traiter',"
            "datetime('now'), 70, 80)")
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._chemin_initial
        db._schema_verifie = False
        cls._parametres.FICHIER = cls._fichier_initial
        shutil.rmtree(cls.dossier, ignore_errors=True)

    def setUp(self):
        """Les methodes s'executent dans l'ordre alphabetique et partagent la
        base : sans remise a zero, le cycle de vie testerait l'etat laisse par
        le test precedent."""
        conn = db.connect()
        conn.execute("DELETE FROM candidatures")
        conn.execute("UPDATE offres SET statut = 'a_traiter' WHERE id = 1")
        conn.commit()
        conn.close()

    def test_contexte(self):
        d = self.client.get("/api/contexte").get_json()
        for cle in ("vues", "profil", "cv", "tache", "dernier_echec"):
            self.assertIn(cle, d)

    def test_offres_par_statut(self):
        d = self.client.get("/api/offres?statut=a_traiter").get_json()
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["entreprise"], "Exemple SA")

    def test_statut_inconnu_refuse(self):
        r = self.client.get("/api/offres?statut=nimportequoi")
        self.assertEqual(r.status_code, 400)

    def test_toutes_les_vues_repondent(self):
        """Une vue declaree dans la navigation et refusee par l'API donnerait
        un onglet mort."""
        for vue in self.dashboard.CLES_VISIBLES:
            with self.subTest(vue=vue):
                self.assertEqual(
                    self.client.get(f"/api/offres?statut={vue}").status_code, 200)

    def test_cycle_de_vie_complet(self):
        """Le pipeline s'arretait a l'envoi : aucun bouton ne menait aux vues
        Entretien, Refus et Signee."""
        for statut in ("lettre_prete", "envoyee", "entretien", "refus",
                       "envoyee", "signee"):
            r = self.client.post("/api/offre/1/statut", json={"statut": statut})
            self.assertEqual(r.status_code, 200, statut)
            self.assertEqual(r.get_json()["statut"], statut)

    def test_reponse_desarme_la_relance(self):
        """Sans ce report, on relancait un recruteur ayant deja repondu."""
        self.client.post("/api/offre/1/statut", json={"statut": "envoyee"})
        conn = db.connect()
        ligne = conn.execute(
            "SELECT date_relance_prevue FROM candidatures WHERE offre_id = 1"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(ligne, "aucune ligne de candidature creee")
        self.assertIsNotNone(ligne["date_relance_prevue"])

        self.client.post("/api/offre/1/statut", json={"statut": "refus"})
        conn = db.connect()
        ligne = conn.execute(
            "SELECT date_relance_prevue, type_reponse FROM candidatures "
            "WHERE offre_id = 1").fetchone()
        conn.close()
        self.assertIsNone(ligne["date_relance_prevue"])
        self.assertEqual(ligne["type_reponse"], "refus")

    def test_statut_invalide_refuse(self):
        r = self.client.post("/api/offre/1/statut", json={"statut": "pirate"})
        self.assertEqual(r.status_code, 400)

    def test_offre_inexistante(self):
        r = self.client.post("/api/offre/999999/statut", json={"statut": "refus"})
        self.assertEqual(r.status_code, 404)

    def test_code_postal_invalide_refuse(self):
        r = self.client.post("/api/parametres",
                             json={"adresse_postale": {"code_postal": "94"}})
        self.assertEqual(r.status_code, 400)

    def test_email_invalide_refuse(self):
        r = self.client.post("/api/parametres",
                             json={"profil": {"email": "pas-un-email"}})
        self.assertEqual(r.status_code, 400)

    def test_code_rome_invalide_refuse(self):
        r = self.client.post("/api/parametres", json={"romes": ["PASUNROME"]})
        self.assertEqual(r.status_code, 400)

    def test_refuse_de_ne_chercher_ni_alternance_ni_stage(self):
        """Une collecte sans nature cochee ne trouverait rien."""
        r = self.client.post("/api/parametres", json={
            "recherche_alternance": False, "recherche_stages": False})
        self.assertEqual(r.status_code, 400)

    def test_erreur_toujours_en_json(self):
        """L'interface ne sait lire que du JSON : une page HTML d'erreur lui
        arrivait comme un « HTTP 500 » sans explication."""
        r = self.client.get("/api/route/qui/nexiste/pas")
        self.assertEqual(r.status_code, 404)
        self.assertIn("erreur", r.get_json())

    def test_journal_lisible(self):
        d = self.client.get("/api/journal").get_json()
        self.assertIn("contenu", d)


if __name__ == "__main__":
    unittest.main()
