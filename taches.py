"""Execution des traitements longs en arriere-plan, avec suivi de progression.

Pourquoi ce module existe : une collecte prend environ 3 minutes, une generation
de lettres 20 secondes par offre, un depot de candidature 15 a 18 secondes. Ces
durees sont incompatibles avec une requete HTTP, qui expire cote navigateur bien
avant. L'interface lance donc une tache, recoit immediatement son identifiant,
puis interroge sa progression.

Choix d'implementation :

  - Un thread par tache, pas de file d'attente ni de broker. L'outil est
    mono-utilisateur et tourne en local : Celery ou RQ ajouteraient un service
    a maintenir pour zero benefice.
  - L'etat vit en base, pas en memoire. Si le serveur Flask redemarre pendant
    une tache, on retrouve son etat au lieu de perdre la trace. Les taches
    restees "en_cours" apres un redemarrage sont marquees interrompues.
  - Une seule tache a la fois. Deux collectes simultanees se marcheraient sur
    les pieds en base, et deux navigateurs Playwright en parallele declenchent
    les protections anti-bot des sites.
"""

import json
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import db
import journal

BASE = Path(__file__).parent

# Verrou global : une seule tache longue a la fois.
_verrou = threading.Lock()
_thread_courant = None


def _maintenant():
    return datetime.now().isoformat(timespec="seconds")


def dernier_echec(conn=None, depuis_heures=6):
    """Derniere tache echouee, si elle est recente.

    Le panneau d'erreur ne vivait que dans la page ouverte au moment de
    l'echec : un rechargement, et le message disparaissait sans laisser de
    trace a l'ecran. On le remonte au demarrage, borne dans le temps pour ne
    pas ressortir l'echec de la semaine derniere.
    """
    propre = conn is None
    conn = conn or db.connect()
    try:
        r = conn.execute(
            "SELECT * FROM taches ORDER BY id DESC LIMIT 1").fetchone()
        if r is None or r["statut"] != "echouee" or not r["fin"]:
            return None
        ecoule = datetime.now() - datetime.fromisoformat(r["fin"])
        return dict(r) if ecoule.total_seconds() < depuis_heures * 3600 else None
    except (ValueError, TypeError):
        return None
    finally:
        if propre:
            conn.close()


