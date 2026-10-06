# Politique de confidentialité de DeskMonitor

*Dernière mise à jour : 6 octobre 2026*

DeskMonitor est une application de bureau pour Windows et macOS, éditée par Alpha Oumar Diallo et Abdourahmane Kaba. Cette page explique quelles données l'application utilise, où elles vont, et comment garder le contrôle.

## En résumé

- **Nous ne collectons aucune donnée.** DeskMonitor n'a pas de compte utilisateur, pas de serveur à nous, pas de publicité et pas de statistiques d'utilisation.
- Vos réglages restent sur votre ordinateur, dans `%APPDATA%\DeskMonitor` sous Windows et `~/Library/Application Support/DeskMonitor` sous macOS.
- Certaines fonctions contactent des services en ligne. Elles sont toutes listées ci-dessous, et la plupart se désactivent.

## Ce qui reste sur votre ordinateur

| Fonction | Données | Conservées où |
|---|---|---|
| Monitoring (processeur, mémoire, disque, réseau, batterie) | Mesures de la machine | En mémoire seulement |
| Bureau organisé | Liste des applications installées et des fichiers du bureau | Sur l'ordinateur (cache local) |
| Assistant : ouvrir un fichier ou un dossier | Index des noms de fichiers de vos dossiers personnels | En mémoire seulement |
| Reconnaissance vocale | Le son du micro, analysé par le moteur de reconnaissance de Windows ou de macOS, **hors ligne** | Rien n'est enregistré, sauf le texte compris, écrit dans un journal local (`assistant.log`) |
| Journal d'erreurs | Messages d'erreur techniques | `erreurs.log`, sur l'ordinateur |

**Le micro** n'est utilisé que si vous parlez à l'assistant : raccourci clavier, ou « activation par la voix » si vous l'activez. Cette écoute continue est désactivée par défaut et se coupe dans Paramètres › Assistant.

## Services en ligne contactés

| Service | Quand | Ce qui est envoyé |
|---|---|---|
| **Microsoft (voix neuronales)**, service de lecture vocale de Microsoft Edge | Quand l'assistant parle avec une voix « neuronale » (réglage par défaut) | Le texte de la phrase à prononcer et votre adresse IP. Pour ne rien envoyer, choisissez une voix « naturelle » ou « classique » dans Paramètres › Assistant. |
| **Open-Meteo** (open-meteo.com) | Carte Météo | La ville choisie, ou des coordonnées approximatives, et votre adresse IP |
| **ipwho.is** | Carte Météo, seulement si aucune ville n'est indiquée | Votre adresse IP, pour situer la ville |
| **ipify, icanhazip, ifconfig.me** | Seulement si l'indicateur « IP publique » est affiché | Votre adresse IP |
| **Serveur du ping** (1.1.1.1 par défaut, modifiable) | Indicateur « Ping » | Un paquet de test réseau |
| **Votre agenda** (lien ICS que vous fournissez) | Carte Agenda, si vous avez saisi un lien | La requête vers le lien que vous avez indiqué |
| **GitHub** (github.com) | Recherche de mises à jour (version téléchargée sur GitHub, pas la version Microsoft Store) | Votre adresse IP et la version de DeskMonitor |
| **Microsoft Store** | Mises à jour de la version Store | Géré par Windows |

## Ce que l'assistant ouvre pour vous

Quand vous demandez une recherche (« cherche… ») ou un site, DeskMonitor ouvre votre **navigateur** sur la page demandée : Google, YouTube, Wikipédia… La suite relève de ce site et de votre navigateur.

## Signaler un problème

Le bouton « Signaler un problème » ouvre dans votre navigateur un formulaire GitHub pré-rempli : version, système et dernières erreurs, sans votre nom d'utilisateur. **Rien n'est envoyé tant que vous ne l'avez pas relu et validé vous-même.** Ce que vous publiez sur GitHub est alors public.

## Enfants

DeskMonitor ne s'adresse pas spécifiquement aux enfants et ne collecte aucune donnée personnelle.

## Contact

Pour toute question sur cette politique, ouvrez une demande dans l'onglet **Issues** du projet : https://github.com/AlphoBakos/DeskMonitor-App/issues
