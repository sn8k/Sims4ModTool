# Sims4ModTool

## Informations générales
- **Version de l'application :** v3.40.1
- **Dernière mise à jour :** 27/10/2025
- **Description :** utilitaire PyQt5 pour analyser, organiser et maintenir vos mods Sims 4.

## Fonctionnalités principales
- Analyse récursive du dossier de mods avec détection précise des paires `.package` / `.ts4script` (prise en compte des suffixes de version, ex. `_V1.23`). Le seuil de similarité plus strict et une garde sur les noms très courts réduisent les faux positifs; les `.ts4script` seuls sont listés correctement.
- Colonne **Version**: extraction de la version explicite depuis le nom du fichier lorsqu’elle est présente (sinon estimation à partir de la table des patchs Sims 4). Lors d’une installation, si aucune version n’est détectée, la version du jeu la plus proche (selon la date du fichier) est proposée par défaut.
- Marquage des mods ignorés (persisté dans `ignorelist.txt`) et filtres dynamiques configurables via plages de versions (sélection des patchs de départ et d'arrivée).
- Affichage sélectif des mods contenant des fichiers `.package` et/ou `.ts4script` grâce aux cases à cocher cumulables **Show Package** et **Show TS4Script**.
- Export des résultats au format Excel (`.xlsx`) avec conservation de toutes les colonnes visibles.
- Nettoyage guidé du cache Sims 4 via le bouton **Clear Sims4 Cache**.
- Sauvegarde et archivage horodaté des journaux (logs) vers le dossier de backups, avec ouverture automatique de l'emplacement et possibilité d'exclure certains fichiers par nom.
- Lancement direct de `TS4_X64.exe` avec arguments optionnels. Un indicateur d’état affiche si le jeu est en cours d’exécution sur l’interface principale.
- Archives .zip/.7z/.rar: extraction normalisée (temporaire) avec .ts4script qui définit la racine, puis copie vers Mods.
- Installateur ZIP (règles Mod Root): extraction déterministe des archives ZIP hétérogènes avec détection de la racine du mod (FLAT / SINGLE_DIR / MIXED), copie uniquement des `.package` et `.ts4script` par défaut et conservation de l’arborescence relative sous Mods/.
  - Dans la fenêtre Mod Installer, un bouton Settings permet d’activer/désactiver la logique Mod Root et l’inclusion des fichiers non essentiels.
  - Un "Plan d’installation" s’affiche avant copie: possibilité d’ajuster le dossier destination, de choisir la racine (pour les archives MIXED) et de décider d’inclure les extras ; la saisie version/URL intervient après validation.
  - Tableau du Mod Installer: colonnes redimensionnables (mode interactif), colonne URL déplacée en dernière position, indicateur Add-ons sous forme de case à cocher (lecture seule).
- Outils visibles directement sur la fenêtre principale dans un panneau "Tools" à droite du panneau "Actions".
  - Nouveau: Log Manager — sélection d’un fichier log (`.log`, `.txt`, `.html`) avec affichage texte, filtre (mot-clé/regex, casse), recherche incrémentale et bouton d’analyse.
    - Analyse dédiée des rapports MCCC Last Exception (`mc_lastexception.html`) : extraction du type d’exception, message, chemins impliqués et détection heuristique du mod probable (dossier sous `Mods/`). Le titre de la fenêtre affiche la version du jeu détectée.
    - Bouton « Analyser dossier… » pour analyser récursivement un dossier de logs (ex.: `./logs`) et consolider les résultats (avec résumé détaillé).
    - Bouton « Entrainer IA (ce log) » pour alimenter le modèle directement depuis le log (ou le dossier) analysé.
  - Conflict Checker — détecte les résidus d’anciennes versions d’un même mod (ex.: foo_v1.2.ts4script et foo_v1.3.ts4script) et propose de supprimer les plus anciens après confirmation.
  - Updates Checker — vérifie les mises à jour de l’intégralité des mods présents dans le dossier Mods (pas uniquement ceux installés via Mod Installer), en se basant par défaut sur la feuille publique « Mod List Checker » (Google Sheets CSV) de Scarlet's Realm.
    - Source par défaut: `https://docs.google.com/spreadsheets/d/e/2PACX-1vRexBc8fcYyfsjbGRo3sH18jj9DuwKH8J7_SvQvpK_fvjsnILKRz1xGOwYz-xtG0wIKQcs1eDN1yw9V/pub?gid=119778444&single=true&range=A:I&output=csv`
    - Clé de configuration pour surcharger: `updates_checker_csv_url` dans `settings.json`.
    - Fallback automatique sur l’index TS4ModHound si la feuille CSV est indisponible.
    - Parsing de dates étendu (ex.: « Jul 2, 2025 ») pour une comparaison fiable « distant vs local ».
- Fonction IA (expérimentale) — lorsqu’elle est activée dans la Configuration, l’application apprend des scans (noms, fichiers, chemins) pour mieux comprendre/associer les mods. Le Log Manager affiche une colonne « IA Mod (conf.) » suggérant le mod le plus probable.
  - Entrainement A.I. — bouton dans Tools pour lancer manuellement l’apprentissage. L’entraînement ignore les filtres UI et construit un jeu de données non filtré depuis le dossier Mods, puis apprend aussi depuis les logs (.log/.txt/.html + extensions configurées). Une fenêtre dédiée affiche l’état en temps réel (progression) et un résumé final (comptes, top tokens/mods). Le modèle est sauvegardé à la fin.
- Filtre additionnel: "Masquer Mod Installer" pour cacher les mods installés via l’Installer.
  - Nouvelle colonne "Installer" (✓) pour distinguer visuellement les mods installés via le Mod Installer.
- Actions de l'interface dotées d'icônes (Rafraîchir, Exporter, Nettoyer cache, Récupérer logs, Mod Installer, Outils, Group View, Kill, Configuration, Lancer le jeu).
  - Nouveau: bouton "Ouvrir Mods" dans Actions pour ouvrir le dossier des mods dans l'explorateur de fichiers.
  - Boutons d'actions normalisés en taille et disposés en grille adaptative, avec icônes au‑dessus des libellés.
  - La taille des icônes des actions s’ajuste automatiquement selon l’espace disponible afin de préserver l’aire du tableau.
- Personnalisation : fond d'écran de l'application et fond du SplashScreen configurables dans **Configuration**.
  - Opacité des cadres: le curseur d’opacité n’affecte plus la fenêtre entière mais les cadres (panneaux, tables, en‑têtes). Le fond d’écran reste net derrière des panneaux translucides.
  - SplashScreen: titre abaissé et police plus "gothic" (si disponible) pour un style plus affirmé. Le fond d’écran personnalisé du Splash est correctement affiché (dégradé semi‑transparent par‑dessus).
  - Protected : possibilité de marquer un mod comme Protected (tableau principal et Mod Installer). Les mods Protected s'affichent en texte noir sur fond rose et requièrent une confirmation avant mise à jour.

## Nouveautés v3.40
- Log Manager: analyse spéciale MCCC, filtre/recherche, et intégration IA optionnelle.
- IA: apprentissage léger des mods (activable dans Configuration) + entraînement automatique lors des scans.
- Correctif: le scan de démarrage est différé pour laisser l’arrière‑plan de la fenêtre s’afficher avant l’analyse.
- Entrainement A.I.: popup d’information à l’ouverture, fenêtre dédiée avec progression en temps réel, logs détaillés et sauvegarde du modèle.
- UI: la barre du bas affiche "AI Mode Activated" lorsque l’IA est activée et chargée.
- L’entraînement IA ignore les filtres d’affichage: il construit son propre jeu de données (mods + logs) depuis le disque.
- Log Manager: ajoute un Résumé détaillé (top exceptions, top mods via IA, top fichiers) après chaque analyse.

## Prérequis
- Python 3.9 ou supérieur.
- Dépendances Python :
  - `PyQt5`
  - `openpyxl`
- Système supportant l'ouverture d'un gestionnaire de fichiers via `os.startfile`, `open` (macOS) ou `xdg-open` (Linux).

Installez les dépendances avec :
```bash
pip install PyQt5 openpyxl
```

## Démarrage rapide
1. Clonez le dépôt puis placez-vous dans le dossier racine :
   ```bash
   git clone <url>
   cd Sims4ModTool
   ```
2. Lancez l'application :
   ```bash
   python main.py
   ```

### Interface Web

Une interface Web est disponible pour consulter vos mods, appliquer des filtres, ignorer des mods, exporter vers Excel et installer des archives (.zip/.7z/.rar/.ts4script/.package). Par défaut, le serveur Web démarre automatiquement au lancement de l'application sur `http://127.0.0.1:5000/` (paramétrable via settings: `web_enabled`, `web_host`, `web_port`, `web_debug`).

1. Installer les dépendances (incluant Flask) :
   ```bash
   pip install -r requirements.txt
   ```
2. Démarrer manuellement (optionnel) :
   ```bash
   python webapp.py
   ```
3. Ouvrez votre navigateur sur http://127.0.0.1:5000/.

Notes:
- Le serveur lit et écrit `settings.json` (dossier des mods, préférences de filtres, liste ignorés).
- Le bouton d'installation accepte `.zip`, `.7z`, `.rar`, `.ts4script` et `.package` (Mod Root appliqué pour les archives lorsque possible; 7‑Zip requis pour .7z/.rar).
- Le bouton "Export" télécharge un fichier `.xlsx` avec la table courante.

### Installation de ZIP en ligne de commande (mod root)

Un utilitaire en ligne de commande est fourni pour installer une archive ZIP dans `Mods/` en respectant des règles déterministes de « mod root ».

```bash
python zip_installer_cli.py chemin/vers/mon_mod.zip --mods-root "C:\\Users\\<vous>\\Documents\\Electronic Arts\\Les Sims 4\\Mods"
```

Options:
- `--include-extras` : copie aussi les fichiers non essentiels (readme/images/docs). Par défaut seuls les `.package` et `.ts4script` sont installés.
- `--log DEBUG` : affiche les logs détaillant le type d’archive (FLAT/SINGLE_DIR/MIXED), le mod root choisi, la destination et la liste des fichiers installés.

Règles appliquées:
- FLAT: si des fichiers utiles sont à la racine de l’archive → extraction vers `Mods/<NomArchiveNettoyé>/` en conservant l’arborescence relative.
- SINGLE_DIR: si un seul dossier top‑level contient tous les fichiers utiles → extraction directe sous `Mods/<NomDuDossier>/` (pas de couche `<NomZip>/`).
- MIXED: s’il y a plusieurs dossiers top‑level → choix heuristique du dossier contenant le plus de fichiers utiles (égalité brisée par la profondeur médiane la plus courte), puis extraction vers `Mods/<NomArchiveNettoyé>/` en conservant l’arborescence relative depuis ce dossier.

Sécurité:
- Aucune traversée de chemin (..), aucun chemin absolu.
- Fichiers bruits ignorés (`__MACOSX/`, `Thumbs.db`, `.DS_Store`).

Formats pris en charge
- `.zip` (direct)
- `.7z`/`.rar` via 7‑Zip: extraction temporaire puis application des mêmes règles Mod Root.

### Outils
- Comparateur de mods: sélectionnez deux dossiers de mods et comparez les différences:
  - Fichiers `.package` (taille et hash) et `.ts4script` (taille et hash)
  - Contenu interne des `.ts4script` (noms, tailles, CRC)
  - Compteurs (packages, ts4scripts, entrées internes) et add-ons (depuis le marqueur si présent)
  - Utile pour identifier les changements entre une version patchée et non patchée d’un mod.


## Paramétrage initial
Ouvrez la fenêtre **Configuration** pour définir :
- Le dossier principal des mods.
- Le dossier cache des Sims (`localthumbcache.package`, etc.).
- Le dossier de backups où seront copiés les logs.
- Le chemin complet vers `TS4_X64.exe` ainsi que les arguments additionnels éventuels.
- Les extensions supplémentaires de journaux à inclure lors de l'extraction (en plus de `.log` et `.txt`).
- Les fichiers de logs à ignorer lors de la collecte.
- Les versions de patch disponibles pour le filtrage (affichage de la liste et ajout via le bouton **Add update info**).

Les paramètres sont enregistrés dans `settings.json` dès la sauvegarde de la fenêtre.

## Lecture du tableau des mods
La table principale affiche une ligne par mod détecté avec les colonnes suivantes :
1. **État** — `X` si un duo `.package`/`.ts4script` est présent, `MS` lorsqu'il manque le `.ts4script`, `MP` lorsqu'il manque le `.package`.
2. **Fichier .package** et **Date .package**.
3. **Fichier .ts4script** et **Date .ts4script**.
4. **Version** — estimée grâce à la date la plus récente du mod et aux informations de patch connues (ex. un fichier daté du 10/10/2025 sera associé au patch `1.118.257.1020`).
5. **Ignoré** — cochez pour masquer un mod lors des prochains scans (persisté dans `ignorelist.txt`).

Un clic droit sur une ligne permet d'ignorer, d'ouvrir dans l'explorateur, de supprimer ou de lancer une recherche Google/Patreon sur le mod sélectionné.

## Boutons de l'interface\n- Informations jeu : affichage Version/Build en bas au centre (issu de config.log si présent).
- **Analyser / Rafraîchir** : relance le scan du dossier de mods configuré.
- **Exporter vers Excel** : crée ou met à jour le fichier `.xlsx` choisi.
- **Clear Sims4 Cache** : supprime les fichiers/dossiers de cache connus et affiche un compte rendu.
- **Grab Logs** : déplace les fichiers journaux trouvés dans le dossier des mods vers un sous-dossier horodaté du dossier de backups.
- **Launch Sims 4** : exécute `TS4_X64.exe` avec les arguments configurés (bouton désactivé si le chemin est invalide).
- **Kill Sims 4** : termine le processus `TS4_x64.exe` en cours d'exécution.
- **Mod Installer** : ouvre une fenêtre listant les mods installés via l'outil, accepte le glisser-déposer de fichiers `.package`, `.ts4script` ou `.zip`, gère la mise à jour ou l'ajout d'add-ons pour un mod existant et range automatiquement les fichiers dans des sous-dossiers dédiés du dossier de mods.

Astuce: clic droit sur l'en-tête de la table du Mod Installer pour choisir quelles colonnes afficher/masquer (préférences mémorisées).
Au bas de la fenêtre, la version et le build du jeu (si disponibles) sont affichés, lus depuis `config.log` dans le dossier de caches.

## Gestion des journaux
Les fichiers dont l'extension correspond à `.log`, `.txt` ou toute extension supplémentaire configurée sont déplacés dans un dossier nommé `Logs_YYYYMMDD_HHMMSS` sous le dossier de backups (sauf ceux dont le nom figure dans la liste d'exclusion configurée). L'arborescence relative depuis le dossier de mods est conservée et l'explorateur est ouvert automatiquement à la fin de l'opération.

