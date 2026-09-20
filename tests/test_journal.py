# -*- coding: utf-8 -*-
"""Traduction des echecs.

Un message d'erreur doit repondre a « et maintenant ? ». Ces tests verifient
que les pannes deja rencontrees sont reconnues, et qu'aucune ne retombe sur
« code de sortie 1 ».
"""

import unittest

import journal


class TestDiagnostics(unittest.TestCase):
    CAS = [
        ("CLAUDE_CODE_OAUTH_TOKEN absent du .env", "Jeton Claude"),
        ("ModuleNotFoundError: No module named 'flask'", "flask"),
        ("Error: Executable doesn't exist at /ms-playwright/chromium",
         "playwright install"),
        ("sqlite3.OperationalError: no such column: url_ats", "git pull"),
        ("sqlite3.OperationalError: database is locked", "verrouillee"),
        ("requests.exceptions.ConnectionError: Max retries exceeded",
         "connexion reseau"),
        ("HTTP 429 Too Many Requests", "limite"),
        ("# session WTTJ expiree", "session"),
    ]

    def test_chaque_panne_connue_est_traduite(self):
        for sortie, attendu in self.CAS:
            with self.subTest(sortie=sortie[:40]):
                phrase = journal.expliquer(sortie, 1)
                self.assertIn(attendu.lower(), phrase.lower())
                self.assertNotIn("code de sortie", phrase.lower())

    def test_nom_du_module_manquant_repris(self):
        self.assertIn("bs4", journal.expliquer(
            "ModuleNotFoundError: No module named 'bs4'", 1))

    def test_exception_inconnue_remontee_telle_quelle(self):
        phrase = journal.expliquer(
            "Traceback...\nValueError: quelque chose d'inattendu", 1)
        self.assertIn("ValueError", phrase)

    def test_arret_sans_message_n_est_pas_pris_pour_un_succes(self):
        """Une tache tuee affichait sa derniere ligne comme motif d'echec,
        soit « OK # 857 Essilor deja_ecrite » en rouge."""
        phrase = journal.expliquer("10 lettre(s) a produire\n  OK  # 857 deja_ecrite", 1)
        self.assertIn("Arret inattendu", phrase)

    def test_sortie_vide(self):
        self.assertIn("sans message", journal.expliquer("", 1))


class TestEcriture(unittest.TestCase):
    def test_enregistrer_ne_leve_jamais(self):
        """Un journal qui casse son appelant serait pire que pas de journal."""
        initial = journal.FICHIER
        try:
            journal.FICHIER = journal.DOSSIER / "?" / "impossible.log"
            journal.enregistrer("test", "message", "detail")
        finally:
            journal.FICHIER = initial

    def test_exception_retourne_un_resume(self):
        try:
            raise ValueError("cas de test")
        except ValueError as e:
            resume = journal.exception("test", e)
        self.assertIn("ValueError", resume)
        self.assertIn("cas de test", resume)


if __name__ == "__main__":
    unittest.main()
