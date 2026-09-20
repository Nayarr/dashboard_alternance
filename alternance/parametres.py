"""Parametres modifiables depuis l'interface, superposes aux valeurs de config.

config.py porte les valeurs par defaut et la definition des motifs. Ce module
lit data/parametres.json et ecrase les valeurs correspondantes dans config au
moment de l'import, puis a chaud apres chaque enregistrement.

Pourquoi un JSON separe plutot qu'une reecriture de config.py : les scripts en
ligne de commande importent config sans passer par le serveur web, donc la
valeur doit vivre dans un fichier de donnees, pas en base. Et reecrire du code
source par expression reguliere pour y poser une liste ne tient pas la route.

Le jeton Claude n'est PAS ici : c'est un secret, il va dans .env, jamais dans
un fichier de donnees susceptible d'etre commite ou sauvegarde.
"""

import json
import re

from alternance import config
from alternance import texte

FICHIER = config.BASE_DIR / "data" / "parametres.json"

# Reglages scalaires : cle JSON -> attribut de config
SCALAIRES = {
    "adresse": "ADRESSE_REFERENCE",
    "stage_duree_semaines": "STAGE_DUREE_SEMAINES",
    "stage_ecart_court": "STAGE_ECART_COURT",
    "stage_ecart_long": "STAGE_ECART_LONG",
    "rayon_km": "RAYON_KM",
    "seuil_matching": "SEUIL_MATCHING",
    "duree_max_mois": None,          # traite a part : vit dans PROFIL
    "prime_grand_groupe": "PRIME_GRAND_GROUPE",
}


def motif_depuis_terme(terme):
    """Convertit un terme saisi a la main en motif utilisable par le scoring.

    L'utilisateur tape "cybersecurite" ou "Chef de rayon", pas une expression
    reguliere. On normalise (le titre est normalise avant comparaison), on
    echappe, et on pose des bornes de mot pour eviter le probleme qui a fausse
    les scores precedemment : "vite" qui matche "eviter".
    """
    propre = texte.normalise(terme).strip()
    if not propre:
        return None
    return rf"(?<![a-z0-9]){re.escape(propre)}(?![a-z0-9])"


def charger():
    """Contenu brut du fichier, ou un dictionnaire vide s'il n'existe pas."""
    if not FICHIER.exists():
        return {}
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def appliquer(donnees=None):
    """Ecrase les valeurs de config par celles du fichier. Idempotent."""
    d = charger() if donnees is None else donnees

    for cle, attribut in SCALAIRES.items():
        if cle in d and attribut and d[cle] not in (None, ""):
            setattr(config, attribut, d[cle])

    if d.get("origine") and len(d["origine"]) == 2:
        config.ORIGINE = tuple(d["origine"])

    # Le profil est fusionne, pas remplace : une cle absente garde sa valeur
    # par defaut plutot que de disparaitre.
    config.PROFIL = dict(config.DEFAUTS["profil"])
    if isinstance(d.get("profil"), dict):
        config.PROFIL.update({k: v for k, v in d["profil"].items()
                              if k in config.DEFAUTS["profil"]})

    # Fusionnee comme le profil, pour la meme raison : une cle absente garde
    # sa valeur par defaut au lieu de disparaitre.
    config.ADRESSE_POSTALE = dict(config.DEFAUTS["adresse_postale"])
    if isinstance(d.get("adresse_postale"), dict):
        config.ADRESSE_POSTALE.update(
            {k: v for k, v in d["adresse_postale"].items()
             if k in config.DEFAUTS["adresse_postale"]})

    # Applique apres le profil : duree_max_mois est un critere de tri qui vit
    # dans PROFIL, la surcharge doit gagner sur la valeur fusionnee.
    if d.get("duree_max_mois"):
        config.PROFIL["duree_negociable_jusqu_a"] = int(d["duree_max_mois"])

    # Listes editables : une valeur presente remplace entierement le defaut,
    # c'est ce qui permet de supprimer une entree.
    config.ROMES = list(d["romes"]) if isinstance(d.get("romes"), list)         else list(config.DEFAUTS["romes"])
    config.MOTS_CLES = dict(d["mots_cles"]) if isinstance(d.get("mots_cles"), dict)         else dict(config.DEFAUTS["mots_cles"])
    config.ECOLE_BLOCKLIST = list(d["ecole_blocklist"])         if isinstance(d.get("ecole_blocklist"), list)         else list(config.DEFAUTS["ecole_blocklist"])

    for cle, attribut in (("recherche_alternance", "RECHERCHE_ALTERNANCE"),
                          ("recherche_stages", "RECHERCHE_STAGES"),
                          ("lettre_relecture", "LETTRE_RELECTURE")):
        if cle in d:
            setattr(config, attribut, bool(d[cle]))

    if isinstance(d.get("exclusions"), dict):
        for cle, actif in d["exclusions"].items():
            if cle in config.EXCLUSIONS_ACTIVES:
                config.EXCLUSIONS_ACTIVES[cle] = bool(actif)

    stricts = [str(t).strip() for t in (d.get("exclusions_perso") or [])
               if str(t).strip()]
    souples = [str(t).strip() for t in (d.get("exclusions_perso_souples") or [])
               if str(t).strip()]
    config.TERMES_PERSO = stricts
    config.TERMES_PERSO_SOUPLES = souples
    config.EXCLUSIONS_PERSO = [m for m in map(motif_depuis_terme, stricts) if m]
    config.EXCLUSIONS_PERSO_SOUPLES = [m for m in map(motif_depuis_terme, souples) if m]

    # Les vetos sont derives : les reconstruire est obligatoire, sinon la
    # modification n'a aucun effet tant que le processus n'a pas redemarre.
    config.TITRE_VETO = config.construire_veto()
    config.TITRE_VETO_SI_NON_IT = config.construire_veto_souple()
    return d