## Nettoyage du cache Sims 4
Le bouton **Clear Sims4 Cache** supprime :
- `localthumbcache.package`
- `localsimtexturecache.package`
- `avatarcache.package`
- Le dossier `cachestr`
- Le dossier `onlinethumbnailcache`

Une boîte de dialogue récapitule les éléments supprimés, absents ou en erreur.

## Export Excel
Le fichier Excel généré contient l'intégralité des colonnes visibles, y compris la colonne **Version** et l'état `Ignoré`. Vous pouvez sélectionner un fichier cible lors du premier export ; le chemin est ensuite mémorisé.

## Dépannage
- Vérifiez que les chemins configurés existent réellement et que vous disposez des droits nécessaires.
- En cas de lancement du jeu impossible, assurez-vous que `TS4_X64.exe` est présent et que les arguments saisis sont valides.
- Pour réinitialiser les préférences, supprimez `settings.json` et `ignorelist.txt` (ils seront recréés au prochain lancement).

## Licence
Ce projet est fourni tel quel pour un usage personnel. Adaptez-le selon vos besoins.
# Sims 4 Mod Manager (Sims4ModTool)

Recent updates:

- Mod Installer
  - Writes a per‑mod marker file `.s4mt_mod_marker.json` on install/update/add‑ons.
  - Recovery list: scans Mods folder to rebuild installed list from markers.
  - ZIP extraction now preserves internal folders and filenames, keeping original timestamps.
  - Added support for `.7z` and `.rar` extraction using 7‑Zip if available.

