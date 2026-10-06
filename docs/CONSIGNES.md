# Consignes pour reprendre DeskMonitor (versions 1.5.1 à 1.8.0)

Bonjour Doura,

Depuis ta 1.5.0, la branche `AK_Update` a reçu cinq mises à jour, de la 1.5.1 à la 1.8.0. Elles ont été faites et vérifiées sur Windows, et l'autotest passe aussi sur les deux runners Mac de GitHub (arm64 et Intel). Ce document résume ce qui a changé dans le code, les règles à respecter pour ne rien casser, et ce qu'il reste à vérifier sur un vrai Mac.

> **Le projet a déménagé dans un dépôt public : https://github.com/AlphoBakos/DeskMonitor-App**
>
> - Clone ce dépôt-là et travaille dessus. L'ancien dépôt privé `DeskMonitor` est gardé comme archive.
> - Le nouveau dépôt ne contient plus les fonds d'écran protégés (fan art). Ils sont remplacés par des fonds originaux générés par `tools/make_wallpapers.py`.
> - **N'ajoute jamais d'image protégée au dépôt public** : tout ce qui y entre devient visible par tout le monde, même si tu l'effaces ensuite.
> - Les mises à jour automatiques de l'application pointent maintenant vers ce dépôt (`update_repo`).
> - Les retours des testeurs arrivent dans l'onglet **Issues**, avec les étiquettes « problème » et « idée ». L'application ouvre ces formulaires pré-remplis depuis Paramètres › À propos.

## 1. Ce qui a changé

| Version | Contenu |
|---|---|
| 1.5.1 | Tes nouveautés (cartes, assistant, voix, fond vivant) adaptées à Windows : verre acrylique, voix OneCore, reconnaissance System.Speech, batterie et processus. |
| 1.5.x | L'assistant comprend son nom (« Bakos ») sans raccourci clavier, et « Ranger tout le bureau » aligne cartes et panneaux sans chevauchement. |
| 1.6.0 | Une seule apparence pour tous les widgets. Les paramètres sont réorganisés et n'ont plus de doublons. Les panneaux d'applications ont le style des cartes. |
| 1.7.0 | Animations et interactions : nouveau module `anim.py`. |
| 1.8.0 | L'assistant agit (ouvre des applications, dossiers et fichiers, fait des recherches) : nouveau module `actions.py`. Boutons d'action sur les cartes, voix neuronales, correction du fond vivant. |

## Où se trouve quoi (depuis le découpage de `desk_monitor.py`)

`desk_monitor.py` est passé de 3 000 à environ 1 300 lignes. La classe `DeskWidget` hérite des blocs déplacés : on appelle toujours `app.speak()`, `app.answer()`, etc., comme avant.

| Fichier | Contenu |
|---|---|
| `desk_monitor.py` | `DeskWidget` : construction des widgets, mesures, positions, boucles, menu ; démarrage (`main`). |
| `app_voice.py` | Voix : synthèse, récapitulatif parlé, annonces de ce qui passe dans le rouge. |
| `app_assistant.py` | Assistant : écoute, compréhension (`answer`), actions demandées (`_do_action`). |
| `app_wallpaper.py` | Fonds d'écran, écran de verrouillage, fond assorti, fond vivant. |
| `app_updates.py` | Mises à jour depuis GitHub. |
| `app_alerts.py` | Alertes et notifications. |
| `app_actions.py` | Actions d'entretien (cache, RAM, DNS…) et formulaires de retour GitHub. |
| `optimizer.py` | `Optimizer` : le nettoyage et l'optimisation proprement dits. |
| `process_window.py` | Fenêtre des processus gourmands. |
| `selftest.py` | Autotests (`--selftest`, `--wake-test`, `--speech-test`). |

- Pour une nouvelle méthode, choisis le module de son thème. Si un module importe un nom qui lui manque, `python -m pyflakes *.py` le signale.
- `tools/prune_imports.py` retire les imports devenus inutiles.

## 2. Règles à respecter

### Apparence : une seule palette

- Le thème `mac_theme` (auto / dark / light) et la couleur d'accent `accent_mode` (system / custom / wallpaper) décident des couleurs de **tous** les widgets.
- `DeskWidget._sync_palette()` (dans `desk_monitor.py`) recalcule à chaque `build()` les anciennes clés : `bg_color`, `text_color`, `bar_bg`, `warn_color`, `accent_color`, `clock_color`, `date_color`, `rounded`, `text_size`.
- **N'écris pas ces clés directement** : elles seraient écrasées au build suivant. Change `mac_theme`, `accent_mode` ou `accent_color` (en mode custom).
- Les panneaux d'applications (`organizer._fill`) reprennent la palette des cartes (`cm.fg`, `cm.sub`, `cm.track`, `cm.bg`) et le verre acrylique quand `card_blur` est actif.
- `card_system_accent` et `theme_auto_wallpaper` sont désormais dérivés de `accent_mode`. Ne les règle plus à la main.

