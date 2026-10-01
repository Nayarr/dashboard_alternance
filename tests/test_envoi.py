# -*- coding: utf-8 -*-
"""Aiguillage des candidatures vers le site dont vient chaque offre.

Aucun navigateur n'est ouvert : les canaux sont remplaces. Ces tests portent
sur ce qui est envoye ou et dans quelle quantite, pas sur les formulaires.
"""

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from alternance import db
from alternance import journal
from alternance.candidature import aiguillage


class TestAiguillage(unittest.TestCase):
    """Le bouton « Envoyer les candidatures » ne lancait que l'envoi LBA. Chez
    une testeuse dont la seule lettre prete portait sur une offre WTTJ, la
    tache echouait sur « aucune offre avec lettre prete » alors que la vue en
    affichait une."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._chemin_initial = db.DB_PATH
        db.DB_PATH = self.dossier / "test.db"
        db._schema_verifie = False
        self.n = 0

    def tearDown(self):
        db.DB_PATH = self._chemin_initial
        db._schema_verifie = False
        shutil.rmtree(self.dossier, ignore_errors=True)

    def offre(self, source, statut="lettre_prete", destinataire=None):
        self.n += 1
        conn = db.connect()
        conn.execute(
            "INSERT INTO offres (uid, source, entreprise, intitule, statut, "
            "date_collecte, score, matching, recipient_id) VALUES "
            "(?, ?, 'Exemple', 'Developpeur', ?, datetime('now'), 70, 80, ?)",
            (f"u{self.n}", source, statut, destinataire))
        conn.commit()
        conn.close()

    def lancer(self, *arguments, canaux_ok=True):
        """main() avec des canaux factices ; renvoie (appels, sortie)."""
        appels = []

        def canal(module, args):
            appels.append((module.rsplit(".", 1)[1], args))
            return canaux_ok if isinstance(canaux_ok, bool) \
                else module.rsplit(".", 1)[1] not in canaux_ok

        sortie = io.StringIO()
        with mock.patch.object(aiguillage, "lancer_canal", side_effect=canal), \
                mock.patch("sys.argv", ["postuler", *arguments]), \
                redirect_stdout(sortie):
            aiguillage.main()
        return appels, sortie.getvalue()

    def test_la_repartition_suit_la_source_de_l_offre(self):
        self.offre("lba", destinataire="r1")
        self.offre("lba")                      # relayee, sans formulaire
        self.offre("wttj")
        self.offre("jobteaser")
        self.offre("lba", statut="a_traiter", destinataire="r2")

        conn = db.connect()
        etat = aiguillage.repartition(conn)
        conn.close()
        self.assertEqual(etat["canaux"], {"lba": 1, "wttj": 1})
        self.assertEqual(etat["manuelles"], {"lba": 1, "jobteaser": 1})

    def test_une_lettre_wttj_seule_est_envoyee_par_wttj(self):
        """Le cas reel : la tache partait sur LBA et ne trouvait rien."""
        self.offre("wttj")
        appels, _ = self.lancer("--limite", "5", "--confirmer")
        self.assertEqual(appels, [("wttj", ["--limite", "1", "--confirmer"])])

    def test_chaque_canal_recoit_sa_part_de_la_limite(self):
        for _ in range(3):
            self.offre("lba", destinataire="r")
            self.offre("wttj")
        appels, _ = self.lancer("--limite", "4")
        self.assertEqual(appels, [("lba", ["--limite", "3"]),
                                  ("wttj", ["--limite", "1"])])

    def test_sans_rien_d_envoyable_la_tache_se_termine_normalement(self):
        """Pas une panne : il n'y a rien que l'outil sache envoyer. La tache
        ne doit plus finir en rouge sur « arret inattendu »."""
        self.offre("jobteaser")
        appels, sortie = self.lancer("--confirmer")
        self.assertEqual(appels, [])
        self.assertIn("JobTeaser", sortie)
        self.assertIn("a la main", sortie)

    def test_les_offres_sans_depot_automatique_sont_annoncees(self):
        self.offre("wttj")
        self.offre("apec")
        _, sortie = self.lancer()
        self.assertIn("Sans depot automatique : 1 Apec", sortie)

    def test_un_canal_en_echec_n_empeche_pas_le_suivant(self):
        self.offre("lba", destinataire="r")
        self.offre("wttj")
        with self.assertRaises(SystemExit) as capture:
            self.lancer(canaux_ok={"lba"})
        self.assertIn("La Bonne Alternance", str(capture.exception.code))
        self.assertNotIn("Welcome", str(capture.exception.code))

    def test_un_site_en_pause_n_est_pas_tente(self):
        """WTTJ suspend le compte quand il est trop sollicite : pendant la
        pause, ses candidatures attendent et LBA part quand meme."""
        from datetime import datetime, timedelta
        self.offre("lba", destinataire="r")
        self.offre("wttj")
        fin = datetime.now() + timedelta(minutes=20)
        with mock.patch("alternance.candidature.cadence.reprise",
                        side_effect=lambda site: fin if site == "wttj" else None):
            appels, sortie = self.lancer("--confirmer")
        self.assertEqual([a[0] for a in appels], ["lba"])
        self.assertIn("reportee", sortie)
        self.assertIn(f"{fin:%H:%M}", sortie)

    def test_les_conditions_sont_celles_des_canaux(self):
        """La repartition recopie les requetes de lba.py et wttj.py. Si l'une
        change seule, la confirmation annonce des candidatures que le canal
        ne trouvera pas."""
        racine = Path(aiguillage.__file__).parent
        for cle, _, module in aiguillage.CANAUX:
            source = (racine / f"{module.rsplit('.', 1)[1]}.py").read_text(
                encoding="utf-8")
            for fragment in aiguillage.CONDITIONS[cle].split(" AND "):
                self.assertIn(fragment, source, f"{cle} : {fragment}")

    def test_lancer_canal_traduit_la_sortie_du_module(self):
        module = mock.Mock()
        with mock.patch("importlib.import_module", return_value=module), \
                redirect_stdout(io.StringIO()):
            module.main.side_effect = SystemExit("aucune offre avec lettre prete")
            self.assertFalse(aiguillage.lancer_canal("x.lba", []))
            module.main.side_effect = SystemExit(0)
            self.assertTrue(aiguillage.lancer_canal("x.lba", []))
            module.main.side_effect = None
            self.assertTrue(aiguillage.lancer_canal("x.lba", []))


class TestMessagesDEnvoi(unittest.TestCase):
    def test_l_echec_d_un_canal_est_nomme(self):
        sortie = "--- Welcome to the Jungle : 1\n  ECHEC du canal (code 1)\n" \
                 "Echec sur : Welcome to the Jungle. Le detail est au-dessus."
        self.assertIn("Welcome to the Jungle", journal.expliquer(sortie, 1))
        self.assertNotIn("inattendu", journal.expliquer(sortie, 1))

    def test_la_cause_precise_l_emporte_sur_le_resume(self):
        sortie = "session WTTJ expiree\nEchec sur : Welcome to the Jungle."
        self.assertIn("reconnecter", journal.expliquer(sortie, 1))

    def test_un_canal_lance_seul_sans_rien_a_envoyer(self):
        """Le message exact de la panne : « Arret inattendu, sans message
        d'erreur », au-dessus d'une phrase qui disait pourtant tout."""
        raison = journal.expliquer(
            "aucune offre avec lettre prete. Lancer : python cli.py lettres", 1)
        self.assertNotIn("inattendu", raison)


if __name__ == "__main__":
    unittest.main()
