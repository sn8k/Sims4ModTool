Changelog

v3.47.0 (2025-11-01)

- ID Conflict Viewer
  - Outil migré vers `modules/id_conflict_viewer.py` avec interface modernisée, coloration par sévérité, icônes dédiées et tri hiérarchisé des conflits critiques.
  - Nouveaux filtres dynamiques (catégorie de ressource, niveau de sévérité, plages de dates, mots-clés dont WickedWhims/Basemental, présence de `.ts4script`) et surcouches statistiques.
  - Boutons d’actions : désactivation en masse des mods conflictuels, génération d’un fichier `load_order_suggestion.json`, vérification de compatibilité (versions installées vs patchs récents) et export Excel enrichi.
  - Journalisation alignée sur le logger principal (`Sims4ModTool`) et respect du paramétrage INFO/DEBUG.
- Intégration
  - Nouveau helper `open_id_conflict_viewer` dans `main.py` pour lancer la boîte de dialogue depuis l’interface ou les scripts externes.
  - Mise à jour du numéro de version d’application et de la documentation utilisateur (README).

v3.46.0 (2025-11-01)

- Find in ts4script
  - Dialogue extrait de `main.py` vers `modules/ts4script_search.py` pour clarifier l’architecture et faciliter la maintenance.
  - Interface modernisée : groupe de paramètres, bouton d’accès direct au dossier Mods, remise à zéro rapide, panneau de détails et actions (copie, ouverture, suppression) accessibles depuis un menu contextuel.
  - Boutons natifs réduire/maximiser/fermer rétablis sur la barre de titre et hauteur minimale ajustée pour un affichage confortable.
- Journalisation
  - Le module `ts4script_search` utilise désormais `logging.getLogger("Sims4ModTool.Ts4ScriptSearch")` et respecte le niveau configuré dans `main.py` (INFO/DEBUG).

v3.45.0 (2025-10-31)

- Log Manager
  - Outil entièrement extrait dans `modules/log_manager.py` : architecture dédiée pour l’analyse et la surveillance des journaux.
  - Nouvelle interface: sélection simultanée des dossiers Mods/Cache (plus dossiers personnalisés), filtrage par plage date/heure, liste multi-sélection et aperçu combiné.
  - Résultats enrichis avec gravité, mods suspects, suggestions d’actions et export direct en `.xlsx`.
  - Barre de titre modernisée : icônes Windows (réduire/maximiser/fermer) natives et suppression du bouton « Déduire les regroupements (IA) » (toujours accessible via Group View).
  - Journalisation dédiée alignée sur le niveau global (INFO ↔ DEBUG) pour suivre scans, analyses et alertes temps réel.
  - Recherche de scripts `.ts4script` assistée par l’IA : lorsqu’un mod est cité sans fichier, les prédictions TF-IDF complètent automatiquement les chemins manquants.
- Logs IA & diagnostics
  - L’IA apprend désormais des journaux `.log/.html/.txt`, privilégie le classifieur TF-IDF et propose des recommandations contextualisées.
  - Auto-train optionnel depuis les analyses de logs et mise à jour des overrides IA côté Mod Manager.
- Surveillance temps réel
  - Ajout d’un watcher (watchdog) qui alerte l’utilisateur dès qu’un nouveau log est généré pendant la session de jeu.

v3.44.2 (2025-10-31)

- UI
  - Correctif de démarrage: le fond personnalisé (`background_image_path`) est réappliqué via un timer `singleShot` dès l’ouverture de la fenêtre, sans devoir repasser par la configuration.
  - Palette sombre restaurée pour les boutons (QPushButton/QToolButton) afin de résoudre l’affichage « texte blanc sur fond blanc » introduit précédemment.

v3.44.1 (2025-10-31)

- UI
  - Le fond d’écran personnalisé configuré via `background_image_path` est appliqué dès le lancement (palette dédiée + fallback sombre lorsque l’image est absente).
  - Group View adopte un thème sombre cohérent (alternance foncée, surlignage lisible) et force la confiance à **100 %** sur les mods installés via Mod Installer.
