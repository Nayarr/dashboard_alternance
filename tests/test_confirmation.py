# -*- coding: utf-8 -*-
"""Apres le clic sur « Envoyer » : envoyee, ou a verifier, jamais renvoyee.

Une candidature dont le site n'affichait pas de confirmation reconnue restait
en « lettre prete ». Il fallait la marquer a la main, et le clic suivant sur
« Envoyer les candidatures » postulait une seconde fois chez le meme employeur.
"""

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from alternance import chemins
from alternance import db
from alternance.candidature import aiguillage
from alternance.candidature import confirmation


class BaseTemporaire(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._chemin = db.DB_PATH
        self._lettres = chemins.LETTRES
        db.DB_PATH = self.dossier / "test.db"
        chemins.LETTRES = self.dossier / "lettres"
        db._schema_verifie = False
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self._chemin
        chemins.LETTRES = self._lettres
        db._schema_verifie = False
        shutil.rmtree(self.dossier, ignore_errors=True)

    def offre(self, source="wttj", statut="lettre_prete"):
        cur = self.conn.execute(
            "INSERT INTO offres (uid, source, entreprise, intitule, statut, "
            "date_collecte, recipient_id, url_candidature) VALUES "
            "(?, ?, 'Acme', 'Dev', ?, datetime('now'), 'r1', 'https://x')",
            (f"u{source}{statut}{self.id()}", source, statut))
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM offres WHERE id = ?",
                                      (cur.lastrowid,)).fetchone())

    def statut(self, offre):
        return self.conn.execute("SELECT statut FROM offres WHERE id = ?",
                                 (offre["id"],)).fetchone()[0]


class TestEnvoiIncertain(BaseTemporaire):
    def test_une_confirmation_non_lue_passe_en_a_verifier(self):
        o = self.offre()
        confirmation.enregistrer_incertain(self.conn, o, "wttj_formulaire",
                                           "cv.pdf", "wttj_1_acme_apres.png")
        self.assertEqual(self.statut(o), "a_verifier")
        ligne = self.conn.execute(
            "SELECT * FROM candidatures WHERE offre_id = ?", (o["id"],)).fetchone()
        self.assertEqual(ligne["statut"], "incertain")
        self.assertIsNotNone(ligne["date_envoi"])
        # Pas de relance tant que l'envoi n'est pas confirme.
        self.assertIsNone(ligne["date_relance_prevue"])
        self.assertIn("apres.png", ligne["notes"])

    def test_une_offre_a_verifier_n_est_jamais_renvoyee(self):
        """Le defaut : elle restait en lettre prete et repartait au clic
        suivant."""
        o = self.offre()
        confirmation.enregistrer_incertain(self.conn, o, "wttj_formulaire",
                                           "cv.pdf", "x.png")
        self.assertEqual(aiguillage.repartition(self.conn)["canaux"]["wttj"], 0)

    def test_une_ligne_de_candidature_suffit_a_bloquer_l_envoi(self):
        """Derniere barriere : meme revenue en lettre prete par un autre
        chemin, une offre deja candidatee n'est pas reprise."""
        o = self.offre(source="lba")
        confirmation.enregistrer_envoi(self.conn, o, "lba_formulaire", "cv.pdf")
        self.conn.execute("UPDATE offres SET statut = 'lettre_prete' WHERE id = ?",
                          (o["id"],))
        self.assertEqual(aiguillage.repartition(self.conn)["canaux"]["lba"], 0)

    def test_un_envoi_confirme_arme_la_relance(self):
        o = self.offre(source="lba")
        confirmation.enregistrer_envoi(self.conn, o, "lba_formulaire", "cv.pdf")
        self.assertEqual(self.statut(o), "envoyee")
        ligne = self.conn.execute(
            "SELECT date_relance_prevue FROM candidatures WHERE offre_id = ?",
            (o["id"],)).fetchone()
        self.assertIsNotNone(ligne["date_relance_prevue"])

    def test_le_rescore_ne_touche_pas_a_un_envoi_a_verifier(self):
        self.assertIn("a_verifier", db.STATUTS_FIGES)
        self.assertIn("a_verifier", db.STATUTS)


