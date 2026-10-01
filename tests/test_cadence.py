# -*- coding: utf-8 -*-
"""Rythme des interactions avec les sites de candidature.

WTTJ suspendait les interactions du compte pendant 20 a 30 minutes : la
reconnaissance ouvrait un formulaire toutes les huit secondes, et rien ne
s'arretait quand le site commencait a refuser. Aucun navigateur n'est lance
ici, et le temps est simule.
"""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from alternance import journal
from alternance.candidature import cadence


class EtatTemporaire(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._fichier = cadence.FICHIER
        cadence.FICHIER = self.dossier / "cadence.json"

    def tearDown(self):
        cadence.FICHIER = self._fichier
        shutil.rmtree(self.dossier, ignore_errors=True)

    def ecrire(self, etat):
        cadence.FICHIER.write_text(json.dumps(etat), encoding="utf-8")


class TestIntervalle(EtatTemporaire):
    def test_la_premiere_ouverture_n_attend_pas(self):
        dormir = mock.Mock()
        cadence.attendre("wttj", dormir=dormir)
        dormir.assert_not_called()

    def test_deux_ouvertures_rapprochees_sont_espacees(self):
        il_y_a_10_s = (datetime.now() - timedelta(seconds=10)).isoformat()
        self.ecrire({"wttj": {"derniere": il_y_a_10_s}})
        dormir = mock.Mock()
        with redirect_stdout(io.StringIO()):
            cadence.attendre("wttj", dormir=dormir)
        attente = dormir.call_args[0][0]
        self.assertAlmostEqual(attente, cadence.INTERVALLES["wttj"] - 10, delta=2)

    def test_le_rythme_est_partage_entre_les_processus(self):
        """Reconnaissance puis envoi sont deux processus : l'etat est sur
        disque, pas en memoire."""
        cadence.attendre("wttj", dormir=mock.Mock())
        etat = json.loads(cadence.FICHIER.read_text(encoding="utf-8"))
        self.assertIn("derniere", etat["wttj"])

    def test_un_fichier_illisible_ne_bloque_rien(self):
        cadence.FICHIER.write_text("{pas du json", encoding="utf-8")
        cadence.attendre("wttj", dormir=mock.Mock())


class TestPause(EtatTemporaire):
    def test_une_pause_en_cours_interdit_toute_tentative(self):
        dans_10_min = (datetime.now() + timedelta(minutes=10)).isoformat()
        self.ecrire({"wttj": {"pause_jusqu_a": dans_10_min}})
        dormir = mock.Mock()
        with self.assertRaises(cadence.SiteEnPause) as capture:
            cadence.attendre("wttj", dormir=dormir)
        dormir.assert_not_called()
        self.assertIn("Rien n'a ete tente", str(capture.exception))

    def test_une_pause_echue_ne_compte_plus(self):
        il_y_a_1_min = (datetime.now() - timedelta(minutes=1)).isoformat()
        self.ecrire({"wttj": {"pause_jusqu_a": il_y_a_1_min}})
        self.assertIsNone(cadence.reprise("wttj"))
        cadence.attendre("wttj", dormir=mock.Mock())

    def test_la_pause_ne_concerne_que_son_site(self):
        cadence.poser_pause("wttj", "test")
        self.assertIsNotNone(cadence.reprise("wttj"))
        self.assertIsNone(cadence.reprise("lba"))

    def test_la_pause_depasse_la_suspension_observee(self):
        """Reprendre avant la fin de la suspension la relance."""
        self.assertGreater(cadence.PAUSES_MINUTES["wttj"], 30)


class TestSurveillance(EtatTemporaire):
    def test_un_echec_isole_ne_suffit_pas(self):
        s = cadence.Surveillance("wttj")
        s.echec("formulaire absent")
        s.succes()
        s.echec("formulaire absent")
        self.assertIsNone(cadence.reprise("wttj"))

    def test_deux_echecs_de_suite_arretent_et_posent_une_pause(self):
        """Avant, chaque offre suivante echouait en quelques secondes et la
        boucle continuait, ce qui prolonge la suspension."""
        s = cadence.Surveillance("wttj")
        s.echec("formulaire absent")
        with self.assertRaises(cadence.SiteEnPause):
            s.echec("formulaire absent")
        self.assertIsNotNone(cadence.reprise("wttj"))

    def test_une_limite_explicite_arrete_tout_de_suite(self):
        with self.assertRaises(cadence.SiteEnPause):
            cadence.Surveillance("wttj").limite("429")
        self.assertIsNotNone(cadence.reprise("wttj"))


class TestDetection(unittest.TestCase):
    def page(self, texte):
        page = mock.Mock()
        page.inner_text.return_value = texte
        return page

    def test_un_statut_429_signale_une_limite(self):
        self.assertTrue(cadence.page_limitee(self.page(""), 429))

    def test_le_texte_de_la_page_signale_une_limite(self):
        for texte in ("Too Many Requests", "Trop de requêtes, réessayez plus tard",
                      "Please try again later"):
            self.assertTrue(cadence.page_limitee(self.page(texte)), texte)

    def test_une_page_normale_n_est_pas_une_limite(self):
        self.assertFalse(cadence.page_limitee(
            self.page("Postuler à l'offre Développeur Python"), 200))

    def test_une_page_illisible_n_est_pas_une_limite(self):
        page = mock.Mock()
        page.inner_text.side_effect = Exception("detachee")
        self.assertFalse(cadence.page_limitee(page))


class TestMessages(unittest.TestCase):
    def test_l_heure_de_reprise_s_affiche_telle_quelle(self):
        sortie = ("REPETITION A BLANC - 3 candidature(s)\n"
                  "  ARRET  Welcome to the Jungle limite les interactions : "
                  "reprise possible apres 14:35. Rien n'a ete tente.\n"
                  "Welcome to the Jungle limite les interactions : reprise "
                  "possible apres 14:35. Rien n'a ete tente.")
        raison = journal.expliquer(sortie, 1)
        self.assertTrue(raison.startswith("Welcome to the Jungle limite"), raison)
        self.assertIn("14:35", raison)


if __name__ == "__main__":
    unittest.main()
