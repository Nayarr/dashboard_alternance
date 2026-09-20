"""Profil candidat, criteres de recherche et parametres de scoring."""

from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = BASE_DIR / "data" / "candidatures.db"
LETTRES_DIR = BASE_DIR / "lettres"
TEMPLATES_DIR = BASE_DIR / "templates"

# --- Profil ---------------------------------------------------------------

# Valeurs d'EXEMPLE. Les tiennes se saisissent depuis la page Parametres, qui
# les ecrit dans data/parametres.json, exclu du git. Ce qui suit n'est qu'un
# gabarit et une valeur de repli : ce fichier est publie.
PROFIL = {
    "nom": "Prenom Nom",
    "email": "prenom.nom@example.com",
    "telephone": "+33600000000",
    "telephone_affiche": "06 00 00 00 00",
    # Localisation AFFICHEE (CV, portfolio, formulaires). Volontairement
    # "Paris" et non la commune exacte : coherence avec le CV et le portfolio.
    # Le domicile reel sert au calcul des distances via ORIGINE plus bas.
    "ville": "Paris",
    "code_postal": "",
    "formation": "BUT Informatique - parcours Realisation d'Applications",
    "etablissement": "IUT d'Exemple (Universite d'Exemple)",
    "debut": "des que possible (formation commencee le 01/09/2026)",
    "fin": "2027-08-31",
    "duree_mois": 12,
    "disponibilite": "immediate",
    "rythme": "1 semaine entreprise / 1 semaine formation de septembre a juin, "
              "puis temps plein en entreprise en juillet-aout",
    "jours_entreprise": 170,
    "jours_formation": 86,
    # Poursuite d'etudes prevue apres le BUT3 : rend les contrats de 24 mois
    # compatibles, et constitue un argument a placer dans les lettres.
    "poursuite_etudes": "Master / ecole d'ingenieur apres le BUT3 (septembre 2027)",
    "duree_negociable_jusqu_a": 24,
    # Pied de signature des emails. Vide = aucune ligne de liens.
    "liens": "",
    # Ligne d'accroche et profil LinkedIn, reclames par certains formulaires
    # (WTTJ notamment). Vides, les champs sont simplement laisses de cote.
    "titre": "",
    "linkedin": "",
}

# --- Adresse administrative ------------------------------------------------
#
# Distincte de PROFIL["ville"], qui n'est qu'un libelle d'affichage aligne sur
# le CV et le portfolio. Ici c'est l'adresse reelle, exigee par les formulaires
# de candidature des grands comptes (Workday impose un code postal valide).
# Un formulaire de candidature est un document contractuel : on n'y met pas
# une localisation approximative.
ADRESSE_POSTALE = {
    "voie": "1 rue de l'Exemple",
    "code_postal": "75001",
    "commune": "Paris",
    "region": "Paris",
    "pays": "France",
    "indicatif": "+33",
}

# Consentement au traitement du dossier par un outil d'IA cote recruteur.
# Exige par le formulaire Thales (Workday) : sans lui, la candidature est
# impossible. Decision de l'utilisateur, posee explicitement ici plutot qu'enfouie
# dans le code d'un script.
CONSENTEMENT_IA_RECRUTEUR = True

# Comment le candidat a trouve l'offre, pour les formulaires qui le demandent
ORIGINE_CANDIDATURE = "Job Board"

# Point de reference pour le calcul des distances.
# Geocode via l'API Adresse (api-adresse.data.gouv.fr), score 0.973.
# Toutes les distances de la base sont des distances a vol d'oiseau depuis ce
# point : c'est un ordre de grandeur, pas un temps de trajet.
ADRESSE_REFERENCE = "1 rue de l'Exemple, 75001 Paris"  # domicile
ORIGINE = (48.8566, 2.3522)
RAYON_KM = 35

# Codes ROME cibles (developpement, expertise SI, conseil, exploitation)
ROMES = ["M1805", "M1802", "M1806", "M1810"]

DEPARTEMENTS = ["75", "92", "93", "94", "77", "78", "91", "95"]


