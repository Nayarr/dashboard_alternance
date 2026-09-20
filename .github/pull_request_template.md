<!--
Les quatre titres ci-dessous sont obligatoires : la CI les verifie et refuse
la proposition s'il en manque un, ou si une section est restee vide.

Pas de formalite pour la formalite. Chaque section repond a une question que
se pose forcement celui qui relit, et a laquelle le diff ne repond pas.
-->

## Ce que ça change

<!-- En deux ou trois phrases, du point de vue de quelqu'un qui utilise
     l'outil. Pas la liste des fichiers : le diff la donne deja. -->

## Pourquoi

<!-- Le probleme constate, pas l'intention. « Le panneau d'erreur disparaissait
     au rechargement » vaut mieux que « ameliorer la gestion des erreurs ».
     S'il s'agit d'un bug, dire comment il se reproduit. -->

## Comment c'est vérifié

<!-- Ce qui a reellement ete execute : tests ajoutes, parcours manuel dans le
     navigateur, mesure chiffree. « Ca marche chez moi » n'est pas une
     verification. Si quelque chose n'a pas pu etre teste, le dire ici. -->

## Risques et limites

<!-- Ce qui peut casser, ce qui reste a faire, ce qui a ete volontairement
     laisse de cote. « Aucun » est une reponse valable, mais elle s'ecrit. -->

---

- [ ] Les tests passent en local (`python -m unittest discover -s tests -t .`)
- [ ] Aucune donnee personnelle ni secret ajoute (`python outils/verifier_depot.py`)
- [ ] Le comportement modifie est couvert par un test, ou le motif est indique
      dans « Risques et limites »
