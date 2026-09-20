# -*- coding: utf-8 -*-
"""Scoring et detection de nature.

Chaque test correspond a un defaut constate en production, pas a une ligne de
code choisie au hasard : c'est ce qui rend une regression visible.
"""

import unittest

import filters
import texte


class TestCorrespondanceMotEntier(unittest.TestCase):
    """Le mot-cle `vite` matchait dans « eviter » et gonflait les scores.

    La correction pose des bornes alphanumeriques plutot que \\b, pour que les
    termes contenant une ponctuation continuent de matcher.
    """

    def test_ne_matche_pas_a_l_interieur_d_un_mot(self):
        self.assertFalse(filters.contient("vite", "il faut eviter cela"))
        self.assertFalse(filters.contient("java", "javascript uniquement"))
        self.assertFalse(filters.contient("go", "gouvernance des donnees"))

    def test_matche_le_mot_entier(self):
        self.assertTrue(filters.contient("vite", "build avec vite"))
        self.assertTrue(filters.contient("java", "developpeur java confirme"))

    def test_termes_ponctues_matchent_encore(self):
        # Des bornes \b auraient casse ces quatre cas.
        self.assertTrue(filters.contient("api rest", "conception d'api rest"))
        self.assertTrue(filters.contient("ci/cd", "pipeline ci/cd complet"))
        self.assertTrue(filters.contient("no-code", "outils no-code"))
        self.assertTrue(filters.contient("bac+3", "niveau bac+3 exige"))

    def test_attend_un_texte_deja_normalise(self):
        """`contient` ne normalise pas : c'est l'appelant qui s'en charge.

        Le contrat est documente, et le respecter evite de normaliser des
        milliers de fois le meme texte pour 85 mots-cles.
        """
        self.assertFalse(filters.contient("securite", "SÉCURITÉ applicative"))
        self.assertTrue(filters.contient(
            "securite", texte.normalise("SÉCURITÉ applicative")))


class TestNatureContrat(unittest.TestCase):
    """La nature se lit sur contrat_type, jamais sur l'intitule.

    Une offre d'alternance intitulee « ... (ex-stagiaire bienvenu) » ne doit
    pas basculer en stage.
    """

    def test_stage_reconnu(self):
        for valeur in ("Stage", "STAGE 6 mois", "internship", "Stagiaire"):
            self.assertTrue(filters.est_stage({"contrat_type": valeur}), valeur)

    def test_alternance_non_confondue(self):
        for valeur in ("Apprentissage", "Professionnalisation", "CDI", None):
            self.assertFalse(filters.est_stage({"contrat_type": valeur}), valeur)

    def test_accepte_un_objet_sqlite(self):
        """filters plantait sur sqlite3.Row, qui n'expose pas .get().

        La generation de lettres echouait alors pour TOUTES les offres, pas
        seulement les stages.
        """
        class FausseLigne:
            def __init__(self, d):
                self._d = d

            def __getitem__(self, k):
                return self._d[k]

            def keys(self):
                return self._d.keys()

        ligne = FausseLigne({"contrat_type": "Stage"})
        self.assertTrue(filters.est_stage(ligne))


class TestPlafondTechnique(unittest.TestCase):
    """Le plafond suit la longueur du texte.

    A plafond fixe, une annonce Apec de 283 caracteres etait structurellement
    penalisee face a une annonce WTTJ de 1885.
    """

    def test_croit_avec_la_longueur(self):
        court = filters.plafond_technique(300)
        long_ = filters.plafond_technique(2000)
        self.assertLess(court, long_)

    def test_plancher_respecte(self):
        self.assertGreater(filters.plafond_technique(0), 0)

    def test_plafonne_au_maximum(self):
        self.assertLessEqual(filters.plafond_technique(100000),
                             filters.PLAFONDS["technique"] + 0.01)


class TestTitreInformatique(unittest.TestCase):
    def test_reconnait_un_poste_technique(self):
        self.assertTrue(filters.titre_est_informatique(
            "developpeur back-end python"))

    def test_rejette_un_poste_non_technique(self):
        self.assertFalse(filters.titre_est_informatique(
            "charge de mission ressources humaines"))


if __name__ == "__main__":
    unittest.main()
