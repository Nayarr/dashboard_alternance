"""Envoi d'une candidature par email, avec les pieces jointes generees.

Rien ne part sans confirmation explicite : sans --confirmer, le script affiche
le message et s'arrete.

    python cli.py envoyer --offre 925              # apercu, n'envoie rien
    python cli.py envoyer --offre 925 --confirmer  # envoie reellement
"""

import argparse
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from alternance import chemins
from alternance import config
from alternance import db
from alternance.courrier import graph as graph_mail

BASE = config.RACINE
LETTRES = BASE / "lettres"

PIECES = ["lettre.pdf", chemins.CV.name, "dossier_de_motivation.pdf"]


def slug(texte):
    return "".join(c if c.isalnum() else "_" for c in (texte or "").lower()).strip("_")


BRUIT_INTITULE = re.compile(
    r"\(?\s*[hf]\s*/\s*[fh]\s*\)?"                  # (H/F), F/H
    r"|\balternances?\b"                            # deja porte par l'objet
    r"|\balternant\(?e?\)?\b|\balternant\.e\b"      # alternant, alternant(e)
    r"|\bapprenti\(?e?\)?\b|\bstages?\b"
    r"|r[ée]f\.?\s*\S+",                            # references internes
    re.I)

# Suffixes inclusifs residuels : DEVELOPPEUR(SE), charge(e), technicien(ne)
SUFFIXE_INCLUSIF = re.compile(r"\((?:e|se|ne|ere|ère|euse|trice|ive)\)", re.I)


def nettoyer_intitule(intitule):
    """Retire d'un intitule ce que l'objet du mail porte deja ou n'apporte rien."""
    texte = BRUIT_INTITULE.sub(" ", intitule or "")
    texte = SUFFIXE_INCLUSIF.sub("", texte)
    texte = re.sub(r"\s{2,}", " ", texte)
    texte = texte.strip(" -–—·,/()").strip()

    # Les annonces en capitales crient dans une boite de reception
    lettres = [c for c in texte if c.isalpha()]
    if lettres and sum(c.isupper() for c in lettres) / len(lettres) > 0.8:
        texte = texte.capitalize()
    elif texte:
        texte = texte[0].upper() + texte[1:]
    return texte


def objet_mail(offre):
    """L'objet porte le nom : il sert au tri et a la recherche ulterieure dans
    la boite du recruteur. On vise 70 caracteres, seuil de troncature mobile."""
    nom = config.PROFIL["nom"]
    if offre["genre"] == "spontanee":
        return f"Alternance dev fullstack & automatisation - sept. 2026 - {nom}"

    intitule = nettoyer_intitule(offre["intitule"])
    if not intitule:
        intitule = "Développeur"

    suffixe = f" - Alternance sept. 2026 - {nom}"
    marge = 70 - len(suffixe)
    if len(intitule) > marge:
        # On coupe sur un mot entier plutot qu'en plein milieu
        intitule = intitule[:marge].rsplit(" ", 1)[0].rstrip(" -(") + "…"
    return f"{intitule}{suffixe}"


def corps_mail(offre, lettre=None):
    """Message d'accompagnement court : la lettre reste en piece jointe.

    Le parametre `lettre` est ignore. Il subsiste pour pouvoir rebasculer sans
    changer les appelants si on veut remettre la lettre dans le corps du mail.
    """
    return (
        f"Madame, Monsieur,\n\n"
        f"Je vous adresse ma candidature pour une alternance de "
        f"{config.PROFIL['duree_mois']} mois à partir du 1er septembre 2026, "
        f"dans le cadre de ma troisième année de BUT Informatique à l'IUT de "
        f"Créteil-Vitry.\n\n"
        f"Vous trouverez en pièces jointes ma lettre de motivation, mon CV et "
        f"un dossier détaillant mon parcours, mes projets et mon calendrier "
        f"d'alternance.\n\n"
        f"Cordialement,\n"
        f"{config.PROFIL['nom']}\n"
        f"{config.PROFIL['telephone_affiche']} · {config.PROFIL['email']}"
        + (f"\n{config.PROFIL['liens']}" if config.PROFIL.get("liens") else "")
    )


def lire_lettre(dossier):
    fichier = dossier / "lettre.txt"
    return fichier.read_text(encoding="utf-8") if fichier.exists() else None


def construire_smtp(offre, pieces):
    msg = EmailMessage()
    msg["From"] = f"{config.PROFIL['nom']} <{os.environ['SMTP_USER']}>"
    msg["To"] = offre["contact_email"]
    msg["Reply-To"] = config.PROFIL["email"]
    msg["Subject"] = objet_mail(offre)
    msg.set_content(corps_mail(offre, lire_lettre(pieces[0].parent)))

    for chemin in pieces:
        msg.add_attachment(chemin.read_bytes(), maintype="application",
                           subtype="pdf", filename=chemin.name)
    return msg