- Groupes (AI)
  - « Reconstruire Groupes (AI) » n’exploite plus les logs mais inspecte directement les fichiers `.package` / `.ts4script` : détection des paires `foo.package` + `foo.ts4script`, regroupement par préfixes entre crochets (`[NF]_foo`) et scripts isolés comme groupes autonomes.
  - Les overrides générés sont persistés dans `settings.json` (clé `ai_group_overrides`) et déclenchent un rafraîchissement immédiat de la table principale.

v3.42.0 (2025-10-30)

- Entrainement IA
  - Nouvelle interface avec options avancées: sélection des sources (Mods, Logs, Index Updates Checker), moteur d’entrainement (Basique vs TF‑IDF/LinearSVC) et paramètres ML (split de validation, max features, n‑grammes).
  - Calcul de métriques lorsque le classifieur est activé (accuracy, F1 macro) et affichage d’un résumé clair (compteurs, vocabulaire, top tokens, top mods).
  - Le bouton « Annuler » devient « Terminer » en fin d’entrainement.
  - Export du résumé vers un fichier texte.
- Prédiction IA
  - La prédiction préfère désormais automatiquement le modèle TF‑IDF entraîné (si présent), avec repli sur le vote par tokens.
- Groupes (non‑Installer)
  - Quand aucun marqueur Mod Installer n’est présent, les lignes sont désormais regroupées par nom de fichier (base normalisée) plutôt que par dossier de tête, afin d’éviter que des dossiers hétérogènes ne fusionnent plusieurs mods distincts.
- Configuration
  - Section « Intelligence Artificielle »: activer/désactiver l’IA, auto‑train au démarrage et choisir le chemin du modèle JSON.
- Dépendances
  - Ajout (optionnel): `scikit-learn` et `joblib` pour le classifieur TF‑IDF (la voie Basique reste disponible sans dépendances supplémentaires).

v3.41.3 (2025-10-30)

- Tests
  - Ajout de tests automatisés pour la fonction « Analyser / Rafraîchir »:
    - `tests/test_analyser_refresh.py` vérifie que le moteur de scan retourne des lignes attendues sur un dossier Mods factice et que la GUI remplit la table après un scan en arrière‑plan.
  - Script de debug `scripts/dev_debug_refresh.py` pour reproduire rapidement un scan en mode headless.
- Docs
  - README: section « Tests » ajoutée avec les commandes pour exécuter les tests PyTest.
 - Logs & Perf
   - `scan_directory`: logs de début/fin avec nombre d’éléments et durée.
   - `generate_data_rows`: logs de début couplage (packages/scripts), résumé d’appariement (matches restants), et fin (lignes générées, durée, état du snapshot).
   - `save_mod_scan_cache`: log « Writing cache… » + « Cache written… » avec taille/temps; notification UI « Écriture du cache… » pendant l’opération.
   - Au démarrage: log de la date/heure de dernière modification de `mod_scan_cache.json`, sa taille et le nombre d’entrées si présent.

v3.41.2 (2025-10-30)

- GUI
  - Correction: les résultats du scan s’affichent de nouveau correctement, même si la recherche instantanée est désactivée (rendu forcé après scan).
  - Quand l’option « Scan au démarrage » est désactivée, la liste des mods est automatiquement remplie à partir de mod_scan_cache.json pour garantir un affichage immédiat.
  - Le bouton « Kill Sims 4 » est déplacé en bas de la fenêtre.
  - Le bouton « Kill Sims 4 » est redimensionné pour correspondre à « Configuration » et « Launch Sims 4 ».
  - Tous les dialogues/fenêtres (hors boîtes d’alerte) sont désormais redimensionnables (grip + maximisation activés).
- Cache Sims 4
  - Le bouton « Analyser / Rafraîchir » n’exécute plus de « clear sims4 cache ».
  - Le cache n’est vidé automatiquement qu’après une modification effective (ex: installation via Mod Installer), conformément à la règle générale.
