"""Scoring des offres et detection des annonces emises par des ecoles/CFA."""

import math
import re
import unicodedata

from alternance import config


def normalise(texte):
    """Minuscules sans accents, pour que les regex n'aient pas a gerer les deux."""
    if not texte:
        return ""
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


_MOTIFS = {}


def contient(mot, texte):
    """Presence de `mot` comme mot entier dans `texte` deja normalise.

    Une simple recherche de sous-chaine produit des faux positifs qui gonflent
    le score : "vite" dans "eviter", "git" dans "digital" ou "logiciel", "ia"
    dans "mediatique", "vente" dans "inventer". Les bornes s'appuient sur les
    caracteres alphanumeriques et non sur \b, pour que les cles ponctuees
    ("api rest", "ci/cd", "no-code", "bac+3") restent correctes.
    """
    motif = _MOTIFS.get(mot)
    if motif is None:
        motif = _MOTIFS[mot] = re.compile(
            rf"(?<![a-z0-9]){re.escape(mot)}(?![a-z0-9])")
    return motif.search(texte) is not None


def _offre(objet):
    """Accepte indifferemment un dict ou une ligne sqlite3.Row.

    Les fonctions de ce module lisent les offres avec .get(), que sqlite3.Row
    n'expose pas. Les appelants convertissaient tous en dict, sauf un : la
    generation de lettres a echoue sur TOUTES les offres le jour ou une
    nouvelle fonction a oublie la conversion. Plutot que de compter sur la
    discipline des appelants, on normalise ici.
    """
    return objet if isinstance(objet, dict) or objet is None else dict(objet)


MARQUEURS_STAGE = ("stage", "internship", "stagiaire")


def est_stage(offre):
    """L'offre est-elle un stage plutot qu'une alternance ?

    On se fie au type de contrat fourni par la source, jamais au titre : une
    annonce d'alternance mentionne souvent "stage" dans son texte sans en etre
    un, et l'inverse est vrai aussi.
    """
    offre = _offre(offre)
    contrat = normalise(str(offre.get("contrat_type") or ""))
    return any(marque in contrat for marque in MARQUEURS_STAGE)


def distance_km(lat, lon):
    """Distance a vol d'oiseau depuis Vitry-sur-Seine (haversine)."""
    if lat is None or lon is None:
        return None
    lat0, lon0 = config.ORIGINE
    r = 6371.0
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat0)) * math.cos(math.radians(lat))
         * math.sin(dlon / 2) ** 2)
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def effectif_bonus(taille):
    """Bonus par palier d'effectif. `taille` arrive sous des formes variees
    ("250-499", "> 2000 salaries", "1000-1999") : on lit le plus grand nombre."""
    if not taille:
        return 0
    nombres = [int(n) for n in re.findall(r"\d+", str(taille))]
    if not nombres:
        return 0
    effectif = max(nombres)
    for seuil, bonus in config.BONUS_EFFECTIF:
        if effectif >= seuil:
            return bonus
    return 0


# --- Detection ecole ------------------------------------------------------

def detecte_ecole(entreprise, intitule, description, compteur_employeur=None):
    """Retourne (flag, raisons). flag=1 des qu'un signal fort est present.

    Trois familles de signaux :
      1. le nom de l'employeur ressemble a un organisme de formation
      2. le texte vend une formation plutot qu'un poste
      3. le meme employeur publie un volume anormal d'annonces identiques
    """
    raisons = []
    nom = normalise(entreprise)
    texte = normalise(f"{intitule} {description}")

    # Matching sur mot entier : "studi" ne doit pas matcher "LEIKIR STUDIO"
    for marque in config.ECOLE_BLOCKLIST:
        if re.search(rf"(?<![a-z0-9]){re.escape(normalise(marque))}(?![a-z0-9])", nom):
            raisons.append(f"blocklist:{marque}")

    hits_fort = [p for p in config.ECOLE_NOM_FORT if re.search(p, nom)]
    raisons += [f"nom_fort:{p}" for p in hits_fort]

    # Tokens sans ambiguite, y compris colles : "LIVECAMPUS", "TECHBOOTCAMP"
    colles = [t for t in config.ECOLE_TOKENS_COLLES if t in nom]
    hits_fort += colles
    raisons += [f"token:{t}" for t in colles]

    hits_faible = [p for p in config.ECOLE_NOM_FAIBLE if re.search(p, nom)]
    raisons += [f"nom_faible:{p}" for p in hits_faible]

    # Un nom ambigu ("KAISCHOOL") vaut signal faible : combine a un seul indice
    # textuel, il suffit a trancher.
    ambigus = [t for t in config.ECOLE_TOKENS_DOUTEUX if t in nom]
    hits_faible += ambigus
    raisons += [f"nom_ambigu:{t}" for t in ambigus]

    hits_texte = [pat for pat in config.ECOLE_TEXTE_PATTERNS if re.search(pat, texte)]
    raisons += [f"texte:{p}" for p in hits_texte]

    if compteur_employeur and entreprise:
        n = compteur_employeur.get(entreprise, 0)
        if n >= config.SEUIL_DOUBLONS_EMPLOYEUR:
            raisons.append(f"volume:{n}_annonces")

    # Un signal faible seul ne suffit pas : "Institut Pasteur" ou "Ecole 42"
    # recrutent de vrais alternants. Un signal fort, lui, tranche seul.
    certain = (
        any(r.startswith("blocklist:") for r in raisons)
        or hits_fort
        or len(hits_texte) >= 2
        or (hits_faible and hits_texte)
        or any(r.startswith("volume:") for r in raisons)
    )
    return (1 if certain else 0), "; ".join(raisons)


