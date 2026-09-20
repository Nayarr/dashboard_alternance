"""Recherche d'alternance et de stage automatisee.

Organisation par role, de la donnee brute a la candidature deposee :

    socle         config, parametres, texte, chemins, journal, db, filtres
    sources/      un module par site interroge
    collecte      orchestration de la collecte et du rescore
    redaction/    lettres et pieces jointes
    candidature/  depot dans les formulaires, sessions de site
    courrier/     envoi par email, quand aucun formulaire n'existe
    interface/    serveur web, taches de fond, fichiers statiques

Point d'entree unique : cli.py, a la racine du depot.
"""
