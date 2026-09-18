# -*- coding: utf-8 -*-
"""Gabarit d'identite. Copie ce fichier en identite_locale.py et remplis-le.

    cp identite_locale.exemple.py identite_locale.py

identite_locale.py est exclu du git : c'est la qu'on met ce qui permet
d'identifier ou de joindre quelqu'un. config.py, lui, est publie, et ne porte
que des valeurs d'exemple.

Les cles absentes gardent la valeur d'exemple de config.py. Le fichier entier
est facultatif : sans lui, l'outil tourne avec un profil fictif, ce qui suffit
pour explorer l'interface mais pas pour candidater.

Le reste du profil - formation, rythme, dates, disponibilite - se regle depuis
la page Parametres de l'interface, qui ecrit dans data/parametres.json.
"""

PROFIL = {
    "nom": "Prenom Nom",
    "email": "prenom.nom@etu.exemple.fr",
    # Format international pour les formulaires, format lisible pour les
    # signatures d'email : les deux sont demandes selon les sites.
    "telephone": "+33600000000",
    "telephone_affiche": "06 00 00 00 00",
    # Pied de signature des emails. Laisser vide pour n'afficher aucun lien.
    "liens": "linkedin.com/in/prenom-nom",
    # Reclames par certains formulaires, WTTJ en tete. Laisses vides, les
    # champs correspondants ne sont simplement pas remplis.
    "titre": "BUT 3 Informatique - Developpeur back-end",
    "linkedin": "https://www.linkedin.com/in/prenom-nom/",
    # Le reste du profil - rythme, dates, disponibilite - se regle depuis la
    # page Parametres, mais peut aussi etre fige ici.
    "formation": "BUT Informatique - parcours Realisation d'Applications",
    "etablissement": "IUT d'Exemple (Universite d'Exemple)",
}

# Adresse postale reelle. Les formulaires des grands comptes (Workday et
# assimiles) la reclament et refusent un code postal invalide.
ADRESSE_POSTALE = {
    "voie": "1 rue de l'Exemple",
    "code_postal": "75001",
    "commune": "Paris",
    "region": "Paris",
    "pays": "France",
    "indicatif": "+33",
}

# Point de depart du calcul des distances. Les coordonnees se recuperent sur
# https://api-adresse.data.gouv.fr/search/?q=<ton+adresse> ; a defaut, la page
# Parametres sait geocoder l'adresse saisie et memorise le resultat.
ADRESSE_REFERENCE = "1 rue de l'Exemple, 75001 Paris"
ORIGINE = (48.8566, 2.3522)
