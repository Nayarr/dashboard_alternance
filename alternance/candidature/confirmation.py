"""Ce qui se passe apres le clic sur « Envoyer », commun a LBA et WTTJ.

Avant, une candidature ne passait en « envoyee » que si le site affichait un
message reconnu dans les 25 secondes. Sinon l'offre restait en « lettre
prete », alors que le formulaire avait bien ete valide :

  - il fallait la marquer a la main, sans savoir si elle etait partie ;
  - surtout, le clic suivant sur « Envoyer les candidatures » la reprenait,
    et postulait une seconde fois chez le meme employeur.

Desormais une telle offre passe en « Envoi a verifier » : elle n'est plus
jamais reprise par un envoi, et c'est la personne, apres avoir regarde ses
emails ou son espace sur le site, qui confirme ou la remet en lettre prete.
"""

from datetime import datetime

from alternance import chemins
from alternance import db

# Messages affiches apres un envoi reussi : une formule de confirmation, pas
# deux mots voisins. L'ancien motif LBA, « candidature.*envoy », reconnaissait
# le texte fixe de la page - « soumettre votre candidature spontanee. Les
# candidats envoyant... » - present AVANT le clic : toute candidature LBA
# passait en « envoyee » sans la moindre preuve. Celui de WTTJ cherchait
# « recue » sans cedille et ne reconnaissait jamais « reçue ».
MOTIF = (r"/candidature(\s+spontan[ée]e)?\s+(a\s+)?(bien\s+)?(été\s+)?"
         r"(envoy[ée]e|transmise|re[çc]ue|enregistr[ée]e)"
         r"|merci pour (ta|votre) candidature"
         r"|application\s+(was\s+|has\s+been\s+)?(sent|received|submitted)/i")

# Une offre qui a deja une ligne de candidature n'est jamais reprise par un
# envoi automatique : c'est la derniere barriere contre le double envoi.
JAMAIS_CANDIDATE = "id NOT IN (SELECT offre_id FROM candidatures)"


def compter(page):
    """Elements qui ressemblent deja a une confirmation, AVANT le clic.

    Une page peut en contenir sans que rien n'ait ete envoye : seule une
    confirmation apparue apres le clic prouve l'envoi.
    """
    try:
        return page.locator("text=" + MOTIF).count()
    except Exception:
        return 0


def attendre(page, avant, delai_ms=25000, pas_ms=500):
    """Vrai si une confirmation APPARAIT apres le clic, dans le delai."""
    ecoule = 0
    while ecoule < delai_ms:
        page.wait_for_timeout(pas_ms)
        ecoule += pas_ms
        if compter(page) > avant:
            return True
    return False


def enregistrer_envoi(conn, offre, canal, cv):
    """Le site a confirme : l'offre est envoyee, la relance armee a J+7."""
    maintenant = datetime.now().isoformat(timespec="seconds")
    conn.execute("UPDATE offres SET statut = 'envoyee' WHERE id = ?", (offre["id"],))
    conn.execute(
        "INSERT INTO candidatures (offre_id, canal, lettre_path, cv_path,"
        " date_preparation, date_envoi, statut, date_relance_prevue)"
        " VALUES (?, ?, ?, ?, ?, ?, 'envoyee', date('now', '+7 days'))",
        (offre["id"], canal, str(chemins.lettre_txt(offre)), str(cv),
         maintenant, maintenant))
    db.log(conn, offre["id"], f"envoi:{canal}", offre["url_candidature"])
    conn.commit()


def enregistrer_incertain(conn, offre, canal, cv, capture):
    """Formulaire valide, confirmation non lue : a verifier, jamais a renvoyer.

    La ligne de candidature est creee des maintenant, avec l'heure du clic :
    si la personne confirme, la relance partira de cette heure-la, pas de
    celle de sa verification.
    """
    maintenant = datetime.now().isoformat(timespec="seconds")
    conn.execute("UPDATE offres SET statut = 'a_verifier' WHERE id = ?",
                 (offre["id"],))
    conn.execute(
        "INSERT INTO candidatures (offre_id, canal, lettre_path, cv_path,"
        " date_preparation, date_envoi, statut, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, 'incertain', ?)",
        (offre["id"], canal, str(chemins.lettre_txt(offre)), str(cv),
         maintenant, maintenant, f"capture apres envoi : {capture}"))
    db.log(conn, offre["id"], f"envoi:{canal}:incertain",
           f"formulaire valide, confirmation non detectee ({capture})")
    conn.commit()
