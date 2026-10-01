# -*- coding: utf-8 -*-
"""API HTTP du tableau de bord.

Le client de test Flask suffit : aucun serveur n'est lance, aucun appel reseau
n'est emis. Les tests ecrivent dans une base temporaire.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from alternance import db


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier = Path(tempfile.mkdtemp())
        cls._chemin_initial = db.DB_PATH
        db.DB_PATH = cls.dossier / "test.db"
        db._schema_verifie = False

        from alternance.interface import serveur
        from alternance import parametres
        cls.serveur = serveur
        cls.client = serveur.app.test_client()

        # La surcouche est redirigee elle aussi : un test qui enregistre des
        # reglages ne doit pas ecraser ceux de la personne qui lance la suite.
        cls._parametres = parametres
        cls._fichier_initial = parametres.FICHIER
        parametres.FICHIER = cls.dossier / "parametres.json"

        # Idem pour le parcours : il est personnel.
        from alternance.redaction import parcours
        cls._parcours = parcours
        cls._parcours_initial = (parcours.FICHIER, parcours.SYSTEME)
        parcours.FICHIER = cls.dossier / "parcours.md"
        parcours.SYSTEME = cls.dossier / "systeme_lettre.md"

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
        cls._parcours.FICHIER, cls._parcours.SYSTEME = cls._parcours_initial
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
        for vue in self.serveur.CLES_VISIBLES:
            with self.subTest(vue=vue):
                self.assertEqual(
                    self.client.get(f"/api/offres?statut={vue}").status_code, 200)

    def test_cycle_de_vie_complet(self):
        """Le pipeline s'arretait a l'envoi : aucun bouton ne menait aux vues
        Entretien, Refus et Signee."""
        for statut, rouvrir in (("lettre_prete", False), ("envoyee", False),
                                ("entretien", False), ("refus", False),
                                ("envoyee", True), ("signee", False)):
            r = self.client.post("/api/offre/1/statut",
                                 json={"statut": statut, "rouvrir": rouvrir})
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

    def candidature(self):
        conn = db.connect()
        ligne = conn.execute(
            "SELECT * FROM candidatures WHERE offre_id = 1").fetchone()
        conn.close()
        return ligne

    def envoyer_il_y_a(self, jours):
        """Une candidature partie il y a `jours` jours, relance comprise."""
        self.client.post("/api/offre/1/statut", json={"statut": "envoyee"})
        conn = db.connect()
        conn.execute(
            "UPDATE candidatures SET date_envoi = datetime('now', ?), "
            "date_relance_prevue = date('now', ?) WHERE offre_id = 1",
            (f"-{jours} days", f"{7 - jours} days"))
        conn.commit()
        conn.close()

    def test_marquer_envoyee_deux_fois_ne_change_rien(self):
        """L'outil avait depose la candidature 26 secondes plus tot ; le clic
        par-dessus recalculait la relance depuis le clic, sans rien dire."""
        self.envoyer_il_y_a(5)
        avant = dict(self.candidature())
        r = self.client.post("/api/offre/1/statut", json={"statut": "envoyee"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["inchange"])
        self.assertIsNotNone(r.get_json()["date_envoi"])
        self.assertEqual(dict(self.candidature()), avant)

    def test_une_reponse_ne_s_efface_pas_d_un_clic(self):
        """Marquer envoyee une offre refusee remettait la reponse a vide,
        sans avertissement ni retour possible."""
        self.envoyer_il_y_a(2)
        self.client.post("/api/offre/1/statut", json={"statut": "refus"})
        r = self.client.post("/api/offre/1/statut", json={"statut": "envoyee"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Rouvrir", r.get_json()["erreur"])
        ligne = self.candidature()
        self.assertEqual(ligne["type_reponse"], "refus")
        self.assertIsNotNone(ligne["date_reponse"])

    def test_rouvrir_recalcule_la_relance_depuis_l_envoi(self):
        """Elle partait du clic : une offre envoyee cinq jours plus tot etait
        relancee au douzieme jour."""
        self.envoyer_il_y_a(5)
        self.client.post("/api/offre/1/statut", json={"statut": "refus"})
        r = self.client.post("/api/offre/1/statut",
                             json={"statut": "envoyee", "rouvrir": True})
        self.assertEqual(r.status_code, 200)
        conn = db.connect()
        attendue = conn.execute("SELECT date('now', '+2 days')").fetchone()[0]
        conn.close()
        ligne = self.candidature()
        self.assertEqual(ligne["date_relance_prevue"], attendue)
        self.assertIsNone(ligne["type_reponse"])

    # ---------------------------------------------------------- relances
    # Une relance etait enregistree a chaque envoi, et rien ne l'affichait :
    # pas d'onglet, pas de compteur, rien dans le detail. 53 relances prevues
    # chez un testeur, aucune visible.

    def relance_prevue_dans(self, jours):
        self.client.post("/api/offre/1/statut", json={"statut": "envoyee"})
        conn = db.connect()
        conn.execute("UPDATE candidatures SET date_relance_prevue = "
                     "date('now', ?) WHERE offre_id = 1", (f"{jours} days",))
        conn.commit()
        conn.close()

    def a_relancer(self):
        ids = [o["id"] for o in
               self.client.get("/api/offres?statut=a_relancer").get_json()]
        compte = self.client.get("/api/tache").get_json()["compte"]["a_relancer"]
        return ids, compte

    def test_une_relance_due_apparait(self):
        self.relance_prevue_dans(-1)
        self.assertEqual(self.a_relancer(), ([1], 1))
        suivi = self.client.get("/api/offre/1").get_json()["suivi"]
        self.assertEqual(suivi["relance_due"], 1)
        self.assertIsNotNone(suivi["date_envoi"])

    def test_une_relance_a_venir_n_apparait_pas(self):
        self.relance_prevue_dans(3)
        self.assertEqual(self.a_relancer(), ([], 0))
        self.assertEqual(
            self.client.get("/api/offre/1").get_json()["suivi"]["relance_due"], 0)

    def test_relance_faite_prevoit_la_suivante_puis_s_arrete(self):
        self.relance_prevue_dans(0)
        r = self.client.post("/api/offre/1/relance").get_json()
        self.assertEqual(r["nb_relances"], 1)
        self.assertIsNotNone(r["prochaine"])
        self.assertEqual(self.a_relancer(), ([], 0))

        conn = db.connect()
        conn.execute("UPDATE candidatures SET date_relance_prevue = "
                     "date('now') WHERE offre_id = 1")
        conn.commit()
        conn.close()
        r = self.client.post("/api/offre/1/relance").get_json()
        self.assertEqual(r["nb_relances"], 2)
        self.assertIsNone(r["prochaine"])
        self.assertEqual(self.a_relancer(), ([], 0))

    def test_une_reponse_sort_l_offre_des_relances(self):
        self.relance_prevue_dans(-2)
        self.client.post("/api/offre/1/statut", json={"statut": "entretien"})
        self.assertEqual(self.a_relancer(), ([], 0))

    def test_relance_refusee_sans_candidature_en_attente(self):
        r = self.client.post("/api/offre/1/relance")
        self.assertEqual(r.status_code, 409)

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


    def test_parcours_saisi_puis_rendu_au_cv(self):
        r = self.client.post("/api/parcours",
                             json={"texte": "Stage chez Globex."})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["source"], "manuel")
        self.assertEqual(self.client.get("/api/parcours").json["texte"],
                         "Stage chez Globex.")

        r = self.client.delete("/api/parcours")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json["source"], "manuel")


if __name__ == "__main__":
    unittest.main()
