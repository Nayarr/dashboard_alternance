# -*- coding: utf-8 -*-
"""Redaction des lettres.

Aucun appel a Claude n'est emis : le sous-processus est remplace. Ces tests
portent sur ce qui entoure l'appel, pas sur le texte produit.
"""

import unittest
from unittest import mock

from alternance import config
from alternance.redaction import lettres


class TestAppelClaude(unittest.TestCase):
    def setUp(self):
        # Volontairement sans la forme d'un vrai jeton : le garde-fou du
        # depot refuse toute chaine en sk-ant-..., et il a raison — rien ne
        # distingue un faux d'un vrai dans un fichier versionne. Le code
        # teste ne verifie que la presence de la variable.
        self.env = mock.patch.dict(
            "os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "jeton-de-test"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_claude_absent_donne_un_message_utilisable(self):
        """L'interface affichait « FileNotFoundError: [WinError 2] Le fichier
        specifie est introuvable » : exact, et muet sur le fichier en question.
        Le message doit nommer ce qui manque et dire comment l'obtenir."""
        with mock.patch("subprocess.run", side_effect=FileNotFoundError(2, "x")):
            with self.assertRaises(RuntimeError) as capture:
                lettres.appeler_claude("une offre")

        message = str(capture.exception)
        self.assertIn("claude", message)
        self.assertIn("npm install", message)
        self.assertNotIn("WinError", message)

    def test_skill_est_autorise(self):
        """--allowedTools est la liste des outils qui n'exigent PAS
        d'autorisation. Vide, les skills restaient inertes en mode headless."""
        faux = mock.Mock(returncode=0, stdout="Madame, Monsieur, " + "mot " * 200,
                         stderr="")
        with mock.patch("subprocess.run", return_value=faux) as run:
            lettres.appeler_claude("une offre")

        commande = run.call_args[0][0]
        self.assertIn("--allowedTools", commande)
        self.assertEqual(commande[commande.index("--allowedTools") + 1], "Skill")

    def test_relecture_ajoute_sa_consigne_au_prompt_systeme(self):
        faux = mock.Mock(returncode=0, stdout="lettre", stderr="")
        initial = config.LETTRE_RELECTURE
        try:
            for actif, attendu in ((True, True), (False, False)):
                config.LETTRE_RELECTURE = actif
                with mock.patch("subprocess.run", return_value=faux) as run:
                    lettres.appeler_claude("une offre")
                commande = run.call_args[0][0]
                systeme = commande[commande.index("--append-system-prompt") + 1]
                self.assertEqual("humanizer-fr" in systeme, attendu,
                                 f"relecture={actif}")
        finally:
            config.LETTRE_RELECTURE = initial


if __name__ == "__main__":
    unittest.main()