# --- Scoring --------------------------------------------------------------

def score_offre(offre):
    """Score entier + detail par critere, pour pouvoir auditer un mauvais tri."""
    offre = _offre(offre)
    detail = {}
    texte = normalise(f"{offre.get('intitule', '')} {offre.get('description', '')}")
    titre = normalise(offre.get("intitule", ""))

    # Mots-cles techniques, comptes une fois, double poids dans le titre
    total_kw = 0
    trouves = []
    for mot, poids in config.MOTS_CLES.items():
        if contient(mot, texte):
            gain = poids * 2 if contient(mot, titre) else poids
            total_kw += gain
            trouves.append(mot)
    detail["mots_cles"] = total_kw
    detail["mots_cles_trouves"] = trouves
    # Conservee pour pondere l'axe technique : une annonce courte ne peut pas
    # accumuler autant de mots-cles qu'une annonce longue, ce qui la penalisait
    # sans rapport avec sa pertinence.
    detail["longueur_texte"] = len(texte)

    total_neg = 0
    negatifs = []
    # "stage" vaut -20 dans la liste : c'est la bonne penalite quand on ne
    # cherche que de l'alternance, et un contresens des qu'on cherche des
    # stages. Meme logique pour "cdd", souvent la forme juridique d'un stage.
    ignores = {"stage", "cdd"} if config.RECHERCHE_STAGES else set()
    for mot, poids in config.MOTS_CLES_NEGATIFS.items():
        if mot in ignores:
            continue
        if contient(mot, texte):
            total_neg += poids
            negatifs.append(mot)
    detail["negatifs"] = total_neg
    detail["negatifs_trouves"] = negatifs

    # Proximite : plein pot sous 15 km, degressif ensuite
    d = offre.get("distance_km")
    if d is None:
        prox = 0
    elif d <= 15:
        prox = 20
    elif d <= 25:
        prox = 12
    elif d <= 35:
        prox = 5
    else:
        prox = -10
    detail["proximite"] = prox

    # Duree. Les deux natures ne se mesurent pas dans la meme unite : une
    # alternance se compte en mois, un stage en semaines. Les comparer au meme
    # bareme reviendrait a juger un stage de 14 semaines comme un contrat de
    # 14 mois, donc a lui donner la note maximale par accident.
    stage = est_stage(offre)
    trop_court = False
    duree = offre.get("contrat_duree")
    if stage:
        cible = config.STAGE_DUREE_SEMAINES
        trop_court = False
        if duree is None:
            dur = 0
        else:
            ecart = duree - cible
            if ecart < -config.STAGE_ECART_COURT:
                # En dessous du minimum : le stage ne validera pas le semestre.
                # Ce n'est pas une offre mediocre, c'est une offre inutilisable.
                dur = -5
                trop_court = True
            elif ecart > config.STAGE_ECART_LONG:
                dur = -10         # au-dela de la tolerance haute
            elif abs(ecart) <= 1:
                dur = 15          # pile la cible
            else:
                dur = 8           # dans la tolerance
    else:
        limite = config.PROFIL["duree_negociable_jusqu_a"]
        if duree is None:
            dur = 0
        elif 10 <= duree <= 14:
            dur = 15
        elif duree < 10:
            dur = -5
        elif duree <= limite:
            dur = 5
        else:
            dur = -20
    detail["duree"] = dur
    detail["stage"] = stage

    # Type de contrat : on valorise la nature effectivement recherchee.
    contrat = normalise(str(offre.get("contrat_type", "")))
    cherchee = config.RECHERCHE_STAGES if stage else config.RECHERCHE_ALTERNANCE
    if stage:
        ctr = 10 if cherchee else 0
    else:
        ctr = 10 if ("apprentissage" in contrat or "professionnalisation" in contrat
                     or "alternance" in contrat) else 0
    detail["contrat"] = ctr

    # Une nature non recherchee n'est pas une offre mediocre, c'est une offre
    # hors sujet. Un simple malus la laissait a 75 % : elle passait le seuil.
    # Le drapeau est lu par pourcentage_matching, qui renvoie alors zero.
    detail["nature_exclue"] = (not cherchee) or (stage and trop_court)
    if stage and trop_court:
        detail["duree_insuffisante"] = True

    # Une candidature spontanee n'a pas de description exploitable : on la juge
    # sur le secteur d'activite de l'entreprise plutot que sur des mots-cles.
    naf_score = 0
    if offre.get("genre") == "spontanee":
        naf = normalise(offre.get("naf") or "")
        for libelle, poids in config.NAF_POIDS.items():
            if normalise(libelle) in naf:
                naf_score = poids
                break
        # petite prime aux structures a taille humaine, ou un alternant compte
        taille = str(offre.get("taille") or "")
        if taille in ("3-5", "6-9", "10-19", "20-49"):
            naf_score += 8
    detail["secteur_naf"] = naf_score

    # Prime aux intitules franchement dev : l'administration systeme reste dans
    # le perimetre mais ne doit pas occuper le haut du classement.
    est_spontanee = offre.get("genre") == "spontanee"
    prime = 0 if est_spontanee else (config.PRIME_TITRE_DEV if any(
        re.search(p, titre) for p in config.TITRE_DEV
    ) else 0)
    detail["prime_dev"] = prime

    # Taille de la structure : une grande entreprise a une DSI interne quel que
    # soit son code NAF, encadre reellement un alternant, et pese sur un CV.
    bonus_taille = effectif_bonus(offre.get("taille"))
    detail["bonus_taille"] = bonus_taille

    # Reconnaissance par le nom, quand la source ne donne pas d'effectif : la
    # plupart des offres WTTJ et France Travail n'ont pas de champ taille.
    nom = normalise(offre.get("entreprise"))
    groupe = next((g for g in config.GRANDS_GROUPES
                   if re.search(rf"(?<![a-z]){re.escape(normalise(g).strip())}", nom)), None)
    prime_groupe = config.PRIME_GRAND_GROUPE if groupe else 0
    # On ne cumule pas prime de nom et gros bonus d'effectif : c'est le meme signal
    if prime_groupe and bonus_taille:
        prime_groupe = max(0, prime_groupe - bonus_taille // 2)
    detail["grand_groupe"] = groupe
    detail["prime_groupe"] = prime_groupe

    total = (total_kw + total_neg + prox + dur + ctr + naf_score + prime
             + bonus_taille + prime_groupe)
    detail["total"] = total
    return total, detail


# --- Pourcentage d'adequation ----------------------------------------------
#
# Le score brut n'a pas de referentiel : 220 ne veut rien dire tant qu'on ne
# sait pas a quoi le comparer. On le convertit en un pourcentage lisible en
# normalisant chaque composante par un plafond calibre sur la distribution
# reelle du vivier (percentile 90), puis en ponderant selon ce qui compte.
#
# Le plafond est volontairement le p90 et non le maximum observe : une offre
# exceptionnelle sature sa composante plutot que d'ecraser toutes les autres.

PLAFONDS = {
    "technique": 90,    # mots-cles : p90 = 72, max = 202
    "proximite": 20,
    "conditions": 25,   # duree (15) + type de contrat (10)
    "structure": 45,    # effectif ou appartenance a un grand groupe
    "secteur": 50,      # candidatures spontanees, jugees sur le NAF
}

# Poids en pourcentage. Leur somme fait 100.
POIDS = {
    "technique": 45,    # l'adequation du poste prime sur tout le reste
    "nature": 15,       # intitule franchement oriente developpement
    "proximite": 15,
    "structure": 15,    # priorite explicite aux grands groupes
    "conditions": 10,   # duree et type de contrat
}


def _borne(valeur, plafond):
    """Ramene une composante dans [0, 1]."""
    if plafond <= 0:
        return 0.0
    return max(0.0, min(1.0, valeur / plafond))


# Longueur de texte au-dela de laquelle une annonce ne gagne plus de mots-cles.
# Mesuree sur la base : la mediane des points plafonne vers 1000-2000 caracteres
# (39 points entre 1000 et 2000, 34 entre 2000 et 4000, 39 au-dela).
REFERENCE_TEXTE = 1500

# Part du plafond accordee meme a un texte tres court. Sans plancher, une
# annonce de 100 caracteres aurait un plafond quasi nul et n'importe quel
# mot-cle la porterait a 100 %.
PLANCHER_TEXTE = 0.35


def plafond_technique(longueur):
    """Plafond de l'axe technique, proportionne a la longueur de l'annonce.

    Les sources ne fournissent pas le meme volume de texte : l'Apec tronque a
    283 caracteres, Welcome to the Jungle en donne 1900 en mediane. Rapporter
    les points de mots-cles a un plafond fixe revenait a noter la longueur de
    l'annonce plutot que son adequation.
    """
    part = min(1.0, max(0, longueur or 0) / REFERENCE_TEXTE)
    return PLAFONDS["technique"] * (PLANCHER_TEXTE + (1 - PLANCHER_TEXTE) * part)


def pourcentage_matching(detail, genre="offre"):
    """Convertit la ventilation du score en adequation 0-100.

    Retourne (pourcentage, ventilation) ou la ventilation donne la note de
    chaque axe, pour pouvoir expliquer un mauvais classement sans relire le
    code.
    """
    # Stage alors qu'on ne cherche que l'alternance, ou l'inverse : rien a
    # evaluer, l'offre ne correspond pas a ce qui est demande.
    if detail.get("nature_exclue"):
        return 0, {cle: 0 for cle in POIDS}

    axes = {}

    # Adequation technique. Pour une candidature spontanee il n'y a pas de
    # description exploitable : c'est le secteur d'activite qui en tient lieu.
    if genre == "spontanee":
        axes["technique"] = _borne(detail.get("secteur_naf") or 0,
                                   PLAFONDS["secteur"])
    else:
        axes["technique"] = _borne(
            detail.get("mots_cles") or 0,
            plafond_technique(detail.get("longueur_texte")))

    # Les signaux negatifs (poste commercial, data science...) rabotent l'axe
    # technique plutot que le total : c'est bien l'adequation qui se degrade.
    penalite = abs(detail.get("negatifs") or 0)
    if penalite:
        axes["technique"] = max(0.0, axes["technique"] - penalite / 100)

    if genre == "spontanee":
        # Aucun poste n'est decrit : on sait que l'entreprise fait du logiciel,
        # pas qu'elle cherche un developpeur. Valeur neutre assumee.
        axes["nature"] = 0.4
    else:
        axes["nature"] = 1.0 if (detail.get("prime_dev") or 0) > 0 else 0.0
    axes["proximite"] = _borne(detail.get("proximite") or 0, PLAFONDS["proximite"])
    axes["structure"] = _borne(max(detail.get("bonus_taille") or 0,
                                   detail.get("prime_groupe") or 0),
                               PLAFONDS["structure"])
    axes["conditions"] = _borne((detail.get("duree") or 0) + (detail.get("contrat") or 0),
                                PLAFONDS["conditions"])

    total = sum(axes[a] * POIDS[a] for a in POIDS)
    ventilation = {a: round(axes[a] * 100) for a in axes}
    return round(total), ventilation


def titre_est_informatique(titre):
    """Le titre prouve-t-il a lui seul qu'il s'agit d'un poste informatique ?

    Sert deux fois : a lever un veto levable ("chef de projet informatique"
    passe, "chef de projet service client" non) et a simuler l'effet d'un terme
    d'exclusion avant de l'enregistrer. `titre` doit deja etre normalise.
    """
    return any(re.search(p, titre) for p in config.TECH_SIGNAUX) or            any(re.search(p, titre) for p in config.IT_QUALIFICATIFS)


def est_mission_technique(intitule, description, genre="offre"):
    """La mission est-elle technique (dev ou administration systeme/reseau) ?

    Retourne (bool, raison). Les candidatures spontanees echappent a la porte :
    aucune mission n'y est decrite, c'est la lettre qui fixe le poste vise.
    """
    if genre == "spontanee":
        return True, "spontanee"

    titre = normalise(intitule)
    texte = normalise(f"{intitule} {description}")

    vetos = [p for p in config.TITRE_VETO if re.search(p, titre)]
    signaux = [p for p in config.TECH_SIGNAUX if re.search(p, texte)]
    est_it = titre_est_informatique(titre)

    # Un veto sur le titre est sans appel : "Data Scientist (Python)" coche
    # des signaux techniques mais reste hors appetence.
    if vetos:
        return False, f"veto_titre:{vetos[0]}"

    # Vetos levables : "chef de projet informatique" passe, "chef de projet
    # service client" non.
    for pat in config.TITRE_VETO_SI_NON_IT:
        if re.search(pat, titre) and not est_it:
            return False, f"veto_non_it:{pat}"

    if not signaux:
        return False, "aucun_signal_technique"

    # Sans signal technique dans le titre, on exige un minimum de densite dans
    # la description : evite qu'un poste non informatique passe parce que
    # l'annonce mentionne "Excel" ou "outils bureautiques".
    if not est_it and len(signaux) < config.MIN_SIGNAUX_DESCRIPTION:
        return False, f"pas_it:titre_non_informatique_{len(signaux)}_signaux"

    return True, f"technique:{len(signaux)}_signaux"


EMPLOYEURS_INCONNUS = {"", "?", "(non communique)", "(non communiqué)",
                       "partenaire", "entreprise", "confidentiel"}


def doute(offre, raison_ecole, raison_mission):
    """Y a-t-il un doute qui justifie un arbitrage humain ?

    Retourne la raison du doute, ou None. Tout ce qui remonte ici part en file
    de validation manuelle plutot que d'etre retenu ou jete en silence.
    """
    offre = _offre(offre)
    nom = normalise(offre.get("entreprise"))

    # Un employeur masque n'est pas un motif d'arbitrage : seule la description
    # du poste compte. Le risque residuel (une ecole qui recrute pour ses
    # "entreprises partenaires" sans se nommer) est couvert par les motifs
    # textuels de ECOLE_TEXTE_PATTERNS, qui taguent l'annonce en amont.
    if nom in EMPLOYEURS_INCONNUS or not nom:
        return None

    # Nom evoquant une ecole sans certitude
    ambigus = [t for t in config.ECOLE_TOKENS_DOUTEUX if t in nom]
    if ambigus:
        return f"nom ambigu ({', '.join(ambigus)}) : ecole ou entreprise ?"

    # Signaux d'ecole presents mais insuffisants pour trancher
    if raison_ecole and not offre.get("flag_ecole"):
        return f"signaux d'organisme de formation non concluants : {raison_ecole[:80]}"

    # Veto leve par un qualificatif informatique : a confirmer
    if raison_mission and raison_mission.startswith("veto_non_it"):
        return "veto leve par un qualificatif informatique, a confirmer"

    # Une duree jusqu'a 24 mois passe sans arbitrage : la poursuite d'etudes
    # apres le BUT3 la rend compatible. Au-dela, il faut en parler.
    duree = offre.get("contrat_duree")
    limite = config.PROFIL["duree_negociable_jusqu_a"]
    if duree and duree > limite:
        return (f"duree annoncee {duree} mois : couvrirait trois cycles, "
                "a discuter avec l'entreprise et l'ecole")

    # Volontairement PAS de doute sur un score faible : une offre mediocre n'est
    # pas un cas d'arbitrage, elle rejoint le vivier et se classe en bas.

    return None


def a_un_canal(offre):
    """Existe-t-il un moyen concret de postuler ?

    Les recruteurs LBA sans recipient_id n'exposent ni email ni formulaire : leur
    page n'affiche qu'un numero de telephone. Les retenir dans le vivier revient
    a generer des lettres qu'on ne pourra jamais envoyer.

    Fait derive des donnees, donc recalcule a chaque rescore : le poser une fois
    par script externe ne tenait pas, statut_initial le rabotait au passage.
    """
    offre = _offre(offre)
    if offre.get("recipient_id"):
        return True
    if offre.get("contact_email"):
        return True
    # Une URL LBA sans recipient_id mene a une page sans formulaire
    if offre.get("source") == "lba" and not offre.get("recipient_id"):
        return False
    return bool(offre.get("url_candidature"))


def statut_initial(score, flag_ecole, mission_technique=True, raison_doute=None,
                   canal=True, matching=None):
    if flag_ecole:
        return "ecole"
    if not mission_technique:
        return "hors_cible"
    # Sans canal, le score n'a plus d'importance : on ne pourra pas postuler.
    if not canal:
        return "sans_canal"
    if score < config.SEUIL_RETENU:
        return "ecarte"
    # Seuil d'adequation : critere principal de selection, applique apres les
    # filtres structurels (ecole, mission, canal) qui priment sur lui.
    if matching is not None and matching < config.SEUIL_MATCHING:
        return "ecarte"
    if raison_doute:
        return "a_valider"
    return "a_traiter"