### Paramètres (`settings_ui.py`)

- Pages : Apparence, Widgets, Heure et date, Applications, Fond d'écran, Écran de verrouillage, Assistant, Alertes, Profils, Général, À propos.
- Les pages « Monitoring » et « Cartes et fond vivant » n'existent plus. Leur contenu est réparti ailleurs :
  - le fond vivant est dans « Fond d'écran » ;
  - le raccourci et l'infobulle sont dans « Général » ;
  - les notifications natives sont dans « Alertes ».
- Un réglage ne doit exister qu'à **un seul** endroit. Utilise `cond=` pour ne l'afficher que dans la disposition concernée (`self.layout == "classic"`, etc.).
- Si une option fait apparaître ou disparaître d'autres réglages, ajoute sa clé à `RELAYOUT_KEYS` : la page se redessine alors automatiquement.

### Animations (`anim.py`)

- Un seul moteur, `app.anim`, avec une boucle à environ 60 images/s qui ne tourne que tant qu'une animation est en cours.
- Méthodes :
  - `play(clé, ms, étape, courbe, fin)` : une nouvelle animation de même clé remplace l'ancienne ;
  - `glide(fen, x, y)` : déplacement en douceur d'une fenêtre ;
  - `fade(fen, alpha)` : fondu ;
  - `appear(fen, délai)` : entrée en scène ;
  - `color(...)` : transition de couleur ;
  - `pos(fen)` : position d'arrivée d'une fenêtre en train de glisser.
- **Pendant un glissement, lis les positions avec `app.anim.pos(win)`, jamais avec `winfo_x()` seul.** `auto_layout` et `avoid_cards` le font déjà.
- Chaque carte a une méthode `frame()`, appelée à 30 images/s par `_cards_loop` : c'est là que vont les animations continues (trotteuse, courbe réseau, égaliseur).
- **Ne redessine que ce qui change.** Utilise `Card.fill(item, couleur)`, qui n'applique la couleur que si elle est différente, et le cache des traits de `Ring`. Recolorier les 48 traits d'une jauge à chaque image faisait monter DeskMonitor à 1,5 % de CPU au repos ; il est revenu à environ 0,1 %.
- L'autotest coupe les animations (`c["animations"] = False`) pour vérifier les positions tout de suite. Fais de même dans tes tests de positions.

### Cartes (`cards.py`) : nouvelles aides

- `self.chip("Libellé", lambda fin: …)` : bouton d'action qui apparaît au survol, en haut à droite. L'action appelle `fin(texte)` quand elle se termine, et le bouton affiche le résultat (« ✓ 1,2 Go »).
- `self.clickable(items, commande)` : zone cliquable. Exemple : la jauge CPU ouvre les processus.
- `self.button(item, commande)` : texte cliquable qui s'éclaire au survol.
- `self.count(item, clé, valeur, format)` : compteur animé.
- `self.swap_text(item, texte)` : changement de texte en fondu.
- **Les lambdas de `tag_bind` doivent avoir `e=None`.** Tk n'envoie pas toujours l'événement, et l'oubli provoque des TypeError intermittentes.

### Assistant : actions (`actions.py`) et reconnaissance Windows (`assistant.py`)

- `actions.parse(texte)` renvoie l'un des résultats suivants :
  - `("open", cible, "folder" | "file" | "any")` ;
  - `("search", requête, site)` ;
  - `None`.

  `DeskWidget._do_action()` exécute ensuite l'action, dans cet ordre :
  1. emplacements système (corbeille, Ce PC…) ;
  2. dossiers connus ;
  3. applications installées (`find_app`) ;
  4. sites web ;
  5. index des fichiers (`FileIndex`, reconstruit toutes les 10 minutes).
- Sous Windows, la liste des applications et des dossiers est donnée au moteur de reconnaissance sous forme de grammaire (`act_grammar_ps`). C'est ce qui permet de reconnaître « Excel » ou « téléchargements ». Ça a été vérifié avec des phrases réellement prononcées : 6 sur 6 reconnues, et une conversation ordinaire ignorée.
- Pièges System.Speech :
  - **un même `GrammarBuilder` ou `Choices` ne peut pas servir à deux grammaires**. C'est pour ça que `act_grammar_ps(..., sfx)` crée des copies avec des variables suffixées ;
  - les scripts PowerShell passent par un fichier `.ps1` en **UTF-8 avec BOM** (`assistant.run_ps`). Sinon les accents sont perdus et la ligne de commande dépasse 32 000 caractères ;
  - `EmulateRecognize` ne reflète pas le vrai comportement face à l'attrape-tout « other ». Teste avec de l'audio : une voix synthétisée en WAV, puis `SetInputToWaveFile`.
- À vérifier : dans la grammaire « wake », `$wb.Append($pre, 0, 1)` reçoit un `Choices`. PowerShell pourrait choisir la surcharge `Append(string, int, int)`, ce qui rendrait inopérants les préfixes « dis / hey / ok ». Ce n'est pas bloquant, puisque le préfixe est facultatif.