def enregistrer(modifications):
    """Fusionne `modifications` dans le fichier, applique, et retourne l'etat."""
    d = charger()
    d.update({k: v for k, v in modifications.items() if v is not None})
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(d, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    return appliquer(d)


def etat():
    """Vue complete destinee a l'interface : valeurs effectives + definitions."""
    d = charger()
    return {
        "adresse": config.ADRESSE_REFERENCE,
        "origine": list(config.ORIGINE),
        "rayon_km": config.RAYON_KM,
        "seuil_matching": config.SEUIL_MATCHING,
        "duree_max_mois": config.PROFIL["duree_negociable_jusqu_a"],
        "lettre_relecture": config.LETTRE_RELECTURE,
        "recherche_alternance": config.RECHERCHE_ALTERNANCE,
        "recherche_stages": config.RECHERCHE_STAGES,
        "stage_duree_semaines": config.STAGE_DUREE_SEMAINES,
        "stage_ecart_court": config.STAGE_ECART_COURT,
        "stage_ecart_long": config.STAGE_ECART_LONG,
        "profil": dict(config.PROFIL),
        "adresse_postale": dict(config.ADRESSE_POSTALE),
        "romes": list(config.ROMES),
        "romes_connus": dict(config.ROMES_CONNUS),
        "mots_cles": dict(config.MOTS_CLES),
        "ecole_blocklist": list(config.ECOLE_BLOCKLIST),
        "personnalise": {
            "profil": "profil" in d,
            "adresse_postale": "adresse_postale" in d,
            "romes": "romes" in d,
            "mots_cles": "mots_cles" in d,
            "ecole_blocklist": "ecole_blocklist" in d,
        },
        "prime_grand_groupe": config.PRIME_GRAND_GROUPE,
        "exclusions_perso": d.get("exclusions_perso") or [],
        "exclusions_perso_souples": d.get("exclusions_perso_souples") or [],
        "groupes": [
            {
                "cle": g["cle"],
                "libelle": g["libelle"],
                "exemples": g["exemples"],
                "motifs": len(g["motifs"]),
                "actif": config.EXCLUSIONS_ACTIVES.get(g["cle"], True),
            }
            for g in config.GROUPES_EXCLUSION
        ],
    }


# Appliquee des l'import : un script en ligne de commande qui fait
# `import config` doit voir les reglages de l'interface sans rien appeler.
appliquer()


def simuler(termes_souples, termes_stricts, exclusions, offres):
    """Que couperait cette configuration, sur les offres deja en base ?

    Repond avant enregistrement : c'est la seule facon de voir qu'un terme
    aussi anodin que "data" emporte la meilleure offre du vivier. Ne modifie
    rien, ne touche pas a config.

    `offres` : iterable de dicts {intitule, description, statut}.
    """
    import re
    from alternance import filtres as filters

    ACTIONNABLES = {"a_traiter", "lettre_prete", "a_valider"}
    rapport = []

    def examiner(libelle, motifs, levable):
        touchees = []
        compiles = [re.compile(m) for m in motifs]
        for o in offres:
            titre = texte.normalise(o.get("intitule"))
            if not any(c.search(titre) for c in compiles):
                continue
            if levable and filters.titre_est_informatique(titre):
                continue        # le veto est leve : l'offre reste
            touchees.append(o)
        if touchees:
            rapport.append({
                "libelle": libelle,
                "levable": levable,
                "total": len(touchees),
                "actionnables": sum(1 for o in touchees
                                    if o.get("statut") in ACTIONNABLES),
                "exemples": [
                    {"intitule": o.get("intitule"),
                     "matching": o.get("matching"),
                     "vivier": o.get("statut") in ACTIONNABLES}
                    for o in sorted(touchees,
                                    key=lambda x: -(x.get("matching") or 0))[:5]
                ],
            })

    for terme in termes_souples:
        motif = motif_depuis_terme(terme)
        if motif:
            examiner(terme, [motif], True)
    for terme in termes_stricts:
        motif = motif_depuis_terme(terme)
        if motif:
            examiner(terme, [motif], False)
    for groupe in config.GROUPES_EXCLUSION:
        if exclusions.get(groupe["cle"], config.EXCLUSIONS_ACTIVES.get(groupe["cle"])):
            examiner(groupe["libelle"], groupe["motifs"], False)

    return rapport


def reinitialiser(cle):
    """Retire une liste de la surcouche : la valeur par defaut reprend la main."""
    d = charger()
    d.pop(cle, None)
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    return appliquer(d)
