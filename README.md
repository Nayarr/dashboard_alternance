# dashboard_alternance

Recherche d'alternance et de stage automatisee de bout en bout : collecte des
offres sur cinq sources, dedoublonnage, notation, redaction des lettres, puis
depot de la candidature dans le formulaire du site. L'envoi final reste une
decision humaine.

Concu pour un BUT Informatique en Ile-de-France, mais **rien n'est code en
dur** : profil, mots-cles, codes ROME, familles de postes exclues, blocklist
d'organismes de formation et seuils se reglent depuis l'interface.

> Aucune candidature ne part sans le drapeau explicite `--confirmer`. Par
> defaut tout tourne en dry-run : les formulaires sont remplis jusqu'a la
> derniere etape, jamais valides.

---

## Mise en route

```bash
pip install -r requirements.txt
playwright install chromium
```

Quatre choses a mettre en place. L'outil demarre sans elles, avec un profil
fictif : suffisant pour explorer l'interface, pas pour candidater.

**1. Identite**

Rien a editer : nom, email, telephone, adresse postale et point de reference
des distances se saisissent depuis la page **Parametres** de l'interface, qui
les ecrit dans `data/parametres.json`. `config.py` ne porte qu'un profil
d'exemple, qui sert de valeur de repli et reste publie.

L'adresse de reference est geocodee a l'enregistrement : une adresse
introuvable est refusee plutot que silencieusement ignoree.

**2. Secrets**

```bash
cp .env.exemple .env
```

`LBA_API_KEY` est deja renseignee : la collecte fonctionne sans rien faire.
Reste a produire ton jeton Claude avec `claude setup-token` et a le coller dans
`CLAUDE_CODE_OAUTH_TOKEN`, ou depuis la page Parametres, qui ecrit dans `.env`.

Les lettres sont redigees par Claude Code en mode headless via ce jeton, donc
sur un abonnement plutot que sur l'API facturee au token.

Le reste du fichier ne sert qu'a l'envoi par email, decrit ci-dessous.

**3. Faits du candidat pour les lettres**

```bash
cp prompts/systeme_lettre.exemple.md prompts/systeme_lettre.md
```

Parcours, experiences, projets, competences reelles. C'est la **seule** source
dont dispose le redacteur : ce qui n'y figure pas ne sera pas ecrit, et c'est
volontaire — une lettre qui invente un chiffre se disqualifie plus vite qu'une
lettre sobre.

**4. CV**

Deposer le PDF dans `templates/cv/` (ou par glisser-deposer depuis la page
Parametres). Son nom est conserve tel quel : il part en piece jointe chez le
recruteur.

---

## Utilisation

```bash
python dashboard.py                  # interface sur http://127.0.0.1:5000
```

Tout se pilote de la. En ligne de commande :

```bash
python sourcing.py                   # collecte les cinq sources
python sourcing.py --source lba      # lba | wttj | apec | jobteaser | service_public
python sourcing.py --rescore         # recalcule scores et filtres sans recollecter

python reconnaissance.py             # releve ce que chaque formulaire accepte
python generer_lettres.py --limite 5 # redige les lettres des meilleurs scores

python postuler_lba.py --offre 59    # dry-run : remplit sans envoyer
python postuler_lba.py --offre 59 --confirmer   # envoie reellement

python connecter_compte.py wttj      # ouvre un navigateur pour se connecter
python inspect_db.py resume          # repartition de la base
python geocode.py "ton adresse"      # coordonnees du point de reference
```

`reconnaissance.py` avant `generer_lettres.py` n'est pas un detail : une lettre
coute environ 60 000 jetons, et certains formulaires n'ont aucun endroit ou la
mettre. L'inspection le constate avant qu'on paie.

---

## Envoyer par email

Necessaire uniquement pour les offres qui se candidatent par courrier — le
portail de l'emploi public, principalement. Les autres sources ont leur propre
formulaire.

Deux canaux, le premier renseigne dans `.env` etant utilise automatiquement :