- GUI
  - New Group View dialog (tree) to collapse/expand rows by mod group.
  - Table highlights rows installed via Mod Installer (green background, white text).
  - Search: "Afficher recherche" et "Instant search" en ligne 1; étiquette, zone de saisie et bouton "Rechercher" en ligne 2.
  - File filter dropdown: Show both / Show Package / Show TS4Script / Mod Installer Only.
  - Auto-scan on startup: configurable in settings (enabled by default). When enabled, the app scans the Mods folder at launch.
   - Startup splash screen now features a gradient background and a plumbob-like diamond.
   - Configuration dialog reorganized and enlarged for easier navigation.
   - Added icons to action buttons.
   - Action buttons normalized and arranged in an adaptive grid; bottom buttons are smaller; bottom center shows Version/Build (from caches).
  - Toutes les opérations sensibles (scan, installation, suppression, export) sont bloquées lorsque TS4_x64.exe est en cours d’exécution (message d’attente affiché). Indicateur d’état en bas de fenêtre.
  - Kill Sims 4 attempts elevation on Windows when required (UAC prompt), with clear status.
  - Tools: “Correct resource.cfg” checks and fixes Mods\Resource.cfg to recommended defaults.
  - Column visibility: right‑click the table header to show/hide columns; preferences are saved and restored.
   - Top bar: Filters group (left) and Actions group (right) for quicker access to filters and actions.