- AI
  - L’entraînement IA inclut désormais l’index CSV de l’Updates Checker (liste publique), améliorant la couverture des mods connus.
- Log Manager / Group View
  - Le bouton « Reconstruire Groupes (AI) » est déplacé dans la vue Group View, pour centraliser les actions de regroupement.
 - Tools (modules)
   - Nouveau dossier `modules`: tous les outils externes placés ici sont détectés automatiquement et ajoutés au panneau Tools (format simple: `get_tools(app)` ou `register_tools(app)`).
 - Log Manager
   - Bouton « Entrainer IA (ce log) » supprimé.
 - Mod Installer
   - Correction: l’installation d’archives 7z/rar fonctionne de nouveau (bug d’import des helpers corrigé).
v3.41.0 (2025-10-29)

- Scan & UI
  - Le scan principal s’exécute désormais en arrière‑plan via QThread: l’UI ne se fige plus pendant l’analyse. La barre d’avancement et le compteur sont mis à jour en direct.
  - Accélération des scans: collecte des métadonnées fichiers (os.stat) parallélisée avec ThreadPoolExecutor. Gain notable sur les grands dossiers Mods.
  - Résultats et filtres inchangés; uniquement des améliorations de performance et de réactivité.

v3.40.4 (2025-10-29)

- Conflict Checker
  - Evite les faux positifs entre `.package` et `.ts4script` en groupant par extension. Les anciennes versions sont proposées à la suppression par groupe homogène.
  - Lisibilité: affichage du nom du mod pour chaque ligne enfant; suppression des lignes « vides ».

- Updates Checker
  - Ne lance plus de scan complet: s’appuie sur `mod_scan_cache.json` pour lister tous les mods (plus de limite à ~208 éléments).
  - Ajout d’une colonne « URL » affichant le lien de téléchargement quand il est détecté dans l’index.
  - Nouveau bouton « Check Obsolete »: compare avec la feuille publique d’obsolescence et marque les mods obsolètes dans la colonne Status.

- Mod Installer
  - Nouveau dans le menu contextuel: « Search for Update » ouvre l’Updates Checker filtré sur le mod et déclenche la recherche.
  - Nouveau: « Repair definition… » permet de re-vérifier un dossier sélectionné et de recréer un fichier `.s4mt_mod_marker.json` propre.

v3.40.3 (2025-10-29)

- GUI
  - Rétabli: curseur « Opacité des cadres » dans Configuration > Apparence. La valeur est persistée dans `settings.json` (clé `ui_frame_opacity`) et s’applique à l’interface pour laisser apparaître le fond d’écran.
  - Menus contextuels: correction d’un crash `UnboundLocalError` (variable `current_atf`) lors de l’ouverture du menu sur des lignes sans groupe. L’état par défaut est correctement initialisé.

- Updates Checker
  - Bouton « Open »: robuste face aux URL non textuelles. Le clic ne reconfigure le bouton que pour des URL HTTP/HTTPS valides; évite l’exception `QUrl(bool)`.

- Context Menus
  - Ajout explicite de l’action « Chercher sur Patreon » dans le menu contextuel principal là où elle manquait, supprimant l’avertissement Pylance « reportUndefinedVariable » et rétablissant l’action.

- Splash Screen
  - Le fond personnalisé du splash est désormais affiché (clé `splash_background_image_path`). Correction de l’ordre de dessin et d’un dégradé opaque qui masquait l’image.
  - Lisibilité améliorée: zone de titre plus haute, alignement en haut, légère ombre portée, et dégradé semi‑transparent pour conserver le contraste sans cacher l’image.

v3.40.2 (2025-10-28)

- Duplicate Finder
  - Durable fix: `_run_scan` and related helpers are now defined on `DuplicateFinderDialog` (not another class). Prevents the recurrent `AttributeError: 'DuplicateFinderDialog' object has no attribute '_run_scan'` when opening the tool.

