"""Releve ce que chaque formulaire de candidature accepte, avant d'ecrire quoi
que ce soit.

    python reconnaissance.py                 # toutes les sources connues
    python reconnaissance.py --source wttj
    python reconnaissance.py --limite 5

Pourquoi cette etape existe : le depot WTTJ faisait `if lettre_champ is not
None` puis passait a la suite. Une lettre payee 65 000 jetons pouvait donc etre
redigee, ecrite sur disque, puis abandonnee en silence parce que le formulaire
n'avait pas de champ pour elle. Sur les sept offres WTTJ du vivier, deux
seulement pouvaient l'utiliser.

On distingue deux facons de transmettre une lettre, parce qu'elles n'ont pas les
memes consequences :

    lettre_texte    une zone de texte attend la lettre (LBA, WTTJ)
    lettre_fichier  un champ fichier se designe comme destine a une lettre

Aucun des deux canaux actuels n'accepte de lettre en piece jointe : LBA n'a
qu'un champ fichier, pour le CV, et WTTJ en a deux dont le second est un avatar
qui n'accepte que des images. Dans les deux cas la lettre passe en texte.
Une offre qui n'accepte ni l'un ni l'autre n'a pas besoin de lettre du tout.

Aucun jeton Claude n'est consomme ici : c'est du pilotage de navigateur.
Aucune candidature n'est envoyee, aucun champ n'est rempli.
"""

import argparse
import time

from playwright.sync_api import sync_playwright

import config
import db
import postuler_lba
import postuler_wttj

SOURCES = ("lba", "wttj")
PAUSE = 1.5

NAVIGATEUR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def _releve(page):
    """Ce que le formulaire ouvert accepte reellement."""
    return page.evaluate("""() => {
        const visible = (e) => e.offsetParent !== null || e.type === 'file';
        const fichiers = [...document.querySelectorAll('input[type=file]')];
        const zones = [...document.querySelectorAll('textarea')].filter(visible);
        const nomme = (e) => (e.name || e.id || '').toLowerCase();
        return {
            // Une zone de texte dediee a la lettre, reperee par son nom quand
            // il existe, sinon par la presence d'au moins deux zones (la
            // premiere etant en general le message, la seconde la lettre).
            lettre_texte: zones.some(z => /cover|lettre|message|motivation/.test(nomme(z))),
            zones: zones.map(nomme),
            // Compter les champs fichier ne dit rien : sur WTTJ le second est
            // "avatar", une photo de profil qui n'accepte que des images. Il
            // faut donc chercher un champ qui se designe lui-meme comme
            // destine a une lettre, par son nom ou son etiquette.
            lettre_fichier: fichiers.some(f => {
                const etiquette = (f.closest('label')?.innerText
                    || f.labels?.[0]?.innerText || '').toLowerCase();
                return /cover|lettre|motivation/.test(nomme(f) + ' ' + etiquette);
            }),
            fichiers: fichiers.map(f => nomme(f) + ':' + (f.accept || '*').slice(0, 20)),
        };
    }""")