# --- Nature des contrats recherches ---------------------------------------
#
# Le BUT impose un stage en plus de l'alternance : 8 semaines en BUT2,
# 14 semaines en BUT3. Les deux natures se cherchent donc separement, et rien
# n'oblige a chercher les deux en meme temps.
#
# Consequences ailleurs dans le code :
#   - sources/wttj.py construit son filtre Algolia depuis ces deux drapeaux
#   - filters.py neutralise le malus "stage" quand les stages sont cherches,
#     et note la duree en SEMAINES pour un stage, en MOIS pour une alternance
#   - generer_lettres.py annonce la bonne nature au redacteur

RECHERCHE_ALTERNANCE = True
RECHERCHE_STAGES = False

# Duree de stage visee, en semaines. 8 en BUT2, 14 en BUT3.
STAGE_DUREE_SEMAINES = 14

# Tolerance autour de la cible, dissociee dans les deux sens parce que les deux
# ecarts ne se negocient pas pareil : un stage plus long que prevu se raccourcit
# parfois d'un commun accord, un stage trop court ne validera jamais le semestre.
#
# Reperes mesures sur le vivier WTTJ : la quasi-totalite des stages du marche
# durent 26 semaines (six mois, stage de fin d'etudes). Avec une cible a 14,
# il faut donc une tolerance longue d'au moins 12 pour les voir remonter.
# Un stage doit durer AU MINIMUM la duree visee : c'est une exigence de
# l'universite, pas une preference. L'ecart court vaut donc zero par defaut,
# et un stage plus court est ecarte, pas seulement penalise.
STAGE_ECART_COURT = 0
STAGE_ECART_LONG = 2


# --- Grands groupes ---------------------------------------------------------
#
# Priorite explicite : les grandes structures offrent un encadrement reel, une
# vraie equipe technique, et une ligne qui pese sur un CV junior.

# Reconnaissance par le nom, quand la source ne donne pas d'effectif fiable.
GRANDS_GROUPES = [
    # telecoms, energie, transport
    "orange", "sfr", "bouygues", "free", "iliad", "edf", "engie", "totalenergies",
    "veolia", "suez", "sncf", "ratp", "keolis", "transdev", "air france", "adp",
    "vinci", "eiffage", "alstom", "safran", "thales", "dassault", "airbus",
    "naval group", "arianegroup", "mbda", "renault", "stellantis", "michelin",
    # banque, assurance
    "bnp", "societe generale", "credit agricole", "credit mutuel", "banque populaire",
    "caisse d'epargne", "bpce", "la banque postale", "axa", "allianz", "generali",
    "cnp", "maif", "macif", "matmut", "groupama", "ag2r", "malakoff", "klesia",
    "natixis", "amundi", "euronext",
    # conseil, IT, ESN
    "capgemini", "sopra", "atos", "cgi", "accenture", "deloitte", "kpmg", "ey ",
    "pwc", "mazars", "inetum", "devoteam", "alten", "altran", "akka", "expleo",
    "ausy", "sii ", "cs group", "worldline", "ingenico", "docaposte", "orange business",
    # industrie, grande conso, distribution
    "saint-gobain", "schneider", "legrand", "air liquide", "arkema", "solvay",
    "loreal", "l'oreal", "danone", "nestle", "pernod", "lvmh", "kering", "hermes",
    "chanel", "essilor", "luxottica", "sanofi", "servier", "ipsen", "biomerieux",
    "carrefour", "auchan", "leclerc", "intermarche", "casino", "fnac", "darty",
    "decathlon", "leroy merlin", "adeo", "sephora", "cdiscount", "la poste",
    # public et parapublic
    "pole emploi", "france travail", "urssaf", "cnaf", "cnam", "ap-hp", "inria",
    "cea", "cnrs", "onera", "ifremer", "meteo france", "ign ", "bpifrance",
    "caisse des depots", "ministere", "prefecture", "agence nationale",
]