- Context Menus
  - Fixed undefined variable error: `patreon_action` is now added to the main table context menu before being used (resolves Pylance reportUndefinedVariable at main.py:7090).
  - Cleanup: removed a duplicated `patreon_action = menu.addAction("Chercher sur Patreon")` entry in an older context menu.

v3.40.1 (2025-10-27)

- Export
  - Excel export now respects visible columns only and writes matching headers (including Version and Ignoré when visible).

- Updates Checker
  - Default source switched to Scarlet's Realm "Mod List Checker" Google Sheets CSV.
    - CSV URL (default): https://docs.google.com/spreadsheets/d/e/2PACX-1vRexBc8fcYyfsjbGRo3sH18jj9DuwKH8J7_SvQvpK_fvjsnILKRz1xGOwYz-xtG0wIKQcs1eDN1yw9V/pub?gid=119778444&single=true&range=A:I&output=csv
    - Config override via settings key: `updates_checker_csv_url`.
  - Automatic fallback to TS4ModHound index if CSV fails to load.
  - Improved date parsing to support textual month formats (e.g., "Jul 2, 2025").
  - Now checks all mods found in the Mods folder (not only those installed via Mod Installer).

- AI Training
  - Training dialog now ignores UI filters and builds an unfiltered dataset directly from the Mods folder.
  - Also learns from log files found under Mods (.log/.txt/.html + configured extras).
  - Adds a detailed summary at the end (counts, top tokens, top mods).
  - Bottom bar "AI Mode Activated" now appears only when AI is enabled and a model is actually loaded.

- Web
  - Re-enabled Web interface auto-start on app launch (configurable via settings: web_enabled, web_host, web_port, web_debug).
  - Added an action button "Ouvrir Mods" to open the Mods folder in the system file explorer.

v3.40 (2025-10-25)

- Tools
  - New: Log Manager — choose a log file (`.log`, `.txt`, `.html`), view it with live filtering (keyword/regex, case sensitivity), quick search, and run an analysis.
  - MCCC Last Exception (`mc_lastexception.html`) analyzer: extracts exception type/message, involved file paths and heuristically infers the probable mod (first folder under `Mods/`). Shows detected Sims 4 version in the dialog title.
  - Optional AI integration: when enabled in Configuration, the app learns from scans (names/files/paths) and the Log Manager shows an “IA Mod (conf.)” column with a suggested mod and confidence.
  - Added "Entrainement A.I." button to run manual AI training on the current table with a real-time status window and cancel; saves the model on completion.
  - Log Manager: added "Analyser dossier…" to parse entire folders (incl. `./logs`) and "Entrainer IA (ce log)" to feed analyzed results directly into the model.
  - Info popup when opening "Entrainement A.I." explains purpose and how it works.

- Bugfix
  - Startup scan now waits ~300ms before launching, allowing the app background to render before the analysis begins.

- AI Logging and UI
  - Added detailed AI logs (load/save model, training start/stop, batch progress, per-guess debug) under logger name `Sims4ModTool.AI`.
  - Bottom bar shows "AI Mode Activated" when AI is enabled and the model is loaded.
  - Training now ignores UI filters: it builds an unfiltered dataset from the Mods folder and also learns from log files (.log/.txt/.html + configured extras).
  - Training window shows a final detailed summary (counts and top tokens/mods).
  - Log Manager displays a detailed summary after analysis (top exceptions, top mods via AI, top files).

v3.39 (2025-10-24)

- Mod Installer
  - Colonne URL déplacée en dernière position dans la table.
  - Colonnes redimensionnables (mode interactif) dans la table du Mod Installer.
  - Indicateur Add-ons corrigé: case à cocher (lecture seule) cochée lorsque des add-ons sont présents.
  - Détection de version lors de l’installation: si un suffixe de nom de fichier de type `_vX.Y.Z` est présent, la version est pré‑remplie; à défaut, la version du jeu la plus récente antérieure à la date du fichier est proposée automatiquement.

