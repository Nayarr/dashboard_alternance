"""Generation des lettres de motivation via Claude Code en mode headless.

Le token `claude setup-token` du .env permet d'appeler Claude Code sans session
interactive : c'est le mecanisme officiel prevu pour un abonnement.

    python cli.py lettres --limite 5          # les 5 meilleurs scores
    python cli.py lettres --offre 59          # une offre precise
    python cli.py lettres --limite 50 --force # regenere meme si deja ecrite
"""

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from alternance import chemins
from alternance import config
from alternance import db

BASE = config.RACINE
LETTRES = BASE / "lettres"
# Le prompt systeme porte les faits verifies du candidat : parcours, projets,
# competences. C'est une piece personnelle, exclue du git. Le .exemple qui
# l'accompagne sert de gabarit, et de repli pour que l'outil demarre sans lui.
SYSTEME = BASE / "prompts" / "systeme_lettre.md"
if not SYSTEME.exists():
    SYSTEME = BASE / "prompts" / "systeme_lettre.exemple.md"
TIMEOUT = 300


def slug(texte):
    texte = unicodedata.normalize("NFD", (texte or "").lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = re.sub(r"[^a-z0-9]+", "_", texte).strip("_")
    return texte or "entreprise"


def contexte_offre(o):
    """Ce que Claude doit savoir de l'offre, sans bruit."""
    lignes = [f"Entreprise : {o['entreprise'] or 'non communiquee'}"]
    if o["naf"]:
        lignes.append(f"Secteur : {o['naf']}")
    if o["taille"]:
        lignes.append(f"Effectif : {o['taille']}")
    if o["lieu"]:
        d = f" (a {o['distance_km']} km du domicile)" if o["distance_km"] else ""
        lignes.append(f"Lieu : {o['lieu']}{d}")
    if o["contrat_duree"]:
        lignes.append(f"Duree annoncee : {o['contrat_duree']} mois")

    if o["genre"] == "spontanee":
        lignes.append(
            "\nIl s'agit d'une CANDIDATURE SPONTANEE : aucune offre n'est publiee. "
            "Le 'Vous' doit donc porter sur le metier et le secteur de l'entreprise, "
            "pas sur des missions precises. Sois concret sur ce qu'il peut leur "
            "apporter compte tenu de leur activite."
        )
    else:
        lignes.append("\nIntitule du poste : " + (o["intitule"] or ""))
        lignes.append("\nTexte de l'annonce :\n" + (o["description"] or "")[:6000])
    return "\n".join(lignes)


def nature_contrat(o):
    """Ligne d'en-tete qui dit au redacteur de quoi il s'agit.

    Sans elle, toute lettre parlait de rythme d'alternance, y compris pour un
    stage — ce qui se voit immediatement a la lecture.
    """
    from alternance import filtres as filters
    # Les offres arrivent en sqlite3.Row, qui n'expose pas .get() : filters
    # travaille sur des dictionnaires. Sans cette conversion, la generation
    # echouait pour TOUTES les offres, pas seulement les stages.
    o = dict(o)
    if not filters.est_stage(o):
        return ("NATURE : ALTERNANCE, rythme 1 semaine entreprise / 1 semaine "
                "formation. Ne parle pas de duree de stage.")

    cible = config.STAGE_DUREE_SEMAINES
    base = (f"NATURE : STAGE de {cible} semaines, a temps plein. "
            "Ne parle pas de rythme d'alternance.")

    duree = o.get("contrat_duree")
    if duree is None:
        # Pres de la moitie des annonces de stage n'indiquent aucune duree.
        # La lettre doit alors poser le besoin explicitement, sinon le
        # recruteur decouvre la contrainte au premier echange.
        return (base + f" L'annonce n'indique AUCUNE duree : formule clairement "
                f"que le stage recherche dure {cible} semaines, en une phrase "
                "simple, sans en faire un point de blocage.")
    if duree > cible + config.STAGE_ECART_LONG:
        return (base + f" L'annonce annonce {duree} semaines, plus que les "
                f"{cible} necessaires : dis en une phrase que la duree requise "
                f"est de {cible} semaines et que le calendrier reste a caler "
                "ensemble. Pas de justification longue.")
    return base + " La duree annoncee correspond : ne reviens pas dessus."


# Consigne ajoutee au prompt systeme quand la relecture est active. Elle est
# ici et non dans systeme_lettre.md parce que ce fichier-la est personnel et
# recopie depuis un .exemple : une consigne technique n'a pas a dependre du
# fait que quelqu'un ait pense a la reporter.
RELECTURE = """
Avant de rediger, invoque le skill lettre-motivation et applique sa methode.
Une fois la lettre ecrite, invoque humanizer-fr puis lettre-motivation-anti-ia
et corrige le texte selon leurs retours. Ne renvoie que la lettre finale, sans
commentaire sur les corrections apportees."""


def appeler_claude(contexte, nature=None):
    env = dict(os.environ)
    token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        sys.exit("CLAUDE_CODE_OAUTH_TOKEN absent du .env")

    prompt = (
        "Redige la lettre de motivation correspondant a cette candidature.\n\n"
        + ((nature + "\n\n") if nature else "")
        + contexte
    )
    systeme = SYSTEME.read_text(encoding="utf-8")
    if config.LETTRE_RELECTURE:
        systeme += "\n" + RELECTURE

    resultat = subprocess.run(
        ["claude", "-p", prompt,
         "--append-system-prompt", systeme,
         # "Skill" et pas "" : --allowedTools est une liste d'outils autorises
         # SANS demande de permission, pas une restriction de ce qui existe.
         # Avec une liste vide, le Skill tool restait present mais toute
         # invocation attendait une approbation que personne ne peut donner en
         # mode headless. Les skills du projet etaient donc inertes.
         "--allowedTools", "Skill"],
        capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=TIMEOUT, cwd=str(BASE),
    )
    if resultat.returncode != 0:
        raise RuntimeError((resultat.stderr or resultat.stdout)[:400])
    return resultat.stdout.strip()


def nettoyer(texte):
    """Retire les residus de formatage et les caracteres typographiques IA."""
    texte = re.sub(r"^```[a-z]*\n|\n```$", "", texte.strip())
    for mauvais, bon in [("—", ", "), ("–", ", "), ("’", "'"),
                         ("‘", "'"), ("“", '"'), ("”", '"'),
                         ("…", "..."), (" ", " "), (" ", " ")]:
        texte = texte.replace(mauvais, bon)
    return re.sub(r"\n{3,}", "\n\n", texte).strip()


def generer(conn, o, force=False):
    # Chemin indexe sur l'offre et non sur l'entreprise : deux postes chez un
    # meme employeur doivent avoir deux lettres distinctes.
    chemins.dossier_candidature(o, creer=True)
    fichier = chemins.lettre_txt(o)

    if fichier.exists() and not force:
        return fichier, "deja_ecrite"

    texte = nettoyer(appeler_claude(contexte_offre(o), nature_contrat(o)))
    mots = len(texte.split())
    if mots < 120:
        raise RuntimeError(f"lettre anormalement courte ({mots} mots)")

    fichier.write_text(texte + "\n", encoding="utf-8")
    conn.execute("UPDATE offres SET statut = 'lettre_prete' WHERE id = ?", (o["id"],))
    db.log(conn, o["id"], "lettre:generee", f"{mots} mots -> {fichier.name}")
    conn.commit()
    return fichier, f"{mots} mots"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=5)
    p.add_argument("--offre", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--sans-relecture", action="store_true",
                   help="ignore les skills de relecture, environ 8 fois moins "
                        "de jetons et 4 fois plus rapide")
    args = p.parse_args()

    if args.sans_relecture:
        config.LETTRE_RELECTURE = False
    if config.LETTRE_RELECTURE:
        print("relecture par les skills active "
              "(--sans-relecture pour l'ignorer)\n")

    conn = db.connect()
    if args.offre:
        offres = conn.execute("SELECT * FROM offres WHERE id = ?",
                              (args.offre,)).fetchall()
    else:
        # Une offre dont la reconnaissance a montre qu'elle n'accepte ni zone
        # de texte ni piece jointe n'a pas besoin de lettre : la rediger
        # couterait 65 000 jetons pour un fichier que personne ne lira.
        # NULL signifie "pas encore inspectee" : on la traite normalement.
        offres = conn.execute(
            "SELECT * FROM offres WHERE statut = 'a_traiter' "
            "AND NOT (COALESCE(lettre_texte, 1) = 0 AND COALESCE(lettre_fichier, 1) = 0) "
            "ORDER BY score DESC LIMIT ?", (args.limite,)).fetchall()

        ignorees = conn.execute(
            "SELECT COUNT(*) c FROM offres WHERE statut = 'a_traiter' "
            "AND lettre_texte = 0 AND lettre_fichier = 0").fetchone()[0]
        if ignorees:
            print(f"{ignorees} offre(s) ignoree(s) : leur formulaire n'accepte "
                  "aucune lettre" + '\n')

    print(f"{len(offres)} lettre(s) a produire\n")
    ok = echecs = 0
    for o in offres:
        nom = (o["entreprise"] or "?")[:30]
        try:
            fichier, info = generer(conn, o, args.force)
            print(f"  OK   #{o['id']:4} [{o['score']:3}] {nom:32} {info}")
            ok += 1
        except Exception as e:
            print(f"  ECHEC #{o['id']:4} {nom:32} {str(e)[:90]}")
            echecs += 1

    print(f"\n{ok} lettre(s) ecrite(s), {echecs} echec(s)")
    conn.close()


if __name__ == "__main__":
    main()