# Effectif : bareme par palier, pour que la taille pese vraiment
BONUS_EFFECTIF = [
    (5000, 45),   # tres grand groupe
    (2000, 40),
    (1000, 35),
    (500, 28),
    (250, 22),
    (100, 12),
    (50, 6),
]

PRIME_GRAND_GROUPE = 40

# --- Scoring --------------------------------------------------------------

# Mots-cles techniques : poids applique si present dans titre ou description
MOTS_CLES = {
    # coeur de cible - ce que le candidat sait faire et veut faire
    "automatisation": 12, "automatiser": 10, "script": 6,
    "python": 12, "api rest": 10, "api": 6, "integration": 6,
    "fullstack": 12, "full stack": 12, "full-stack": 12,
    "php": 9, "symfony": 7, "laravel": 7,
    "javascript": 8, "typescript": 10, "node": 6,
    "react": 11, "reactjs": 11, "flask": 8,
    # "vite" retire : meme en mot entier, l'adverbe francais est
    # indiscernable du bundler et bien plus frequent dans une annonce.
    "sql": 7, "mysql": 7, "postgres": 9, "postgresql": 9, "mongodb": 5,
    "supabase": 8, "oracle": 5,
    "outil interne": 12, "outils internes": 12, "back-office": 8,
    "pipeline": 9, "etl": 8, "donnees": 5, "data": 5,
    "ocr": 10, "scraping": 8, "regex": 6,
    "docker": 6, "ci/cd": 6, "git": 4,
    "web": 5, "application web": 8, "developpeur": 8, "developpement": 6,
    "ia": 8, "intelligence artificielle": 8, "llm": 11,
    "agent ia": 12, "agents ia": 12, "agentique": 12, "rag": 12,
    "embedding": 10, "embeddings": 10, "chunking": 9, "vectoriel": 9,
    "base vectorielle": 10, "vector": 8, "fine-tuning": 7,
    "prompt": 6, "n8n": 9, "no-code": 5, "automatisation de workflow": 10,
    # administration systeme et reseau : dans les cordes
    "linux": 8, "unix": 6, "bash": 6, "powershell": 5, "windows server": 6,
    "administration": 6, "administrateur": 6, "systeme": 4, "reseau": 5,
    "virtualisation": 6, "vmware": 5, "active directory": 5,
    "supervision": 5, "devops": 8, "kubernetes": 6, "ansible": 6,
    "cloud": 5, "azure": 5, "aws": 5,
    # signaux positifs de contexte
    "alternance": 5, "apprentissage": 5, "but": 3, "bac+3": 4, "licence": 3,
}

# --- Porte "mission technique informatique" ------------------------------
#
# Le critere de tri est la MISSION, pas l'entreprise. Le perimetre couvre le
# developpement ET l'administration systeme/reseau. Sont exclus : la data
# science, le jeu video, et tout ce qui n'est pas technique (pilotage,
# fonctionnel, marketing, RH, support utilisateur).

# Il en faut au moins un dans le titre ou la description.
TECH_SIGNAUX = [
    # developpement
    r"d[eé]veloppeur", r"d[eé]veloppement", r"d[eé]velopper", r"dev\b",
    r"programmation", r"programmer", r"cod(er|age)", r"impl[eé]ment",
    r"full ?-? ?stack", r"back ?-? ?end", r"front ?-? ?end", r"logiciel",
    r"application (web|mobile|m[eé]tier|interne)", r"applicatif",
    r"software engineer", r"ing[eé]nieur (logiciel|[eé]tudes|d[eé]veloppement)",
    r"python", r"java\b", r"php", r"javascript", r"typescript", r"symfony",
    r"laravel", r"react", r"angular", r"vue\.?js", r"node\.?js", r"\.net",
    r"spring", r"django", r"flask", r"api rest", r"microservices?",
    r"scripts?\b", r"automatisation", r"pipeline",
    # administration systeme et reseau
    r"administrat(eur|rice|ion)", r"\bsysadmin\b", r"syst[eè]mes? et r[eé]seaux",
    r"linux", r"unix", r"windows server", r"active directory", r"\bvmware\b",
    r"virtualisation", r"\bansible\b", r"\bterraform\b", r"kubernetes", r"docker",
    r"supervision", r"\bcloud\b", r"\bazure\b", r"\baws\b", r"\bgcp\b",
    r"\bdevops\b", r"\bci ?/ ?cd\b", r"infrastructures?", r"exploitation",
    r"\bbash\b", r"powershell", r"r[eé]seaux?\b", r"\bvlan\b", r"\bfirewall\b",
    r"base de donn[eé]es", r"\bsql\b",
]

