# Sims4ModTool

## Informations générales
- **Version de l'application :** v3.25
- **Dernière mise à jour :** 22/10/2025 10:19 UTC
- **Description :** utilitaire PyQt5 pour analyser, organiser et maintenir vos mods Sims 4.

## Fonctionnalités principales
- Analyse récursive du dossier de mods avec détection des paires `.package` / `.ts4script`.
- Estimation automatique de la colonne **Version** à partir de la dernière date connue du mod et de la table de sorties Sims 4.
- Marquage des mods ignorés (persisté dans `ignorelist.txt`) et filtres dynamiques configurables via plages de versions (sélection des patchs de départ et d'arrivée).
- Affichage sélectif des mods contenant des fichiers `.package` et/ou `.ts4script` grâce aux cases à cocher cumulables **Show Package** et **Show TS4Script**.
- Export des résultats au format Excel (`.xlsx`) avec conservation de toutes les colonnes visibles.
- Nettoyage guidé du cache Sims 4 via le bouton **Clear Sims4 Cache**.
- Sauvegarde et archivage horodaté des journaux (logs) vers le dossier de backups, avec ouverture automatique de l'emplacement et possibilité d'exclure certains fichiers par nom.
- Lancement direct de `TS4_X64.exe` avec arguments optionnels.
- Installation de mods par glisser-déposer via la fenêtre **Mod Installer**, avec journalisation des installations, mise à jour dédiée, ajout et suppression d'add-ons.
- Actions de l'interface dotées d'icônes (Rafraîchir, Exporter, Nettoyer cache, Récupérer logs, Mod Installer, Outils, Group View, Kill, Configuration, Lancer le jeu).
  - Boutons d'actions normalisés en taille et disposés en grille adaptative, avec icônes au‑dessus des libellés.

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

Un clic droit sur une ligne permet d'ignorer, d'ouvrir dans l'explorateur, de supprimer ou de lancer une recherche Google sur le mod sélectionné.

## Boutons de l'interface
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
  - Deleting mods is disabled while TS4_x64.exe is running (safety guard).
  - Kill Sims 4 attempts elevation on Windows when required (UAC prompt), with clear status.
  - Tools: “Correct resource.cfg” checks and fixes Mods\Resource.cfg to recommended defaults.
  - Column visibility: right‑click the table header to show/hide columns; preferences are saved and restored.
  - Top bar: Filters group (left) and Actions group (right) for quicker access to filters and actions.

- Duplicate Finder
  - Recursively scans subfolders; supports advanced mode by filename + size.
  - Progress bar and multi‑select delete.

- Logging
  - Central logging (console + `sims4modtool.log`) with configurable level in settings.

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