def tache_en_cours(conn=None):
    """Tache actuellement active, ou None."""
    propre = conn is None
    conn = conn or db.connect()
    try:
        r = conn.execute(
            "SELECT * FROM taches WHERE statut = 'en_cours' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(r) if r else None
    finally:
        if propre:
            conn.close()


def purger_taches_orphelines():
    """Marque interrompues les taches restees en_cours apres un redemarrage.

    Sans ca, une tache tuee par un arret du serveur bloquerait le verrou
    logique pour toujours.
    """
    conn = db.connect()
    n = conn.execute(
        "UPDATE taches SET statut = 'echouee', fin = ?, "
        "message = 'interrompue par un redemarrage du serveur' "
        "WHERE statut = 'en_cours'", (_maintenant(),)).rowcount
    conn.commit()
    conn.close()
    return n


def _creer(type_, parametres, total=0):
    conn = db.connect()
    cur = conn.execute(
        "INSERT INTO taches (type, statut, parametres, total, message, journal, debut) "
        "VALUES (?, 'en_cours', ?, ?, '', '', ?)",
        (type_, json.dumps(parametres, ensure_ascii=False), total, _maintenant()))
    conn.commit()
    tache_id = cur.lastrowid
    conn.close()
    return tache_id


def _avancer(tache_id, progression=None, total=None, message=None, ligne=None):
    conn = db.connect()
    champs, valeurs = [], []
    if progression is not None:
        champs.append("progression = ?")
        valeurs.append(progression)
    if total is not None:
        champs.append("total = ?")
        valeurs.append(total)
    if message is not None:
        champs.append("message = ?")
        valeurs.append(message)
    if ligne:
        # Journal borne : on garde les 200 dernieres lignes, suffisant pour
        # diagnostiquer sans faire gonfler la base.
        actuel = (conn.execute("SELECT journal FROM taches WHERE id = ?",
                               (tache_id,)).fetchone()["journal"] or "")
        # Le separateur manquait : `actuel + ligne` recollait chaque nouvelle
        # ligne a la fin de la precedente, et le journal se lisait comme un
        # seul pave. Le detail d'un echec y etait illisible.
        lignes = ((actuel + "\n" if actuel else "") + ligne).splitlines()[-200:]
        champs.append("journal = ?")
        valeurs.append("\n".join(lignes))
    if champs:
        valeurs.append(tache_id)
        conn.execute(f"UPDATE taches SET {', '.join(champs)} WHERE id = ?", valeurs)
        conn.commit()
    conn.close()


def _terminer(tache_id, statut, message):
    conn = db.connect()
    conn.execute("UPDATE taches SET statut = ?, message = ?, fin = ? WHERE id = ?",
                 (statut, message, _maintenant(), tache_id))
    conn.commit()
    conn.close()


def _executer(tache_id, commande, total, extraire_progression=None):
    """Lance un script du pipeline et suit sa sortie ligne par ligne.

    On passe par subprocess plutot que par un import : chaque script a ses
    propres effets de bord (Playwright, Word COM, appels reseau) et un plantage
    ne doit pas emporter le serveur web avec lui.
    """
    try:
        processus = subprocess.Popen(
            [sys.executable, "-u"] + commande,
            cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
        fait = 0
        # La sortie complete sert au diagnostic : le journal en base est borne
        # a 200 lignes, et l'erreur utile est souvent plus haut que ca.
        sortie = []
        for ligne in processus.stdout:
            ligne = ligne.rstrip()
            if not ligne:
                continue
            sortie.append(ligne)
            if extraire_progression and extraire_progression(ligne):
                fait += 1
            _avancer(tache_id, progression=fait, message=ligne[:160], ligne=ligne)

        code = processus.wait()
        texte = "\n".join(sortie)
        if code == 0:
            # Toutes les taches n'ont pas de total connu d'avance : une
            # collecte n'en a pas. "termine (17/0)" laissait croire a une
            # division ratee.
            if total:
                resume = f"termine ({fait}/{total})"
            elif fait:
                resume = f"termine, {fait} etape(s)"
            else:
                resume = "termine"
            _terminer(tache_id, "terminee", resume)
        else:
            # "code de sortie 1" ne dit rien a personne. On cherche dans la
            # sortie de quoi repondre a "et maintenant ?", et on garde la
            # trace complete dans data/logs/app.log.
            raison = journal.expliquer(texte, code)
            journal.enregistrer(
                f"tache#{tache_id} {' '.join(commande)}",
                f"echec (code {code}) : {raison}", texte)
            _terminer(tache_id, "echouee", raison)
    except Exception as e:
        raison = journal.exception(f"tache#{tache_id}", e,
                                   contexte=" ".join(commande))
        _terminer(tache_id, "echouee", raison)
    finally:
        if _verrou.locked():
            _verrou.release()


def lancer(type_, parametres):
    """Demarre une tache. Retourne (tache_id, erreur)."""
    global _thread_courant

    if not _verrou.acquire(blocking=False):
        return None, "une tache est deja en cours"

    try:
        if type_ == "collecte":
            # Sans --source, sourcing.py interroge ses cinq sources. La liste
            # etait dupliquee ici, et reduite a deux : l'Apec, JobTeaser et le
            # portail de l'emploi public n'etaient jamais collectes depuis
            # l'interface, qui est pourtant le parcours recommande.
            commande = ["sourcing.py"]
            for s in (parametres.get("sources") or []):
                commande += ["--source", s]
            total = 0
            marqueur = lambda l: l.strip().startswith("ROME ") or "':" in l

        elif type_ == "lettres":
            limite = int(parametres.get("limite", 10))
            commande = ["generer_lettres.py", "--limite", str(limite)]
            total = limite
            marqueur = lambda l: l.strip().startswith(("OK ", "ECHEC"))

        elif type_ == "connexion":
            # Ouvre un navigateur visible : c'est l'utilisateur qui se connecte,
            # le script ne fait qu'attendre et enregistrer les cookies.
            site = parametres.get("site")
            if site not in ("wttj", "apec", "jobteaser"):
                _verrou.release()
                return None, f"site inconnu : {site}"
            commande = ["connecter_compte.py", site]
            if parametres.get("url"):
                commande += ["--url", parametres["url"]]
            total = 0
            marqueur = lambda l: l.startswith("# OK")

        elif type_ == "connexion_outlook":
            # Device code : rien ne s'ouvre sur la machine, l'utilisateur saisit
            # un code sur une page Microsoft depuis le navigateur de son choix.
            # L'interface extrait ce code du journal de la tache.
            commande = ["graph_mail.py", "--connexion"]
            total = 0
            marqueur = lambda l: l.startswith("# OK")

        elif type_ == "reconnaissance":
            # Inspecte les formulaires avant toute redaction : sans elle, on
            # paie des lettres pour des offres qui n'ont pas de champ ou qui
            # redirigent vers un ATS tiers.
            commande = ["reconnaissance.py"]
            for source in (parametres.get("sources") or []):
                commande += ["--source", source]
            total = 0
            marqueur = lambda l: l.strip().startswith("#")

        elif type_ == "rescore":
            # Rejoue le scoring sur la base existante, sans rien recollecter :
            # c'est ce qui donne effet a une modification des criteres.
            commande = ["sourcing.py", "--rescore"]
            total = 0
            marqueur = lambda l: "rescorees" in l

        elif type_ == "candidatures":
            canal = parametres.get("canal", "lba")
            limite = int(parametres.get("limite", 5))
            script = "postuler_lba.py" if canal == "lba" else "postuler_wttj.py"
            commande = [script, "--limite", str(limite)]
            if parametres.get("confirmer"):
                commande.append("--confirmer")
            total = limite
            marqueur = lambda l: l.strip().startswith("#")

        else:
            _verrou.release()
            return None, f"type de tache inconnu : {type_}"

        tache_id = _creer(type_, parametres, total)
        _thread_courant = threading.Thread(
            target=_executer, args=(tache_id, commande, total, marqueur), daemon=True)
        _thread_courant.start()
        return tache_id, None

    except Exception as e:
        if _verrou.locked():
            _verrou.release()
        return None, str(e)