# --- Exclusions thematiques (modulables depuis la page Parametres) --------
#
# Chaque groupe est un motif de rejet active ou desactive independamment.
# Un titre qui matche un groupe ACTIF est ecarte sans appel, meme si l'annonce
# coche par ailleurs tous les signaux techniques : "Data Scientist (Python)"
# reste un poste de data science.
#
# L'etat actif/inactif vit dans data/parametres.json, pas ici : ce fichier ne
# porte que les valeurs par defaut et la definition des motifs.

GROUPES_EXCLUSION = [
    {
        "cle": "data",
        "libelle": "Data science et analyse de donnees",
        "exemples": "Data Scientist, Data Analyst, ML Engineer, BI",
        "motifs": [
            r"data scientist", r"data analyst", r"datascience", r"data science",
            r"machine learning", r"\bml engineer\b", r"statisticien",
            r"analyste (de )?donn[eé]es", r"business intelligence", r"\bbi\b",
        ],
    },
    {
        "cle": "jeu_video",
        "libelle": "Jeu video",
        "exemples": "Gameplay Programmer, Level Designer, Unity, Unreal",
        "motifs": [
            r"jeu ?x? ?vid[eé]o", r"game (developer|designer|programmer|play)",
            r"gameplay", r"level design", r"\bunity\b", r"unreal engine",
        ],
    },
    {
        "cle": "gestion_projet",
        "libelle": "Gestion de projet et fonctionnel",
        "exemples": "Product Owner, Scrum Master, Business Analyst, MOA",
        "motifs": [
            r"product owner", r"scrum master",
            r"business analyst", r"consultant fonctionnel", r"\bmoa\b",
        ],
    },
    {
        "cle": "relation_client",
        "libelle": "Support et relation client",
        "exemples": "Support niveau 1, Helpdesk, Hotline, Charge de clientele",
        "motifs": [
            r"charg[eé]e? de (projet|mission|communication|client[eè]le)",
            r"support (utilisateur|client|niveau 1)", r"helpdesk", r"hotline",
        ],
    },
    {
        "cle": "fonctions_support",
        "libelle": "Marketing, communication, RH",
        "exemples": "Marketing, Commercial, Communication, SIRH",
        "motifs": [
            r"marketing", r"commercial", r"communication", r"sirh", r"\brh\b",
        ],
    },
    {
        "cle": "design",
        "libelle": "Design et graphisme",
        "exemples": "UX/UI Designer, Graphiste",
        "motifs": [r"\bux\b", r"\bui\b", r"designer", r"graphiste"],
    },
    {
        "cle": "terrain",
        "libelle": "Interventions terrain et industrie",
        "exemples": "Cablage, Electricien, Technicien de maintenance",
        "motifs": [
            r"ing[eé]nieur (m[eé]thodes|maintenance|qualit[eé])",
            r"c[aâ]blage", r"[eé]lectricien", r"technicien de maintenance",
        ],
    },
    {
        "cle": "cybersecurite",
        "libelle": "Cybersecurite",
        "exemples": "Pentest, SOC, Analyste SOC, RSSI",
        "motifs": [
            r"cybers[eé]curit[eé]", r"\bpentest", r"\bsoc\b",
            r"s[eé]curit[eé] (des )?(syst[eè]mes|informatique|offensive)",
            r"\brssi\b",
        ],
        "actif": False,
    },
    {
        "cle": "embarque",
        "libelle": "Systemes embarques et temps reel",
        "exemples": "Embarque, Firmware, VHDL, Automatisme",
        "motifs": [
            r"embarqu[eé]", r"firmware", r"\bvhdl\b", r"automatisme",
            r"temps r[eé]el",
        ],
        "actif": False,
    },
]