class TestDepuisLInterface(BaseTemporaire):
    def setUp(self):
        super().setUp()
        from alternance.interface import serveur
        self.client = serveur.app.test_client()
        self.o = self.offre()
        confirmation.enregistrer_incertain(self.conn, self.o, "wttj_formulaire",
                                           "cv.pdf", "x.png")
        # Le clic a eu lieu il y a trois jours.
        self.conn.execute("UPDATE candidatures SET date_envoi = "
                          "datetime('now', '-3 days') WHERE offre_id = ?",
                          (self.o["id"],))
        self.conn.commit()

    def test_confirmer_l_envoi_arme_la_relance_depuis_le_clic(self):
        r = self.client.post(f"/api/offre/{self.o['id']}/statut",
                             json={"statut": "envoyee"})
        self.assertEqual(r.status_code, 200)
        ligne = self.conn.execute(
            "SELECT statut, date_relance_prevue, date('now', '+4 days') attendue "
            "FROM candidatures WHERE offre_id = ?", (self.o["id"],)).fetchone()
        self.assertEqual(ligne["statut"], "envoyee")
        self.assertEqual(ligne["date_relance_prevue"], ligne["attendue"])

    def test_pas_parti_rend_l_offre_a_l_envoi(self):
        r = self.client.post(f"/api/offre/{self.o['id']}/statut",
                             json={"statut": "lettre_prete"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM candidatures WHERE offre_id = ?",
            (self.o["id"],)).fetchone()[0], 0)
        self.assertEqual(aiguillage.repartition(self.conn)["canaux"]["wttj"], 1)

    def test_la_vue_existe_et_le_detail_le_dit(self):
        ids = [x["id"] for x in
               self.client.get("/api/offres?statut=a_verifier").get_json()]
        self.assertEqual(ids, [self.o["id"]])
        suivi = self.client.get(f"/api/offre/{self.o['id']}").get_json()["suivi"]
        self.assertEqual(suivi["statut"], "incertain")


class TestMessageDeConfirmation(unittest.TestCase):
    """Le motif cherchait « recue » sans cedille sur WTTJ : « Ta candidature
    a bien ete reçue » n'etait jamais reconnue."""

    def motif(self):
        corps = confirmation.MOTIF
        self.assertTrue(corps.startswith("/") and corps.endswith("/i"))
        return re.compile(corps[1:-2], re.I)

    def test_les_confirmations_sont_reconnues(self):
        for texte in ("Ta candidature a bien été reçue !",
                      "Votre candidature a été envoyée",
                      "Votre candidature spontanée a bien été envoyée",
                      "Candidature transmise au recruteur",
                      "Merci pour votre candidature",
                      "Your application was sent"):
            self.assertTrue(self.motif().search(texte), texte)

    def test_le_bouton_d_envoi_n_est_pas_une_confirmation(self):
        """Le texte du formulaire, avant le clic, ne doit pas suffire."""
        for texte in ("J'envoie ma candidature !",
                      "Envoyer ma candidature spontanée",
                      "Je suis déjà inscrit en formation",
                      # Texte fixe de la page LBA, present avant tout clic :
                      # l'ancien motif « candidature.*envoy » le prenait pour
                      # une confirmation, et toute candidature LBA passait en
                      # « envoyee » sans preuve.
                      "avant de soumettre votre candidature spontanée. Les "
                      "candidats envoyant des candidatures spontanées ont plus "
                      "de chance de trouver"):
            self.assertIsNone(self.motif().search(texte), texte)


class PageSimulee:
    """Une page dont le nombre de confirmations change au fil du temps."""

    def __init__(self, comptes):
        self.comptes = list(comptes)

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selecteur):
        page = self

        class L:
            def count(self):
                return page.comptes.pop(0) if len(page.comptes) > 1 \
                    else page.comptes[0]
        return L()


class TestApparition(unittest.TestCase):
    """Seule une confirmation apparue apres le clic prouve l'envoi."""

    def test_un_texte_deja_present_ne_suffit_pas(self):
        page = PageSimulee([1])
        avant = confirmation.compter(page)
        self.assertFalse(confirmation.attendre(page, avant, delai_ms=2000))

    def test_une_confirmation_qui_apparait_compte(self):
        page = PageSimulee([1, 1, 1, 2])
        avant = confirmation.compter(page)
        self.assertTrue(confirmation.attendre(page, avant, delai_ms=5000))

    def test_une_page_illisible_ne_confirme_rien(self):
        class Cassee:
            def wait_for_timeout(self, ms):
                pass

            def locator(self, s):
                raise RuntimeError("page fermee")
        self.assertFalse(confirmation.attendre(Cassee(), 0, delai_ms=1000))


if __name__ == "__main__":
    unittest.main()