- Tools additions:
  - Find in ts4script: recherche à l’intérieur des archives `.ts4script` (ZIP) d’un dossier. Entrez un ou plusieurs noms de fichiers (wildcards autorisés, séparés par espace/virgule/point‑virgule). Le résultat s’affiche dans un tableau sans filtres (fonctionnement « Show both ») avec les colonnes: « occurence » (entrée trouvée dans l’archive), « filename » (nom du `.ts4script`), « chemin » (chemin du fichier), « date » (date de modification). Inclut une barre d’avancement, un menu contextuel sur les lignes et un menu de colonnes sur l’en‑tête.
  - Check placement .ts4script: vérifie que les scripts `.ts4script` ne sont pas à plus d'un sous‑dossier de profondeur sous Mods; affiche une liste des contrevenants, ou un message "Tout va bien, tout le monde est à sa place 👍" si conforme.
  - Scan dossier (mod) : choisissez n'importe quel dossier à analyser (option « Récursif » cochée par défaut) et affichez les résultats dans un tableau.
  - L’outil consigne en debug les contrevenants et publie un résumé en niveau warning.
 - Mod Installer:
   - À la fin d’une installation ou d’une mise à jour, une fenêtre propose de renseigner la version et l’URL du mod (champs optionnels; valeurs vides acceptées).
   - La fenêtre Mod Installer est redimensionnable (bouton maximiser et poignée de redimensionnement).
   - Ajouter des add‑ons affiche maintenant le dossier du mod maître dans la boîte de dépôt.
   - Correction: le champ « Type » affiche correctement « archive .7z » ou « archive .rar » pour les archives correspondantes.