# Etat par defaut : un groupe sans cle "actif" est actif.
EXCLUSIONS_ACTIVES = {g["cle"]: g.get("actif", True) for g in GROUPES_EXCLUSION}

# Termes ajoutes a la main depuis la page Parametres, en deux familles.
# Saisis en langage courant, convertis en motifs par motif_depuis_terme().
#
# SOUPLES : le terme n'ecarte que si le titre ne prouve pas par ailleurs qu'il
# s'agit d'un poste informatique. C'est le mecanisme deja utilise pour "chef de
# projet", et le defaut recommande : "data" n'y tuera pas une offre intitulee
# "Developpement Outils oriente IA & Data", parce que "developpement" leve le
# veto.
#
# STRICTS : le terme ecarte quoi qu'il arrive. A reserver aux intitules qui
# n'ont aucune chance d'etre interessants.
EXCLUSIONS_PERSO = []           # stricts
EXCLUSIONS_PERSO_SOUPLES = []


def construire_veto():
    """TITRE_VETO derive de l'etat des groupes. Rappele apres chaque
    modification des parametres, y compris a chaud dans le serveur."""
    motifs = []
    for groupe in GROUPES_EXCLUSION:
        if EXCLUSIONS_ACTIVES.get(groupe["cle"], groupe.get("actif", True)):
            motifs += groupe["motifs"]
    return motifs + list(EXCLUSIONS_PERSO)


def construire_veto_souple():
    """Vetos levables : appliques seulement si le titre n'est pas informatique."""
    return list(_VETO_SI_NON_IT_BASE) + list(EXCLUSIONS_PERSO_SOUPLES)


TITRE_VETO = construire_veto()

# Vetos levables : le poste n'est hors cible que s'il n'est PAS informatique.
# "Chef de projet informatique" reste recevable, "chef de projet service
# client" non.
_VETO_SI_NON_IT_BASE = [
    r"chef ?fe? de projet", r"chef de produit",
]
TITRE_VETO_SI_NON_IT = list(_VETO_SI_NON_IT_BASE)

# Qualificatifs qui prouvent qu'un intitule releve de l'informatique.
IT_QUALIFICATIFS = [
    r"informatique", r"technique", r"\bit\b", r"\bsi\b", r"digital",
    r"num[eé]rique", r"\bweb\b", r"logiciel", r"applicatif", r"application",
    r"d[eé]veloppement", r"syst[eè]me", r"r[eé]seau", r"donn[eé]es",
    r"\berp\b", r"\bcrm\b", r"infrastructure", r"cloud", r"\bmoe\b",
]

# Intitules franchement orientes developpement : prime de score, pour que le
# dev remonte au-dessus de l'administration systeme sans l'exclure.
TITRE_DEV = [
    r"d[eé]veloppeur", r"d[eé]veloppement", r"full ?-? ?stack", r"back ?-? ?end",
    r"front ?-? ?end", r"software engineer", r"programmeur", r"\bdev\b",
    r"ing[eé]nieur (logiciel|[eé]tudes|d[eé]veloppement)", r"applicatif",
]
PRIME_TITRE_DEV = 30

# Une offre publiee doit prouver qu'elle est informatique : soit un signal
# technique dans le titre, soit un minimum dans la description.
MIN_SIGNAUX_DESCRIPTION = 3

# Signaux negatifs : postes hors cible malgre un code ROME proche
MOTS_CLES_NEGATIFS = {
    "commercial": -15, "vente": -12, "technico-commercial": -18,
    "support utilisateur": -10, "hotline": -12, "helpdesk": -10,
    "cablage": -15, "technicien de maintenance": -12,
    "data scientist": -25, "machine learning": -18, "jeu video": -20,
    "bac+5": -8, "master": -6, "ingenieur diplome": -8,
    # 24 mois reste compatible (poursuite en master) : seule une duree
    # au-dela est penalisee ici, en coherence avec filters.score_offre
    "3 ans": -12, "36 mois": -12,
    "stage": -20, "cdi": -6, "cdd": -6,
}

