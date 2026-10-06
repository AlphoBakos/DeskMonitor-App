# Publier DeskMonitor sur le Microsoft Store

Ce guide explique comment publier la version MSIX de DeskMonitor sur le Microsoft Store. Avec cette version, le Store signe l'application gratuitement : plus d'avertissement « Windows a protégé votre ordinateur », et les mises à jour arrivent automatiquement.

## 1. Créer le compte (une seule fois)

1. Va sur https://storedeveloper.microsoft.com et crée un compte **Particulier** (Individual). C'est gratuit pour les particuliers.
2. Microsoft vérifie ton identité. Compte quelques jours.
3. Dans **Partner Center**, clique sur **Applications et jeux**, puis **Nouveau produit** et **Application MSIX ou PWA**. Réserve le nom **DeskMonitor**. S'il est déjà pris, essaie par exemple « DeskMonitor Widgets ».
4. Ouvre **Gestion des produits › Identité du produit** et recopie dans `installer/msix/identity.json` :
   - `Package/Identity/Name` → `name` ;
   - `Package/Identity/Publisher` → `publisher` (commence par `CN=`) ;
   - `Package/Properties/PublisherDisplayName` → `publisher_display`.

## 2. Fabriquer le paquet

```
build.bat
python tools/build_msix.py
```

Le fichier à envoyer est `Installateur\DeskMonitor-<version>.msix`.

Pour chaque nouvelle version : changer `APP_VERSION` dans `core.py`, refaire ces deux commandes, puis créer une nouvelle soumission dans Partner Center. Le Store refuse un numéro de version déjà envoyé.

## 3. La fiche du Store (textes à copier)

**Description courte :**
> Des widgets pour votre bureau : la machine en un coup d'œil, vos applications rangées et un assistant vocal qui agit pour vous.

**Description :**
> DeskMonitor transforme votre bureau en tableau de bord élégant.
>
> • Cartes façon widgets : heure, processeur et mémoire, stockage, réseau, batterie, météo, agenda, musique.
> • Actions en un clic : nettoyer le cache, libérer la mémoire, vider le cache DNS, voir les programmes qui ralentissent l'ordinateur.
> • Bureau organisé : vos applications rangées par thème dans des panneaux, sans déplacer aucun fichier.
> • Assistant vocal : « ouvre Chrome », « ouvre le dossier téléchargements », « cherche une recette », « fais le point ».
> • Verre dépoli, thème clair ou sombre, animations fluides, fonds d'écran originaux et écran de verrouillage personnalisé.

**Catégorie :** Utilitaires et outils.

**Captures d'écran :** utiliser celles de `docs/images/`. Le Store demande au moins une capture d'au moins 1366×768 : `bureau-sombre.png` et `bureau-clair.png` conviennent (1600×900).

**Politique de confidentialité (URL) :**
https://github.com/AlphoBakos/DeskMonitor-App/blob/main/docs/confidentialite.md

**Âge :** remplir le questionnaire IARC. DeskMonitor n'a ni contenu sensible ni échanges entre utilisateurs.

## 3 bis. La fiche en anglais (English listing)

Depuis la 1.9.1, l'interface existe aussi en anglais, et le paquet déclare les deux langues. Partner Center demande donc aussi une fiche **English (United States)**. Pour l'ajouter : Descriptions dans le Store › Ajouter/supprimer des langues › English (United States).

**Description :**
> DeskMonitor turns your desktop into a sleek dashboard.
>
> • Widget-style cards: clock, processor and memory, storage, network, battery, weather, calendar, music.
> • One-click actions: clean the cache, free up memory, flush the DNS cache, see which programs slow your computer down.
> • Organized desktop: your apps grouped by theme into panels, without moving a single file.
> • Voice assistant: "open Chrome", "open the downloads folder", "search for a recipe", "give me a summary".
> • Frosted glass, light or dark theme, smooth animations, original wallpapers and a custom lock screen.
> • Available in English and French.

**Description courte :**
> Widgets for your desktop: your computer at a glance, your apps organized and a voice assistant that gets things done.

**Fonctionnalités (une par ligne) :**
> Widget-style monitoring cards
> One-click cache cleanup and memory release
> Organized desktop: apps grouped by theme
> Voice assistant that opens apps, folders and web searches
> Light or dark theme, glass effect, smooth animations

**Captures d'écran :** `docs/images/en/` (`desktop-dark.png`, `actions.png`, `desktop-light.png`, `settings.png`).

**Logos :** les mêmes que la fiche française (`docs/store/`).

## 4. Justifier les « fonctionnalités restreintes »

Partner Center demande pourquoi l'application utilise des fonctionnalités restreintes. Voici les textes à copier.

**runFullTrust :**
> DeskMonitor est une application de bureau classique (Win32, Python) : elle affiche des widgets sur le bureau, lit les mesures du système (processeur, mémoire, disque, réseau, batterie) et range les raccourcis d'applications dans des panneaux.

**unvirtualizedResources :**
> DeskMonitor modifie à la demande de l'utilisateur des réglages de Windows : fond d'écran, écran de verrouillage, format de l'horloge, affichage des icônes du bureau. Il garde sa configuration dans %APPDATA%\DeskMonitor, partagée avec la version téléchargeable. Ces écritures doivent atteindre le vrai registre et les vrais dossiers de l'utilisateur, sinon elles n'auraient aucun effet.

**Micro :**
> Commandes vocales de l'assistant, reconnues hors ligne par le moteur de Windows. L'écoute continue est désactivée par défaut.

## 5. Différences avec la version téléchargeable (GitHub)

- **Mises à jour :** la version Store ne cherche pas de mise à jour sur GitHub. Le bouton « Vérifier maintenant » ouvre le Store.
- **Lancement au démarrage :** la version Store passe par la « tâche de démarrage » du paquet. Elle reste désactivée tant que l'utilisateur ne l'active pas, comme le veulent les règles du Store.
- Le bouton « Relancer en administrateur » est masqué.
- Le code détecte la version Store avec `core.is_packaged()`.

## 6. Essayer le paquet avant de l'envoyer

1. Active le **mode développeur** : Paramètres › Système › Espace développeurs.
2. Ferme DeskMonitor s'il tourne.
3. Lance :
   ```
   python tools/build_msix.py --layout
   powershell Add-AppxPackage -Register build\msix\AppxManifest.xml
   ```
4. Lance DeskMonitor depuis le menu Démarrer.
5. Pour le retirer : `powershell "Get-AppxPackage *DeskMonitor* | Remove-AppxPackage"`.

Le **Kit de certification des applications Windows** (`appcert.exe`, installé avec le Windows SDK) fait passer au paquet les mêmes tests que le Store, avant l'envoi.
