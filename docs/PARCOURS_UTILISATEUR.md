# Parcours utilisateur

## Cycle de vie d'une offre

```mermaid
stateDiagram-v2
    [*] --> collectee : sourcing.py

    collectee --> ecole : nom ou texte d'organisme de formation
    collectee --> hors_cible : veto sur le titre (data science, jeu video, non technique)
    collectee --> ecarte : score sous le seuil de 25
    collectee --> sans_canal : aucun email ni formulaire (LBA telephone seul)
    collectee --> a_valider : doute necessitant un arbitrage humain
    collectee --> a_traiter : retenue sans reserve

    a_valider --> a_traiter : bouton Valider du dashboard
    a_valider --> rejete_manuel : bouton Rejeter

    ecole --> a_traiter : bouton Recuperer (faux positif)
    hors_cible --> a_traiter : bouton Recuperer
    ecarte --> a_traiter : bouton Recuperer

    a_traiter --> lettre_prete : generer_lettres.py
    lettre_prete --> envoyee : postuler_lba.py --confirmer<br/>ou envoyer.py --confirmer
    envoyee --> entretien : reponse positive
    envoyee --> refus : reponse negative
    entretien --> signee : contrat signe
    signee --> [*]
    refus --> [*]
```

Les statuts poses par une decision humaine (`db.STATUTS_FIGES`) ne sont jamais
ecrases par `sourcing.py --rescore`. Un arbitrage rendu est definitif.

## Parcours type, dans l'ordre

```mermaid
sequenceDiagram
    actor R as Utilisateur
    participant T as Terminal
    participant D as Dashboard
    participant N as Navigateur Playwright
    participant E as Entreprise

    Note over R,T: 1. Collecte (a relancer chaque semaine)
    R->>T: python sourcing.py
    T-->>R: 431 collectees, 344 retenues

    Note over R,D: 2. Arbitrage des cas douteux
    R->>D: http://127.0.0.1:5000
    D-->>R: file "A valider" avec la raison du doute
    R->>D: Valider / Rejeter

    Note over R,T: 3. Redaction
    R->>T: python generer_lettres.py --limite 10
    T-->>R: 10 lettres ecrites dans lettres/

    Note over R,D: 4. Relecture
    R->>D: onglet "Lettre prete"
    R->>R: lit les lettres, corrige si besoin

    Note over R,N: 5. Repetition a blanc
    R->>T: python postuler_lba.py --limite 5
    N->>N: remplit, capture, n'envoie pas
    R->>R: verifie data/captures/

    Note over R,E: 6. Envoi reel
    R->>T: python postuler_lba.py --limite 5 --confirmer
    N->>E: soumet le formulaire
    N-->>D: statut envoyee, relance a J+7
```

## Connexion a un site carriere

Necessaire une seule fois par site, et uniquement pour les sites qui exigent
un compte (WTTJ, Apec, JobTeaser). Le formulaire LBA n'en demande
pas.

```mermaid
sequenceDiagram
    actor R as Utilisateur
    participant S as connecter_compte.py
    participant N as Chromium Playwright
    participant F as data/sessions/&lt;site&gt;.json

    R->>S: python connecter_compte.py wttj
    S->>N: ouvre une fenetre visible sur la page de connexion
    R->>N: se connecte par email et mot de passe
    S->>S: detecte la disparition du champ mot de passe
    S->>F: storage_state (cookies + localStorage)
    S->>N: ferme la fenetre
    Note over F: reutilise par les scripts de candidature<br/>aucun mot de passe n'est lu ni stocke
```

Le script ne lit jamais les identifiants : il ne recupere que l'etat de session
produit par le navigateur apres une connexion faite a la main.