- Sécurité globale
  - Aucune opération (scan, installation, suppression, export) n’est autorisée lorsque TS4_x64.exe est en cours d’exécution. Affichage d’un message d’attente.
  - Étiquette d’état du processus du jeu ajoutée à l’interface principale (mis à jour périodiquement).

- Terminologie
  - Remplacement du terme « ATF » par « Protected » dans l’interface (menus, confirmations, info‑bulles). Le stockage interne reste inchangé (clé `atf`).

- Menus contextuels
  - Ajout d’une action « Chercher sur Patreon » à tous les menus contextuels pertinents (tableau principal, Mod Installer, Scan dossier, Recherche dans ts4script).
  - Recherche Patreon effectuée via Google (`site:patreon.com <mod>`), plus robuste que la recherche interne Patreon.

- Scan dossier (mods)
  - Plus d’auto-analyse: aucun scan avant que l’utilisateur ait choisi le dossier et cliqué « Analyser ».
  - Le dernier dossier scanné est mémorisé (`last_folder_scan_directory`).
  - Fenêtre redimensionnable (maximiser + poignée).

- Tools
  - Panneau « Tools » rendu adaptatif comme « Actions » (grille réactive).
  - Nouveau: « Conflict Checker » — détecte plusieurs versions d’un même mod (basé sur l’extraction de version dans le nom). Coche les anciennes versions par défaut et propose la suppression après confirmation.

v3.38 (2025-10-23)

- Appariement .package ⇄ .ts4script
  - Meilleure précision: suppression des suffixes de version en fin de nom (ex: `_V1.23`) côté package/ts4script lors de la normalisation des noms.
  - La colonne Version affiche désormais la version explicite extraite du nom (si présente), sinon une estimation basée sur la date du patch.
  - Le pass "même dossier parent" requiert désormais une similarité minimale (≥ 0,70) pour éviter des appariements erronés (ex.: éviter de lier un script `[Kuttoe] ScoutBadgeFix.ts4script` au package `LittleMsSam_RBF_SpookyCandyBowlTrickTreatFixes.package`).
  - Seuil de similarité principal relevé (≥ 0,70) et garde contre les noms trop courts (< 4 caractères) pour réduire les faux positifs.
  - Les `.ts4script` livrés sans `.package` sont listés comme `MP` (mod script seul) sans tentative d’appariement forcé.

- Outil Doublons
  - Correction du crash: `_run_scan` manquant sur `DuplicateFinderDialog`. Les méthodes de scan de doublons sont maintenant rattachées à la bonne classe.

- Splashscreen
  - Titre abaissé pour un meilleur équilibre visuel et police plus "gothic" si disponible (ex.: Old English Text MT).
  - Le texte du haut n'est plus coupé: marge supérieure augmentée et correction de l'ordre de dessin.

- Version
  - Bumped application version to v3.38.

v3.37 (2025-10-23)

- ZIP Installer (Mod Root)
  - New deterministic extraction for heterogeneous ZIPs with mod-root detection and predictable placement under `Mods/`.
  - Rules: FLAT (files at root) → `Mods/<ZipName>/`; SINGLE_DIR (one top folder) → `Mods/<FolderName>/`; MIXED (multiple folders) → pick folder with most useful files (tie-breaker: shortest median depth) and extract to `Mods/<ZipName>/`.
  - Copies `.package` and `.ts4script` by default; optional `--include-extras` to also copy docs/images.
  - Security: prevents traversal/absolute paths; ignores noise (`__MACOSX/`, `Thumbs.db`, `.DS_Store`).
  - Detailed DEBUG logs: archive type, chosen mod_root + justification, destination and installed files.
  - Also supports `.7z` and `.rar`: extraction to a temporary directory via 7‑Zip, then the same Mod Root rules are applied.

- Mod Installer
  - Added a Settings button within the Mod Installer window to toggle “Use Mod Root” and “Include extras” without leaving the dialog.
  - New pre-install Plan dialog lets you review and adjust the structure before install: edit destination folder name, choose the mod root among top‑level folders (for MIXED), and decide whether to include extras. The metadata prompt (version/URL) now shows after this step.

