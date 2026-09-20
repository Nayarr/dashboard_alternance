---
name: lettre-motivation-anti-ia
description: |
  Verifier et corriger qu'une lettre de motivation ne ressemble pas a une
  lettre generee par IA - signes specifiques aux lettres de motivation
  (differents du style general traite par humanizer-fr). Utiliser en derniere
  passe, apres avoir redige une bonne lettre avec le skill lettre-motivation,
  juste avant l'envoi.
allowed-tools:
  - Read
  - Edit
---

# Anti-IA : lettre de motivation

## Principe

Ce skill ne traite pas ce qui rend une lettre bonne (voir
`lettre-motivation` pour ca) - seulement ce qui trahit qu'elle n'a pas
ete retravaillee. La cause profonde est toujours la meme : l'absence de
matiere specifique. Ce skill sert de checklist de verification finale,
pas de methode de redaction.

## Ce qui trahit une lettre IA non retravaillee

**Vocabulaire generique sans preuve juste apres** : "dynamique",
"motive", "rigoureux", "passionne", "oriente resultats", "professionnel
passionne", "crucial", "revolutionnaire", "passionnant", "fascinant",
"transformateur", "captivant", "fondamental".

**Marqueurs typographiques** : le tiret cadratin (—) utilise pour
encadrer une precision "a l'americaine" - devenu si associe a ChatGPT
que sa seule presence eveille le soupcon, meme legitime en typographie
francaise. Autre trace d'influence anglaise : une virgule placee avant
"et" alors que l'usage francais ne le fait pas.

**Constructions calquees** : "non seulement... mais aussi" revient de
facon disproportionnee dans les textes generes - a utiliser avec
parcimonie, jamais plus d'une fois dans une lettre courte.

**Phrases figees identifiables** ("signature ChatGPT") :
- "C'est avec un grand interet que j'ai lu votre offre"
- "Je me permets de vous contacter"
- "Actuellement en recherche active, je souhaite mettre mes competences... au service de votre entreprise"
- "Je suis convaincu(e) que mon dynamisme et ma rigueur me permettront d'apporter une contribution efficace"
- "Votre entreprise est leader dans son domaine"
- "Il est important de noter que" / "Il convient de souligner que" / "Force est de constater que"
- "J'ai eu l'immense privilege de..." / "un profond desir de contribuer"

**Structure trop parfaite** : paragraphes de longueur quasi identique,
plan mecanique en trois temps sans respiration, listes a puces
artificielles, transitions trop lisses ("par ailleurs", "en outre", "de
surcroit").

**Uniformite syntaxique (burstiness faible)** : les detecteurs comme
GPTZero mesurent la variabilite de longueur/complexite des phrases
d'un texte a l'autre. Un humain alterne naturellement phrases courtes
et longues, simples et complexes ; un texte IA garde un debit
regulier. Verifier concretement : les phrases de la lettre varient-elles
vraiment en longueur d'un paragraphe a l'autre, ou est-ce un rythme
metronomique ?

**Vocabulaire trop previsible (perplexite faible)** : la perplexite
mesure a quel point le choix des mots est statistiquement attendu. Un
LLM choisit presque toujours le mot le plus probable ; un humain glisse
des tournures personnelles, un mot plus rare ou moins "moyen". Chercher
si un mot precis ou un tour propre au candidat pourrait remplacer un
mot generique attendu.

**Ego mal place** : phrases qui commencent systematiquement par "Je
suis" / "J'ai fait" au lieu de partir d'un besoin de l'entreprise.

**Zero specificite - le test le plus fiable** : si remplacer le nom de
l'entreprise ou l'intitule du poste ne change rien au texte, la lettre
est generique. C'est le signal que les recruteurs reperent le plus vite,
avec ou sans detecteur automatique.

## Checklist de verification (passe finale)

1. Chercher chaque phrase figee de la liste ci-dessus - la reformuler ou
   la supprimer.
2. Chercher chaque adjectif generique - verifier qu'une preuve concrete
   le suit immediatement, sinon le supprimer ou l'etayer.
3. Mesurer la longueur des paragraphes/phrases - s'il y a une
   uniformite suspecte, casser le rythme (une phrase courte, une plus
   longue).
4. Compter les connecteurs logiques ("egalement", "par ailleurs", "en
   outre", "ainsi", "neanmoins") - en garder au plus un ou deux dans
   toute la lettre.
5. Appliquer le test du nom d'entreprise : le texte reste-t-il vrai si
   on change l'entreprise ? Si oui, remplacer par du specifique.
6. Chercher les tirets cadratins (—) et les supprimer ou reformuler
   sans - meme si l'usage est correct en francais, le risque de
   perception "IA" l'emporte. Verifier l'absence de virgule avant "et".
7. Chercher "non seulement... mais aussi" - en garder au plus une
   occurrence, sinon reformuler.
8. Passer par le skill `humanizer-fr` pour le traitement systematique
   phrase par phrase (31 patterns d'ecriture IA en francais) - voir
   [[lettres-humanizer-fr]].

## A ne jamais faire

- Considerer qu'une lettre "anti-IA" (qui passe ce filtre) est
  suffisante en soi - le fond doit venir du skill `lettre-motivation`
  avant cette passe.
- Ajouter artificiellement des fautes ou du desordre pour "faire
  humain" sans lien avec un vrai contenu specifique.
