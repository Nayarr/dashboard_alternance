# -*- coding: utf-8 -*-
"""Redaction des lettres.

Aucun appel a Claude n'est emis : le sous-processus est remplace. Ces tests
portent sur ce qui entoure l'appel, pas sur le texte produit.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from alternance import chemins
from alternance import config
from alternance import journal
from alternance.redaction import lettres
from alternance.redaction import parcours

PROFIL_SAISI = dict(config.DEFAUTS["profil"], nom="Camille Martin",
                    email="camille.martin@exemple.org",
                    rythme="2 jours formation / 3 jours entreprise")


class prompt_rempli:
    """Un parcours rempli et un profil saisi, comme apres la mise en route.

    Le vrai parcours est personnel et absent de la CI, et le profil y reste
    aux valeurs d'exemple : les tests qui passent l'appel en ont besoin, sans
    quoi ils s'arretent sur le controle du prompt avant d'atteindre ce qu'ils
    verifient. Tout est redirige vers un dossier temporaire : rien ne lit ni
    n'ecrit le parcours de la personne qui lance la suite.
    """

    def start(self):
        dossier = Path(tempfile.mkdtemp())
        fichier = dossier / "parcours.md"
        fichier.write_text("## Projets\n\nUn outil de suivi de candidatures.\n",
                           encoding="utf-8")
        self._patches = [mock.patch.object(parcours, "FICHIER", fichier),
                         mock.patch.object(parcours, "SYSTEME",
                                           dossier / "systeme_lettre.md"),
                         mock.patch.object(config, "PROFIL", dict(PROFIL_SAISI))]
        for patch in self._patches:
            patch.start()

    def stop(self):
        for patch in self._patches:
            patch.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


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


def pdf_texte(lignes):
    """Un PDF d'une page portant ces lignes en texte, lisible par pypdf.

    Fabrique a la main : aucune dependance de plus pour les tests, et aucun
    vrai CV dans le depot.
    """
    flux = "BT /F1 10 Tf 50 800 Td 12 TL "
    for ligne in lignes:
        propre = (ligne.replace("\\", "\\\\").replace("(", "\\(")
                  .replace(")", "\\)"))
        flux += f"({propre}) Tj T* "
    flux += "ET"
    objets = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(flux)} >>\nstream\n{flux}\nendstream",
    ]
    sortie = "%PDF-1.4\n"
    positions = []
    for i, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{i} 0 obj\n{corps}\nendobj\n"
    xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n"
    sortie += "".join(f"{p:010d} 00000 n \n" for p in positions)
    sortie += (f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\n"
               f"startxref\n{xref}\n%%EOF\n")
    return sortie.encode("latin-1")


CV_LIGNES = (["Camille Martin", "EXPERIENCE PROFESSIONNELLE",
              "Stage chez Acme Logistique, 2026 : API de suivi des colis en Flask"]
             + [f"Projet {i} : application web de gestion, Python et PostgreSQL"
                for i in range(8)])


class TestParcours(unittest.TestCase):
    """Le parcours ne venait que de systeme_lettre.md, un fichier a editer a
    la main. Qui s'en tenait a l'interface n'obtenait aucune lettre : le
    message lui demandait d'ouvrir un fichier qu'il ne saurait pas trouver,
    alors que son CV, depose depuis l'interface, porte exactement ces faits."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self.cv = self.dossier / "CV-Camille Martin.pdf"
        self.cv.write_bytes(pdf_texte(CV_LIGNES))
        self.systeme = self.dossier / "systeme_lettre.md"
        self.saisi = self.dossier / "parcours.md"
        self._patches = [
            mock.patch.object(config, "PROFIL", dict(PROFIL_SAISI)),
            mock.patch.object(parcours, "SYSTEME", self.systeme),
            mock.patch.object(parcours, "FICHIER", self.saisi),
            mock.patch.object(chemins, "trouver_cv", return_value=self.cv),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()

    def test_sans_fichier_le_cv_fournit_le_parcours(self):
        systeme = lettres.prompt_systeme()
        self.assertIn("Acme Logistique", systeme)
        self.assertIn("Camille Martin", systeme)
        # Les consignes d'ecriture du gabarit suivent, sa section candidat
        # d'exemple et son commentaire d'emploi non.
        self.assertIn("# Comment écrire", systeme)
        self.assertIn("# Interdits absolus", systeme)
        for marqueur in parcours.MARQUEURS_GABARIT:
            self.assertNotIn(marqueur, systeme)
        self.assertNotIn("GABARIT", systeme)

    def test_gabarit_recopie_tel_quel_cede_la_place_au_cv(self):
        self.systeme.write_text(parcours.GABARIT.read_text(encoding="utf-8"),
                                encoding="utf-8")
        self.assertIn("Acme Logistique", lettres.prompt_systeme())

    def test_ancien_gabarit_recopie_cede_la_place_au_cv(self):
        """Les copies faites avant que l'identite passe dans les Parametres
        commencent par « Prénom Nom, 20 ans. »."""
        self.systeme.write_text("# Le candidat\n\nPrénom Nom, 20 ans. BUT.\n",
                                encoding="utf-8")
        self.assertIn("Acme Logistique", lettres.prompt_systeme())

    def test_un_parcours_rempli_garde_la_priorite(self):
        """Plus precis qu'un PDF dont la mise en page est perdue."""
        self.systeme.write_text("## Projets\n\nUn outil de suivi.\n",
                                encoding="utf-8")
        systeme = lettres.prompt_systeme()
        self.assertIn("Un outil de suivi", systeme)
        self.assertNotIn("Acme Logistique", systeme)

    def test_un_marqueur_figure_bien_dans_le_gabarit(self):
        """Si le gabarit est reformule, le controle ne doit pas devenir
        muet sans que personne ne s'en apercoive."""
        gabarit = parcours.GABARIT.read_text(encoding="utf-8")
        self.assertTrue(any(m in gabarit for m in parcours.MARQUEURS_GABARIT))
        self.assertIn("# Le candidat", gabarit)
        self.assertIn("# Comment écrire", gabarit)

    def test_ni_parcours_ni_cv_refuse_avant_tout_appel(self):
        self.cv.unlink()
        with mock.patch.dict("os.environ",
                             {"CLAUDE_CODE_OAUTH_TOKEN": "jeton-de-test"}), \
                mock.patch("subprocess.run") as run:
            with self.assertRaises(RuntimeError) as capture:
                lettres.appeler_claude("une offre")
        run.assert_not_called()
        message = str(capture.exception)
        self.assertIn("CV", message)
        # L'utilisateur de l'interface n'a aucun fichier a ouvrir.
        self.assertNotIn("systeme_lettre", message)

    def test_un_cv_image_est_refuse(self):
        """Un scan ne donne que des bribes : une lettre ecrite dessus
        inventerait le reste."""
        self.cv.write_bytes(pdf_texte(["Camille Martin"]))
        with self.assertRaises(RuntimeError) as capture:
            lettres.prompt_systeme()
        self.assertIn("image", str(capture.exception))

    def test_un_pdf_corrompu_est_refuse_proprement(self):
        self.cv.write_bytes(b"ceci n'est pas un pdf")
        with self.assertRaises(RuntimeError) as capture:
            lettres.prompt_systeme()
        self.assertIn(self.cv.name, str(capture.exception))

    def test_profil_reste_a_l_exemple_est_refuse(self):
        with mock.patch.object(config, "PROFIL",
                               dict(config.DEFAUTS["profil"])):
            with self.assertRaises(RuntimeError) as capture:
                lettres.prompt_systeme()
        self.assertIn("Parametres", str(capture.exception))

    def test_le_refus_s_affiche_tel_quel_dans_l_interface(self):
        """Sans cas connu, l'interface titrait « Arret inattendu, sans
        message d'erreur » au-dessus d'un message qui disait quoi faire."""
        self.cv.unlink()
        try:
            lettres.prompt_systeme()
        except RuntimeError as e:
            sortie = "relecture active\n" + str(e)
        else:
            self.fail("sans CV ni parcours, le prompt devait etre refuse")
        raison = journal.expliquer(sortie, 1)
        self.assertNotIn("inattendu", raison)
        self.assertNotIn("Lettres impossibles", raison)

    # ------------------------------------------------ saisie dans l'interface

    def test_la_page_affiche_le_texte_du_cv_sans_les_puces(self):
        self.cv.write_bytes(pdf_texte(CV_LIGNES + ["Git et Docker ->"]))
        etat = parcours.lire()
        self.assertEqual(etat["source"], "cv")
        self.assertEqual(etat["cv"], self.cv.name)
        self.assertIn("Acme Logistique", etat["texte"])

    def test_les_fleches_des_puces_sont_retirees(self):
        texte = parcours.nettoyer_cv("Projet Papyrus\n\u2192\nPipeline Python.\u2192")
        self.assertEqual(texte, "Projet Papyrus\nPipeline Python.")

    def test_un_parcours_saisi_passe_avant_tout(self):
        self.systeme.write_text("## Projets\n\nAncien fichier.\n",
                                encoding="utf-8")
        parcours.enregistrer("Stage chez Globex : refonte du back-office.")
        systeme = lettres.prompt_systeme()
        self.assertIn("Globex", systeme)
        self.assertNotIn("Ancien fichier", systeme)
        self.assertNotIn("Acme Logistique", systeme)
        # Les consignes d'ecriture viennent du gabarit.
        self.assertIn("# Interdits absolus", systeme)
        self.assertEqual(parcours.lire()["source"], "manuel")

    def test_un_parcours_saisi_se_passe_de_cv(self):
        self.cv.unlink()
        parcours.enregistrer("Stage chez Globex : refonte du back-office.")
        self.assertIn("Globex", lettres.prompt_systeme())

    def test_enregistrer_un_texte_vide_rend_la_main_au_cv(self):
        parcours.enregistrer("Stage chez Globex.")
        parcours.enregistrer("   ")
        self.assertEqual(parcours.lire()["source"], "cv")

    def test_revenir_au_cv_met_la_saisie_de_cote(self):
        parcours.enregistrer("Stage chez Globex.")
        parcours.oublier()
        self.assertEqual(parcours.lire()["source"], "cv")
        self.assertIn("Globex", (self.dossier / "parcours.precedent.md")
                      .read_text(encoding="utf-8"))

    def test_l_ancien_fichier_s_affiche_sans_les_consignes(self):
        """Le candidat y corrige ses faits, pas les regles du redacteur."""
        self.systeme.write_text(
            "Intro.\n\n# Le candidat - faits\n\nStage chez Initech.\n\n"
            "# Comment écrire\n\nVous / Moi / Nous.\n", encoding="utf-8")
        etat = parcours.lire()
        self.assertEqual(etat["source"], "fichier")
        self.assertEqual(etat["texte"], "Stage chez Initech.")

    def test_sans_cv_ni_saisie_la_page_dit_quoi_faire(self):
        self.cv.unlink()
        etat = parcours.lire()
        self.assertEqual(etat["source"], "aucun")
        self.assertEqual(etat["texte"], "")
        self.assertIn("CV", etat["erreur"])
        self.assertNotIn("Lettres impossibles", etat["erreur"])


class TestLettresDejaEnregistrees(unittest.TestCase):
    """Le controle d'ouverture empeche d'enregistrer un nouveau refus, pas
    d'effacer ceux qui sont deja sur disque. Chez une testeuse, l'un d'eux
    s'affichait en « lettre prete », a un clic d'etre colle dans le
    formulaire d'un recruteur."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self._lettres = chemins.LETTRES
        chemins.LETTRES = self.dossier
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            "CREATE TABLE offres (id INTEGER, entreprise TEXT, statut TEXT);"
            "CREATE TABLE evenements (offre_id INTEGER, date TEXT, type TEXT,"
            " detail TEXT);")

    def tearDown(self):
        chemins.LETTRES = self._lettres
        self.conn.close()

    def offre(self, id_, texte):
        o = {"id": id_, "entreprise": f"Societe {id_}"}
        self.conn.execute("INSERT INTO offres VALUES (?, ?, 'lettre_prete')",
                          (id_, o["entreprise"]))
        if texte is not None:
            chemins.dossier_candidature(o, creer=True)
            chemins.lettre_txt(o).write_text(texte, encoding="utf-8")
        return o

    def statut(self, id_):
        return self.conn.execute("SELECT statut FROM offres WHERE id = ?",
                                 (id_,)).fetchone()[0]

    def test_un_refus_enregistre_est_remis_a_rediger(self):
        refus = self.offre(1, "- **Expériences pro** : pour chacune, "
                              "entreprise, période, poste " + "mot " * 150)
        bonne = self.offre(2, "Madame, Monsieur,\n\n" + "mot " * 200)
        absente = self.offre(3, None)

        self.assertEqual(lettres.purger_lettres_invalides(self.conn), 2)

        self.assertEqual(self.statut(1), "a_traiter")
        self.assertEqual(self.statut(2), "lettre_prete")
        self.assertEqual(self.statut(3), "a_traiter")
        # Renomme, pas supprime : on peut encore lire ce qui s'est passe.
        self.assertFalse(chemins.lettre_txt(refus).exists())
        self.assertTrue(chemins.lettre_txt(refus).with_name(
            "lettre.rejetee.txt").exists())
        self.assertTrue(chemins.lettre_txt(bonne).exists())
        self.assertIsNone(chemins.lire_lettre(absente))

    def test_une_seconde_passe_ne_trouve_plus_rien(self):
        self.offre(1, "Voici la lettre demandee : " + "mot " * 150)
        lettres.purger_lettres_invalides(self.conn)
        self.assertEqual(lettres.purger_lettres_invalides(self.conn), 0)

    def test_est_une_lettre(self):
        self.assertTrue(chemins.est_une_lettre("Madame, Monsieur,\n\nJe..."))
        self.assertTrue(chemins.est_une_lettre("  Monsieur,\n..."))
        self.assertFalse(chemins.est_une_lettre("Le fichier contient..."))
        self.assertFalse(chemins.est_une_lettre(""))
        self.assertFalse(chemins.est_une_lettre(None))


class TestIdentiteDepuisLesParametres(unittest.TestCase):
    """La page Parametres annoncait que le profil « part dans les lettres ».
    La redaction ne le lisait pas : qui installait l'outil et remplissait
    l'interface obtenait des lettres sans son nom, ou un refus."""

    def test_le_profil_saisi_entre_dans_le_prompt_systeme(self):
        with prompt_rempli():
            systeme = lettres.prompt_systeme()
        self.assertIn("Camille Martin", systeme)
        self.assertIn("camille.martin@exemple.org", systeme)
        self.assertIn("Un outil de suivi de candidatures", systeme)

    def test_un_champ_vide_n_apparait_pas(self):
        with prompt_rempli():
            config.PROFIL["linkedin"] = ""
            config.PROFIL["titre"] = ""
            bloc = lettres.bloc_identite()
        self.assertNotIn("Accroche", bloc)

    def test_le_rythme_d_alternance_est_celui_du_profil(self):
        """Il etait ecrit en dur, et contredisait celui du candidat."""
        with prompt_rempli():
            nature = lettres.nature_contrat(
                {"intitule": "Alternance developpeur", "contrat_duree": 12,
                 "genre": "offre", "description": "", "source": "lba"})
        self.assertIn("2 jours formation / 3 jours entreprise", nature)


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
