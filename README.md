# DeskMonitor

Des widgets pour le bureau de Windows et de macOS : la machine en un coup d'œil, vos applications bien rangées, et un assistant vocal qui agit pour vous.

## Ce que fait DeskMonitor

- **Cartes façon widgets** : heure, processeur et mémoire, stockage, réseau, batterie, météo, agenda, musique, processus gourmands, note rapide, presse-papiers.
- **Actions en un clic** : au survol d'une carte, libérer la RAM, nettoyer le cache ou vider le cache DNS. Un clic sur la jauge du processeur montre les programmes qui le ralentissent.
- **Bureau organisé** : vos applications rangées par thème dans des panneaux (Internet, Bureautique, Développement…), sans déplacer aucun fichier.
- **Assistant vocal** : dites son nom, puis votre demande.
  - « ouvre Chrome », « ouvre le dossier téléchargements » ;
  - « cherche recette de crêpes » ;
  - « libère la mémoire » ;
  - « fais le point », « la météo », « range le bureau ».
- **Apparence soignée** : verre dépoli, thème clair ou sombre, couleur d'accent du système, animations fluides.
- **Fonds d'écran et écran de verrouillage** : une collection de fonds originaux, un diaporama, un fond « vivant » qui suit l'heure, et un écran de verrouillage avec la date.
- **Alertes, profils et mises à jour automatiques.**

## Installation

Téléchargez la dernière version dans l'onglet **Releases** :

- **Windows 10/11** : `DeskMonitor-Setup-<version>.exe`.
- **Mac** : `DeskMonitor-<version>-mac-arm64.dmg` pour les puces Apple (M1 à M4), ou `-mac-intel.dmg` pour les Mac Intel. Les explications sont dans `installer/Lisez-moi (Mac).txt`.

Les installateurs ne sont pas encore signés :
- **Windows** affiche « Windows a protégé votre ordinateur » : cliquez sur « Informations complémentaires », puis « Exécuter quand même » ;
- **macOS** : faites un clic droit sur l'application, puis « Ouvrir ».

## Vie privée

- Le monitoring, le rangement du bureau et la reconnaissance vocale fonctionnent **sur l'ordinateur, hors ligne**.
- L'écoute continue (activation par le nom) est facultative et se coupe dans Paramètres › Assistant.
- **Voix neuronales** : quand elles sont choisies (c'est le réglage par défaut), les phrases dites par l'assistant sont envoyées aux serveurs de Microsoft pour être lues. Pour ne rien envoyer, choisissez une voix « classique » ou « naturelle » installée sur l'ordinateur.
- La météo interroge Open-Meteo. Si aucune ville n'est indiquée, ipwho.is sert à situer la ville d'après l'adresse IP.

## Développement

Il faut Python 3.12.

```
pip install -r requirements.txt
python desk_monitor.py             # lancer l'application
python desk_monitor.py --selftest  # autotest complet (configuration temporaire)
build.bat                          # installateur Windows (Inno Setup 6 requis)
```

- **Mac** : l'installateur `.dmg` est construit par le workflow GitHub « Installateur macOS ».
- **Fonds d'écran** : les fonds livrés sont générés par `tools/make_wallpapers.py`. Ce sont des créations originales, sans droit d'auteur tiers.
- **Pour contribuer** : les règles et les pièges connus sont dans `docs/CONSIGNES.md`.

Projet d'Alpha Oumar Diallo (@AlphoBakos) et Doura (@abdourahmanekaba).

## Droits

© 2026 Alpha Oumar Diallo et Doura. Tous droits réservés.

Le code est public pour être consulté. Il ne peut pas être copié, modifié, redistribué ni réutilisé dans un autre projet sans notre autorisation écrite. L'application peut être téléchargée et utilisée librement depuis les Releases.
