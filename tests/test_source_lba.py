# -*- coding: utf-8 -*-
"""Collecte La Bonne Alternance : seules les entrees avec formulaire.

180 entrees sur 285 etaient collectees, notees, puis classees « Sans moyen de
postuler » chez un testeur : sans recipient_id, la page LBA n'a pas de
formulaire. Aucun appel reseau ici, l'API est simulee.
"""

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from alternance import db
from alternance.sources import lba


def entree(nom, destinataire):
    return {
        "workplace": {"name": nom, "siret": nom, "location": {"address": "Paris"}},
        "apply": {"url": f"https://lba/{nom}", "recipient_id": destinataire},
        "identifier": {"id": nom},
        "offer": {"title": "Developpeur"},
        "contract": {},
    }


def reponse(jobs, recruiters):
    r = mock.Mock(status_code=200)
    r.json.return_value = {"jobs": jobs, "recruiters": recruiters}
    return r


class TestCollecte(unittest.TestCase):
    def collecter(self, **options):
        api = reponse([entree("Acme", "r1"), entree("Relayee", None)],
                      [entree("Globex", "r2"), entree("Sansform", None)])
        with mock.patch.dict("os.environ", {"LBA_API_KEY": "cle-de-test"}), \
                mock.patch("requests.get", return_value=api), \
                mock.patch("time.sleep"), redirect_stdout(io.StringIO()) as sortie:
            offres = lba.collecte(romes=["M1805"], radius=30, **options)
        return offres, sortie.getvalue()

    def test_les_entrees_sans_formulaire_ne_sont_pas_collectees(self):
        offres, sortie = self.collecter()
        self.assertEqual(sorted(o["entreprise"] for o in offres), ["Acme", "Globex"])
        self.assertIn("2 entree(s) sans formulaire", sortie)

    def test_on_peut_encore_les_garder_explicitement(self):
        offres, _ = self.collecter(garder_sans_formulaire=True)
        self.assertEqual(len(offres), 4)


class TestReprise(unittest.TestCase):
    """L'insertion ignore un uid deja connu : une entreprise vue sans
    formulaire, puis revenue avec un, restait « sans moyen de postuler »."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._chemin = db.DB_PATH
        db.DB_PATH = self.dossier / "test.db"
        db._schema_verifie = False
        self.conn = db.connect()
        self.conn.execute(
            "INSERT INTO offres (uid, source, entreprise, intitule, statut, "
            "date_collecte) VALUES ('u1', 'lba', 'Acme', 'Dev', 'sans_canal', "
            "datetime('now'))")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self._chemin
        db._schema_verifie = False
        shutil.rmtree(self.dossier, ignore_errors=True)

    def test_un_formulaire_apparu_est_reporte(self):
        repris = db.raviver_sans_canal(self.conn, {
            "uid": "u1", "recipient_id": "r9",
            "url_candidature": "https://lba/acme", "url_offre": "https://lba/acme"})
        self.assertTrue(repris)
        ligne = self.conn.execute(
            "SELECT recipient_id, url_candidature FROM offres WHERE uid = 'u1'"
        ).fetchone()
        self.assertEqual(ligne["recipient_id"], "r9")

    def test_rien_a_reprendre_sans_formulaire(self):
        self.assertFalse(db.raviver_sans_canal(
            self.conn, {"uid": "u1", "recipient_id": None}))

    def test_une_offre_deja_traitee_n_est_pas_touchee(self):
        self.conn.execute("UPDATE offres SET statut = 'envoyee' WHERE uid = 'u1'")
        self.assertFalse(db.raviver_sans_canal(
            self.conn, {"uid": "u1", "recipient_id": "r9"}))


if __name__ == "__main__":
    unittest.main()