SEUIL_RETENU = 25          # score brut, en dessous : statut 'ecarte'

# Seuil d'adequation retenu. En dessous, l'offre part en 'ecarte'.
# 70 est le point de rupture observe sur le vivier : au-dessus on a les
# offres publiees bien ciblees plus les spontanees du bon secteur, en
# dessous on tombe dans le bruit.
SEUIL_MATCHING = 70
SEUIL_PRIORITAIRE = 60     # au dessus : traiter en premier

# --- Filtre anti-ecoles ---------------------------------------------------
#
# Une large part des annonces "alternance" emane de CFA et d'ecoles privees qui
# vendent une formation, pas un poste. Le candidat a deja son ecole : ces
# annonces sont integralement du bruit.
#
# Les offres detectees sont TAGUEES, pas supprimees : certaines ecoles recrutent
# de vrais alternants pour leur propre service informatique.

# Signaux FORTS : un nom qui contient ca est un organisme de formation, point.
ECOLE_NOM_FORT = [
    r"\bcfa\b", r"\bcampus\b", r"\bacademy\b", r"\bschool\b", r"\bsup\s?de\b",
    r"\bcentre de formation\b", r"\bgroupe scolaire\b", r"\balternances?\b",
    r"\becole sup", r"\borganisme de formation\b", r"\bapprentissage\b",
]

# Signaux FAIBLES : demandent une confirmation par le texte.
# "Institut Pasteur", "Ecole 42" ou une universite recrutent de vrais alternants.
ECOLE_NOM_FAIBLE = [
    r"\becoles?\b", r"\binstitut\b", r"\bacad[eé]mie\b",
    r"\buniversit[eé]\b", r"\bcoll[eè]ge\b", r"\blyc[eé]e\b",
    # Beaucoup d'ESN ont une branche formation sans etre des ecoles :
    # "HN SERVICES - HN FORMATION" est un employeur reel.
    r"\bformations?\b",
]

# Secteurs NAF utilises pour scorer les candidatures spontanees, qui n'ont pas
# de description exploitable : on juge l'entreprise sur son activite.
NAF_POIDS = {
    "programmation informatique": 45,
    "conseil en systemes et logiciels": 42,
    "tierce maintenance de systemes": 30,
    "traitement de donnees": 35,
    "hebergement": 25,
    "portails internet": 30,
    "edition de logiciels": 45,
    "conseil en systemes": 40,
    "ingenierie": 15,
    "activites informatiques": 35,
    "reparation d'ordinateurs": -10,
    "commerce": -12,
    "enseignement": -25,
    "formation continue": -30,
}

# Emetteurs connus d'annonces "ecole" en volume
ECOLE_BLOCKLIST = [
    "iscod", "studi", "openclassrooms", "skill&you", "skill and you",
    "mydigitalschool", "digital campus", "ipssi", "esgi", "eemi",
    "sup de vinci", "ecole cube", "walt", "diplomeo", "alternance.fr",
    "cfa insta", "ifocop", "m2i formation", "onlineformapro", "icademie",
    "esatic", "isefac", "cerfal", "aftec", "ascencia", "ifa delorozoy",
    "eductive", "studialis", "galileo", "wild code school", "webforce3",
    "simplon", "epitech", "ecole ducasse", "cesi", "cnam",
    # bootcamps et ecoles de code
    "ironhack", "livecampus", "le wagon", "jedha", "datascientest",
    "o'clock", "oclock", "la capsule", "holberton", "efrei", "esiea",
    "hetic", "sup galilee", "ecole 42", "42 paris",
]

# Tokens sans ambiguite, cherches meme colles a un autre mot : "LIVECAMPUS"
# n'a pas de frontiere de mot avant "campus".
ECOLE_TOKENS_COLLES = ["campus", "bootcamp", "academie", "cfa"]

