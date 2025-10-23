Changelog

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

