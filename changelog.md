Changelog

v3.32 (2025-10-22)

- GUI
  - Actions: added context-appropriate icons to main buttons (Refresh, Export, Clear Cache, Grab Logs, Mod Installer, Tools, Group View, Kill, Configuration, Launch).
  - Search UI split into two rows inside Filters: row 1 has "Afficher recherche" and "Instant search"; row 2 has label, input and "Rechercher" button.
  - Mod Installer: header context menu to show/hide columns with persisted preferences.
  - Actions buttons normalized and arranged in an adaptive grid; labels under large icons.
  - Bottom bar buttons reduced in height.
  - Bottom center now displays Sims 4 Version/Build read from caches `config.log` when available.

- SplashScreen
  - New gradient background with a plumbob-like diamond and soft glow.
  
- Mod Installer
  - ZIP plan now preserves subfolder names (e.g. "data") when a `.ts4script` defines the mod root.

v3.31 (2025-10-22)

- Mod Installer
  - Added marker file `.s4mt_mod_marker.json` per mod install/update.
  - Recovery list to rebuild installed list from markers.
  - ZIP extraction preserves structure and original timestamps.
  - Added `.7z` and `.rar` extraction via 7‑Zip.

- GUI
  - Group View (tree) with collapse/expand by mod.
  - Highlight rows for mods installed via Mod Installer.
  - Instant search toggle and manual search button.
  - File filter dropdown (both/package/ts4script/installer only).
  - Auto-scan on startup setting (default on) and startup splash screen with live status.
  - Configuration dialog reorganized and enlarged.
  - Delete guard: prevents deletions while TS4_x64.exe is running.
  - Kill Sims 4: tries elevation on Windows if needed (UAC).
  - Column visibility menu on table header with persisted preferences.
  - Moved filters into a “Filtres” group (top-left) and actions into an “Actions” group (top-right).

- Duplicate Finder
  - Recursive scan of subfolders.
  - Progress bar and delete selected files.

- Logging
  - Centralized logging with configurable level.

- Tools
  - Correct resource.cfg: validates and fixes Mods\Resource.cfg to the recommended defaults.
  - Placeholders added: Symlink Mods, Backup Mods.

- Build
  - Added `build.ps1` PowerShell script to build the application via PyInstaller.