### Voix (`voice.py`)

- Les voix neuronales Microsoft passent par le paquet `edge-tts`. Leur nom de voix commence par `neural:` (par exemple `neural:fr-FR-VivienneMultilingualNeural`).
- Lecture des MP3 : MCI (`winmm`) sous Windows, `afplay` sous macOS.
- Sans internet, la voix bascule automatiquement sur la meilleure voix hors ligne (`offline_voice`) pendant 5 minutes.
- Les réponses courtes sont préparées au démarrage (`prefetch_voice`).
- Les erreurs vont dans `%TEMP%\deskmonitor-voix\erreurs.log`, qui sert aussi de cache.
- Confidentialité : chaque phrase dite par l'assistant est envoyée aux serveurs de Microsoft. C'est indiqué dans les paramètres. Garde cette mention si tu modifies la page.

### Fond vivant

- Quand tous les effets sont coupés, l'image d'origine (`wallpaper_last`) est remise. Avant, les jauges CPU / RAM / disque restaient figées dans l'image du fond d'écran.
- Le drapeau `wp_dyn_applied` indique qu'une image retouchée est actuellement au bureau.
- Une image déjà retouchée (`dyn-*.jpg`) ne sert jamais de base, sinon les jauges s'empilaient.

### Migrations

- `_migrate()` utilise un compteur `migrated`, qui vaut aujourd'hui 3 :
  - 1 : liste des noms appris nettoyée, écoute de nuit réactivée ;
  - 2 : `accent_mode` ;
  - 3 : voix neuronale et fond d'écran d'origine.
- Ajoute toujours la migration suivante **à la fin** (`< 4`), jamais avant les autres. Sinon les migrations plus anciennes sont sautées sur une nouvelle installation.

### Autres pièges connus

- **Pas de `WM_SETREDRAW` sur une fenêtre principale** : les widgets devenaient invisibles. `ensure_visible` corrige les fenêtres cachées par Windows.
- **`build.bat` doit garder des fins de ligne Windows (CRLF).** Sinon `cmd` le lit de travers (« 'thon' n'est pas reconnu… »). Un `sed -i` sous Git Bash les convertit en LF.
- Les tests ne doivent jamais modifier la vraie configuration (`%APPDATA%\DeskMonitor\config.json`). L'autotest utilise un dossier temporaire ; fais de même.

## 3. À vérifier sur un vrai Mac

L'autotest passe sur les runners Mac de GitHub, mais il ne remplace pas un essai sur une vraie machine.

1. **Animations sur les cartes natives** (`mac_native.style_card`) : entrée en cascade, survol lumineux, carte soulevée pendant le glisser, autres cartes qui s'écartent. Ces effets jouent sur `-alpha` et la position de la fenêtre. Vérifie que ça ne casse pas le flou natif.
2. **Boutons d'action des cartes** :
   - « Nettoyer » marche sur Mac (`clean_cache`).
   - « Libérer la RAM » répond simplement « Windows uniquement ». Il faudrait soit masquer le bouton sur Mac, soit trouver un équivalent.
   - « Vider le DNS » répond lui aussi « Windows uniquement ». Sur Mac, l'équivalent serait `dscacheutil -flushcache`, mais il demande les droits administrateur.
3. **Voix neuronale avec `afplay`** : vérifie aussi que `stop()` coupe bien la lecture en cours.
4. **Actions vocales sur Mac** :
   - Il n'y a pas de grammaire comme sous Windows : la phrase passe par la dictée de macOS. Vérifie que « ouvre Safari » et « cherche … » sont bien transcrits.
   - `find_app` cherche dans les applications listées par `_mac_apps()`, et `open_target` utilise `open`.
   - `known_folders()` lit les dossiers personnels standards (`~/Downloads`, `~/Documents`…).
5. **Fond vivant** : il faut couper les effets et vérifier que l'image d'origine revient sur tous les bureaux.

## 4. Construire et publier

- **Windows** : lancer `build.bat`. Il produit `Installateur\DeskMonitor-Setup-<version>.exe` et a besoin d'Inno Setup 6.
- **Mac** : lancer le workflow GitHub « Installateur macOS » (`.github/workflows/macos.yml`) sur la branche voulue. Il produit un `.dmg` arm64 et un `.dmg` Intel, après l'autotest.
- **Version** : elle se change à un seul endroit, `APP_VERSION` dans `core.py`.
- **Autotest** : `python desk_monitor.py --selftest`. Il doit finir sur « Aucune erreur ». Le rapport est écrit dans le fichier indiqué par `DM_SELFTEST_OUT`.
- **Dépendances ajoutées** : `edge-tts` (voix neuronales), déjà ajouté à `requirements.txt`, `build.bat` et `build_mac.sh`.

Bon courage, et merci pour les cartes et l'assistant : c'est une très bonne base.
