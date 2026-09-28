# -*- coding: utf-8 -*-
"""Redaction des lettres.

Aucun appel a Claude n'est emis : le sous-processus est remplace. Ces tests
portent sur ce qui entoure l'appel, pas sur le texte produit.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alternance import chemins
from alternance import config
from alternance.redaction import lettres


def prompt_rempli():
    """Un prompt systeme dont la section candidat a ete remplie.

    Le vrai systeme_lettre.md est personnel et absent de la CI : les tests
    qui passent l'appel en ont besoin d'un, sans quoi ils s'arretent sur le
    controle du prompt avant d'atteindre ce qu'ils verifient.
    """
    fichier = Path(tempfile.mkdtemp()) / "systeme_lettre.md"
    fichier.write_text("Camille Martin, 20 ans, BUT informatique.\n",
                       encoding="utf-8")
    return mock.patch.object(lettres, "SYSTEME", fichier)


class TestAppelClaude(unittest.TestCase):
    def setUp(self):
        # Volontairement sans la forme d'un vrai jeton : le garde-fou du
        # depot refuse toute chaine en sk-ant-..., et il a raison — rien ne
        # distingue un faux d'un vrai dans un fichier versionne. Le code
        # teste ne verifie que la presence de la variable.
        self.env = mock.patch.dict(
            "os.environ", {"CLAUDE_CODE_OAUTH_TOKEN": "jeton-de-test"})
        self.env.start()
        self.systeme = prompt_rempli()
        self.systeme.start()

    def tearDown(self):
        self.systeme.stop()
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


class TestPromptSysteme(unittest.TestCase):
    """Sur un poste ou systeme_lettre.md n'avait pas ete recopie, le gabarit
    servait de repli. Claude refusait d'ecrire faute de faits, et ce refus
    etait enregistre comme lettre de l'offre."""

    def test_fichier_absent_est_refuse_avant_tout_appel(self):
        absent = Path(tempfile.mkdtemp()) / "systeme_lettre.md"
        with mock.patch.object(lettres, "SYSTEME", absent), \
                mock.patch.dict("os.environ",
                                {"CLAUDE_CODE_OAUTH_TOKEN": "jeton-de-test"}), \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as capture:
                lettres.appeler_claude("une offre")
        run.assert_not_called()
        self.assertIn("systeme_lettre.exemple.md", str(capture.exception))

    def test_gabarit_recopie_tel_quel_est_refuse(self):
        dossier = Path(tempfile.mkdtemp())
        copie = dossier / "systeme_lettre.md"
        copie.write_text(lettres.GABARIT.read_text(encoding="utf-8"),
                         encoding="utf-8")
        with mock.patch.object(lettres, "SYSTEME", copie):
            with self.assertRaises(RuntimeError) as capture:
                lettres.prompt_systeme()
        self.assertIn("gabarit", str(capture.exception))

    def test_le_marqueur_figure_bien_dans_le_gabarit(self):
        """Si le gabarit est reformule, le controle ne doit pas devenir
        muet sans que personne ne s'en apercoive."""
        self.assertIn(lettres.MARQUEUR_GABARIT,
                      lettres.GABARIT.read_text(encoding="utf-8"))


class TestReponseQuiNestPasUneLettre(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._lettres = chemins.LETTRES
        chemins.LETTRES = self.dossier

    def tearDown(self):
        chemins.LETTRES = self._lettres

    def generer(self, reponse):
        conn = mock.Mock()
        with mock.patch.object(lettres, "appeler_claude", return_value=reponse), \
                mock.patch.object(lettres, "contexte_offre", return_value=""), \
                mock.patch.object(lettres, "nature_contrat", return_value=""):
            resultat = lettres.generer(conn, {"id": 7, "entreprise": "Acme"})
        return conn, resultat

    def test_un_refus_nest_pas_enregistre(self):
        """Le texte de la panne reelle : plus de 120 mots, donc accepte."""
        refus = ("Le fichier `prompts/systeme_lettre.md` contient encore le "
                 "gabarit vide, sans les informations du candidat. Je ne peux "
                 "pas rediger la lettre sans ces donnees. " + "mot " * 150)
        with self.assertRaises(RuntimeError) as capture:
            self.generer(refus)
        self.assertIn("pas une lettre", str(capture.exception))
        self.assertEqual(list(self.dossier.rglob("*.txt")), [])

    def test_une_lettre_est_enregistree(self):
        conn, (fichier, info) = self.generer(
            "Madame, Monsieur,\n\n" + "mot " * 200)
        self.assertTrue(fichier.exists())
        self.assertIn("lettre_prete", conn.execute.call_args_list[0][0][0])


if __name__ == "__main__":
    unittest.main()