def _wttj(page, offre):
    page.goto(offre["url_candidature"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)

    postuler_wttj.refuser_cookies(page)

    bouton = postuler_wttj.premier_visible(page.locator(
        "a:has-text('Postuler'), button:has-text('Postuler')"))
    if bouton is None:
        return None, "aucun bouton Postuler"

    # Meme detection d'ATS tiers que le depot : un lien absolu hors domaine
    # signale une offre portee par le site de l'employeur.
    href = bouton.get_attribute("href") or ""
    if href.startswith("http") and postuler_wttj.HOTE_WTTJ not in href:
        return None, "redirige vers " + href.split("/")[2]

    bouton.click()
    page.wait_for_timeout(3500)

    if "authenticate" in page.url or "signin" in page.url:
        return None, "session WTTJ expiree"
    if postuler_wttj.HOTE_WTTJ not in page.url:
        return None, "redirige vers " + page.url.split("/")[2]

    try:
        page.wait_for_selector("input[name='firstname']", timeout=20000)
    except Exception:
        return None, "formulaire non affiche"

    return _releve(page), None


def _lba(page, offre):
    page.goto(offre["url_candidature"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1500)

    fermer = postuler_lba.premier_visible(page.locator("button:has-text('Fermer')"))
    if fermer:
        fermer.click()
        page.wait_for_timeout(400)

    ouvrir = postuler_lba.premier_visible(page.locator(postuler_lba.BOUTON_OUVRIR))
    if ouvrir is None:
        return None, "pas de formulaire sur la page"
    ouvrir.scroll_into_view_if_needed()
    ouvrir.click()
    page.wait_for_selector("#applicant_email", timeout=20000)
    return _releve(page), None


INSPECTEURS = {"lba": _lba, "wttj": _wttj}


def inspecter(conn, source, limite):
    offres = [dict(r) for r in conn.execute(
        "SELECT id, entreprise, url_candidature, statut FROM offres "
        "WHERE source = ? AND statut IN ('a_traiter', 'lettre_prete') "
        "AND lettre_texte IS NULL ORDER BY matching DESC LIMIT ?",
        (source, limite))]
    if not offres:
        print(f"[{source}] rien a inspecter")
        return 0

    print(f"\n[{source}] {len(offres)} offre(s)")
    externes = [0]
    session = config.BASE_DIR / "data" / "sessions" / f"{source}.json"
    traitees = 0

    with sync_playwright() as pw:
        navigateur = pw.chromium.launch(headless=True)
        contexte = navigateur.new_context(
            storage_state=str(session) if session.exists() else None,
            viewport={"width": 1440, "height": 950}, locale="fr-FR",
            user_agent=NAVIGATEUR)
        page = contexte.new_page()

        for offre in offres:
            try:
                releve, souci = INSPECTEURS[source](page, offre)
            except Exception as e:
                releve, souci = None, f"{type(e).__name__}"

            if releve is None:
                # Une redirection hors domaine est un fait etabli : l'offre
                # est portee par l'ATS de l'employeur et ne sera jamais
                # automatisable. On la sort du vivier une bonne fois.
                if souci and souci.startswith("redirige vers"):
                    conn.execute(
                        "UPDATE offres SET statut = 'ats_externe', url_ats = ? "
                        "WHERE id = ?", (souci.replace("redirige vers ", ""),
                                         offre["id"]))
                    db.log(conn, offre["id"], "ats_externe", souci)
                    conn.commit()
                    externes[0] += 1
                # Un formulaire simplement inaccessible reste a NULL : lenteur,
                # bandeau de consentement, bouton renomme... rien ne prouve
                # qu'il soit externe, on reessaiera.
                print(f"  #{offre['id']:5} {offre['entreprise'][:24]:26} {souci}")
                time.sleep(PAUSE)
                continue

            texte = 1 if releve["lettre_texte"] else 0
            fichier = 1 if releve["lettre_fichier"] else 0
            conn.execute(
                "UPDATE offres SET lettre_texte = ?, lettre_fichier = ? WHERE id = ?",
                (texte, fichier, offre["id"]))
            db.log(conn, offre["id"], "reconnaissance",
                   f"texte={texte} fichier={fichier} "
                   f"zones={releve['zones']} fichiers={releve['fichiers']}")
            # Enregistre offre par offre : un seul commit en fin de parcours
            # faisait perdre quatre minutes de travail a la moindre
            # interruption, sans que rien ne le signale.
            conn.commit()
            traitees += 1

            verdict = ("lettre en texte" if texte else "") + \
                      (" + piece jointe" if fichier else "")
            print(f"  #{offre['id']:5} {offre['entreprise'][:24]:26} "
                  f"{verdict or 'AUCUNE lettre possible'}")
            time.sleep(PAUSE)

        navigateur.close()

    conn.commit()
    if externes[0]:
        print(f"  {externes[0]} offre(s) sorties du vivier : ATS de l'employeur")
    return traitees


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", choices=SOURCES, action="append", dest="sources")
    p.add_argument("--limite", type=int, default=40)
    args = p.parse_args()

    conn = db.init()
    total = 0
    for source in (args.sources or SOURCES):
        total += inspecter(conn, source, args.limite)

    reste = conn.execute(
        "SELECT COUNT(*) c FROM offres WHERE statut IN ('a_traiter','lettre_prete') "
        "AND lettre_texte IS NULL").fetchone()["c"]
    sans = conn.execute(
        "SELECT COUNT(*) c FROM offres WHERE lettre_texte = 0 AND lettre_fichier = 0"
    ).fetchone()["c"]

    print(f"\n{total} offre(s) inspectee(s), {reste} encore inconnue(s)")
    print(f"{sans} offre(s) n'acceptent aucune lettre : "
          "generer_lettres.py les ignorera")
    conn.close()


if __name__ == "__main__":
    main()