- **mot de passe d'application Gmail** — `SMTP_USER` / `SMTP_APP_PASSWORD`.
  Ce n'est pas le mot de passe du compte mais un code dedie, cree sur
  [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
  et revocable a tout moment. La validation en deux etapes doit etre active.
- **adresse universitaire via Microsoft 365** — `GRAPH_CLIENT_ID` /
  `GRAPH_TENANT_ID` / `GRAPH_EXPEDITEUR`, ce qui suppose une application
  declaree dans l'Entra ID de l'etablissement. Authentification par device
  code : aucun mot de passe n'est stocke.

```bash
python envoyer.py --offre 925               # apercu, n'envoie rien
python envoyer.py --offre 925 --confirmer   # envoie par le canal disponible
python envoyer.py --offre 925 --canal gmail --confirmer
```

---

## Le dashboard

Application Flask locale, **sans authentification** : elle ecoute sur
`127.0.0.1` et ne doit jamais etre exposee sur `0.0.0.0`.

- **File de validation** — les offres sur lesquelles le filtrage n'a pas
  tranche, avec la raison du doute. Valider / Rejeter.
- **Vivier** — les offres retenues, triees par score.
- **Pipeline** — lettre prete, envoyee, entretien, refus, signee.
- **Vues de rejet** (`hors_cible`, `ecole`, `ecarte`, `sans_canal`) —
  consultables, avec un bouton Recuperer pour rattraper un faux positif.
- **Parametres** — CV, jeton Claude, comptes de sites, profil, adresse,
  mots-cles, ROME, exclusions, seuils.

Toute decision prise dans l'interface est journalisee et passe en statut fige :
`sourcing.py --rescore` ne l'ecrasera jamais.

---

## Ce qui se regle sans toucher au code

Les reglages vivent dans `data/parametres.json`, ecrit par la page Parametres.
Ils se superposent aux valeurs de `config.py`, qui reste la reference : une
entree supprimee depuis l'interface peut toujours etre retrouvee, et le bouton
« defaut » de chaque section restaure la valeur d'origine.

| Reglage | Effet |
|---|---|
| Profil, adresse postale, rayon | Identite, distances, remplissage des formulaires |
| Alternance / stage | Change les requetes envoyees aux sources, le bareme et la lettre |
| Duree de stage | 8 semaines en BUT2, 14 en BUT3 ; tolerance reglable |
| Mots-cles techniques | ~85 termes ponderes, ajoutables et supprimables |
| Codes ROME | Ce qui est interroge chez La Bonne Alternance |
| Familles exclues | 9 groupes cochables : data, jeu video, design, support… |
| Termes exclus perso | En version stricte (elimine) ou souple (penalise) |
| Blocklist d'ecoles | ~51 organismes de formation |
| Seuils | Score minimal, prime grand groupe |

Un simulateur montre ce qu'un filtre ecarterait **avant** de l'appliquer.

---

## Sources

**La Bonne Alternance** (`sources/lba.py`) — `GET /api/job/v1/search`, cle
Bearer gratuite. Deux gisements : `jobs`, les offres publiees (qui agregent
France Travail, PASS, Veritone, Meteojob, Maazi), et `recruiters`, environ 150
entreprises par code ROME susceptibles de recruter sans offre publiee — c'est
la donnee de La Bonne Boite, exploitee en candidature spontanee.

**Welcome to the Jungle** (`sources/wttj.py`) — le site est une SPA, `/fr/jobs`
renvoie 550 Ko de HTML sans aucun `JobPosting`. Son propre front interroge un
index Algolia avec une cle de recherche publique embarquee dans le bundle JS :
on utilise le meme point d'entree, ce qui donne du JSON structure et une charge
tres inferieure a un rendu de page complet. `contract_type` est en MAJUSCULES
(`APPRENTICESHIP`, `INTERNSHIP`), `_geoloc` est un tableau, et l'index renvoie
des doublons — dedoublonnage sur `objectID`.

**Apec** (`sources/apec.py`) — `POST /cms/webservices/rechercheOffre`, sans
authentification. Les descriptions completes ne sont **pas** recuperees : le
point d'entree de detail est protege par DataDome et renvoie un captcha. On
travaille sur les resumes, ce qui explique le plafond technique proportionnel
a la longueur du texte (voir Scoring).

**JobTeaser** (`sources/jobteaser.py`) — pages de recherche par chemin,
autorisees par leur `robots.txt`. Les pages de detail sont derriere Cloudflare
et ne sont pas sollicitees.

**Choisir le service public** (`sources/service_public.py`) — WordPress rendu
cote serveur. Pas de filtre de contrat : la nature est deduite du texte. Les
candidatures se font par email, l'adresse figure dans l'annonce.

**France Travail** (`sources/france_travail.py`) — code present, **desactive**.
L'API fonctionne (OAuth client_credentials, `natureContrat=E2`, et il faut
geocoder le libelle de lieu qui n'est pas fourni en coordonnees), mais
automatiser le depot de candidature sur leur portail expose a un signalement.
Le stock est de toute facon partiellement agrege par La Bonne Alternance.

**HelloWork** — ecarte. `robots.txt` interdit `/emploi/recherche.html` et le
sitemap renvoie 403 aux requetes scriptees.

Les doublons entre sources sont detectes par empreinte (`db.empreinte`) :
employeur, intitule et lieu normalises.

---

## Scoring

Score entier, detail conserve en JSON dans `offres.score_detail` pour pouvoir
auditer un mauvais classement. Composantes : mots-cles techniques (poids double
dans le titre), mots-cles negatifs, distance a vol d'oiseau, duree de contrat,
type de contrat, secteur NAF pour les spontanees.

Deux details qui ont demande une correction :

- **Le matching se fait sur mot entier.** Le mot-cle `vite` (le bundler)
  matchait dans « eviter » et gonflait les scores de plusieurs points. Les
  bornes utilisees sont alphanumeriques et non `\b`, pour que `api rest`,
  `ci/cd`, `no-code` et `bac+3` continuent de matcher.
- **Le plafond technique est proportionnel a la longueur du texte.** Une
  annonce Apec fait 283 caracteres la ou une annonce WTTJ en fait 1885 : a
  plafond fixe, la source courte etait structurellement penalisee.

---

## Porte « mission technique »

Le critere de tri est la **mission**, pas l'entreprise. Dans le perimetre : le
developpement (web, back-end, full-stack, automatisation, API) et
l'administration systeme et reseau. Hors perimetre par defaut : data science,
jeu video, design, support utilisateur, et les postes non techniques — chacune
de ces familles se decoche depuis l'interface.

Le veto sur le titre est sans appel : « Data Scientist (Python) » coche des
signaux techniques mais reste hors appetence. Les candidatures spontanees
echappent a la porte, aucune mission n'y etant decrite.

---

## Filtre anti-ecoles

Une part importante des annonces « alternance » emane de CFA et d'ecoles
privees qui vendent une formation, pas un poste. C'est le filtre le plus simple
et le plus rentable. Trois familles de signaux :

- **nom fort** (`cfa`, `campus`, `academy`, `school`…) → tranche seul
- **nom faible** (`ecole`, `institut`, `universite`, `formation`…) → demande une
  confirmation par le texte. « Institut Pasteur » et « Ecole 42 » recrutent de
  vrais alternants.
- **texte** : « nous te trouvons ton entreprise », « frais de scolarite »,
  « titre RNCP niveau 6 »…
- **volume** : un meme employeur au-dela de 15 annonces identiques

Le matching se fait sur mot entier, sans quoi `studi` capture `LEIKIR STUDIO`.
Les annonces detectees passent au statut `ecole` et **ne sont pas supprimees**.

---

## Schema

- `offres` — le vivier, avec score, flags et statut
- `candidatures` — une ligne par candidature envoyee, canal, relances, reponse
- `evenements` — journal horodate par offre
- `runs` — historique des collectes

Cycle de vie : `a_traiter → lettre_prete → envoyee → entretien → refus | signee`,
plus les voies de garage `ecarte`, `hors_cible`, `ecole` et `sans_canal`.

---

## Ce que l'outil ne fait pas

Ce sont des choix, pas des manques :

- **Il ne contourne aucune protection anti-bot.** Captcha DataDome sur les
  details Apec, Cloudflare sur les details JobTeaser : les donnees sont
  abandonnees, pas arrachees.
- **Il ne cree aucun compte** et ne stocke aucun mot de passe.
  `connecter_compte.py` ouvre un navigateur, la connexion se fait a la main,
  seuls les cookies resultants sont conserves dans `data/` — un fichier de
  session vaut un mot de passe.
- **Il n'envoie rien tout seul.** `--confirmer` est obligatoire.
- **Il ne poste pas sur France Travail.**

---

## Donnees personnelles

Ne sont pas versionnes, et ne doivent pas l'etre : `.env`,
`prompts/systeme_lettre.md`, `templates/cv/`, `templates/dossier/`, `data/`
(base, sessions, profils de navigateur, et `parametres.json` qui porte
l'identite saisie dans l'interface) et `lettres/`.

Avant de publier un fork, verifier que `git status` ne propose aucun de ces
chemins.