def envoyer_graph(offre, pieces):
    """Envoi depuis l'adresse universitaire via Microsoft Graph."""
    graph_mail.envoyer(
        destinataire=offre["contact_email"],
        objet=objet_mail(offre),
        corps=corps_mail(offre, lire_lettre(pieces[0].parent)),
        pieces=pieces,
    )
    return os.environ.get("GRAPH_EXPEDITEUR", "(adresse universitaire)")


def canal_disponible():
    """Premier canal reellement configure, ou None.

    Le defaut ne peut pas etre fixe une fois pour toutes : graph suppose une
    application declaree dans l'Entra ID d'un etablissement, ce que personne
    n'a en dehors de celui pour qui l'outil a ete ecrit. Choisir a la place de
    l'utilisateur evite un echec d'authentification incomprehensible.
    """
    if os.environ.get("GRAPH_CLIENT_ID") and os.environ.get("GRAPH_TENANT_ID"):
        return "graph"
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_APP_PASSWORD"):
        return "gmail"
    return None


def envoyer_smtp(offre, pieces):
    """Envoi de secours via Gmail, avec Reply-To sur l'adresse universitaire."""
    user = os.environ.get("SMTP_USER")
    mdp = os.environ.get("SMTP_APP_PASSWORD")
    if not user or not mdp:
        sys.exit("SMTP_USER et SMTP_APP_PASSWORD doivent être renseignés dans .env")

    msg = construire_smtp(offre, pieces)
    contexte = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=contexte) as s:
        s.login(user, mdp)
        s.send_message(msg)
    return user


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--offre", type=int, required=True)
    p.add_argument("--confirmer", action="store_true",
                   help="sans ce drapeau, rien n'est envoye")
    p.add_argument("--canal", choices=["auto", "graph", "gmail"], default="auto",
                   help="auto = premier canal configure ; graph = Microsoft 365 ; "
                        "gmail = mot de passe d'application")
    args = p.parse_args()

    if args.canal == "auto":
        args.canal = canal_disponible()
        if args.canal is None:
            sys.exit("Aucun canal d'envoi configure : renseigner SMTP_USER et "
                     "SMTP_APP_PASSWORD dans .env, ou les trois variables "
                     "GRAPH_* pour une adresse Microsoft 365.")

    conn = db.connect()
    o = conn.execute("SELECT * FROM offres WHERE id = ?", (args.offre,)).fetchone()
    if o is None:
        sys.exit(f"offre {args.offre} introuvable")
    if not o["contact_email"]:
        sys.exit(f"aucune adresse de contact pour l'offre {args.offre}")

    # chemins.dossier_candidature indexe par ID D'OFFRE, pas par entreprise.
    # L'ancien schema LETTRES/<entreprise> faisait partager le meme dossier a
    # deux offres du meme employeur : la seconde candidature partait avec la
    # lettre de la premiere. Le reste du projet a migre, pas ce script.
    dossier = chemins.dossier_candidature(o)
    pieces = [dossier / n for n in PIECES]
    manquantes = [p.name for p in pieces if not p.exists()]
    if manquantes:
        sys.exit(f"pieces manquantes : {manquantes}\nLancer d'abord : python cli.py pieces")

    expediteur = {
        "graph": os.environ.get("GRAPH_EXPEDITEUR") or "(GRAPH_EXPEDITEUR absent)",
        "gmail": os.environ.get("SMTP_USER") or "(SMTP_USER absent du .env)",
    }[args.canal]
    print(f"Canal   : {args.canal}")
    print(f"De      : {expediteur}")
    print(f"À       : {o['contact_email']}")
    print(f"Objet   : {objet_mail(o)}")
    print(f"Pièces  : " + ", ".join(
        f"{p.name} ({p.stat().st_size // 1024} Ko)" for p in pieces))
    print("\n" + "-" * 68)
    print(corps_mail(o, lire_lettre(dossier)))
    print("-" * 68)

    if not args.confirmer:
        print("APERÇU — rien n'a été envoyé. Ajouter --confirmer pour envoyer.")
        return

    envoye_par = {"graph": envoyer_graph,
                  "gmail": envoyer_smtp}[args.canal](o, pieces)

    maintenant = datetime.now().isoformat(timespec="seconds")
    conn.execute("UPDATE offres SET statut = 'envoyee' WHERE id = ?", (args.offre,))
    conn.execute(
        "INSERT INTO candidatures (offre_id, canal, lettre_path, cv_path, "
        "dossier_path, date_preparation, date_envoi, statut, date_relance_prevue) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'envoyee', date('now', '+7 days'))",
        (args.offre, args.canal, str(pieces[0]), str(pieces[1]), str(pieces[2]),
         maintenant, maintenant),
    )
    db.log(conn, args.offre, f"envoi:{args.canal}",
           f"de {envoye_par} vers {o['contact_email']}")
    conn.commit()
    conn.close()
    print(f"\nEnvoyé de {envoye_par} à {o['contact_email']}.")
    print("Relance prévue dans 7 jours.")


if __name__ == "__main__":
    main()