# Tokens colles ambigus : "KAISCHOOL" est une ecole, "Schoolab" un studio
# d'innovation. On ne tranche pas, on envoie en file de validation manuelle.
# "talent" et "skill" ont ete retires : trop de vraies entreprises tech les
# portent dans leur nom pour que le signal soit exploitable.
ECOLE_TOKENS_DOUTEUX = ["school", "schol", "campus", "academ", "educ"]

ECOLE_TEXTE_PATTERNS = [
    r"nous (te|vous) trouvons (ton|votre) entreprise",
    r"entreprises? partenaires?",
    r"frais de scolarit[eé]",
    r"pris en charge par l'?opco",
    r"titre rncp niveau [3-7]",
    r"int[eé]grer? notre (programme|formation|cursus)",
    r"rentr[eé]e (en |de )?(septembre|janvier|octobre|f[eé]vrier)",
    r"(notre|nos) (centre|centres) de formation",
    r"d[eé]croche(r|z) (ton|votre) (dipl[oô]me|alternance)",
    r"formation (100 ?% )?(en ligne|[aà] distance)",
    r"aucun frais (pour|[aà] la charge) (du|de l'?)(candidat|[eé]tudiant|apprenti)",
    r"nous recherchons des (candidats|[eé]tudiants) pour (nos|le compte de nos)",
    # Quand France Travail masque l'employeur, le nom ne dit rien : c'est le
    # texte qui trahit l'organisme de formation.
    r"\bcfa\b", r"[eé]cole sup[eé]rieure", r"notre [eé]cole",
    r"pour (l'une de |une de )?(ses|nos) entreprises? partenaires?",
]

# Nombre d'offres identiques publiees par un meme "employeur" au dela duquel
# on suspecte un organisme de formation plutot qu'un recruteur reel
SEUIL_DOUBLONS_EMPLOYEUR = 15

# --- Valeurs par defaut ----------------------------------------------------
#
# Photographie prise avant l'application de la surcouche. Elle sert de point
# de retour : l'interface propose "retablir les valeurs par defaut" sur chaque
# liste editable, et il faut bien que ces valeurs survivent quelque part une
# fois que parametres.json a pris la main.
#
# Une liste editee remplace ENTIEREMENT la valeur par defaut : c'est ce qui
# permet de supprimer une entree. Une cle absente de parametres.json signifie
# "valeur par defaut", pas "liste vide".

import copy as _copy  # noqa: E402

DEFAUTS = {
    "profil": _copy.deepcopy(PROFIL),
    "adresse_postale": _copy.deepcopy(ADRESSE_POSTALE),
    "romes": list(ROMES),
    "mots_cles": dict(MOTS_CLES),
    "ecole_blocklist": list(ECOLE_BLOCKLIST),
}

# Libelles indicatifs des codes ROME du domaine informatique, pour que la
# saisie ne se fasse pas a l'aveugle. La liste n'est pas exhaustive et
# n'importe quel code reste saisissable.
ROMES_CONNUS = {
    "M1801": "Administration de systemes d'information",
    "M1802": "Expertise et support en systemes d'information",
    "M1803": "Direction des systemes d'information",
    "M1804": "Etudes et developpement de reseaux de telecoms",
    "M1805": "Etudes et developpement informatique",
    "M1806": "Conseil et maitrise d'ouvrage en systemes d'information",
    "M1810": "Production et exploitation de systemes d'information",
}


# --- Surcouche utilisateur -------------------------------------------------
#
# Importe en toute fin de fichier : `parametres` importe `config`, qui est
# entierement defini a ce stade. Le garde-fou `hasattr` couvre le cas ou c'est
# `parametres` qui a ete importe en premier : il est alors partiellement
# initialise ici, et appliquera la surcouche lui-meme en fin d'import.
import parametres as _parametres  # noqa: E402

if hasattr(_parametres, "appliquer"):
    _parametres.appliquer()