- GUI
  - New filter: “Masquer Mod Installer” next to “Afficher les mods ignorés” to hide mods installed via Mod Installer from results.
  - Tools moved onto the main window in a dedicated “Tools” group to the right of “Actions”, now arranged in a 2‑column grid.
  - “Analyser / Rafraîchir” moved to the first position in Actions.
  - Fix: Google search from a ts4script row now searches the ts4script (was incorrectly using the package name).
  - Per-row indicator: a new “Installer” column shows ✓ when the row belongs to a Mod Installer group.
  - Horizontal scrolling: the mods table enables a horizontal scrollbar when columns exceed the viewport width.
  - “Kill Sims 4” moved to the bottom bar; added a “Quitter” button to close the app.

- Tools
  - New: Comparateur de mods — compare two mod folders, including `.package` files (size/hash), `.ts4script` archives (size/hash), and internal contents of `.ts4script` (file name, size, CRC). Also shows counts and add-ons (from marker if present). Helps identify differences between patched vs non‑patched versions.

- Web
  - Added a basic Web interface (Flask) to browse mods, apply filters (including “Masquer Mod Installer”), ignore/unignore mods, export to Excel and install archives (`.zip`/`.7z`/`.rar`/`.ts4script`/`.package`).
  - Run with `python webapp.py` and open http://127.0.0.1:5000/.
  - Upgraded UI to Bootstrap 5 with a SPA-like table fed by `/api/rows` (client-side search, header sorting, column visibility with persistence via `/api/columns`).
  - Added endpoints: `/api/install`, `/api/installer/update` (update a specific target folder), `/api/atf-toggle` (toggle ATF on a mod), `/api/columns` (persist hidden columns). Per-row actions include “Ouvrir” and “ATF”.
  - The web server starts automatically in the background when running `main.py` (configurable host/port via env: `S4MT_WEB_HOST`, `S4MT_WEB_PORT`).

v3.36 (2025-10-23)

- Mod Installer
  - After installing or updating a mod, prompts for version and URL (optional; empty allowed). Values are saved to installed_mods.json and the per‑mod marker.
  - Window can be resized and supports maximize; size grip added.
  - “Ajouter des add-ons” dialog now displays the master mod folder path.
  - Fix: installing .7z or .rar archives now sets Type to "archive .7z/.rar" instead of empty.

- ATF
  - Fixed persistence: load_installed_mods now preserves the `atf` flag; marker recovery also restores it.

v3.35 (2025-10-23)

- Tools
  - New: Find in ts4script — enter one or more filenames (wildcards supported) and the tool searches inside `.ts4script` archives (ZIP) for matches. Results shown in a dedicated table with columns: occurence (archive entry), filename (ts4script file), chemin (full path), date (file timestamp). Includes a progress bar, header menu for column visibility and a row context menu. This tool ignores global filters (behaves like "Show both").

- Version
  - Bumped application version to v3.35.

v3.34 (2025-10-23)

- Duplicate Finder
  - Fixed crash: AttributeError on `_run_scan` caused by methods bound to the wrong class. Methods are now properly defined on `DuplicateFinderDialog`.