- Duplicate Finder
  - Recursively scans subfolders; supports advanced mode by filename + size.
  - Progress bar and multi‑select delete.
  - Fix: crash at launch due to missing `_run_scan` in dialog.
## Internationalisation
- Fichiers de langue prêts sous `lang/` : `fr-fr.lng` et `en-us.lng`. Format JSON clé/valeur pour les titres, actions, filtres, outils et apparence.
- Sélection de la langue (fr-FR / en-US) dans **Configuration**.

- Logging
  - Central logging (console + `sims4modtool.log`) with configurable level in settings.
  - Debug étendu (mise en page des actions, SplashScreen, lecture Version/Build, outils), avec un usage cohérent de info/warn/error.

Requirements for 7z/rar:

- Install 7‑Zip and ensure `7z` is in PATH (or installed under `C:\Program Files\7-Zip\7z.exe`).

Notes:

- Grouping relies on Mod Installer tracking of installed files, so files added outside the installer won’t be grouped unless a marker exists.
- Tools
  - Added placeholders: "Symlink Mods" and "Backup Mods" in Tools dialog.

Build

- Use the provided PowerShell script to build an executable with PyInstaller:
  - `powershell -ExecutionPolicy Bypass -File .\build.ps1`
  - Options: `-OneFile`, `-NoConsole`, `-Name <AppName>`, `-Icon <path.ico>`
  - Requires Python and PyInstaller. The script installs PyInstaller if missing.

- Alternatively, from Windows CMD, run:
  - `build.bat`

Notes:
- If `version_release.json` exists, it is bundled via `--add-data`.
- Output is written to the `dist` folder.
- To avoid multiple Qt bindings conflicts, the build scripts exclude `PySide6`, `PySide2` and `PyQt6` because the app targets `PyQt5`.





