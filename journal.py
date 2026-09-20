"""Journal des erreurs, et traduction des echecs en messages utilisables.

Ce module existe parce que l'interface affichait « code de sortie 1 » et rien
d'autre. Le detail existait pourtant : la sortie des scripts etait bien
capturee, mais jetee. Deux manques, donc deux reponses :

    enregistrer()  ecrit tout dans data/logs/app.log, avec l'horodatage, la
                   source et la trace complete
    expliquer()    remonte a l'interface une phrase qui dit quoi faire

Une erreur affichee doit repondre a « et maintenant ? ». « code de sortie 1 »
n'y repond pas, « CLAUDE_CODE_OAUTH_TOKEN absent : page Parametres, bloc Jeton
Claude » si.
"""

import re
import traceback
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
DOSSIER = BASE / "data" / "logs"
FICHIER = DOSSIER / "app.log"

# Au-dela, le fichier courant devient app.log.1 et un neuf le remplace. Une
# seule generation conservee : ce journal sert a comprendre l'echec d'hier, pas
# a faire de l'archeologie.
TAILLE_MAX = 2_000_000

# Motifs reconnus dans la sortie d'un script, du plus precis au plus general.
# Chaque entree donne la phrase affichee a l'utilisateur. L'ordre compte : le
# premier motif qui correspond gagne.
DIAGNOSTICS = [
    (r"CLAUDE_CODE_OAUTH_TOKEN absent",
     "Jeton Claude absent. Page Parametres, bloc « Jeton Claude » : le produire "
     "avec `claude setup-token` dans un terminal."),
    (r"(?:command not found|n'est pas reconnu|WinError 2).{0,40}claude|"
     r"FileNotFoundError.{0,40}'claude'",
     "La commande `claude` est introuvable. Installer Claude Code, ou verifier "
     "qu'il est dans le PATH du compte qui lance le serveur."),
    (r"LBA_API_KEY",
     "Cle La Bonne Alternance absente ou invalide. Voir LBA_API_KEY dans .env "
     "— une cle gratuite s'obtient sur api.apprentissage.beta.gouv.fr."),
    (r"ModuleNotFoundError: No module named '([^']+)'",
     "Dependance manquante : {1}. Lancer `pip install -r requirements.txt`."),
    (r"Executable doesn't exist|playwright install|"
     r"BrowserType\.launch.{0,60}not found",
     "Le navigateur Playwright n'est pas installe. Lancer "
     "`playwright install chromium`."),
    (r"session (?:WTTJ )?expiree|authenticate|/signin",
     "La session du site a expire. Page Parametres, bloc « Comptes connectes » : "
     "reconnecter le compte concerne."),
    (r"no such (?:column|table)",
     "La base date d'une version anterieure du code. Faire `git pull` puis "
     "relancer : la colonne manquante est ajoutee automatiquement a la "
     "prochaine ouverture."),
    (r"database is locked",
     "La base est verrouillee par un autre processus. Fermer les autres "
     "instances du tableau de bord, puis relancer."),
    (r"(?:Max retries exceeded|ConnectionError|Temporary failure in name "
     r"resolution|getaddrinfo failed)",
     "Aucune connexion reseau, ou le service interroge est injoignable."),
    (r"\b429\b|rate.?limit|Too Many Requests",
     "Trop de requetes envoyees a la source : elle nous limite. Reessayer dans "
     "quelques minutes."),
    (r"\b(?:401|403)\b",
     "Acces refuse par la source (401/403). Cle d'API expiree, ou session a "
     "renouveler."),
    (r"pieces manquantes",
     "Les pieces jointes n'ont pas ete generees. Lancer `python generer.py` "
     "pour l'offre concernee."),
    (r"MemoryError|Cannot allocate memory",
     "Memoire insuffisante pour terminer la tache."),
]

# Une ligne de traceback n'apprend rien a qui lit l'interface. La derniere
# ligne, elle, porte le type et le message de l'exception.
DERNIERE_EXCEPTION = re.compile(r"^(\w*(?:Error|Exception|Exit)\b.*)$", re.M)


def _pivoter():
    if FICHIER.exists() and FICHIER.stat().st_size > TAILLE_MAX:
        precedent = FICHIER.with_suffix(".log.1")
        precedent.unlink(missing_ok=True)
        FICHIER.rename(precedent)


def enregistrer(source, message, detail=None):
    """Ajoute une entree. Ne leve jamais : un journal qui casse l'appelant
    serait pire que pas de journal du tout."""
    try:
        DOSSIER.mkdir(parents=True, exist_ok=True)
        _pivoter()
        horodatage = datetime.now().isoformat(timespec="seconds")
        bloc = f"[{horodatage}] {source} | {message}\n"
        if detail:
            bloc += "".join(f"    {l}\n" for l in str(detail).splitlines())
        with FICHIER.open("a", encoding="utf-8") as f:
            f.write(bloc)
    except OSError:
        pass


def exception(source, erreur, contexte=None):
    """Enregistre une exception avec sa trace complete."""
    trace = "".join(traceback.format_exception(type(erreur), erreur,
                                               erreur.__traceback__))
    enregistrer(source, f"{type(erreur).__name__}: {erreur}"
                + (f" ({contexte})" if contexte else ""), trace)
    return f"{type(erreur).__name__}: {erreur}"


def expliquer(sortie, code=None):
    """Une phrase qui dit ce qui s'est passe et quoi faire.

    `sortie` est le texte produit par le script, stdout et stderr confondus.
    On cherche d'abord un cas connu, puis a defaut la derniere exception, puis
    la derniere ligne non vide. « code de sortie 1 » n'est retourne que si le
    script n'a vraiment rien dit.
    """
    texte = sortie or ""

    for motif, phrase in DIAGNOSTICS:
        trouve = re.search(motif, texte, re.I)
        if trouve:
            # {1} laisse une entree citer son premier groupe capture, par
            # exemple le nom du module manquant.
            if "{1}" in phrase and trouve.groups():
                return phrase.replace("{1}", trouve.group(1))
            return phrase

    exceptions = DERNIERE_EXCEPTION.findall(texte)
    if exceptions:
        return exceptions[-1].strip()[:300]

    lignes = [l.strip() for l in texte.splitlines() if l.strip()]
    if lignes:
        return lignes[-1][:300]

    return f"Echec sans message (code de sortie {code})"


def lire(lignes=200):
    """Les dernieres lignes du journal, pour la page de diagnostic."""
    if not FICHIER.exists():
        return ""
    try:
        return "\n".join(
            FICHIER.read_text(encoding="utf-8", errors="replace").splitlines()[-lignes:])
    except OSError:
        return ""