- Tools
  - Scan dossier: results are no longer filtered; behavior now matches “Show both” regardless of current filters. Added right‑click context menu on rows with the same actions as the main table (Ignorer, Afficher dans l'explorateur, Supprimer, Recherche Google, ATF toggle). Added header context menu to show/hide columns.
  - Check placement .ts4script: when log level is DEBUG, every scanned file path is logged.

- Version
  - Bumped application version to v3.34.

- Build
  - Fixed PowerShell parser errors in `build.ps1` (removed Bash-style `||`, proper exit checks).
  - Added Windows CMD script `build.bat` with equivalent behavior (auto-installs PyInstaller, bundles `version_release.json` when present).
  - Excludes `PySide6`/`PySide2`/`PyQt6` in build scripts to resolve multiple Qt bindings error when multiple Qt packages are present.

v3.33 (2025-10-23)

- Mod Installer
  - Unified extraction for .7z/.rar: extracts to a temporary folder, normalizes using the same rules as ZIP (the .ts4script defines the mod root), then copies into Mods.
  - ATF safety: prompts an extra confirmation before updating mods flagged as ATF; marker files now include "atf".

- Tools
  - Scan dossier (mod): choose any folder to analyze; new “Récursif” option (enabled by default) scans subfolders; logs an INFO summary on completion.
  - Check placement .ts4script: lists any .ts4script deeper than one subfolder under Mods; details logged at DEBUG and a WARN summary with offender count.

- Mod Scanner
  - Fixed recursive toggle handling so non‑recursive and recursive scans work as expected.

- Duplicate Finder
  - Fixed a method‑name conflict that could raise: 'FolderScannerDialog' object has no attribute 'tree'.

- GUI
  - App and Splash backgrounds are configurable and reliably rendered (styled background + border‑image).
  - Action buttons in an adaptive grid with text under icons; icons now resize based on available width; smaller bottom buttons.
  - Search row split into two lines; Mod Installer header menu to show/hide columns with persisted preferences.
  - Bottom center displays game Version/Build read from caches config.log when available.
  - ATF mods are highlighted (black text on pink background) across views.

- Internationalization
  - Prepared language files under lang/ (fr-fr.lng, en-us.lng) and added a language selector in Configuration.

- Logging
  - Extended DEBUG coverage (action grid/layout, version/build parsing, tools) with consistent INFO/WARN/ERROR usage.

v3.32 (2025-10-22)

- GUI
  - Actions: added context‑appropriate icons to main buttons (Refresh, Export, Clear Cache, Grab Logs, Mod Installer, Tools, Group View, Kill, Configuration, Launch).
  - Search UI split into two rows inside Filters: row 1 has “Afficher recherche” and “Instant search”; row 2 has label, input and “Rechercher” button.
  - Mod Installer: header context menu to show/hide columns with persisted preferences.
  - Actions buttons normalized and arranged in an adaptive grid; labels under large icons.
  - Bottom bar buttons reduced in height.
  - Bottom center now displays Sims 4 Version/Build read from caches config.log when available.

- SplashScreen
  - New gradient background with a plumbob‑like diamond and soft glow.

- Mod Installer
  - ZIP plan preserves subfolder names (e.g. “data”) when a .ts4script defines the mod root.

v3.31 (2025-10-22)

- Mod Installer
  - Added marker file .s4mt_mod_marker.json per mod install/update and a Recovery list to rebuild installed list from markers.
  - ZIP extraction preserves structure and original timestamps.
  - Added .7z and .rar extraction via 7‑Zip.

- GUI
  - Group View (tree) with collapse/expand by mod; highlights rows installed via Mod Installer.
  - Instant search toggle and manual search button.
  - File filter dropdown (both/package/ts4script/installer only).
  - Auto‑scan on startup and startup splash status.
  - Configuration dialog reorganized and enlarged.
  - Delete guard while TS4_x64.exe is running; Kill Sims 4 can elevate on Windows.
  - Column visibility menu on table header with persisted preferences.
  - Filters group (left) and Actions group (right).

- Duplicate Finder
  - Recursive scan of subfolders with progress and multi‑select delete.

- Logging
  - Centralized logging with configurable level.

- Tools
  - Correct resource.cfg: validates and fixes Mods\Resource.cfg to the recommended defaults.
  - Placeholders added: Symlink Mods, Backup Mods.

- Build
  - Added build.ps1 PowerShell script to build the application via PyInstaller.
- GUI
  - L’opacité n’affecte plus la fenêtre entière mais uniquement les cadres de contenu (QGroupBox, QTableWidget, QTreeWidget, en‑têtes). Le fond d’écran choisi devient visible à travers des panneaux translucides.
  - Configuration: le curseur « Opacité de l’interface » met à jour l’opacité des cadres en temps réel.

- Splashscreen
  - Le fond d’écran personnalisable est désormais visible: lorsque défini, le dégradé est rendu semi‑transparent au lieu de recouvrir totalement l’image.
  - Titre toujours visible à l’intérieur du splash (zone de texte recalibrée) et rendu au‑dessus des effets visuels.

- A.I.
  - Ajout d’un groupage déterministe: si tous les fichiers pointent vers le même premier dossier sous Mods, ce dossier est utilisé comme groupe (prioritaire quand aucun marqueur n’existe).
  - Prévention de réinstallation: si un marqueur est présent dans la cible ou si une copie désactivée correspondante est détectée, l’Installateur avertit et propose Remplacer (clean) ou Fusionner, ou Annuler.

v3.41.0 (2025-10-29)

- Tools
  - Added ID Conflict Viewer: scans all `.package` files for resource ID (Type/Group/Instance) conflicts and displays them in a tree view.
  - Context actions: open folder, prefix file with `zzz_`, disable mod folder (moves to `Backups/Disabled Mod`).
  - Excel export of conflicts as `id_conflicts.xlsx`.
  - Added a Stop button to cancel long-running scans with clear UI feedback and logging.
- Performance
  - ID Conflict Viewer now supports using `mod_scan_cache.json` to list files and a fast mode that skips tail fallback parsing.
  - Added persistent per-file TGI cache (`id_index_cache.json`) keyed by path+size+mtime to speed up subsequent runs.
  - Parallel parsing via ThreadPoolExecutor (up to 8 workers) with batched cache writes and responsive progress updates.
- Logging
  - Logs ID conflict scans, renames and disable actions to `sims4modtool.log` at INFO/DEBUG level.
v3.41.3 (2025-10-30)

- Tools (modules)
  - Déplacé: « Entrainement A.I. » dans `modules/ai_training.py`. Les outils externes du dossier `modules` sont chargés automatiquement.
- Entrainement A.I.
  - Correction: ajout d’un champ « Dossier à analyser » dans la fenêtre (l’erreur `AttributeError: 'AITrainingDialog' object has no attribute 'path_edit'` est corrigée).
  - L’entraînement utilise le dossier choisi (par défaut le dossier Mods), les logs et l’index CSV public.
v3.44.0 (2025-10-31)

- Interface IA
  - L’étiquette de statut affiche le moteur courant, la date d’entraînement et le volume appris; elle signale explicitement lorsqu’un nouvel entraînement est requis (modèle manquant, fichier .joblib absent, etc.).
  - Bouton « Vérifier modèle » dans la fenêtre Entrainement A.I. : contrôle la cohérence du JSON et des modèles enregistrés (TF‑IDF / MLP), met à jour le statut et log les anomalies.
- Entrainement A.I.
  - Correction d’un crash (`ml_selected` non défini) apparu lors de l’introduction des nouveaux moteurs.
  - Métadonnées enrichies (engine, métriques, flags) pour déterminer si un ré-entraînement est nécessaire.

v3.43.0 (2025-10-30)

- AI Training
  - Nouvelle gestion des classes rares: seuil configurable (min échantillons/classe), avec suppression des classes trop faibles ou fusion dans une classe « Rare ».
  - Option d’équilibrage `class_weight='balanced'` pour LinearSVC et support de la validation croisée stratifiée (k-folds) lorsque les classes le permettent.
  - Nouveau moteur « Réseau neuronal léger (MLP) » basé sur scikit-learn (vectorisation TF‑IDF + SVD + MLPClassifier), optimisé pour rester léger.
  - Paramètres persistés entre les sessions (sources, moteur, split, n‑grammes, max features, batch, seuil, stratégie rare, équilibrage, k-folds).

v3.42.1 (2025-10-30)

- AI Training
  - La progression inclut désormais l’étape TF‑IDF (barre non bloquée à 100% alors que le classifieur s’entraîne).
  - Appel périodique de `processEvents()` pour rafraîchir l’UI autour des étapes lourdes.
  - Persistance des paramètres d’entraînement (sources, moteur, split, n‑grammes, max features, batch) dans `settings.json`.
