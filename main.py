import sys
import os
import json
import shutil
import shlex
import re
import subprocess
import webbrowser
import zipfile
import stat
import hashlib
import logging
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple
from difflib import SequenceMatcher
from functools import partial
from urllib.parse import quote_plus
from datetime import datetime, time, date
from openpyxl import Workbook

# Qt bindings import shim (supports PyQt5/PySide2/PySide6/PyQt6)
try:
    from PyQt5 import QtWidgets, QtCore, QtGui  # type: ignore
    QT_LIB = "PyQt5"
except Exception:
    try:
        from PySide2 import QtWidgets, QtCore, QtGui  # type: ignore
        QT_LIB = "PySide2"
    except Exception:
        try:
            from PySide6 import QtWidgets, QtCore, QtGui  # type: ignore
            QT_LIB = "PySide6"
        except Exception:
            from PyQt6 import QtWidgets, QtCore, QtGui  # type: ignore
            QT_LIB = "PyQt6"

# Compatibility shims for Qt6 enum/API differences used in this codebase
if 'QT_LIB' in globals() and QT_LIB in ("PyQt6", "PySide6"):
    # QDialogButtonBox: map StandardButton members to direct attributes (Ok, Cancel, ...)
    if hasattr(QtWidgets.QDialogButtonBox, "StandardButton"):
        _STD = QtWidgets.QDialogButtonBox.StandardButton
        for _name in ("Ok", "Cancel", "Yes", "No", "Apply", "Save", "Open", "Close"):
            if not hasattr(QtWidgets.QDialogButtonBox, _name) and hasattr(_STD, _name):
                setattr(QtWidgets.QDialogButtonBox, _name, getattr(_STD, _name))

    # QtCore.Qt enum aliases commonly used by PyQt5-era code
    if hasattr(QtCore, "Qt"):
        _Qt = QtCore.Qt
        # Alignment flags
        if hasattr(_Qt, "AlignmentFlag"):
            if not hasattr(_Qt, "AlignRight"):
                _Qt.AlignRight = _Qt.AlignmentFlag.AlignRight
            if not hasattr(_Qt, "AlignCenter"):
                _Qt.AlignCenter = _Qt.AlignmentFlag.AlignCenter
        # Text interaction
        if hasattr(_Qt, "TextInteractionFlag") and not hasattr(_Qt, "TextSelectableByMouse"):
            _Qt.TextSelectableByMouse = _Qt.TextInteractionFlag.TextSelectableByMouse
        # Context menu policy
        if hasattr(_Qt, "ContextMenuPolicy") and not hasattr(_Qt, "CustomContextMenu"):
            _Qt.CustomContextMenu = _Qt.ContextMenuPolicy.CustomContextMenu
        # Orientation
        if hasattr(_Qt, "Orientation") and not hasattr(_Qt, "Horizontal"):
            _Qt.Horizontal = _Qt.Orientation.Horizontal
        # Check state
        if hasattr(_Qt, "CheckState") and not hasattr(_Qt, "Checked"):
            _Qt.Checked = _Qt.CheckState.Checked
        # Item flags
        if hasattr(_Qt, "ItemFlag"):
            if not hasattr(_Qt, "ItemIsEditable"):
                _Qt.ItemIsEditable = _Qt.ItemFlag.ItemIsEditable
            if not hasattr(_Qt, "ItemIsEnabled"):
                _Qt.ItemIsEnabled = _Qt.ItemFlag.ItemIsEnabled
            if not hasattr(_Qt, "ItemIsSelectable"):
                _Qt.ItemIsSelectable = _Qt.ItemFlag.ItemIsSelectable
        # Item data roles
        if hasattr(_Qt, "ItemDataRole") and not hasattr(_Qt, "UserRole"):
            _Qt.UserRole = _Qt.ItemDataRole.UserRole
    # Widgets enum aliasing
    try:
        if hasattr(QtWidgets, "QAbstractItemView") and hasattr(QtWidgets.QAbstractItemView, "SelectionMode"):
            if not hasattr(QtWidgets.QAbstractItemView, "NoSelection"):
                QtWidgets.QAbstractItemView.NoSelection = QtWidgets.QAbstractItemView.SelectionMode.NoSelection
    except Exception:
        pass
    try:
        if hasattr(QtWidgets, "QComboBox") and hasattr(QtWidgets.QComboBox, "SizeAdjustPolicy"):
            if not hasattr(QtWidgets.QComboBox, "AdjustToContents"):
                QtWidgets.QComboBox.AdjustToContents = QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
    except Exception:
        pass
    try:
        if hasattr(QtWidgets, "QHeaderView") and hasattr(QtWidgets.QHeaderView, "ResizeMode"):
            if not hasattr(QtWidgets.QHeaderView, "Stretch"):
                QtWidgets.QHeaderView.Stretch = QtWidgets.QHeaderView.ResizeMode.Stretch
            if not hasattr(QtWidgets.QHeaderView, "ResizeToContents"):
                QtWidgets.QHeaderView.ResizeToContents = QtWidgets.QHeaderView.ResizeMode.ResizeToContents
    except Exception:
        pass
    # exec_ compatibility for Qt6
    try:
        for _cls in (
            getattr(QtWidgets, "QDialog", None),
            getattr(QtWidgets, "QApplication", None),
            getattr(QtWidgets, "QMenu", None),
        ):
            if _cls is not None and hasattr(_cls, "exec") and not hasattr(_cls, "exec_"):
                setattr(_cls, "exec_", getattr(_cls, "exec"))
    except Exception:
        pass
    # QDialog.DialogCode aliases
    try:
        if hasattr(QtWidgets, "QDialog") and hasattr(QtWidgets.QDialog, "DialogCode"):
            _DC = QtWidgets.QDialog.DialogCode
            if not hasattr(QtWidgets.QDialog, "Accepted"):
                QtWidgets.QDialog.Accepted = _DC.Accepted
            if not hasattr(QtWidgets.QDialog, "Rejected"):
                QtWidgets.QDialog.Rejected = _DC.Rejected
    except Exception:
        pass

SETTINGS_PATH = "settings.json"
IGNORE_LIST_PATH = "ignorelist.txt"
VERSION_RELEASE_PATH = "version_release.json"
APP_VERSION = "v3.31"
APP_VERSION_DATE = "22/10/2025 11:54 UTC"
INSTALLED_MODS_PATH = "installed_mods.json"
MOD_SCAN_CACHE_PATH = "mod_scan_cache.json"
MOD_MARKER_FILENAME = ".s4mt_mod_marker.json"
LOG_FILE_PATH = "sims4modtool.log"

# --- Logging setup (default DEBUG, configurable via settings) ---
_LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

def _normalize_log_level(value):
    if isinstance(value, int):
        return value
    try:
        key = str(value or "").strip().upper()
    except Exception:
        key = "DEBUG"
    return _LEVEL_MAP.get(key, logging.DEBUG)

def setup_logging(level="DEBUG"):
    level_no = _normalize_log_level(level)
    logger = logging.getLogger("Sims4ModTool")
    logger.setLevel(level_no)
    logger.propagate = False

    # Ensure handlers only added once
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(level_no)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        try:
            # File handler (best-effort)
            fh = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
            fh.setLevel(level_no)
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception:
            # If file logging fails, continue with console only
            pass

    # Also set root logger to the same level for libraries if needed
    logging.getLogger().setLevel(level_no)
    return logger

# Initialize logging early with default DEBUG; runtime settings can override later
setup_logging("DEBUG")

SUPPORTED_INSTALL_EXTENSIONS = {".package", ".ts4script", ".zip", ".7z", ".rar"}

IGNORED_ARCHIVE_PREFIXES = {"__MACOSX"}
IGNORED_ARCHIVE_PREFIX_MATCHES = (".git",)
IGNORED_ARCHIVE_FILENAMES = {"thumbs.db", ".ds_store"}
IGNORED_ARCHIVE_NAME_PREFIXES = ("readme", "license")
DISALLOWED_ARCHIVE_EXTENSIONS = {
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".ps1",
    ".vbs",
    ".js",
    ".jar",
    ".scr",
    ".pif",
    ".apk",
    ".app",
    ".sh",
    ".bash",
    ".py",
    ".rb",
    ".php",
}
MAX_RELATIVE_DEPTH = 2

MOD_NAME_SANITIZE_RE = re.compile(r"[^a-z0-9]+")
MIN_SIMILARITY_RATIO = 0.6
MAX_SIMILARITY_CANDIDATES = 80


@dataclass(frozen=True)
class ZipInstallEntry:
    member_name: str
    relative_parts: Tuple[str, ...]


@dataclass
class ZipInstallPlan:
    mod_folder_name: str
    target_folder: str
    entries: List[ZipInstallEntry]
    warnings: List[str]


@dataclass
class ZipPlanResult:
    success: bool
    plan: Optional[ZipInstallPlan]
    message: str = ""


def normalize_addon_metadata(addons):
    normalized = []
    if not isinstance(addons, list):
        return normalized

    def _append_or_merge(target_list, candidate):
        label = candidate.get("label", "")
        if not label:
            return
        key = label.casefold()
        for existing in target_list:
            if existing.get("label", "").casefold() == key:
                existing_paths = existing.setdefault("paths", [])
                for path in candidate.get("paths", []):
                    if path and path not in existing_paths:
                        existing_paths.append(path)
                if candidate.get("added_at") and not existing.get("added_at"):
                    existing["added_at"] = candidate.get("added_at")
                return
        target_list.append(candidate)

    for addon in addons:
        label = ""
        paths = []
        added_at = ""
        if isinstance(addon, dict):
            label = str(
                addon.get("label")
                or addon.get("name")
                or addon.get("source")
                or addon.get("title")
                or ""
            ).strip()
            raw_paths = addon.get("paths", [])
            if isinstance(raw_paths, (list, tuple)):
                for path in raw_paths:
                    path_str = str(path).replace("\\", "/").strip()
                    if path_str:
                        if path_str.startswith("..") or "/../" in path_str:
                            continue
                        if path_str.endswith("/"):
                            base_path = os.path.normpath(path_str[:-1])
                            normalized_path = base_path.replace("\\", "/") + "/"
                        else:
                            base_path = os.path.normpath(path_str)
                            normalized_path = base_path.replace("\\", "/")
                        if normalized_path not in paths:
                            paths.append(normalized_path)
            added_at = str(addon.get("added_at") or "").strip()
        else:
            label = str(addon).strip()

        if not label:
            continue

        _append_or_merge(
            normalized,
            {
                "label": label,
                "paths": paths,
                "added_at": added_at,
            },
        )

    return normalized


DEFAULT_VERSION_RELEASES = [
    {"version": "1.109.185.1030", "release_date": "2024-09-18"},
    {"version": "1.110.265.1030", "release_date": "2024-10-22"},
    {"version": "1.110.311.1020", "release_date": "2024-11-07"},
    {"version": "1.111.102.1030", "release_date": "2024-12-03"},
    {"version": "1.115.216.1030", "release_date": "2025-05-27"},
    {"version": "1.115.253.1020", "release_date": "2025-06-17"},
    {"version": "1.116.202.1030", "release_date": "2025-07-01"},
    {"version": "1.116.223.1030", "release_date": "2025-07-10"},
    {"version": "1.116.232.1030", "release_date": "2025-07-16"},
    {"version": "1.116.240.1020", "release_date": "2025-07-29"},
    {"version": "1.117.227.1030", "release_date": "2025-08-19"},
    {"version": "1.117.244.1020", "release_date": "2025-09-04"},
    {"version": "1.118.242.1030", "release_date": "2025-09-18"},
    {"version": "1.118.257.1020", "release_date": "2025-10-02"},
]


def parse_release_date(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def format_release_date(date_obj):
    if not date_obj:
        return ""
    return date_obj.strftime("%d/%m/%Y")


def load_custom_version_releases(path=VERSION_RELEASE_PATH):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    releases = {}
    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = ((entry.get("version"), entry.get("release_date")) for entry in data)
    else:
        return {}

    for version, date_str in items:
        if not version:
            continue
        parsed = parse_release_date(date_str)
        if parsed is None:
            continue
        releases[str(version)] = parsed
    return releases


def save_custom_version_releases(releases, path=VERSION_RELEASE_PATH):
    entries = [
        {"version": version, "release_date": date.isoformat()}
        for version, date in sorted(releases.items(), key=lambda item: (item[1], item[0]))
    ]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=4, ensure_ascii=False)


def merge_version_releases(custom_releases):
    merged = {}
    for entry in DEFAULT_VERSION_RELEASES:
        version = entry.get("version")
        date_str = entry.get("release_date")
        if not version or not date_str:
            continue
        parsed = parse_release_date(date_str)
        if parsed is None:
            continue
        merged[version] = parsed
    for version, date_obj in custom_releases.items():
        if not version or date_obj is None:
            continue
        merged[version] = date_obj
    sorted_items = sorted(merged.items(), key=lambda item: (item[1], item[0]))
    return OrderedDict(sorted_items)


def estimate_version_from_dates(package_date, script_date, version_releases):
    candidates = [value for value in (package_date, script_date) if value is not None]
    if not candidates:
        return ""
    latest_datetime = max(candidates)
    latest_date = latest_datetime.date()
    estimated_version = ""
    for version, release_date in version_releases.items():
        if release_date <= latest_date:
            estimated_version = version
        elif not estimated_version:
            return version
        else:
            break
    return estimated_version


def format_datetime(value):
    if not value:
        return ""
    return value.strftime("%d/%m/%Y %H:%M")


def load_ignore_list(path=IGNORE_LIST_PATH):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_ignore_list(ignored_mods, path=IGNORE_LIST_PATH):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for mod_name in sorted(set(ignored_mods)):
            f.write(f"{mod_name}\n")


def load_installed_mods(path=INSTALLED_MODS_PATH):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return []

    normalized_entries = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("mod_name") or "").strip()
        target_folder = str(entry.get("target_folder") or "").strip()
        if not name or not target_folder:
            continue
        normalized_entries.append({
            "name": name,
            "type": str(entry.get("type") or "").strip(),
            "installed_at": str(entry.get("installed_at") or "").strip(),
            "target_folder": target_folder,
            "source": str(entry.get("source") or "").strip(),
            "addons": normalize_addon_metadata(entry.get("addons", [])),
            "files": [str(p).replace("\\", "/").strip() for p in (entry.get("files", []) or []) if str(p).strip()],
            "mod_version": str(entry.get("mod_version") or "").strip(),
            "url": str(entry.get("url") or "").strip(),
            "disabled": bool(entry.get("disabled", False)),
            "disabled_path": str(entry.get("disabled_path") or "").strip(),
        })

    normalized_entries.sort(key=lambda item: item.get("installed_at", ""), reverse=True)
    return normalized_entries


def save_installed_mods(installed_mods, path=INSTALLED_MODS_PATH):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(installed_mods, handle, indent=4, ensure_ascii=False)


def load_mod_scan_cache(path=MOD_SCAN_CACHE_PATH):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None
    normalized_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path_value = str(entry.get("path") or "").strip()
        if not path_value:
            continue
        normalized_entries.append({
            "path": path_value.replace("\\", "/"),
            "mtime": int(entry.get("mtime", 0)),
            "size": int(entry.get("size", 0)),
            "type": str(entry.get("type") or ""),
        })
    normalized_entries.sort(key=lambda item: item["path"].casefold())
    normalized_root = str(data.get("root") or "").replace("\\", "/").strip()
    return {
        "root": normalized_root,
        "entries": normalized_entries,
    }


def save_mod_scan_cache(snapshot, path=MOD_SCAN_CACHE_PATH):
    if not isinstance(snapshot, dict):
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    serializable = {
        "root": str(snapshot.get("root") or ""),
        "generated_at": snapshot.get("generated_at", ""),
        "entries": list(snapshot.get("entries", [])),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(serializable, handle, indent=2, ensure_ascii=False)


def mod_scan_snapshots_equal(first, second):
    if not first or not second:
        return False
    first_entries = first.get("entries") or []
    second_entries = second.get("entries") or []
    if len(first_entries) != len(second_entries):
        return False
    for a, b in zip(first_entries, second_entries):
        if (
            a.get("path") != b.get("path")
            or int(a.get("mtime", 0)) != int(b.get("mtime", 0))
            or int(a.get("size", 0)) != int(b.get("size", 0))
            or (a.get("type") or "") != (b.get("type") or "")
        ):
            return False
    return True


def sanitize_mod_folder_name(file_name):
    base_name = os.path.splitext(os.path.basename(file_name))[0]
    sanitized = re.sub(r"[\\/:*?\"<>|]", "_", base_name).strip()
    return sanitized or "mod"


def sanitize_archive_member_path(member_name):
    normalized = str(member_name).replace("\\", "/").strip()
    normalized = re.sub(r"/+", "/", normalized.lstrip("/"))
    if not normalized:
        return ""

    parts = []
    for raw_part in normalized.split("/"):
        part = raw_part.strip()
        if not part or part in {".", ".."}:
            continue
        safe_part = re.sub(r"[\\/:*?\"<>|]", "_", part)
        if safe_part:
            parts.append(safe_part)

    return "/".join(parts)


def _zipinfo_is_symlink(info):
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _member_should_be_skipped(parts, name):
    if not parts:
        return True
    first = parts[0].casefold()
    if first in {prefix.casefold() for prefix in IGNORED_ARCHIVE_PREFIXES}:
        return True
    for prefix in IGNORED_ARCHIVE_PREFIX_MATCHES:
        if first.startswith(prefix.casefold()):
            return True
    lowered = name.casefold()
    if lowered in IGNORED_ARCHIVE_FILENAMES:
        return True
    for prefix in IGNORED_ARCHIVE_NAME_PREFIXES:
        if lowered.startswith(prefix):
            return True
    return False


def _collapse_folder_name(parts):
    filtered = [part for part in parts if part]
    if not filtered:
        return ""
    if len(filtered) == 1:
        return filtered[0]
    return "-".join(filtered)


def _ensure_depth(parts):
    if len(parts) <= MAX_RELATIVE_DEPTH:
        return list(parts)
    folder = _collapse_folder_name(parts[:-1])
    if folder:
        return [folder, parts[-1]]
    return [parts[-1]]


def _register_directory(existing_dirs, parts, warnings):
    if not parts:
        return
    normalized = tuple(part.casefold() for part in parts)
    if normalized in existing_dirs:
        return
    existing_dirs.add(normalized)


def _ensure_unique_parts(existing_paths, existing_dirs, parts, warnings, *, is_dir=False):
    normalized = tuple(part.casefold() for part in parts)
    registry = existing_dirs if is_dir else existing_paths
    if normalized not in registry:
        registry.add(normalized)
        if not is_dir and parts[:-1]:
            _register_directory(existing_dirs, parts[:-1], warnings)
        return list(parts)

    base_name = parts[-1]
    if is_dir:
        stem = base_name
        suffix = ""
    else:
        stem, suffix = os.path.splitext(base_name)
    counter = 2
    while True:
        candidate_name = f"{stem}-v{counter}{suffix}"
        candidate_parts = list(parts[:-1]) + [candidate_name]
        normalized_candidate = tuple(part.casefold() for part in candidate_parts)
        if normalized_candidate not in registry:
            registry.add(normalized_candidate)
            if not is_dir:
                _register_directory(existing_dirs, candidate_parts[:-1], warnings)
            warnings.append(
                f"Conflit détecté pour '{base_name}', renommé en '{candidate_name}'."
            )
            return candidate_parts
        counter += 1


def _resolve_file_conflicts(target_root, relative_parts, warnings, written_paths):
    base_name = relative_parts[-1]
    stem, ext = os.path.splitext(base_name)
    if not stem:
        stem = "fichier"
    counter = 1
    renamed_target = None
    candidate_parts = list(relative_parts)

    while True:
        candidate_path = os.path.join(target_root, *candidate_parts)
        candidate_key = tuple(part.casefold() for part in candidate_parts)
        if candidate_key not in written_paths and not os.path.exists(candidate_path):
            written_paths.add(candidate_key)
            if renamed_target is not None:
                warnings.append(
                    f"Fichier existant détecté pour '{'/'.join(relative_parts)}', renommé en '{'/'.join(candidate_parts)}'."
                )
            return candidate_parts

        counter += 1
        renamed_target = f"{stem}-v{counter}{ext}"
        candidate_parts = list(relative_parts[:-1]) + [renamed_target]


def _preferred_parent_parts(entry):
    if len(entry["adjusted_parts"]) <= 1:
        return []
    folder = _collapse_folder_name(entry["adjusted_parts"][:-1])
    return [folder] if folder else []


def _organize_zip_entries(entries):
    plan_entries: List[ZipInstallEntry] = []
    warnings: List[str] = []
    existing_paths: Set[Tuple[str, ...]] = set()
    existing_dirs: Set[Tuple[str, ...]] = set()
    script_parents: Dict[str, Tuple[str, ...]] = {}
    scripts_by_base: Dict[str, List[Dict[str, object]]] = defaultdict(list)

    for entry in entries:
        if entry["is_ts4script"]:
            scripts_by_base[entry["base_name"]].append(entry)

    for entry in entries:
        if not entry["is_ts4script"]:
            continue
        normalized_name = (entry["name"].casefold(),)
        if normalized_name in existing_paths:
            module_base = sanitize_mod_folder_name(entry.get("raw_base") or entry["name"])
            module_base = module_base or "module"
            folder_candidate = module_base
            counter = 2
            while (folder_candidate.casefold(),) in existing_dirs:
                folder_candidate = f"{module_base}-v{counter}"
                counter += 1
            final_parts = _ensure_unique_parts(
                existing_paths,
                existing_dirs,
                [folder_candidate, entry["name"]],
                warnings,
            )
            script_parent = (final_parts[0],)
        else:
            final_parts = _ensure_unique_parts(
                existing_paths,
                existing_dirs,
                [entry["name"]],
                warnings,
            )
            script_parent = tuple(final_parts[:-1])
        script_parents[entry["member_name"]] = script_parent
        plan_entries.append(ZipInstallEntry(entry["member_name"], tuple(final_parts)))

    for entry in entries:
        if not entry["is_package"]:
            continue
        base_key = entry["base_name"]
        parent: Sequence[str] = []
        candidate_scripts = scripts_by_base.get(base_key, [])
        if candidate_scripts:
            script_entry = candidate_scripts[0]
            parent = script_parents.get(script_entry["member_name"], ())
        else:
            parent = _preferred_parent_parts(entry)
        final_parts = list(parent) + [entry["name"]]
        final_parts = _ensure_depth(final_parts)
        final_parts = _ensure_unique_parts(existing_paths, existing_dirs, final_parts, warnings)
        plan_entries.append(ZipInstallEntry(entry["member_name"], tuple(final_parts)))

    for entry in entries:
        if entry["is_ts4script"] or entry["is_package"]:
            continue
        parent = _preferred_parent_parts(entry)
        final_parts = parent + [entry["name"]]
        final_parts = _ensure_depth(final_parts)
        final_parts = _ensure_unique_parts(existing_paths, existing_dirs, final_parts, warnings)
        plan_entries.append(ZipInstallEntry(entry["member_name"], tuple(final_parts)))

    return plan_entries, warnings


def build_zip_install_plan(
    file_path,
    *,
    mod_directory,
    default_mod_name,
    existing_target=None,
):
    try:
        archive = zipfile.ZipFile(file_path, "r")
    except zipfile.BadZipFile as exc:
        return ZipPlanResult(False, None, f"Archive zip invalide : {exc}")

    with archive:
        entries: List[Dict[str, object]] = []
        for info in archive.infolist():
            sanitized = sanitize_archive_member_path(info.filename)
            if not sanitized:
                continue
            parts = sanitized.split("/")
            if not parts:
                continue
            name = parts[-1]
            if info.is_dir():
                if _member_should_be_skipped(parts, name):
                    continue
                continue
            if _zipinfo_is_symlink(info):
                return ZipPlanResult(False, None, f"Lien symbolique détecté dans l'archive : {info.filename}")
            extension = os.path.splitext(name)[1].lower()
            if extension in DISALLOWED_ARCHIVE_EXTENSIONS:
                return ZipPlanResult(False, None, f"Fichier interdit détecté : {name}")
            if _member_should_be_skipped(parts, name):
                continue
            raw_base = os.path.splitext(name)[0]
            entry = {
                "member_name": info.filename,
                "parts": parts,
                "name": name,
                "extension": extension,
                "is_ts4script": extension == ".ts4script",
                "is_package": extension == ".package",
                "base_name": raw_base.casefold(),
                "raw_base": raw_base,
            }
            entries.append(entry)

        if not entries:
            return ZipPlanResult(False, None, "Aucun fichier exploitable dans l'archive.")

        root_dirs: Set[str] = set()
        root_files_present = False
        for entry in entries:
            parts = entry["parts"]
            if len(parts) == 1:
                root_files_present = True
            else:
                root_dirs.add(parts[0])

        drop_segments = 0
        unique_root_name = ""
        if len(root_dirs) == 1 and not root_files_present:
            unique_root_name = next(iter(root_dirs))
            drop_segments = 1

        if existing_target:
            target_folder = existing_target
            mod_folder_name = os.path.basename(existing_target.rstrip("/\\")) or default_mod_name
        else:
            mod_folder_name = default_mod_name
            if unique_root_name:
                candidate = sanitize_mod_folder_name(unique_root_name)
                if candidate:
                    mod_folder_name = candidate
            target_folder = os.path.join(mod_directory, mod_folder_name)

        adjusted_entries: List[Dict[str, object]] = []
        for entry in entries:
            parts = entry["parts"][drop_segments:]
            if not parts:
                continue
            adjusted_entry = dict(entry)
            adjusted_entry["adjusted_parts"] = parts
            adjusted_entries.append(adjusted_entry)

        plan_entries, warnings = _organize_zip_entries(adjusted_entries)
        if not plan_entries:
            return ZipPlanResult(False, None, "Aucun fichier valide après normalisation de l'archive.")

        plan = ZipInstallPlan(
            mod_folder_name=mod_folder_name,
            target_folder=target_folder,
            entries=plan_entries,
            warnings=warnings,
        )
        return ZipPlanResult(True, plan, "")
def format_installation_display(iso_value):
    if not iso_value:
        return ""
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return iso_value
    return parsed.strftime("%d/%m/%Y %H:%M UTC")

def get_file_date(file_path):
    timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(timestamp)

def load_settings(path=SETTINGS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {}
    defaults = {
        "version_filter_start": "",
        "version_filter_end": "",
        "enable_version_filters": True,
        "show_package_mods": True,
        "show_ts4script_mods": True,
        "mod_directory": "",
        "sims_cache_directory": "",
        "backups_directory": "",
        "xls_file_path": "",
        "sims_executable_path": "",
        "sims_executable_arguments": "",
        "log_extra_extensions": [],
        "grab_logs_ignore_files": [],
        "ignored_mods": [],
        "show_ignored": False,
        "show_search_results": True,
        "instant_search": True,
        "file_filter_mode": "both",
        "auto_scan_on_start": True,
        "hidden_columns": [],
        "show_disabled_only": False,
        "log_level": "DEBUG",
    }
    for key, value in defaults.items():
        settings.setdefault(key, value)

    show_search_pref = settings.get("show_search_results")
    if isinstance(show_search_pref, str):
        normalized = show_search_pref.strip().lower()
        settings["show_search_results"] = normalized not in {"false", "0", "non", "no", "off"}
    else:
        settings["show_search_results"] = bool(show_search_pref)

    settings["enable_version_filters"] = bool(settings.get("enable_version_filters", True))
    legacy_combined_filter = settings.pop("filter_package_and_ts4script", None)
    if legacy_combined_filter is True:
        settings["show_package_mods"] = True
        settings["show_ts4script_mods"] = True
    legacy_hide_post_118 = settings.pop("hide_post_118", None)
    legacy_filter_range = settings.pop("filter_116_to_118", None)
    if not settings.get("version_filter_start") and legacy_filter_range:
        settings["version_filter_start"] = "1.116.202.1030"
    if not settings.get("version_filter_end") and (legacy_filter_range or legacy_hide_post_118):
        settings["version_filter_end"] = "1.118.242.1030"

    if isinstance(settings.get("log_extra_extensions"), str):
        settings["log_extra_extensions"] = [part.strip() for part in settings["log_extra_extensions"].split(",") if part.strip()]
    extra_extensions = []
    for entry in settings.get("log_extra_extensions", []):
        if not entry:
            continue
        ext = entry if entry.startswith(".") else f".{entry}"
        extra_extensions.append(ext.lower())
    settings["log_extra_extensions"] = sorted(set(extra_extensions))

    ignore_entries = settings.get("grab_logs_ignore_files", [])
    if isinstance(ignore_entries, str):
        raw_parts = re.split(r"[,;\n]+", ignore_entries)
    else:
        raw_parts = ignore_entries
    normalized_ignore = []
    seen = set()
    for part in raw_parts:
        if not part:
            continue
        cleaned = str(part).strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        normalized_ignore.append(cleaned)
    settings["grab_logs_ignore_files"] = normalized_ignore

    ignored_from_file = load_ignore_list()
    if not ignored_from_file and settings.get("ignored_mods"):
        ignored_from_file = settings.get("ignored_mods", [])
        save_ignore_list(ignored_from_file)
    settings["ignored_mods"] = ignored_from_file
    try:
        logging.getLogger("Sims4ModTool").debug("Settings loaded from %s", path)
    except Exception:
        pass
    return settings

def save_settings(settings, path=SETTINGS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)
    try:
        logging.getLogger("Sims4ModTool").debug("Settings saved to %s", path)
    except Exception:
        pass

def scan_directory(directory, progress_callback=None):
    logging.getLogger("Sims4ModTool").debug("Scanning directory: %s", directory)
    package_files = {}
    ts4script_files = {}
    snapshot_entries = []
    normalized_root = os.path.abspath(directory)
    relevant_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            lower_name = file.lower()
            if lower_name.endswith((".package", ".ts4script")):
                full_path = os.path.join(root, file)
                relevant_files.append((file, lower_name, full_path))

    total_files = len(relevant_files)
    if progress_callback is not None:
        try:
            progress_callback(0, total_files, "")
        except Exception:
            pass

    for index, (file, lower_name, full_path) in enumerate(relevant_files, start=1):
        if lower_name.endswith(".package"):
            package_files[file] = full_path
        else:
            ts4script_files[file] = full_path
        try:
            stat_result = os.stat(full_path)
        except OSError:
            continue
        relative_path = os.path.relpath(full_path, normalized_root)
        snapshot_entries.append({
            "path": relative_path.replace("\\", "/"),
            "mtime": int(stat_result.st_mtime),
            "size": int(stat_result.st_size),
            "type": "package" if lower_name.endswith(".package") else "ts4script",
        })
        if progress_callback is not None:
            try:
                progress_callback(index, total_files, full_path)
            except Exception:
                pass
    snapshot_entries.sort(key=lambda item: item["path"].casefold())
    snapshot = {
        "root": normalized_root.replace("\\", "/"),
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "entries": snapshot_entries,
    }
    logging.getLogger("Sims4ModTool").debug("Scan complete. Found %d relevant files", len(relevant_files))
    return package_files, ts4script_files, snapshot


def normalize_mod_basename(name):
    if not name:
        return ""
    base_name = os.path.splitext(os.path.basename(name))[0]
    normalized = MOD_NAME_SANITIZE_RE.sub("", base_name.casefold())
    return normalized


def stable_mod_name_hash(normalized_name):
    if not normalized_name:
        return 0
    digest = hashlib.sha1(normalized_name.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest, 16)


def similarity_confidence_label(ratio):
    if ratio >= 0.9:
        return "Élevée"
    if ratio >= 0.75:
        return "Moyenne"
    return "Faible"

def generate_data_rows(directory, settings, version_releases, progress_callback=None, yield_callback=None):
    package_files, ts4script_files, snapshot = scan_directory(directory, progress_callback=progress_callback)
    # Build path->mod group mapping from installed_mods.json if available
    group_by_path = {}
    disabled_by_path = {}
    try:
        installed = load_installed_mods()
    except Exception:
        installed = []
    for entry in installed:
        target_folder = entry.get("target_folder") or ""
        name = entry.get("name") or os.path.basename(target_folder) or ""
        if not target_folder:
            continue
        root = os.path.normcase(os.path.abspath(target_folder))
        # direct files list
        disabled_flag = bool(entry.get("disabled", False))
        for rel in (entry.get("files") or []):
            rel_norm = str(rel).replace("\\", "/").strip().lstrip("/")
            if not rel_norm:
                continue
            abs_path = os.path.join(root, *rel_norm.split("/"))
            key = os.path.normcase(os.path.abspath(abs_path))
            group_by_path[key] = name
            disabled_by_path[key] = disabled_flag
        # addons paths
        for addon in (entry.get("addons") or []):
            for rel in (addon.get("paths") or []):
                rel_norm = str(rel).replace("\\", "/").strip().lstrip("/")
                if not rel_norm:
                    continue
                abs_path = os.path.join(root, *rel_norm.split("/"))
                key = os.path.normcase(os.path.abspath(abs_path))
                group_by_path[key] = name
                disabled_by_path[key] = disabled_flag
    previous_snapshot = load_mod_scan_cache()
    snapshot_changed = previous_snapshot is not None and not mod_scan_snapshots_equal(previous_snapshot, snapshot)
    save_mod_scan_cache(snapshot)
    version_filters_enabled = settings.get("enable_version_filters", True)
    start_version = settings.get("version_filter_start") or ""
    end_version = settings.get("version_filter_end") or ""
    if not version_filters_enabled:
        start_version = ""
        end_version = ""
    start_date = version_releases.get(start_version)
    end_date = version_releases.get(end_version)
    start_limit = datetime.combine(start_date, time.min) if start_date else None
    latest_version_key = next(reversed(version_releases)) if version_releases else None
    if end_version and latest_version_key and end_version == latest_version_key:
        end_limit = datetime.combine(date.today(), time.max)
    else:
        end_limit = datetime.combine(end_date, time.max) if end_date else None
    if start_limit and end_limit and start_limit > end_limit:
        start_limit, end_limit = end_limit, start_limit

    data_rows = []
    throttle_counter = 0

    def _maybe_yield():
        nonlocal throttle_counter
        if yield_callback is None:
            return
        throttle_counter += 1
        if throttle_counter % 25 != 0:
            return
        try:
            yield_callback()
        except Exception:
            pass
    ignored_mods = set(settings.get("ignored_mods", []))
    show_ignored = settings.get("show_ignored", False)
    # derive file filter mode
    mode = (settings.get("file_filter_mode") or "both").strip().lower()
    if mode not in {"both", "package", "ts4script", "installer_only"}:
        mode = "both"
    show_packages = mode in {"both", "package", "installer_only"}
    show_scripts = mode in {"both", "ts4script", "installer_only"}

    def _resolve_parent(path):
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(os.path.dirname(path)))

    package_entries = {}
    for pkg, pkg_path in package_files.items():
        normalized_name = normalize_mod_basename(pkg)
        hash_source = normalized_name or os.path.splitext(pkg)[0].casefold()
        package_entries[pkg] = {
            "path": pkg_path,
            "base": os.path.splitext(pkg)[0],
            "normalized": normalized_name,
            "parent": _resolve_parent(pkg_path),
            "hash": stable_mod_name_hash(hash_source),
        }

    script_entries = {}
    for script, script_path in ts4script_files.items():
        normalized_name = normalize_mod_basename(script)
        hash_source = normalized_name or os.path.splitext(script)[0].casefold()
        script_entries[script] = {
            "path": script_path,
            "base": os.path.splitext(script)[0],
            "normalized": normalized_name,
            "parent": _resolve_parent(script_path),
            "hash": stable_mod_name_hash(hash_source),
        }

    unpaired_packages = set(package_entries.keys())
    unpaired_scripts = set(script_entries.keys())
    matches: Dict[str, Dict[str, str]] = {}

    # Pass 1 – même base normalisée
    scripts_by_norm = defaultdict(list)
    for script_name in unpaired_scripts:
        scripts_by_norm[script_entries[script_name]["normalized"]].append(script_name)
    for script_list in scripts_by_norm.values():
        script_list.sort(key=str.casefold)

    for pkg_name in list(unpaired_packages):
        pkg_info = package_entries[pkg_name]
        norm_name = pkg_info["normalized"]
        if not norm_name:
            continue
        candidates = scripts_by_norm.get(norm_name)
        if not candidates:
            continue
        script_name = next((candidate for candidate in candidates if candidate in unpaired_scripts), None)
        if not script_name:
            continue
        normalized_display = norm_name or pkg_info["base"].casefold()
        matches[pkg_name] = {
            "script": script_name,
            "confidence": "Élevée",
            "tooltip": (
                f"Appariement basé sur un nom normalisé identique ({normalized_display})."
            ),
        }
        unpaired_packages.remove(pkg_name)
        unpaired_scripts.remove(script_name)

    # Pass 2 – même dossier parent
    scripts_by_parent = defaultdict(list)
    for script_name in unpaired_scripts:
        scripts_by_parent[script_entries[script_name]["parent"]].append(script_name)
    for script_list in scripts_by_parent.values():
        script_list.sort(key=str.casefold)

    for pkg_name in list(unpaired_packages):
        pkg_info = package_entries[pkg_name]
        parent = pkg_info["parent"]
        candidates = scripts_by_parent.get(parent)
        if not candidates:
            continue
        script_name = next((candidate for candidate in candidates if candidate in unpaired_scripts), None)
        if not script_name:
            continue
        try:
            rel_parent = os.path.relpath(parent, directory) if parent else "."
        except ValueError:
            rel_parent = parent
        if rel_parent in (".", ""):
            folder_display = "(racine du dossier mods)"
        else:
            folder_display = rel_parent.replace("\\", "/")
        tooltip = (
            f"Appariement basé sur le même dossier parent : {folder_display}."
        )
        matches[pkg_name] = {
            "script": script_name,
            "confidence": "Moyenne",
            "tooltip": tooltip,
        }
        unpaired_packages.remove(pkg_name)
        unpaired_scripts.remove(script_name)

    # Pass 3 – similarité + fallback hash
    scripts_by_prefix = defaultdict(list)
    scripts_by_length = defaultdict(list)
    for script_name in unpaired_scripts:
        info = script_entries[script_name]
        normalized = info["normalized"] or info["base"].casefold()
        if normalized:
            if len(normalized) >= 2:
                scripts_by_prefix[(2, normalized[:2])].append(script_name)
            scripts_by_prefix[(1, normalized[:1])].append(script_name)
        else:
            scripts_by_prefix[(0, "")].append(script_name)
        scripts_by_length[len(normalized)].append(script_name)
    for script_list in scripts_by_prefix.values():
        script_list.sort(key=str.casefold)

    similarity_candidates = []
    for pkg_name in list(unpaired_packages):
        pkg_info = package_entries[pkg_name]
        normalized = pkg_info["normalized"] or pkg_info["base"].casefold()
        if not normalized and not pkg_info["base"]:
            continue
        prefixes = []
        if normalized:
            if len(normalized) >= 2:
                prefixes.append((2, normalized[:2]))
            prefixes.append((1, normalized[:1]))
        else:
            base_lower = pkg_info["base"].casefold()
            if len(base_lower) >= 2:
                prefixes.append((2, base_lower[:2]))
            if base_lower:
                prefixes.append((1, base_lower[:1]))
        if not prefixes:
            prefixes.append((0, ""))

        seen_scripts = set()
        for prefix in prefixes:
            for script_name in scripts_by_prefix.get(prefix, []):
                if script_name not in unpaired_scripts or script_name in seen_scripts:
                    continue
                seen_scripts.add(script_name)
                script_info = script_entries[script_name]
                script_norm = script_info["normalized"] or script_info["base"].casefold()
                ratio = SequenceMatcher(None, normalized, script_norm).ratio()
                if ratio < MIN_SIMILARITY_RATIO:
                    continue
                hash_gap = abs(pkg_info["hash"] - script_info["hash"])
                similarity_candidates.append((ratio, hash_gap, pkg_name, script_name))
                if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                    break
            if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                break

        if not seen_scripts:
            target_length = len(normalized)
            length_offsets = [0, 1, -1, 2, -2]
            for offset in length_offsets:
                candidate_length = target_length + offset
                if candidate_length < 0:
                    continue
                for script_name in scripts_by_length.get(candidate_length, []):
                    if script_name not in unpaired_scripts or script_name in seen_scripts:
                        continue
                    seen_scripts.add(script_name)
                    script_info = script_entries[script_name]
                    script_norm = script_info["normalized"] or script_info["base"].casefold()
                    ratio = SequenceMatcher(None, normalized, script_norm).ratio()
                    if ratio < MIN_SIMILARITY_RATIO:
                        continue
                    hash_gap = abs(pkg_info["hash"] - script_info["hash"])
                    similarity_candidates.append((ratio, hash_gap, pkg_name, script_name))
                    if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                        break
                if len(seen_scripts) >= MAX_SIMILARITY_CANDIDATES:
                    break

    similarity_candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))

    for ratio, hash_gap, pkg_name, script_name in similarity_candidates:
        if pkg_name not in unpaired_packages or script_name not in unpaired_scripts:
            continue
        confidence = similarity_confidence_label(ratio)
        hash_note = f" (écart hash {hash_gap})" if hash_gap else ""
        tooltip = (
            f"Appariement basé sur la similarité des noms (SequenceMatcher {ratio:.2f}). "
            f"Départage assuré par un hash stable pour les égalités{hash_note}."
        )
        matches[pkg_name] = {
            "script": script_name,
            "confidence": confidence,
            "tooltip": tooltip,
        }
        unpaired_packages.remove(pkg_name)
        unpaired_scripts.remove(script_name)

    # Lignes finales
    for pkg, pkg_info in package_entries.items():
        pkg_path = pkg_info["path"]
        pkg_date = get_file_date(pkg_path)
        match_info = matches.get(pkg)
        script_name = match_info["script"] if match_info else ""
        script_path = ts4script_files.get(script_name) if script_name else None
        script_date = get_file_date(script_path) if script_path else None

        mod_latest_date = max((dt for dt in (pkg_date, script_date) if dt is not None), default=None)

        if end_limit and mod_latest_date and mod_latest_date > end_limit:
            continue
        if start_limit and mod_latest_date and mod_latest_date < start_limit:
            continue

        has_package = True
        has_script = script_path is not None
        if not ((has_package and show_packages) or (has_script and show_scripts)):
            continue

        candidates = [name for name in (pkg, script_name if script_path else None) if name]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue

        status = "X" if script_path else "MS"
        version = estimate_version_from_dates(pkg_date, script_date, version_releases)
        confidence_value = match_info["confidence"] if match_info else "—"
        confidence_tooltip = match_info["tooltip"] if match_info else "Aucun appariement détecté."

        # Resolve group and disabled via tracked paths
        group_value = ""
        disabled_value = False
        for p in (pkg_path, script_path):
            if not p:
                continue
            key = os.path.normcase(os.path.abspath(p))
            if not group_value:
                group_value = group_by_path.get(key, "")
            if not disabled_value:
                disabled_value = bool(disabled_by_path.get(key, False))

        if mode == "installer_only" and not group_value:
            _maybe_yield()
            continue
        data_rows.append({
            "status": status,
            "group": group_value,
            "disabled": disabled_value,
            "package": pkg,
            "package_date": format_datetime(pkg_date),
            "script": script_name if script_path else "",
            "script_date": format_datetime(script_date),
            "version": version,
            "confidence": confidence_value,
            "confidence_tooltip": confidence_tooltip,
            "ignored": ignored,
            "ignore_candidates": candidates or [pkg],
            "paths": [path for path in (pkg_path, script_path) if path],
        })
        _maybe_yield()

    for script_name in sorted(unpaired_scripts, key=str.casefold):
        script_path = ts4script_files.get(script_name)
        if not script_path:
            continue
        script_date = get_file_date(script_path)

        if end_limit and script_date and script_date > end_limit:
            continue
        if start_limit and script_date and script_date < start_limit:
            continue
        if not show_scripts:
            continue

        candidates = [script_name]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue

        status = "MP"
        version = estimate_version_from_dates(None, script_date, version_releases)

        group_value = ""
        key = os.path.normcase(os.path.abspath(script_path)) if script_path else None
        disabled_value = False
        if key:
            group_value = group_by_path.get(key, "")
            disabled_value = bool(disabled_by_path.get(key, False))
        if mode == "installer_only" and not group_value:
            _maybe_yield()
            continue
        data_rows.append({
            "status": status,
            "group": group_value,
            "disabled": disabled_value,
            "package": "",
            "package_date": "",
            "script": script_name,
            "script_date": format_datetime(script_date),
            "version": version,
            "confidence": "—",
            "confidence_tooltip": "Aucun package correspondant trouvé.",
            "ignored": ignored,
            "ignore_candidates": candidates,
            "paths": [script_path],
        })
        _maybe_yield()

    if yield_callback is not None:
        try:
            yield_callback()
        except Exception:
            pass

    return data_rows, snapshot_changed

def export_to_excel(save_path, data_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Mods"

    headers = [
        "État",
        "Fichier .package",
        "Date .package",
        "Fichier .ts4script",
        "Date .ts4script",
        "Version",
        "Confiance",
        "Ignoré",
    ]
    for idx, h in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=h)

    for row_idx, row in enumerate(data_rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    wb.save(save_path)


class AddUpdateDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter une mise à jour")
        self.setModal(True)

        layout = QtWidgets.QFormLayout(self)
        self.version_edit = QtWidgets.QLineEdit(self)
        self.version_edit.setPlaceholderText("1.118.257.1020")
        self.date_edit = QtWidgets.QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setDate(QtCore.QDate.currentDate())

        layout.addRow("Numéro de version :", self.version_edit)
        layout.addRow("Date de sortie :", self.date_edit)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        if not self.version_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Informations manquantes", "Indique un numéro de version valide.")
            return
        super().accept()

    def get_values(self):
        return self.version_edit.text().strip(), self.date_edit.date()


class ConfigurationDialog(QtWidgets.QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setModal(True)
        self.resize(780, 680)
        self._parent = parent

        layout = QtWidgets.QVBoxLayout()

        # Section: Chemins
        section_paths = QtWidgets.QLabel("Chemins")
        f = section_paths.font()
        f.setBold(True)
        section_paths.setFont(f)
        layout.addWidget(section_paths)

        self.mod_directory_edit = QtWidgets.QLineEdit(self)
        self.mod_directory_edit.setText(settings.get("mod_directory", ""))
        mod_dir_browse = QtWidgets.QPushButton("Parcourir...")
        mod_dir_browse.clicked.connect(lambda: self._browse_directory(self.mod_directory_edit))

        mod_dir_layout = QtWidgets.QHBoxLayout()
        mod_dir_layout.addWidget(QtWidgets.QLabel("Dossier des mods :"))
        mod_dir_layout.addWidget(self.mod_directory_edit)
        mod_dir_layout.addWidget(mod_dir_browse)
        layout.addLayout(mod_dir_layout)

        self.cache_directory_edit = QtWidgets.QLineEdit(self)
        self.cache_directory_edit.setText(settings.get("sims_cache_directory", ""))
        cache_dir_browse = QtWidgets.QPushButton("Parcourir...")
        cache_dir_browse.clicked.connect(lambda: self._browse_directory(self.cache_directory_edit))

        cache_dir_layout = QtWidgets.QHBoxLayout()
        cache_dir_layout.addWidget(QtWidgets.QLabel("Dossier caches sims :"))
        cache_dir_layout.addWidget(self.cache_directory_edit)
        cache_dir_layout.addWidget(cache_dir_browse)
        layout.addLayout(cache_dir_layout)

        self.backups_directory_edit = QtWidgets.QLineEdit(self)
        self.backups_directory_edit.setText(settings.get("backups_directory", ""))
        backups_dir_browse = QtWidgets.QPushButton("Parcourir...")
        backups_dir_browse.clicked.connect(lambda: self._browse_directory(self.backups_directory_edit))

        backups_dir_layout = QtWidgets.QHBoxLayout()
        backups_dir_layout.addWidget(QtWidgets.QLabel("Dossier Backups :"))
        backups_dir_layout.addWidget(self.backups_directory_edit)
        backups_dir_layout.addWidget(backups_dir_browse)
        layout.addLayout(backups_dir_layout)

        layout.addSpacing(6)
        section_exec = QtWidgets.QLabel("Sims 4")
        section_exec.setFont(f)
        layout.addWidget(section_exec)

        self.sims_executable_edit = QtWidgets.QLineEdit(self)
        self.sims_executable_edit.setText(settings.get("sims_executable_path", ""))
        sims_exec_browse = QtWidgets.QPushButton("Parcourir...")
        sims_exec_browse.clicked.connect(self._browse_executable)

        sims_exec_layout = QtWidgets.QHBoxLayout()
        sims_exec_layout.addWidget(QtWidgets.QLabel("Exécutable TS4_X64.exe :"))
        sims_exec_layout.addWidget(self.sims_executable_edit)
        sims_exec_layout.addWidget(sims_exec_browse)
        layout.addLayout(sims_exec_layout)

        self.sims_arguments_edit = QtWidgets.QLineEdit(self)
        self.sims_arguments_edit.setText(settings.get("sims_executable_arguments", ""))
        self.sims_arguments_edit.setPlaceholderText("Arguments supplémentaires (ex: -w)")

        sims_args_layout = QtWidgets.QHBoxLayout()
        sims_args_layout.addWidget(QtWidgets.QLabel("Arguments TS4_X64.exe :"))
        sims_args_layout.addWidget(self.sims_arguments_edit)
        layout.addLayout(sims_args_layout)

        layout.addSpacing(6)
        section_logs = QtWidgets.QLabel("Logs")
        section_logs.setFont(f)
        layout.addWidget(section_logs)

        self.log_extensions_edit = QtWidgets.QLineEdit(self)
        extra_extensions = ", ".join(settings.get("log_extra_extensions", []))
        self.log_extensions_edit.setText(extra_extensions)
        self.log_extensions_edit.setPlaceholderText("Extensions supplémentaires (.mdmp, .html, ...)")

        logs_ext_layout = QtWidgets.QHBoxLayout()
        logs_ext_layout.addWidget(QtWidgets.QLabel("Extensions de logs (supplémentaires) :"))
        logs_ext_layout.addWidget(self.log_extensions_edit)
        layout.addLayout(logs_ext_layout)

        self.grab_logs_ignore_edit = QtWidgets.QPlainTextEdit(self)
        self.grab_logs_ignore_edit.setPlaceholderText("last_crash.txt\nExceptionLog.txt")
        ignore_lines = "\n".join(settings.get("grab_logs_ignore_files", []))
        self.grab_logs_ignore_edit.setPlainText(ignore_lines)
        self.grab_logs_ignore_edit.setFixedHeight(100)

        ignore_layout = QtWidgets.QVBoxLayout()
        ignore_layout.addWidget(QtWidgets.QLabel("Fichiers de logs à ignorer (un par ligne ou séparés par des virgules) :"))
        ignore_layout.addWidget(self.grab_logs_ignore_edit)
        layout.addLayout(ignore_layout)

        # Niveau de logs
        self.log_level_combo = QtWidgets.QComboBox(self)
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        current_level = str(settings.get("log_level", "DEBUG")).upper()
        idx = self.log_level_combo.findText(current_level)
        self.log_level_combo.setCurrentIndex(idx if idx != -1 else 0)

        log_level_layout = QtWidgets.QHBoxLayout()
        log_level_layout.addWidget(QtWidgets.QLabel("Niveau de logs :"))
        log_level_layout.addWidget(self.log_level_combo)
        layout.addLayout(log_level_layout)

        # Options de démarrage
        self.auto_scan_checkbox = QtWidgets.QCheckBox("Scan automatique au démarrage", self)
        self.auto_scan_checkbox.setChecked(bool(settings.get("auto_scan_on_start", True)))
        layout.addWidget(self.auto_scan_checkbox)

        version_group = QtWidgets.QGroupBox("Gestion des versions de patch", self)
        version_layout = QtWidgets.QVBoxLayout(version_group)
        self.version_list_widget = QtWidgets.QListWidget(version_group)
        self.version_list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.version_list_widget.setMinimumHeight(150)
        version_layout.addWidget(self.version_list_widget)
        self.add_version_button = QtWidgets.QPushButton("Add update info", version_group)
        self.add_version_button.clicked.connect(self._open_add_version_dialog)
        version_layout.addWidget(self.add_version_button)
        layout.addWidget(version_group)

        self._refresh_version_list()

        button_box = QtWidgets.QDialogButtonBox()
        save_button = button_box.addButton("Sauvegarder", QtWidgets.QDialogButtonBox.AcceptRole)
        cancel_button = button_box.addButton(QtWidgets.QDialogButtonBox.Cancel)
        save_button.clicked.connect(self._save_configuration)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _refresh_version_list(self):
        if not hasattr(self, "version_list_widget"):
            return
        self.version_list_widget.clear()
        if self._parent is None:
            return
        for version, release_date in self._parent.get_version_entries():
            self.version_list_widget.addItem(f"{version} – {format_release_date(release_date)}")

    def _open_add_version_dialog(self):
        if self._parent is None:
            return
        dialog = AddUpdateDialog(self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        version, release_date = dialog.get_values()
        success, message = self._parent.add_version_release(version, release_date)
        if success:
            QtWidgets.QMessageBox.information(self, "Version ajoutée", message)
            self._refresh_version_list()
        else:
            QtWidgets.QMessageBox.warning(self, "Ajout impossible", message)

    def _browse_directory(self, target_edit):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if folder:
            target_edit.setText(folder)

    def _browse_executable(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Sélectionner TS4_X64.exe",
            "",
            "Executable Sims 4 (TS4_X64.exe);;Tous les fichiers (*)"
        )
        if file_path:
            self.sims_executable_edit.setText(file_path)

    def _save_configuration(self):
        mod_directory = self.mod_directory_edit.text().strip()
        cache_directory = self.cache_directory_edit.text().strip()
        backups_directory = self.backups_directory_edit.text().strip()
        sims_executable_path = self.sims_executable_edit.text().strip()
        sims_executable_arguments = self.sims_arguments_edit.text().strip()
        log_extensions_text = self.log_extensions_edit.text().strip()
        ignore_text = self.grab_logs_ignore_edit.toPlainText()
        log_level_value = self.log_level_combo.currentText().strip().upper()
        auto_scan_on_start = bool(self.auto_scan_checkbox.isChecked())

        extra_extensions = []
        if log_extensions_text:
            for part in re.split(r"[,;\s]+", log_extensions_text):
                cleaned = part.strip()
                if not cleaned:
                    continue
                if not cleaned.startswith("."):
                    cleaned = f".{cleaned}"
                extra_extensions.append(cleaned.lower())

        ignore_files = []
        seen_ignore = set()
        if ignore_text:
            for part in re.split(r"[,;\n]+", ignore_text):
                cleaned = part.strip()
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen_ignore:
                    continue
                seen_ignore.add(key)
                ignore_files.append(cleaned)

        if self._parent is not None:
            self._parent.apply_configuration(
                mod_directory,
                cache_directory,
                backups_directory,
                sims_executable_path,
                sims_executable_arguments,
                sorted(set(extra_extensions)),
                ignore_files,
                log_level_value,
                auto_scan_on_start,
            )
        self.accept()


class FileDropDialog(QtWidgets.QDialog):
    def __init__(self, title, instruction, drop_handler, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 300)
        self.setAcceptDrops(True)
        self._drop_handler = drop_handler

        layout = QtWidgets.QVBoxLayout(self)

        info_label = QtWidgets.QLabel(instruction, self)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.drop_label = QtWidgets.QLabel("Déposez vos fichiers ici", self)
        self.drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self.drop_label.setMinimumHeight(100)
        self._drop_idle_style = "QLabel { border: 2px dashed #aaaaaa; padding: 24px; background-color: #3a3a3a; }"
        self._drop_active_style = "QLabel { border: 2px solid #00aa88; padding: 24px; background-color: #2a2a2a; }"
        self.drop_label.setStyleSheet(self._drop_idle_style)
        layout.addWidget(self.drop_label)

        close_button = QtWidgets.QPushButton("Fermer", self)
        close_button.clicked.connect(self.reject)
        layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

    def dragEnterEvent(self, event):
        if self._contains_supported_files(event):
            event.acceptProposedAction()
            self._set_drop_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self._set_drop_active(False)

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            self._set_drop_active(False)
            return

        file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        success_messages, error_messages = self._drop_handler(file_paths)

        if success_messages:
            QtWidgets.QMessageBox.information(
                self,
                "Opération terminée",
                "\n".join(success_messages),
            )
        if error_messages:
            QtWidgets.QMessageBox.warning(
                self,
                "Certaines opérations ont échoué",
                "\n".join(error_messages),
            )

        if success_messages and not error_messages:
            self.accept()
        elif success_messages:
            # Laisser la fenêtre ouverte pour d'éventuels ajouts complémentaires
            self._set_drop_active(False)
        else:
            self._set_drop_active(False)

        event.acceptProposedAction()

    def _contains_supported_files(self, event):
        if not event.mimeData().hasUrls():
            return False
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            if os.path.splitext(url.toLocalFile())[1].lower() in SUPPORTED_INSTALL_EXTENSIONS:
                return True
        return False

    def _set_drop_active(self, active):
        self.drop_label.setStyleSheet(self._drop_active_style if active else self._drop_idle_style)


class ModInstallerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, mod_directory=""):
        super().__init__(parent)
        self.setWindowTitle("Mod Installer")
        self.setModal(True)
        self.resize(720, 420)
        self.setAcceptDrops(True)

        self.mod_directory = mod_directory
        self.installations_performed = False
        self.installed_mods = load_installed_mods()

        layout = QtWidgets.QVBoxLayout(self)

        info_label = QtWidgets.QLabel(
            "Glissez-déposez un fichier .package, .ts4script ou .zip pour l'installer dans le dossier des mods configuré."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        mod_dir_display = mod_directory if mod_directory else "(dossier non défini)"
        self.target_directory_label = QtWidgets.QLabel(f"Dossier cible : {mod_dir_display}")
        self.target_directory_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.target_directory_label)

        self.drop_label = QtWidgets.QLabel("Déposez vos fichiers ici")
        self.drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self.drop_label.setMinimumHeight(80)
        self._drop_idle_style = "QLabel { border: 2px dashed #aaaaaa; padding: 24px; background-color: #3a3a3a; }"
        self._drop_active_style = "QLabel { border: 2px solid #00aa88; padding: 24px; background-color: #2a2a2a; }"
        self.drop_label.setStyleSheet(self._drop_idle_style)
        layout.addWidget(self.drop_label)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Mod",
            "Type",
            "Installé le",
            "Version",
            "URL",
            "Dossier",
            "Addons",
            "Statut",
        ])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, self.table.columnCount()):
            self.table.horizontalHeader().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, stretch=1)

        footer_layout = QtWidgets.QHBoxLayout()
        self.recovery_button = QtWidgets.QPushButton("Recovery list", self)
        self.recovery_button.clicked.connect(self._recover_from_markers)
        footer_layout.addWidget(self.recovery_button)

        footer_layout.addStretch(1)
        close_button = QtWidgets.QPushButton("Fermer", self)
        close_button.clicked.connect(self.accept)
        footer_layout.addWidget(close_button)
        layout.addLayout(footer_layout)

        self.refresh_table()

    def dragEnterEvent(self, event):
        if self._contains_supported_files(event):
            event.acceptProposedAction()
            self._set_drop_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self._set_drop_active(False)

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            self._set_drop_active(False)
            return

        file_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        success_entries = []
        error_messages = []

        for path in file_paths:
            success, message = self.install_mod_from_path(path)
            if success and message:
                success_entries.append(message)
            elif (not success) and message:
                error_messages.append(message)

        if success_entries:
            QtWidgets.QMessageBox.information(
                self,
                "Installation terminée",
                "\n".join(success_entries),
            )
        if error_messages:
            QtWidgets.QMessageBox.warning(
                self,
                "Installation incomplète",
                "\n".join(error_messages),
            )

        event.acceptProposedAction()
        self._set_drop_active(False)

    def _set_drop_active(self, active):
        self.drop_label.setStyleSheet(self._drop_active_style if active else self._drop_idle_style)

    def _contains_supported_files(self, event):
        if not event.mimeData().hasUrls():
            return False
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            if self._is_supported_extension(url.toLocalFile()):
                return True
        return False

    @staticmethod
    def _is_supported_extension(file_path):
        return os.path.splitext(file_path)[1].lower() in SUPPORTED_INSTALL_EXTENSIONS

    def _collect_tracked_folders(self):
        tracked = set()
        for entry in self.installed_mods:
            folder = entry.get("target_folder")
            if not folder:
                continue
            normalized = os.path.normcase(os.path.abspath(folder))
            tracked.add(normalized)
        return tracked

    def _find_untracked_duplicates(self, file_path):
        if not self.mod_directory or not os.path.isdir(self.mod_directory):
            return []
        file_name = os.path.basename(file_path)
        if not file_name:
            return []
        tracked = self._collect_tracked_folders()
        duplicates = []
        for root, dirs, files in os.walk(self.mod_directory):
            for candidate in files:
                if candidate.lower() != file_name.lower():
                    continue
                candidate_path = os.path.join(root, candidate)
                try:
                    if os.path.samefile(candidate_path, file_path):
                        continue
                except OSError:
                    pass
                parent_dir = os.path.normcase(os.path.abspath(root))
                if parent_dir in tracked:
                    continue
                duplicates.append(os.path.abspath(candidate_path))
        return duplicates

    def install_mod_from_path(self, file_path):
        if not os.path.isfile(file_path):
            return False, f"Fichier introuvable : {file_path}"

        if not self._is_supported_extension(file_path):
            return False, f"Extension non supportée : {os.path.basename(file_path)}"

        if not self.mod_directory or not os.path.isdir(self.mod_directory):
            return False, "Définissez d'abord un dossier de mods valide dans la configuration."

        sanitized_name = sanitize_mod_folder_name(file_path)
        extension = os.path.splitext(file_path)[1].lower()
        zip_plan = None
        display_name = os.path.splitext(os.path.basename(file_path))[0]

        duplicates_to_replace: List[str] = []

        if extension == ".zip":
            plan_result = build_zip_install_plan(
                file_path,
                mod_directory=self.mod_directory,
                default_mod_name=sanitized_name,
            )
            if not plan_result.success or plan_result.plan is None:
                return False, plan_result.message or "Impossible de préparer l'installation de l'archive."
            zip_plan = plan_result.plan
            sanitized_name = zip_plan.mod_folder_name
            target_folder = zip_plan.target_folder
            display_name = sanitized_name
        else:
            target_folder = os.path.join(self.mod_directory, sanitized_name)
            duplicates_to_replace = self._find_untracked_duplicates(file_path)
            if duplicates_to_replace:
                message_lines = [
                    "Le fichier existe déjà dans le dossier des mods en dehors du Mod Installer.",
                    "Chemins détectés :",
                ]
                message_lines.extend(duplicates_to_replace)
                message_lines.append("")
                message_lines.append("Souhaites-tu remplacer ces occurrences ?")
                response = QtWidgets.QMessageBox.question(
                    self,
                    "Fichier déjà présent",
                    "\n".join(message_lines),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.Yes,
                )
                if response != QtWidgets.QMessageBox.Yes:
                    duplicates_to_replace = []

        replace_existing = False
        if not duplicates_to_replace and os.path.exists(target_folder):
            response = QtWidgets.QMessageBox.question(
                self,
                "Mod déjà installé",
                (
                    f"Le mod '{sanitized_name}' existe déjà dans le dossier des mods.\n"
                    "Voulez-vous le mettre à jour avec le fichier sélectionné ?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if response != QtWidgets.QMessageBox.Yes:
                return False, f"Installation de '{display_name}' annulée."
            replace_existing = True

        if duplicates_to_replace:
            parent_directories = []
            for duplicate_path in duplicates_to_replace:
                parent_dir = os.path.dirname(duplicate_path)
                if parent_dir not in parent_directories:
                    parent_directories.append(parent_dir)
            success_messages = []
            for parent_dir in parent_directories:
                success, install_message, installed_paths = self._install_file_to_target(
                    file_path,
                    parent_dir,
                    clean_before=False,
                    merge=True,
                    zip_plan=None,
                    skip_existing_prompt=True,
                )
                if not success:
                    return False, install_message
                success_messages.append(install_message)
                installed_at = datetime.utcnow().replace(microsecond=0).isoformat()
                entry = {
                    "name": display_name,
                    "type": self._describe_install_type([file_path]),
                    "installed_at": installed_at,
                    "target_folder": parent_dir,
                    "source": os.path.basename(file_path),
                    "addons": [],
                    "files": list(installed_paths or []),
                }
                self._record_installation(entry)
                self._write_marker_file(parent_dir, entry)
            self.installations_performed = True
            return True, "\n".join(success_messages)

        success, install_message, installed_paths = self._install_file_to_target(
            file_path,
            target_folder,
            clean_before=replace_existing,
            merge=False,
            zip_plan=zip_plan,
        )
        if not success:
            return False, install_message

        installed_at = datetime.utcnow().replace(microsecond=0).isoformat()
        entry = {
            "name": display_name,
            "type": self._describe_install_type([file_path]),
            "installed_at": installed_at,
            "target_folder": target_folder,
            "source": os.path.basename(file_path),
            "addons": [],
            "files": list(installed_paths or []),
        }
        self._record_installation(entry)
        self._write_marker_file(target_folder, entry)

        self.installations_performed = True
        final_message = install_message or f"'{display_name}' installé avec succès."
        return True, final_message

    def _install_file_to_target(
        self,
        file_path,
        target_folder,
        *,
        clean_before=False,
        merge=False,
        zip_plan=None,
        skip_existing_prompt=False,
    ):
        extension = os.path.splitext(file_path)[1].lower()
        installed_entries = []
        plan_warnings: List[str] = []

        if clean_before and os.path.exists(target_folder):
            try:
                shutil.rmtree(target_folder)
            except OSError as exc:
                return False, f"Impossible de nettoyer le dossier existant : {exc}", []

        if extension == ".zip" and not zipfile.is_zipfile(file_path):
            return False, f"Le fichier n'est pas une archive zip valide : {os.path.basename(file_path)}", []

        try:
            os.makedirs(target_folder, exist_ok=True)
        except OSError as exc:
            return False, f"Impossible de créer le dossier cible : {exc}", []

        try:
            if extension in {".package", ".ts4script"}:
                destination_path = os.path.join(target_folder, os.path.basename(file_path))
                if os.path.exists(destination_path) and not clean_before:
                    if skip_existing_prompt:
                        response = QtWidgets.QMessageBox.Yes
                    else:
                        response = QtWidgets.QMessageBox.question(
                            self,
                            "Fichier déjà présent",
                            (
                                f"Le fichier '{os.path.basename(file_path)}' existe déjà dans le dossier cible.\n"
                                "Souhaitez-vous le remplacer ?"
                            ),
                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                            QtWidgets.QMessageBox.Yes,
                        )
                    if response != QtWidgets.QMessageBox.Yes:
                        return False, f"Copie de '{os.path.basename(file_path)}' annulée.", []
                shutil.copy2(file_path, destination_path)
                installed_entries.append(os.path.basename(destination_path))
            elif extension == ".zip":
                # Extract ZIP preserving internal folder/file names (no renaming), with safety checks
                target_root = os.path.abspath(target_folder)
                with zipfile.ZipFile(file_path, "r") as archive:
                    for info in archive.infolist():
                        member_name = str(info.filename)
                        norm = member_name.replace("\\", "/").lstrip("/").strip()
                        if not norm or norm.endswith("/"):
                            continue  # directory entries handled implicitly
                        parts = [p for p in norm.split("/") if p and p not in {".", ".."}]
                        if not parts:
                            continue
                        # Skip ignored prefixes and files
                        if _member_should_be_skipped(parts, parts[0]):
                            continue
                        # Disallow dangerous extensions
                        _, ext = os.path.splitext(parts[-1])
                        if ext.lower() in DISALLOWED_ARCHIVE_EXTENSIONS:
                            plan_warnings.append(f"Fichier ignoré pour sécurité: {norm}")
                            continue
                        dest_path = os.path.abspath(os.path.join(target_root, *parts))
                        if os.path.commonpath([target_root, dest_path]) != target_root:
                            continue
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        try:
                            with archive.open(info, "r") as source, open(dest_path, "wb") as target_file:
                                shutil.copyfileobj(source, target_file)
                            # Preserve timestamp if present
                            try:
                                dt = datetime(*info.date_time)
                                os.utime(dest_path, (dt.timestamp(), dt.timestamp()))
                            except Exception:
                                pass
                            rel_display = "/".join(parts)
                            installed_entries.append(rel_display)
                        except OSError as exc:
                            plan_warnings.append(f"Écriture impossible: {norm} → {exc}")

                if not installed_entries:
                    return False, "L'archive ne contient aucun fichier exploitable.", []
            else:
                # Try to extract via 7-Zip for .7z/.rar
                seven_zip = self._find_7z_executable()
                if not seven_zip:
                    return False, "7-Zip (7z) est requis pour extraire ce format (7z/rar). Installez 7-Zip et ajoutez-le au PATH.", []
                # Snapshot before extraction
                before_set = self._snapshot_relative_files(target_folder)
                # Extract
                args = [seven_zip, 'x', '-y', f"-o{target_folder}", file_path]
                try:
                    completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                except OSError as exc:
                    return False, f"Échec de l'extraction via 7z: {exc}", []
                if completed.returncode != 0:
                    output = (completed.stderr or completed.stdout or "").strip()
                    return False, f"Extraction 7z a échoué: {output}", []
                # Snapshot after extraction and compute diff
                after_set = self._snapshot_relative_files(target_folder)
                new_rel = sorted(after_set - before_set)
                if not new_rel:
                    return False, "Aucun fichier extrait (archive vide ou sans contenu exploitable).", []
                installed_entries.extend(new_rel)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            return False, f"Erreur lors de la copie : {exc}", []

        verb = "ajouté" if merge and not clean_before else "installé"
        message = f"{os.path.basename(file_path)} {verb} dans '{os.path.basename(target_folder)}'."
        if plan_warnings:
            message = message + "\n" + "\n".join(plan_warnings)
        return True, message, installed_entries

    def _find_7z_executable(self):
        candidates = [
            "7z",
            os.path.join(os.environ.get("ProgramFiles", r"C:\\Program Files"), "7-Zip", "7z.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)"), "7-Zip", "7z.exe"),
        ]
        for path in candidates:
            if not path:
                continue
            try:
                completed = subprocess.run([path, "-h"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if completed.returncode == 0 or completed.stdout or completed.stderr:
                    return path
            except Exception:
                continue
        return None

    def _snapshot_relative_files(self, target_folder):
        root = os.path.abspath(target_folder)
        rels = set()
        for cur, _dirs, files in os.walk(root):
            for f in files:
                rel = os.path.relpath(os.path.join(cur, f), root).replace("\\", "/")
                rels.add(rel)
        return rels

    @staticmethod
    def _describe_install_type(file_paths):
        extensions = []
        for path in file_paths:
            extension = os.path.splitext(path)[1].lower()
            if extension in {".package", ".ts4script"}:
                extensions.append(f"fichier {extension}")
            elif extension == ".zip":
                extensions.append("archive .zip")
        if not extensions:
            return ""
        if len(set(extensions)) == 1:
            return extensions[0]
        return ", ".join(sorted(set(extensions)))

    def _record_installation(self, entry):
        normalized_entry = dict(entry)
        normalized_entry["addons"] = normalize_addon_metadata(entry.get("addons", []))
        # Normalize and store file list if provided
        files = []
        for p in normalized_entry.get("files", []) or []:
            s = str(p).replace("\\", "/").strip()
            if s and s not in files:
                files.append(s)
        if files:
            normalized_entry["files"] = files

        target = normalized_entry.get("target_folder")
        if not target:
            return
        replaced = False
        for existing in self.installed_mods:
            if existing.get("target_folder") == target:
                # Merge dict but union addons and files lists
                for k, v in normalized_entry.items():
                    if k in {"addons", "files"}:
                        continue
                    existing[k] = v
                existing["addons"] = normalize_addon_metadata(existing.get("addons", []))
                merged_files = []
                for lst in (existing.get("files", []) or [], normalized_entry.get("files", []) or []):
                    for p in lst:
                        if p and p not in merged_files:
                            merged_files.append(p)
                if merged_files:
                    existing["files"] = merged_files
                replaced = True
                break
        if not replaced:
            normalized_entry.setdefault("addons", [])
            normalized_entry.setdefault("files", [])
            self.installed_mods.append(normalized_entry)
        self.installed_mods.sort(key=lambda item: item.get("installed_at", ""), reverse=True)
        save_installed_mods(self.installed_mods)
        self.refresh_table()

    def _write_marker_file(self, target_folder, entry):
        try:
            marker_path = os.path.join(target_folder, MOD_MARKER_FILENAME)
            data = {
                "name": entry.get("name", ""),
                "type": entry.get("type", ""),
                "installed_at": entry.get("installed_at", ""),
                "source": entry.get("source", ""),
                "app_version": APP_VERSION,
                "app_version_date": APP_VERSION_DATE,
                "files": list(entry.get("files", []) or []),
                "mod_version": entry.get("mod_version", ""),
                "url": entry.get("url", ""),
            }
            with open(marker_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _recover_from_markers(self):
        if not self.mod_directory or not os.path.isdir(self.mod_directory):
            QtWidgets.QMessageBox.warning(self, "Dossier des mods invalide", "Définis un dossier des mods valide dans la configuration.")
            return
        recovered = 0
        errors = []
        seen_targets = set()
        try:
            for root, dirs, files in os.walk(self.mod_directory):
                if MOD_MARKER_FILENAME in files:
                    marker_path = os.path.join(root, MOD_MARKER_FILENAME)
                    try:
                        with open(marker_path, "r", encoding="utf-8") as fh:
                            data = json.load(fh)
                        entry = {
                            "name": str(data.get("name") or os.path.basename(root)),
                            "type": str(data.get("type") or ""),
                            "installed_at": str(data.get("installed_at") or ""),
                            "target_folder": root,
                            "source": str(data.get("source") or ""),
                            "addons": [],
                            "files": list(data.get("files", []) or []),
                            "mod_version": str(data.get("mod_version") or ""),
                            "url": str(data.get("url") or ""),
                        }
                        target_key = os.path.normcase(os.path.abspath(root))
                        if target_key in seen_targets:
                            continue
                        seen_targets.add(target_key)
                        self._record_installation(entry)
                        recovered += 1
                    except (OSError, json.JSONDecodeError) as exc:
                        errors.append(f"{marker_path} → {exc}")
        finally:
            self.refresh_table()
        message = [f"{recovered} mod(s) récupéré(s) depuis les marqueurs."]
        if errors:
            message.append("Erreurs:\n" + "\n".join(errors))
        QtWidgets.QMessageBox.information(self, "Recovery list", "\n".join(message))

    def _show_context_menu(self, position):
        item = self.table.itemAt(position)
        if item is None:
            return
        row = item.row()
        if row < 0 or row >= len(self.installed_mods):
            return
        entry = self.installed_mods[row]

        menu = QtWidgets.QMenu(self)
        search_action = menu.addAction("Recherche Google")
        menu.addSeparator()
        open_action = menu.addAction("Ouvrir dans l'explorateur")
        rename_action = menu.addAction("Renommer le mod")
        set_version_action = menu.addAction("Définir version…")
        set_url_action = menu.addAction("Définir URL…")
        addons_action = menu.addAction("Ajouter add-ons")
        remove_addons_action = menu.addAction("Supprimer add-ons")
        remove_addons_action.setEnabled(bool(entry.get("addons")))
        disable_action = None
        if entry.get("disabled"):
            disable_action = menu.addAction("Réactiver le mod")
        else:
            disable_action = menu.addAction("Désactiver le mod")
        delete_action = menu.addAction("Supprimer le mod")
        update_action = menu.addAction("Mettre à jour le mod")

        chosen_action = menu.exec_(self.table.viewport().mapToGlobal(position))
        if chosen_action is None:
            return
        if chosen_action == search_action:
            self._open_google_search(entry)
        elif chosen_action == open_action:
            self._open_in_file_manager(entry.get("target_folder"))
        elif chosen_action == rename_action:
            self._rename_mod(entry)
        elif chosen_action == set_version_action:
            self._set_mod_version(entry)
        elif chosen_action == set_url_action:
            self._set_mod_url(entry)
        elif chosen_action == addons_action:
            self._prompt_addons(entry)
        elif chosen_action == remove_addons_action:
            self._prompt_remove_addons(entry)
        elif chosen_action == disable_action:
            self._toggle_disable_mod(entry)
        elif chosen_action == delete_action:
            self._delete_mod(entry)
        elif chosen_action == update_action:
            self._prompt_update_mod(entry)

    def _set_mod_version(self, entry):
        current = entry.get("mod_version", "")
        text, ok = QtWidgets.QInputDialog.getText(self, "Définir version", "Numéro de version :", QtWidgets.QLineEdit.Normal, current)
        if not ok:
            return
        entry["mod_version"] = text.strip()
        self._record_installation(entry)

    def _set_mod_url(self, entry):
        current = entry.get("url", "")
        text, ok = QtWidgets.QInputDialog.getText(self, "Définir URL", "URL du mod :", QtWidgets.QLineEdit.Normal, current)
        if not ok:
            return
        entry["url"] = text.strip()
        self._record_installation(entry)

    def _rename_mod(self, entry):
        old_name = entry.get("name", "")
        target_folder = entry.get("target_folder", "")
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Renommer le mod", "Nouveau nom :", QtWidgets.QLineEdit.Normal, old_name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        # Compute new folder path
        parent = os.path.dirname(target_folder)
        new_folder = os.path.join(parent, sanitize_mod_folder_name(new_name))
        if os.path.abspath(new_folder) == os.path.abspath(target_folder):
            entry["name"] = new_name
            self._record_installation(entry)
            return
        if os.path.exists(new_folder):
            QtWidgets.QMessageBox.warning(self, "Impossible de renommer", "Un dossier portant ce nom existe déjà.")
            return
        try:
            os.rename(target_folder, new_folder)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible de renommer le dossier : {exc}")
            return
        entry["name"] = new_name
        entry["target_folder"] = new_folder
        self._record_installation(entry)

    def _toggle_disable_mod(self, entry):
        backups_dir = self.parent().settings.get("backups_directory", "") if self.parent() else ""
        if not backups_dir:
            QtWidgets.QMessageBox.warning(self, "Backups manquant", "Définis un dossier de backups dans la configuration.")
            return
        disabled_root = os.path.join(backups_dir, "Disabled Mod")
        os.makedirs(disabled_root, exist_ok=True)
        target_folder = entry.get("target_folder", "")
        if entry.get("disabled"):
            # Reactivate
            disabled_path = entry.get("disabled_path") or ""
            if not disabled_path or not os.path.exists(disabled_path):
                QtWidgets.QMessageBox.warning(self, "Réactivation impossible", "Le dossier désactivé est introuvable.")
                return
            destination = target_folder
            final = destination
            i = 1
            while os.path.exists(final):
                final = f"{destination}_{i}"
                i += 1
            try:
                shutil.move(disabled_path, final)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible de réactiver : {exc}")
                return
            entry["disabled"] = False
            entry["disabled_path"] = ""
            entry["target_folder"] = final
            self._record_installation(entry)
            QtWidgets.QMessageBox.information(self, "Mod réactivé", "Le mod a été réactivé.")
        else:
            # Disable (move to backups)
            if not target_folder or not os.path.isdir(target_folder):
                QtWidgets.QMessageBox.warning(self, "Dossier introuvable", "Le dossier du mod est introuvable.")
                return
            dest = os.path.join(disabled_root, os.path.basename(target_folder))
            final = dest
            i = 1
            while os.path.exists(final):
                final = f"{dest}_{i}"
                i += 1
            try:
                shutil.move(target_folder, final)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible de désactiver : {exc}")
                return
            entry["disabled"] = True
            entry["disabled_path"] = final
            # Keep original target_folder to restore later
            self._record_installation(entry)
            QtWidgets.QMessageBox.information(self, "Mod désactivé", "Le mod a été déplacé dans Backups/Disabled Mod.")

    def _on_installer_item_changed(self, item):
        try:
            row = item.row()
            col = item.column()
            if row < 0 or row >= len(self.installed_mods):
                return
            entry = dict(self.installed_mods[row])
            text = item.text().strip()
            if col == 3:  # Version
                entry["mod_version"] = text
                self._record_installation(entry)
            elif col == 4:  # URL
                entry["url"] = text
                self._record_installation(entry)
        except Exception:
            pass

    def _open_in_file_manager(self, target_path):
        if not target_path:
            return
        if not os.path.exists(target_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Dossier introuvable",
                "Le dossier du mod est introuvable. Vérifiez qu'il n'a pas été supprimé.",
            )
            return

        if os.path.isfile(target_path):
            target_path = os.path.dirname(target_path) or target_path

        if sys.platform.startswith("win"):
            try:
                os.startfile(target_path)
            except OSError:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Erreur",
                    "Impossible d'ouvrir l'explorateur de fichiers.",
                )
        elif sys.platform == "darwin":
            QtCore.QProcess.startDetached("open", [target_path])
        else:
            QtCore.QProcess.startDetached("xdg-open", [target_path])

    def _open_google_search(self, entry):
        mod_name = entry.get("name") or os.path.basename(entry.get("target_folder", ""))
        if not mod_name:
            return
        query = quote_plus(mod_name)
        webbrowser.open(f"https://www.google.com/search?q={query}")

    def _prompt_update_mod(self, entry):
        target_folder = entry.get("target_folder")
        if not target_folder or not os.path.isdir(target_folder):
            QtWidgets.QMessageBox.warning(
                self,
                "Dossier introuvable",
                "Le dossier du mod est introuvable. Vérifiez qu'il n'a pas été supprimé.",
            )
            return

        def handle_drop(file_paths):
            return self._perform_update(entry, file_paths)

        instruction = (
            "Glissez-déposez un fichier .package, .ts4script ou .zip pour remplacer le contenu du dossier du mod."
        )
        dialog = FileDropDialog("Mettre à jour le mod", instruction, handle_drop, self)
        dialog.exec_()

    def _prompt_addons(self, entry):
        target_folder = entry.get("target_folder")
        if not target_folder or not os.path.isdir(target_folder):
            QtWidgets.QMessageBox.warning(
                self,
                "Dossier introuvable",
                "Le dossier du mod est introuvable. Vérifiez qu'il n'a pas été supprimé.",
            )
            return

        def handle_drop(file_paths):
            return self._perform_addons(entry, file_paths)

        instruction = (
            "Glissez-déposez des fichiers .package, .ts4script ou .zip pour les ajouter au dossier du mod."
        )
        dialog = FileDropDialog("Ajouter des add-ons", instruction, handle_drop, self)
        dialog.exec_()

    def _prompt_remove_addons(self, entry):
        entry_addons = normalize_addon_metadata(entry.get("addons", []))
        if not entry_addons:
            QtWidgets.QMessageBox.information(
                self,
                "Aucun add-on",
                "Aucun add-on n'est enregistré pour ce mod.",
            )
            return

        entry["addons"] = entry_addons

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Supprimer des add-ons")
        dialog.setModal(True)

        layout = QtWidgets.QVBoxLayout(dialog)
        info_label = QtWidgets.QLabel("Sélectionnez les add-ons à supprimer :")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        list_widget = QtWidgets.QListWidget(dialog)
        list_widget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        for addon in entry_addons:
            label = addon.get("label") or "Add-on"
            added_at_display = format_installation_display(addon.get("added_at", ""))
            if added_at_display:
                item_text = f"{label} – {added_at_display}"
            else:
                item_text = label
            list_item = QtWidgets.QListWidgetItem(item_text)
            list_widget.addItem(list_item)
        layout.addWidget(list_widget)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
        )
        remove_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        remove_button.setText("Supprimer")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        selected_rows = sorted({index.row() for index in list_widget.selectedIndexes()}, reverse=True)
        if not selected_rows:
            QtWidgets.QMessageBox.information(
                self,
                "Aucune sélection",
                "Sélectionnez au moins un add-on à supprimer.",
            )
            return

        success_messages = []
        error_messages = []
        removed_count = 0

        for row in selected_rows:
            if row < 0 or row >= len(entry_addons):
                continue
            addon = entry_addons[row]
            label = addon.get("label") or f"Add-on {row + 1}"
            removed, missing, errors = self._remove_addon_files(entry, addon)
            if errors:
                for message in errors:
                    error_messages.append(f"{label} : {message}")
                continue

            del entry_addons[row]
            removed_count += 1
            details = []
            if removed:
                details.append(f"{len(removed)} élément(s) supprimé(s)")
            if missing:
                details.append(f"{len(missing)} élément(s) introuvable(s)")
            if details:
                success_messages.append(f"{label} – {', '.join(details)}")
            else:
                success_messages.append(f"{label} supprimé.")

        if removed_count:
            updated_entry = dict(entry)
            updated_entry["addons"] = normalize_addon_metadata(entry_addons)
            updated_entry["installed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
            self._record_installation(updated_entry)
            self.installations_performed = True

        if success_messages:
            QtWidgets.QMessageBox.information(
                self,
                "Suppression terminée",
                "\n".join(success_messages),
            )
        if error_messages:
            QtWidgets.QMessageBox.warning(
                self,
                "Suppression partielle",
                "\n".join(error_messages),
            )

    def _remove_addon_files(self, entry, addon):
        target_folder = entry.get("target_folder")
        removed = []
        missing = []
        errors = []

        if not target_folder or not os.path.isdir(target_folder):
            return removed, missing, ["Dossier du mod introuvable."]

        raw_paths = []
        if isinstance(addon, dict):
            raw_paths = list(addon.get("paths", []))
            if not raw_paths and addon.get("label"):
                raw_paths = [addon.get("label")]
        else:
            raw_paths = [str(addon)]

        entries = []
        seen = set()
        for raw_path in raw_paths:
            path_str = str(raw_path).replace("\\", "/").strip()
            if not path_str:
                continue
            is_directory = path_str.endswith("/")
            trimmed = path_str[:-1] if is_directory else path_str
            normalized = os.path.normpath(trimmed).replace("\\", "/")
            if not normalized or normalized in {".", ""}:
                continue
            if normalized.startswith("..") or "/../" in normalized:
                errors.append(f"Chemin invalide ignoré : {path_str}")
                continue
            key = (normalized, is_directory)
            if key in seen:
                continue
            seen.add(key)
            entries.append((normalized, is_directory))

        if not entries:
            return removed, missing, errors

        target_root = os.path.realpath(target_folder)

        def _sorted_by_depth(items):
            return sorted(items, key=lambda value: (value.count("/"), value), reverse=True)

        file_entries = [value for value, is_dir in entries if not is_dir]
        dir_entries = [value for value, is_dir in entries if is_dir]

        for rel_path in _sorted_by_depth(file_entries):
            absolute_path = os.path.realpath(os.path.join(target_root, rel_path))
            if os.path.commonpath([target_root, absolute_path]) != target_root:
                errors.append(f"Chemin hors du mod : {rel_path}")
                continue
            if os.path.isfile(absolute_path):
                try:
                    os.remove(absolute_path)
                    removed.append(rel_path)
                except OSError as exc:
                    errors.append(f"{rel_path} : {exc}")
            elif os.path.isdir(absolute_path):
                try:
                    shutil.rmtree(absolute_path)
                    removed.append(f"{rel_path}/")
                except OSError as exc:
                    errors.append(f"{rel_path} : {exc}")
            else:
                missing.append(rel_path)

        for rel_path in _sorted_by_depth(dir_entries):
            absolute_path = os.path.realpath(os.path.join(target_root, rel_path))
            if os.path.commonpath([target_root, absolute_path]) != target_root:
                errors.append(f"Chemin hors du mod : {rel_path}/")
                continue
            if os.path.isdir(absolute_path):
                try:
                    shutil.rmtree(absolute_path)
                    removed.append(f"{rel_path}/")
                except OSError as exc:
                    errors.append(f"{rel_path}/ : {exc}")
            elif os.path.isfile(absolute_path):
                try:
                    os.remove(absolute_path)
                    removed.append(rel_path)
                except OSError as exc:
                    errors.append(f"{rel_path}/ : {exc}")
            else:
                missing.append(f"{rel_path}/")

        return removed, missing, errors

    def _perform_update(self, entry, file_paths):
        target_folder = entry.get("target_folder")
        if not target_folder:
            return [], ["Dossier cible invalide."]

        success_messages = []
        error_messages = []
        processed_files = []

        for index, path in enumerate(file_paths):
            if not os.path.isfile(path):
                error_messages.append(f"Fichier introuvable : {path}")
                continue
            if not self._is_supported_extension(path):
                error_messages.append(f"Extension non supportée : {os.path.basename(path)}")
                continue
            success, message, _ = self._install_file_to_target(
                path,
                target_folder,
                clean_before=(index == 0),
                merge=False,
            )
            if success:
                success_messages.append(message)
                processed_files.append(path)
            elif message:
                error_messages.append(message)

        if processed_files:
            updated_entry = dict(entry)
            updated_entry["installed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
            updated_entry["type"] = self._describe_install_type(processed_files)
            updated_entry["source"] = ", ".join(os.path.basename(path) for path in processed_files)
            updated_entry["addons"] = []
            self._record_installation(updated_entry)
            self._write_marker_file(target_folder, updated_entry)
            self.installations_performed = True

        return success_messages, error_messages

    def _perform_addons(self, entry, file_paths):
        target_folder = entry.get("target_folder")
        if not target_folder:
            return [], ["Dossier cible invalide."]

        success_messages = []
        error_messages = []
        added_sources = []
        new_addons = []

        for path in file_paths:
            if not os.path.isfile(path):
                error_messages.append(f"Fichier introuvable : {path}")
                continue
            if not self._is_supported_extension(path):
                error_messages.append(f"Extension non supportée : {os.path.basename(path)}")
                continue
            success, message, installed_paths = self._install_file_to_target(
                path,
                target_folder,
                clean_before=False,
                merge=True,
            )
            if success:
                success_messages.append(message)
                label = os.path.basename(path)
                added_sources.append(label)
                new_addons.append(
                    {
                        "label": label,
                        "paths": installed_paths,
                        "added_at": datetime.utcnow().replace(microsecond=0).isoformat(),
                    }
                )
            elif message:
                error_messages.append(message)

        if added_sources:
            updated_entry = dict(entry)
            existing_addons = normalize_addon_metadata(updated_entry.get("addons", []))
            existing_addons.extend(new_addons)
            updated_entry["addons"] = normalize_addon_metadata(existing_addons)
            updated_entry["installed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
            self._record_installation(updated_entry)
            self._write_marker_file(target_folder, updated_entry)
            self.installations_performed = True

        return success_messages, error_messages

    def _delete_mod(self, entry):
        # Prevent deletion if Sims is running
        try:
            if hasattr(self.parent(), "_is_sims_running") and self.parent()._is_sims_running():
                QtWidgets.QMessageBox.warning(self, "Suppression impossible", "TS4_x64.exe est en cours d'exécution. Fermez le jeu avant de supprimer des mods.")
                return
        except Exception:
            pass
        target_folder = entry.get("target_folder")
        mod_name = entry.get("name") or os.path.basename(target_folder or "")
        response = QtWidgets.QMessageBox.question(
            self,
            "Supprimer le mod",
            (
                f"Voulez-vous supprimer le mod '{mod_name}' ?\n"
                "Le dossier correspondant sera supprimé du disque."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return

        if target_folder and os.path.exists(target_folder):
            try:
                shutil.rmtree(target_folder)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Suppression impossible",
                    f"Le dossier n'a pas pu être supprimé : {exc}",
                )
                return

        self.installed_mods = [item for item in self.installed_mods if item.get("target_folder") != target_folder]
        save_installed_mods(self.installed_mods)
        self.refresh_table()
        self.installations_performed = True

    def refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.installed_mods))
        for row, entry in enumerate(self.installed_mods):
            mod_name = entry.get("name", "")
            mod_type = entry.get("type", "")
            installed_at = format_installation_display(entry.get("installed_at", ""))
            mod_version = entry.get("mod_version", "")
            url = entry.get("url", "")
            folder_name = os.path.basename(entry.get("target_folder", ""))
            status = "Désactivé" if entry.get("disabled") else ""

            addons_flag = "✗" if entry.get("addons") else ""

            values = (mod_name, mod_type, installed_at, mod_version, url, folder_name, addons_flag, status)
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                # Only version (3) and URL (4) are editable
                if column in (3, 4):
                    try:
                        item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                    except Exception:
                        pass
                else:
                    item.setFlags(item.flags() ^ QtCore.Qt.ItemIsEditable)
                # visual cue for disabled
                if status:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("#aaaaaa")))
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)
        # Ensure change handler connected once
        try:
            if not getattr(self, "_item_changed_connected", False):
                self.table.itemChanged.connect(self._on_installer_item_changed)
                self._item_changed_connected = True
        except Exception:
            pass


class DuplicateFinderDialog(QtWidgets.QDialog):
    def __init__(self, parent, root_directory):
        super().__init__(parent)
        self.setWindowTitle("Find duplicates")
        self.setModal(True)
        self.resize(800, 520)
        self.root_directory = os.path.abspath(root_directory)

        layout = QtWidgets.QVBoxLayout(self)

        # Controls
        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(QtWidgets.QLabel("Dossier scanné :", self))
        self.root_edit = QtWidgets.QLineEdit(self)
        self.root_edit.setReadOnly(True)
        self.root_edit.setText(self.root_directory)
        path_layout.addWidget(self.root_edit)
        layout.addLayout(path_layout)

        options_layout = QtWidgets.QHBoxLayout()
        self.strict_checkbox = QtWidgets.QCheckBox("Scan avancé (même taille)", self)
        self.strict_checkbox.setChecked(False)
        options_layout.addWidget(self.strict_checkbox)

        self.package_checkbox = QtWidgets.QCheckBox("Inclure .package", self)
        self.package_checkbox.setChecked(True)
        options_layout.addWidget(self.package_checkbox)

        self.ts4_checkbox = QtWidgets.QCheckBox("Inclure .ts4script", self)
        self.ts4_checkbox.setChecked(True)
        options_layout.addWidget(self.ts4_checkbox)

        options_layout.addStretch(1)
        self.scan_button = QtWidgets.QPushButton("Analyser", self)
        self.scan_button.clicked.connect(self._run_scan)
        options_layout.addWidget(self.scan_button)
        layout.addLayout(options_layout)

        # Results tree
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Fichier", "Chemin", "Taille (o)", "Modifié le"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self._open_item_in_explorer)
        self.tree.itemSelectionChanged.connect(self._update_delete_button_enabled)
        layout.addWidget(self.tree, stretch=1)

        # Footer
        footer_layout = QtWidgets.QHBoxLayout()
        self.summary_label = QtWidgets.QLabel("", self)
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        footer_layout.addWidget(self.summary_label)
        footer_layout.addWidget(self.progress_bar, stretch=1)
        footer_layout.addStretch(1)
        self.delete_button = QtWidgets.QPushButton("Supprimer sélection", self)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        footer_layout.addWidget(self.delete_button)
        close_button = QtWidgets.QPushButton("Fermer", self)
        close_button.clicked.connect(self.accept)
        footer_layout.addWidget(close_button)
        layout.addLayout(footer_layout)

        QtCore.QTimer.singleShot(0, self._run_scan)

    def _open_item_in_explorer(self, item, _column):
        # If it is a child (has a path), attempt to open its folder
        path = item.text(1).strip()
        if not path:
            return
        directory = os.path.dirname(path) or path
        parent = self.parent()
        if hasattr(parent, "_open_in_file_manager"):
            parent._open_in_file_manager(directory)

    def _iter_files(self, include_package=True, include_ts4=True):
        allowed = set()
        if include_package:
            allowed.add(".package")
        if include_ts4:
            allowed.add(".ts4script")
        backups_directory = ""
        try:
            if hasattr(self.parent(), "settings"):
                backups_directory = os.path.normpath(self.parent().settings.get("backups_directory", ""))
        except Exception:
            backups_directory = ""

        for current_root, dirs, files in os.walk(self.root_directory):
            # skip backups directory subtree
            if backups_directory:
                dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(current_root, d)) != backups_directory]
            for file_name in files:
                ext = os.path.splitext(file_name)[1].lower()
                if ext not in allowed:
                    continue
                full_path = os.path.join(current_root, file_name)
                yield full_path, file_name

    def _run_scan(self):
        self.tree.clear()
        self.scan_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(0)  # busy while enumerating
        self.progress_bar.setValue(0)
        self._yield()
        include_package = self.package_checkbox.isChecked()
        include_ts4 = self.ts4_checkbox.isChecked()
        strict = self.strict_checkbox.isChecked()
        # enumerate files first
        files = list(self._iter_files(include_package, include_ts4))
        total = len(files)
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(0)

        records_by_key = defaultdict(list)
        for idx, (full_path, file_name) in enumerate(files, start=1):
            try:
                stat_result = os.stat(full_path)
                size = int(stat_result.st_size)
                mtime = int(stat_result.st_mtime)
            except OSError:
                size = -1
                mtime = -1
            name_key = file_name.casefold()
            if strict:
                key = (name_key, size)  # date removed from advanced matching
            else:
                key = name_key
            records_by_key[key].append((file_name, full_path, size, mtime))

            if idx % 25 == 0 or idx == total:
                self.progress_bar.setValue(min(idx, total))
                self._yield()

        duplicate_groups = []
        for key, items in records_by_key.items():
            if len(items) > 1:
                items_sorted = sorted(items, key=lambda t: t[1].casefold())
                filename = items_sorted[0][0]
                duplicate_groups.append((filename, items_sorted))

        duplicate_groups.sort(key=lambda g: g[0].casefold())

        for filename, items in duplicate_groups:
            top = QtWidgets.QTreeWidgetItem([self._format_group_title(filename, len(items)), "", "", ""])
            self.tree.addTopLevelItem(top)
            for _, path, size, mtime in items:
                dt = datetime.fromtimestamp(mtime) if mtime and mtime > 0 else None
                top.addChild(QtWidgets.QTreeWidgetItem([
                    "",
                    os.path.abspath(path),
                    str(size if size >= 0 else ""),
                    format_datetime(dt) if dt else "",
                ]))
            top.setExpanded(True)

        self.progress_bar.setVisible(False)
        self.scan_button.setEnabled(True)
        self._update_summary()
        self._update_delete_button_enabled()
        if hasattr(self.parent(), "logger"):
            try:
                self.parent().logger.info("Duplicate scan in %s: %d groups", self.root_directory, len(duplicate_groups))
            except Exception:
                pass

    def _yield(self):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.processEvents()
            except Exception:
                pass

    def _format_group_title(self, filename, count):
        return f"{filename} ({count})"

    def _update_group_title(self, group_item):
        if group_item is None:
            return
        # Count only children that are still present
        count = group_item.childCount()
        # Extract original filename from current title (before space + '(')
        title = group_item.text(0)
        base = title.split(' (', 1)[0]
        group_item.setText(0, self._format_group_title(base, count))

    def _update_summary(self):
        self.summary_label.setText(f"Groupes de doublons : {self.tree.topLevelItemCount()}")

    def _update_delete_button_enabled(self):
        items = self.tree.selectedItems()
        deletable = False
        for it in items:
            if it and it.parent() is not None and it.text(1).strip():
                deletable = True
                break
        self.delete_button.setEnabled(deletable)

    def _delete_selected(self):
        selected = [it for it in self.tree.selectedItems() if it.parent() is not None and it.text(1).strip()]
        if not selected:
            return
        # Unique paths only
        to_delete = []
        seen = set()
        for it in selected:
            path = it.text(1).strip()
            if path and path not in seen:
                seen.add(path)
                to_delete.append((it, path))

        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirmer la suppression",
            f"Supprimer définitivement {len(to_delete)} fichier(s) ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        errors = []
        deleted = 0
        # Delete files and remove items from tree
        for item, path in to_delete:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    raise OSError("fichier introuvable")
                parent = item.parent()
                idx = parent.indexOfChild(item)
                parent.takeChild(idx)
                self._update_group_title(parent)
                # Remove group if less than 2 remain
                if parent.childCount() < 2:
                    top_index = self.tree.indexOfTopLevelItem(parent)
                    self.tree.takeTopLevelItem(top_index)
                deleted += 1
            except OSError as exc:
                errors.append(f"{path} → {exc}")

        self._update_summary()
        self._update_delete_button_enabled()
        if deleted:
            QtWidgets.QMessageBox.information(self, "Suppression terminée", f"{deleted} fichier(s) supprimé(s).")
        if errors:
            QtWidgets.QMessageBox.warning(self, "Erreurs de suppression", "\n".join(errors))


class GroupViewDialog(QtWidgets.QDialog):
    def __init__(self, parent, rows):
        super().__init__(parent)
        self.setWindowTitle("Group View")
        self.setModal(True)
        self.resize(860, 540)

        layout = QtWidgets.QVBoxLayout(self)
        toolbar = QtWidgets.QHBoxLayout()
        expand_btn = QtWidgets.QPushButton("Expand All", self)
        collapse_btn = QtWidgets.QPushButton("Collapse All", self)
        toolbar.addWidget(expand_btn)
        toolbar.addWidget(collapse_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels([
            "Mod (groupe)", "État", "Fichier .package", "Date .package", "Fichier .ts4script", "Date .ts4script", "Confiance"
        ])
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, stretch=1)

        expand_btn.clicked.connect(self.tree.expandAll)
        collapse_btn.clicked.connect(self.tree.collapseAll)

        # Group rows
        grouped = defaultdict(list)
        for row in rows:
            key = row.get("group") or "(ungrouped)"
            grouped[key].append(row)
        for group_name in sorted(grouped.keys(), key=str.casefold):
            items = grouped[group_name]
            top = QtWidgets.QTreeWidgetItem([group_name, "", "", "", "", "", ""])
            if group_name and group_name != "(ungrouped)":
                top.setBackground(0, QtGui.QBrush(QtGui.QColor("#2e7d32")))
                top.setForeground(0, QtGui.QBrush(QtGui.QColor("#ffffff")))
            self.tree.addTopLevelItem(top)
            for row in items:
                child = QtWidgets.QTreeWidgetItem([
                    "",
                    str(row.get("status", "")),
                    str(row.get("package", "")),
                    str(row.get("package_date", "")),
                    str(row.get("script", "")),
                    str(row.get("script_date", "")),
                    str(row.get("confidence", "")),
                ])
                # Highlight installed via Mod Installer
                if row.get("group"):
                    for col in range(self.tree.columnCount()):
                        child.setBackground(col, QtGui.QBrush(QtGui.QColor("#2e7d32")))
                        child.setForeground(col, QtGui.QBrush(QtGui.QColor("#ffffff")))
                top.addChild(child)
            top.setExpanded(True)


class ModManagerApp(QtWidgets.QWidget):
    def __init__(self, splash=None):
        super().__init__()

        self.setWindowTitle(f"Gestionnaire de Mods Sims 4 – {APP_VERSION} ({APP_VERSION_DATE})")
        self.setGeometry(100, 100, 800, 600)

        # Initialize settings and logging (default DEBUG, overridable by settings)
        self.settings = load_settings()
        self.logger = setup_logging(self.settings.get("log_level", "DEBUG"))
        try:
            self.logger.debug("Application starting with log level: %s", self.settings.get("log_level", "DEBUG"))
        except Exception:
            pass
        self.custom_version_releases = load_custom_version_releases()
        self.version_releases = merge_version_releases(self.custom_version_releases)
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = ""
        self.all_data_rows = []
        self._cache_clear_triggered_this_refresh = False

        self._splash = splash
        self.init_ui()

        auto = bool(self.settings.get("auto_scan_on_start", True))
        if auto or not os.path.exists(MOD_SCAN_CACHE_PATH):
            mod_directory = self.settings.get("mod_directory", "")
            if mod_directory and os.path.isdir(mod_directory):
                QtCore.QTimer.singleShot(0, self.refresh_tree)

    def _yield_ui_events(self, max_time_ms=25):
        try:
            flags_type = QtCore.QEventLoop.ProcessEventsFlag
            flags = flags_type.ExcludeUserInputEvents | flags_type.ExcludeSocketNotifiers
        except AttributeError:
            flags = QtCore.QEventLoop.ExcludeUserInputEvents | QtCore.QEventLoop.ExcludeSocketNotifiers
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        app.processEvents(flags, max_time_ms)

    def init_ui(self):
        # Layout
        layout = QtWidgets.QVBoxLayout()

        # Mode sombre - Définir le style global
        self.setStyleSheet("""
            QWidget {
                background-color: #2e2e2e;
                color: white;
            }
            QTableWidget {
                background-color: #333333;
                color: white;
                border: 1px solid #444444;
            }
            QHeaderView::section {
                background-color: #4e4e4e;
                color: white;
            }
            QCheckBox {
                color: white;
            }
        """)

        # Dossier des mods (affichage uniquement)
        mod_dir_layout = QtWidgets.QHBoxLayout()
        mod_dir_layout.addWidget(QtWidgets.QLabel("Dossier des mods :"))
        self.mod_directory_label = QtWidgets.QLabel()
        self.mod_directory_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        mod_dir_layout.addWidget(self.mod_directory_label, stretch=1)

        layout.addLayout(mod_dir_layout)
        self.update_mod_directory_label()

        # Filtrage
        version_range_layout = QtWidgets.QVBoxLayout()
        self.version_filters_checkbox = QtWidgets.QCheckBox("Versions", self)
        self.version_filters_checkbox.setChecked(self.settings.get("enable_version_filters", True))
        self.version_filters_checkbox.toggled.connect(self._on_version_filters_toggled)
        version_row1 = QtWidgets.QHBoxLayout()
        version_row1.addWidget(self.version_filters_checkbox)

        self.version_start_label = QtWidgets.QLabel("Version de départ :", self)
        version_row1.addWidget(self.version_start_label)
        self.version_start_combo = QtWidgets.QComboBox(self)
        self.version_start_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        version_row1.addWidget(self.version_start_combo)
        version_range_layout.addLayout(version_row1)
        self.version_end_label = QtWidgets.QLabel("Version d'arrivée :", self)
        version_row2 = QtWidgets.QHBoxLayout()
        version_row2.addWidget(self.version_end_label)
        self.version_end_combo = QtWidgets.QComboBox(self)
        self.version_end_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        version_row2.addWidget(self.version_end_combo)
        version_range_layout.addLayout(version_row2)

        # Filter mode dropdown (replaces show package/ts4script checkboxes)
        self.file_filter_combo = QtWidgets.QComboBox(self)
        self.file_filter_combo.addItem("Show both", "both")
        self.file_filter_combo.addItem("Show Package", "package")
        self.file_filter_combo.addItem("Show TS4Script", "ts4script")
        self.file_filter_combo.addItem("Mod Installer Only", "installer_only")
        current_mode = str(self.settings.get("file_filter_mode", "both")).lower()
        idx = self.file_filter_combo.findData(current_mode)
        self.file_filter_combo.setCurrentIndex(idx if idx != -1 else 0)
        self.file_filter_combo.currentIndexChanged.connect(self.on_file_filter_mode_changed)

        self.show_ignored_checkbox = QtWidgets.QCheckBox("Afficher les mods ignorés", self)
        self.show_ignored_checkbox.setChecked(self.settings.get("show_ignored", False))
        self.show_ignored_checkbox.toggled.connect(lambda: self.toggle_show_ignored())
        # Group box for filters (top-left)
        filters_group = QtWidgets.QGroupBox("Filtres", self)
        filters_layout = QtWidgets.QVBoxLayout(filters_group)
        filters_layout.addLayout(version_range_layout)
        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(QtWidgets.QLabel("Type :", self))
        type_row.addWidget(self.file_filter_combo)
        filters_layout.addLayout(type_row)
        filters_layout.addWidget(self.show_ignored_checkbox)
        self.show_disabled_only_checkbox = QtWidgets.QCheckBox("Afficher seulement désactivés", self)
        self.show_disabled_only_checkbox.setChecked(self.settings.get("show_disabled_only", False))
        self.show_disabled_only_checkbox.toggled.connect(self.toggle_show_disabled_only)
        filters_layout.addWidget(self.show_disabled_only_checkbox)

        self.populate_version_combos()
        self.version_start_combo.currentIndexChanged.connect(self.on_version_filter_changed)
        self.version_end_combo.currentIndexChanged.connect(self.on_version_filter_changed)
        self._update_version_filter_visibility()

        # Top bar: Filters left, Actions right (buttons will be added after creation)
        top_bar = QtWidgets.QHBoxLayout()
        # Slightly reduce filters group width
        filters_group.setMaximumWidth(460)
        top_bar.addWidget(filters_group, stretch=1)
        self.actions_group = QtWidgets.QGroupBox("Actions", self)
        self.actions_layout = QtWidgets.QVBoxLayout(self.actions_group)
        top_bar.addWidget(self.actions_group, stretch=1)
        layout.addLayout(top_bar)

        search_layout = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit(self)
        self.search_edit.setPlaceholderText("Nom du mod à rechercher")
        self.search_edit.textChanged.connect(self.apply_search_filter)
        self.show_search_checkbox = QtWidgets.QCheckBox("Afficher recherche", self)
        self.show_search_checkbox.setChecked(self.settings.get("show_search_results", True))
        self.show_search_checkbox.toggled.connect(self.toggle_show_search_results)
        self.instant_search_checkbox = QtWidgets.QCheckBox("Instant search", self)
        self.instant_search_checkbox.setChecked(self.settings.get("instant_search", True))
        self.instant_search_checkbox.toggled.connect(self.toggle_instant_search)
        self.search_button = QtWidgets.QPushButton("Rechercher", self)
        self.search_button.clicked.connect(partial(self.apply_search_filter, forced=True))
        search_layout.addWidget(self.show_search_checkbox)
        search_layout.addWidget(self.instant_search_checkbox)
        search_layout.addWidget(QtWidgets.QLabel("Recherche mod :"))
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(self.search_button)

        self.search_edit.setEnabled(self.show_search_checkbox.isChecked())

        # Move search controls into Filters group
        filters_layout.addLayout(search_layout)

        progress_layout = QtWidgets.QHBoxLayout()
        self.scan_status_label = QtWidgets.QLabel("", self)
        self.scan_status_label.setVisible(False)
        self.scan_progress_bar = QtWidgets.QProgressBar(self)
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_bar.setMinimum(0)
        self.scan_progress_bar.setMaximum(1)
        self.scan_progress_bar.setValue(0)
        self.scan_count_label = QtWidgets.QLabel("", self)
        self.scan_count_label.setVisible(False)
        progress_layout.addWidget(self.scan_status_label)
        progress_layout.addWidget(self.scan_progress_bar, stretch=1)
        progress_layout.addWidget(self.scan_count_label)
        layout.addLayout(progress_layout)

        # Table des mods
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "État",
            "Mod (groupe)",
            "Fichier .package",
            "Date .package",
            "Fichier .ts4script",
            "Date .ts4script",
            "Version",
            "Confiance",
            "Ignoré",
        ])
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)

        header = self.table.horizontalHeader()
        # Header context menu for column visibility
        header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        for column in range(self.table.columnCount()):
            resize_mode = QtWidgets.QHeaderView.Stretch
            # Ajuster la largeur au contenu pour colonnes clés
            if column in (0, 1, 3, 5, 6, 7, self.table.columnCount() - 1):
                resize_mode = QtWidgets.QHeaderView.ResizeToContents
            header.setSectionResizeMode(column, resize_mode)
        header.setStretchLastSection(False)
        self.table.setSortingEnabled(True)
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.table, stretch=1)

        # Apply hidden columns from settings
        self._apply_hidden_columns()

        # Boutons
        self.configuration_button = QtWidgets.QPushButton("Configuration", self)
        self.configuration_button.clicked.connect(self.open_configuration)

        self.mod_installer_button = QtWidgets.QPushButton("Mod Installer", self)
        self.mod_installer_button.clicked.connect(self.open_mod_installer)

        self.refresh_button = QtWidgets.QPushButton("Analyser / Rafraîchir", self)
        self.refresh_button.clicked.connect(self.refresh_tree)

        self.export_button = QtWidgets.QPushButton("Exporter vers Excel", self)
        self.export_button.clicked.connect(self.export_current)

        self.clear_cache_button = QtWidgets.QPushButton("Clear Sims4 Cache", self)
        self.clear_cache_button.clicked.connect(self.clear_sims4_cache)

        self.grab_logs_button = QtWidgets.QPushButton("Grab Logs", self)
        self.grab_logs_button.clicked.connect(self.grab_logs)

        self.launch_button = QtWidgets.QPushButton("Launch Sims 4", self)
        self.launch_button.clicked.connect(self.launch_sims4)

        self.kill_button = QtWidgets.QPushButton("Kill Sims 4", self)
        self.kill_button.clicked.connect(self.kill_sims4)

        self.tools_button = QtWidgets.QPushButton("Tools", self)
        self.tools_button.clicked.connect(self.open_tools_dialog)
        self.group_view_button = QtWidgets.QPushButton("Group View", self)
        self.group_view_button.clicked.connect(self.open_group_view)

        # Populate Actions group (top-right)
        for btn in (
            self.mod_installer_button,
            self.tools_button,
            self.group_view_button,
            self.refresh_button,
            self.export_button,
            self.clear_cache_button,
            self.grab_logs_button,
            self.kill_button,
        ):
            self.actions_layout.addWidget(btn)
        self.actions_layout.addStretch(1)
        self._normalize_actions_buttons()

        # Keep only Configuration and Launch at the bottom
        bottom_buttons = QtWidgets.QHBoxLayout()
        bottom_buttons.addWidget(self.configuration_button)
        bottom_buttons.addStretch(1)
        bottom_buttons.addWidget(self.launch_button)
        layout.addLayout(bottom_buttons)
        # Final
        self.setLayout(layout)
        self.update_launch_button_state()

    def _normalize_actions_buttons(self):
        # Make actions buttons same width
        buttons = []
        for i in range(self.actions_layout.count()):
            w = self.actions_layout.itemAt(i).widget()
            if isinstance(w, QtWidgets.QPushButton):
                buttons.append(w)
        if not buttons:
            return
        maxw = max((b.sizeHint().width() for b in buttons), default=120)
        for b in buttons:
            b.setMinimumWidth(maxw)
            b.setMaximumWidth(maxw)
            b.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        # Finalize handled in init_ui; only size normalization here

    def open_group_view(self):
        dialog = GroupViewDialog(self, list(self.all_data_rows))
        dialog.exec_()

    def _update_scan_status(self, message):
        if hasattr(self, "scan_status_label") and self.scan_status_label is not None:
            self.scan_status_label.setText(message)
            self.scan_status_label.setVisible(bool(message))
            self._yield_ui_events()
        if getattr(self, "_splash", None) is not None and message:
            try:
                self._splash.update_message(message)
            except Exception:
                pass

    def _start_scan_progress(self):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            self.scan_progress_bar.setVisible(True)
            self.scan_progress_bar.setMaximum(0)
            self.scan_progress_bar.setValue(0)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setText("")
            self.scan_count_label.setVisible(True)
        self._yield_ui_events()

    def _finish_scan_progress(self):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            self.scan_progress_bar.setVisible(False)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            self.scan_count_label.setVisible(False)
        self._yield_ui_events()
        if getattr(self, "_splash", None) is not None:
            try:
                self._splash.finish(self)
            except Exception:
                pass
            self._splash = None

    def _handle_scan_progress(self, processed, total, current_path):
        if hasattr(self, "scan_progress_bar") and self.scan_progress_bar is not None:
            if total:
                if self.scan_progress_bar.maximum() != total:
                    self.scan_progress_bar.setMaximum(total)
                self.scan_progress_bar.setValue(min(processed, total))
            else:
                self.scan_progress_bar.setMaximum(0)
        if hasattr(self, "scan_count_label") and self.scan_count_label is not None:
            if total:
                self.scan_count_label.setText(f"Objets scannés : {processed}/{total}")
            else:
                self.scan_count_label.setText(f"Objets scannés : {processed}")
            self.scan_count_label.setVisible(True)
        self._yield_ui_events()
        if getattr(self, "_splash", None) is not None:
            try:
                if total:
                    self._splash.update_message(f"Scan {processed}/{total}")
                elif processed:
                    self._splash.update_message(f"Scan {processed}")
            except Exception:
                pass

    def populate_version_combos(self):
        if not hasattr(self, "version_start_combo"):
            return
        entries = list(self.version_releases.items())
        combo_map = (
            (self.version_start_combo, "version_filter_start"),
            (self.version_end_combo, "version_filter_end"),
        )
        for combo, setting_key in combo_map:
            current_value = self.settings.get(setting_key, "") or ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Aucune (pas de limite)", "")
            for version, release_date in entries:
                combo.addItem(f"{version} – {format_release_date(release_date)}", version)
            index = combo.findData(current_value)
            combo.setCurrentIndex(index if index != -1 else 0)
            combo.blockSignals(False)

    def _on_version_filters_toggled(self, checked):
        self.settings["enable_version_filters"] = bool(checked)
        save_settings(self.settings)
        self._update_version_filter_visibility()
        self.refresh_table_only()

    def _update_version_filter_visibility(self):
        enabled = bool(self.settings.get("enable_version_filters", True))
        if hasattr(self, "version_filters_checkbox"):
            if self.version_filters_checkbox.isChecked() != enabled:
                self.version_filters_checkbox.blockSignals(True)
                self.version_filters_checkbox.setChecked(enabled)
                self.version_filters_checkbox.blockSignals(False)
        widgets = [
            getattr(self, "version_start_label", None),
            getattr(self, "version_start_combo", None),
            getattr(self, "version_end_label", None),
            getattr(self, "version_end_combo", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setVisible(enabled)
                widget.setEnabled(enabled)

    def on_version_filter_changed(self):
        if not hasattr(self, "version_start_combo"):
            return
        start_idx = self.version_start_combo.currentIndex()
        end_idx = self.version_end_combo.currentIndex()
        sender = self.sender()
        if start_idx > 0 and end_idx > 0 and start_idx > end_idx:
            if sender is self.version_start_combo:
                self.version_end_combo.blockSignals(True)
                self.version_end_combo.setCurrentIndex(start_idx)
                self.version_end_combo.blockSignals(False)
            else:
                self.version_start_combo.blockSignals(True)
                self.version_start_combo.setCurrentIndex(end_idx)
                self.version_start_combo.blockSignals(False)
            start_idx = self.version_start_combo.currentIndex()
            end_idx = self.version_end_combo.currentIndex()

        start_value = self.version_start_combo.itemData(start_idx)
        end_value = self.version_end_combo.itemData(end_idx)
        self.settings["version_filter_start"] = start_value or ""
        self.settings["version_filter_end"] = end_value or ""
        save_settings(self.settings)
        self.refresh_table_only()

    def get_version_entries(self):
        return list(self.version_releases.items())

    def add_version_release(self, version, release_date):
        normalized_version = str(version).strip()
        if not normalized_version:
            return False, "Le numéro de version est obligatoire."

        if hasattr(release_date, "toPyDate"):
            release_date = release_date.toPyDate()

        if release_date is None:
            return False, "La date de sortie est obligatoire."

        if normalized_version in self.version_releases:
            return False, "Cette version existe déjà."

        self.custom_version_releases[normalized_version] = release_date
        save_custom_version_releases(self.custom_version_releases)
        self.version_releases = merge_version_releases(self.custom_version_releases)
        self.populate_version_combos()
        self.refresh_table_only()
        return True, f"Version {normalized_version} ajoutée."

    def toggle_setting(self, key):
        self.settings[key] = getattr(self, f"{key}_checkbox").isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_ignored(self):
        self.settings["show_ignored"] = self.show_ignored_checkbox.isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_search_results(self):
        checked = self.show_search_checkbox.isChecked()
        self.settings["show_search_results"] = checked
        save_settings(self.settings)
        self.search_edit.setEnabled(checked)
        self._apply_search_filter()

    def toggle_instant_search(self):
        checked = self.instant_search_checkbox.isChecked()
        self.settings["instant_search"] = bool(checked)
        save_settings(self.settings)
        # Optionally run a refresh when enabling instant search
        if checked:
            self._apply_search_filter()

    def on_file_filter_mode_changed(self):
        idx = self.file_filter_combo.currentIndex()
        mode = self.file_filter_combo.itemData(idx) or "both"
        self.settings["file_filter_mode"] = str(mode)
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_disabled_only(self):
        self.settings["show_disabled_only"] = bool(self.show_disabled_only_checkbox.isChecked())
        save_settings(self.settings)
        self.refresh_table_only()

    def update_mod_directory_label(self):
        directory = self.settings.get("mod_directory", "")
        display_text = directory if directory else "(non défini)"
        self.mod_directory_label.setText(display_text)

    def open_configuration(self):
        dialog = ConfigurationDialog(self, dict(self.settings))
        dialog.exec_()

    def open_mod_installer(self):
        dialog = ModInstallerDialog(self, self.settings.get("mod_directory", ""))
        dialog.exec_()
        if dialog.installations_performed:
            self.refresh_tree()
            if not self._cache_clear_triggered_this_refresh:
                self.clear_sims4_cache()

    def apply_configuration(self, mod_directory, cache_directory, backups_directory, sims_executable_path, sims_executable_arguments, log_extra_extensions, grab_logs_ignore_files, log_level=None, auto_scan_on_start=None):
        previous_mod_directory = self.settings.get("mod_directory", "")
        previous_auto_scan = bool(self.settings.get("auto_scan_on_start", True))
        self.settings["mod_directory"] = mod_directory
        self.settings["sims_cache_directory"] = cache_directory
        self.settings["backups_directory"] = backups_directory
        self.settings["sims_executable_path"] = sims_executable_path
        self.settings["sims_executable_arguments"] = sims_executable_arguments
        self.settings["log_extra_extensions"] = sorted(set(log_extra_extensions))
        self.settings["grab_logs_ignore_files"] = list(grab_logs_ignore_files)
        if log_level:
            self.settings["log_level"] = str(log_level).upper()
        if auto_scan_on_start is not None:
            self.settings["auto_scan_on_start"] = bool(auto_scan_on_start)
        save_settings(self.settings)
        try:
            self.logger.info("Configuration updated (mod dir: %s)", mod_directory)
        except Exception:
            pass
        self.update_mod_directory_label()
        self.update_launch_button_state()

        # Apply log level change immediately (if provided)
        if log_level:
            try:
                setup_logging(self.settings.get("log_level", "DEBUG"))
                self.logger = logging.getLogger("Sims4ModTool")
                self.logger.info("Log level set to %s", self.settings.get("log_level"))
            except Exception:
                pass

        if previous_mod_directory != mod_directory:
            self.last_scanned_directory = ""
            if hasattr(self, "table"):
                self.table.setRowCount(0)
        # Trigger immediate scan if auto-scan has just been enabled
        try:
            if auto_scan_on_start is not None and bool(auto_scan_on_start) and not previous_auto_scan:
                if mod_directory and os.path.isdir(mod_directory):
                    QtCore.QTimer.singleShot(0, self.refresh_tree)
        except Exception:
            pass

    def refresh_tree(self):
        folder = self.settings.get("mod_directory", "")
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.critical(self, "Erreur", "Sélectionne un dossier valide dans la configuration.")
            return
        self.settings["mod_directory"] = folder
        save_settings(self.settings)
        self.update_mod_directory_label()
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = folder
        try:
            self.logger.info("Refreshing tree for directory: %s", folder)
        except Exception:
            pass
        self._update_scan_status("Scan en cours...")
        self._start_scan_progress()
        try:
            rows, scan_changed = generate_data_rows(
                folder,
                self.settings,
                self.version_releases,
                progress_callback=self._handle_scan_progress,
                yield_callback=self._yield_ui_events,
            )
        finally:
            self._finish_scan_progress()
        self.populate_table(rows)
        self._update_scan_status("")
        try:
            self.logger.debug("Tree refreshed. Rows: %d", len(rows))
        except Exception:
            pass
        self._cache_clear_triggered_this_refresh = False
        if scan_changed:
            self._cache_clear_triggered_this_refresh = True
            self.clear_sims4_cache()

    def refresh_table_only(self):
        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.ignored_mods = set(self.settings.get("ignored_mods", []))
            self._update_scan_status("Scan en cours...")
            self._cache_clear_triggered_this_refresh = False
            self._start_scan_progress()
            try:
                rows, scan_changed = generate_data_rows(
                    self.last_scanned_directory,
                    self.settings,
                    self.version_releases,
                    progress_callback=self._handle_scan_progress,
                    yield_callback=self._yield_ui_events,
                )
            finally:
                self._finish_scan_progress()
            self.populate_table(rows)
            self._update_scan_status("")
            try:
                self.logger.debug("Table refreshed only. Rows: %d", len(rows))
            except Exception:
                pass
            if scan_changed:
                self._cache_clear_triggered_this_refresh = True
                self.clear_sims4_cache()

    def clear_sims4_cache(self):
        cache_directory = self.settings.get("sims_cache_directory", "")
        if not cache_directory or not os.path.isdir(cache_directory):
            QtWidgets.QMessageBox.warning(self, "Dossier cache invalide", "Configure un dossier cache Sims 4 valide dans la configuration.")
            return

        targets = [
            "localthumbcache.package",
            "localsimtexturecache.package",
            "avatarcache.package",
            "cachestr",
            "onlinethumbnailcache",
        ]

        removed = []
        missing = []
        errors = []

        for item in targets:
            path = os.path.join(cache_directory, item)
            if not os.path.exists(path):
                missing.append(item)
                continue
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                removed.append(item)
            except OSError as exc:
                errors.append(f"{item} : {exc}")

        messages = []
        if removed:
            messages.append("Supprimé : " + ", ".join(removed))
        if missing:
            messages.append("Absent : " + ", ".join(missing))
        if errors:
            messages.append("Erreurs :\n" + "\n".join(errors))

        if not messages:
            messages.append("Aucun fichier ou dossier à supprimer.")

        QtWidgets.QMessageBox.information(self, "Nettoyage du cache", "\n".join(messages))
        try:
            self.logger.info("Cache cleared. Removed: %s, Missing: %s, Errors: %s", ", ".join(removed) if removed else "—", ", ".join(missing) if missing else "—", "; ".join(errors) if errors else "—")
        except Exception:
            pass

        launch_response = QtWidgets.QMessageBox.question(
            self,
            "Lancer Les Sims 4",
            "Souhaitez-vous lancer Les Sims 4 maintenant ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if launch_response == QtWidgets.QMessageBox.Yes:
            self.launch_sims4()

    def grab_logs(self):
        mod_directory = self.settings.get("mod_directory", "")
        if not mod_directory or not os.path.isdir(mod_directory):
            QtWidgets.QMessageBox.warning(self, "Dossier des mods invalide", "Définis un dossier des mods valide dans la configuration avant d'extraire les logs.")
            return

        backups_directory = self.settings.get("backups_directory", "")
        if not backups_directory:
            QtWidgets.QMessageBox.warning(self, "Dossier backups manquant", "Définis un dossier de backups dans la configuration avant d'extraire les logs.")
            return

        os.makedirs(backups_directory, exist_ok=True)

        extensions = {".log", ".txt"}
        extensions.update(self.settings.get("log_extra_extensions", []))
        ignored_log_names = {name.lower() for name in self.settings.get("grab_logs_ignore_files", []) if name}

        normalized_mod_dir = os.path.normpath(mod_directory)
        backups_directory_norm = os.path.normpath(backups_directory)
        found_logs = []

        for current_root, dirs, files in os.walk(normalized_mod_dir):
            dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(current_root, d)) != backups_directory_norm]
            for file_name in files:
                if file_name.lower() in ignored_log_names:
                    continue
                _, ext = os.path.splitext(file_name)
                if ext.lower() in extensions:
                    file_path = os.path.join(current_root, file_name)
                    normalized_file = os.path.normpath(file_path)
                    try:
                        if os.path.commonpath([normalized_file, backups_directory_norm]) == backups_directory_norm:
                            continue
                    except ValueError:
                        pass
                    found_logs.append(file_path)

        if not found_logs:
            QtWidgets.QMessageBox.information(self, "Aucun log", "Aucun fichier de log correspondant n'a été trouvé.")
            try:
                self.logger.info("Grab Logs: no matching logs found under %s", normalized_mod_dir)
            except Exception:
                pass
            return

        timestamp = datetime.now().strftime("Logs_%Y%m%d_%H%M%S")
        destination_root = os.path.join(backups_directory, timestamp)
        os.makedirs(destination_root, exist_ok=True)

        moved_files = []
        errors = []
        for source_path in found_logs:
            relative_path = os.path.relpath(source_path, normalized_mod_dir)
            destination_path = os.path.join(destination_root, relative_path)
            destination_dir = os.path.dirname(destination_path)
            os.makedirs(destination_dir, exist_ok=True)

            final_destination = destination_path
            counter = 1
            while os.path.exists(final_destination):
                name, ext = os.path.splitext(destination_path)
                final_destination = f"{name}_{counter}{ext}"
                counter += 1

            try:
                shutil.move(source_path, final_destination)
                moved_files.append(final_destination)
            except OSError as exc:
                errors.append(f"{source_path} → {exc}")

        if not moved_files:
            QtWidgets.QMessageBox.information(self, "Aucun log déplacé", "Aucun fichier n'a pu être déplacé.")
            try:
                self.logger.info("Grab Logs: moved 0 files; errors: %d", len(errors))
            except Exception:
                pass
            return

        message_lines = [f"{len(moved_files)} fichier(s) de log déplacé(s) vers {destination_root}."]
        if errors:
            message_lines.append("\nErreurs:\n" + "\n".join(errors))
        QtWidgets.QMessageBox.information(self, "Logs sauvegardés", "\n".join(message_lines))
        try:
            self.logger.info("Grab Logs: moved %d files to %s; errors: %d", len(moved_files), destination_root, len(errors))
        except Exception:
            pass
        self._open_in_file_manager(destination_root)

    def launch_sims4(self):
        executable_path = self.settings.get("sims_executable_path", "")
        if not executable_path:
            QtWidgets.QMessageBox.warning(self, "Exécutable manquant", "Configure le chemin de TS4_X64.exe dans la configuration.")
            return

        if not os.path.isfile(executable_path):
            QtWidgets.QMessageBox.critical(self, "Exécutable introuvable", "Le fichier TS4_X64.exe configuré est introuvable.")
            return

        args_text = self.settings.get("sims_executable_arguments", "").strip()
        try:
            args = shlex.split(args_text, posix=not sys.platform.startswith("win")) if args_text else []
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Arguments invalides", f"Les arguments spécifiés sont invalides : {exc}")
            return

        try:
            if sys.platform == "darwin":
                started = QtCore.QProcess.startDetached(executable_path, args)
            elif sys.platform.startswith("win"):
                started = QtCore.QProcess.startDetached(executable_path, args)
            else:
                started = QtCore.QProcess.startDetached(executable_path, args)
            if not started:
                raise OSError("le processus n'a pas pu être démarré")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible de lancer Sims 4 : {exc}")

    def kill_sims4(self):
        process_name = "TS4_x64.exe"
        if sys.platform.startswith("win"):
            # First, try normal taskkill
            try:
                completed = subprocess.run(["taskkill", "/F", "/IM", process_name], capture_output=True, text=True)
                if completed.returncode == 0:
                    QtWidgets.QMessageBox.information(self, "Sims 4 arrêté", "Le processus TS4_x64.exe a été arrêté avec succès.")
                    return
            except FileNotFoundError:
                pass
            # Try elevated kill via UAC prompt
            try:
                ps_cmd = "Start-Process -Verb RunAs powershell -ArgumentList 'Stop-Process -Name TS4_x64 -Force'"
                completed2 = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
                # We can't detect if user canceled UAC; show informational dialog
                QtWidgets.QMessageBox.information(self, "Tentative d'arrêt", "Une demande d'élévation a été envoyée pour arrêter TS4_x64.exe. Si l'arrêt échoue, exécutez l'application en tant qu'administrateur.")
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Arrêt impossible", f"Impossible d'arrêter TS4_x64.exe : {exc}")
        else:
            try:
                completed = subprocess.run(["pkill", "-f", process_name], capture_output=True, text=True)
                if completed.returncode == 0:
                    QtWidgets.QMessageBox.information(self, "Sims 4 arrêté", "Le processus a été arrêté avec succès.")
                else:
                    output = completed.stderr.strip() or completed.stdout.strip() or "La commande a échoué."
                    QtWidgets.QMessageBox.warning(self, "Aucun processus arrêté", output)
            except FileNotFoundError:
                QtWidgets.QMessageBox.critical(self, "Commande introuvable", "La commande pkill est introuvable.")

    def _is_sims_running(self):
        name = "TS4_x64.exe"
        if sys.platform.startswith("win"):
            try:
                completed = subprocess.run(["tasklist"], capture_output=True, text=True)
                out = (completed.stdout or "") + "\n" + (completed.stderr or "")
                return name.lower() in out.lower()
            except Exception:
                return False
        else:
            try:
                completed = subprocess.run(["pgrep", "-f", "TS4_x64"], capture_output=True)
                return completed.returncode == 0
            except Exception:
                return False

    def update_launch_button_state(self):
        if hasattr(self, "launch_button"):
            executable_path = self.settings.get("sims_executable_path", "")
            self.launch_button.setEnabled(bool(executable_path and os.path.isfile(executable_path)))

    def open_tools_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Tools")
        dialog.setModal(True)

        layout = QtWidgets.QVBoxLayout(dialog)

        btn_dup = QtWidgets.QPushButton("Find dupplicates", dialog)
        btn_dup.clicked.connect(self.open_duplicate_finder)
        layout.addWidget(btn_dup)

        btn_nonmods = QtWidgets.QPushButton("Find non-mods files", dialog)
        btn_nonmods.clicked.connect(partial(self._show_placeholder_message, "Find non-mods files", "La détection des fichiers non mods sera ajoutée ultérieurement."))
        layout.addWidget(btn_nonmods)

        btn_disable = QtWidgets.QPushButton("Disable all mods", dialog)
        btn_disable.clicked.connect(partial(self._show_placeholder_message, "Disable all mods", "La désactivation des mods sera proposée dans une future mise à jour."))
        layout.addWidget(btn_disable)

        btn_cfg = QtWidgets.QPushButton("Correct resource.cfg", dialog)
        btn_cfg.clicked.connect(self.correct_resource_cfg)
        layout.addWidget(btn_cfg)

        btn_symlink = QtWidgets.QPushButton("Symlink Mods", dialog)
        btn_symlink.clicked.connect(partial(self._show_placeholder_message, "Symlink Mods", "La création de liens symboliques vers le dossier Mods sera ajoutée ultérieurement."))
        layout.addWidget(btn_symlink)

        btn_backup = QtWidgets.QPushButton("Backup Mods", dialog)
        btn_backup.clicked.connect(partial(self._show_placeholder_message, "Backup Mods", "La sauvegarde du dossier Mods sera disponible dans une prochaine version."))
        layout.addWidget(btn_backup)

        close_button = QtWidgets.QPushButton("Fermer", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec_()

    def _show_placeholder_message(self, title, message):
        QtWidgets.QMessageBox.information(self, title, message)

    def correct_resource_cfg(self):
        mods_dir = self.settings.get("mod_directory", "")
        if not mods_dir or not os.path.isdir(mods_dir):
            QtWidgets.QMessageBox.warning(self, "Dossier des mods invalide", "Définis un dossier des mods valide dans la configuration.")
            return
        target = os.path.join(mods_dir, "Resource.cfg")
        expected_lines = [
            "Priority 500",
            "PackedFile *.package",
            "PackedFile */*.package",
            "PackedFile */*/*.package",
            "PackedFile */*/*/*.package",
            "PackedFile */*/*/*/*.package",
            "PackedFile */*/*/*/*/*.package",
        ]
        expected_content = "\r\n".join(expected_lines) + "\r\n"
        current = ""
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8", errors="ignore") as fh:
                    current = fh.read()
            except OSError:
                current = ""
        def _normalize(text):
            return "\n".join([line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line is not None])
        if _normalize(current) == _normalize(expected_content):
            QtWidgets.QMessageBox.information(self, "Resource.cfg", "Le fichier Resource.cfg est déjà conforme.")
            return
        # Backup existing if present
        if os.path.exists(target):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = os.path.join(mods_dir, f"Resource.cfg.bak_{ts}")
            try:
                shutil.copy2(target, backup)
            except OSError:
                pass
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(expected_content)
            QtWidgets.QMessageBox.information(self, "Resource.cfg", "Le fichier Resource.cfg a été corrigé.")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible d'écrire Resource.cfg : {exc}")

    def open_duplicate_finder(self):
        root = self.settings.get("mod_directory", "")
        if not root or not os.path.isdir(root):
            QtWidgets.QMessageBox.warning(self, "Dossier des mods invalide", "Définis un dossier des mods valide dans la configuration.")
            return
        dialog = DuplicateFinderDialog(self, root)
        dialog.exec_()

    def populate_table(self, data_rows):
        self.all_data_rows = list(data_rows)
        self._apply_search_filter()

    def apply_search_filter(self, _text=None, forced=False):
        # If instant search disabled, only process when forced=True
        self._apply_search_filter(forced=forced)

    def _apply_search_filter(self, forced=False):
        query = ""
        if hasattr(self, "search_edit"):
            query = self.search_edit.text().strip().lower()

        show_search_results = self.settings.get("show_search_results", True)
        instant = self.settings.get("instant_search", True)
        if not forced and not instant:
            return

        if not show_search_results:
            filtered_rows = list(self.all_data_rows)
        elif not query:
            filtered_rows = list(self.all_data_rows)
        else:
            filtered_rows = [
                row
                for row in self.all_data_rows
                if self._row_matches_query(row, query)
            ]

        # Optionally filter only disabled mods
        if self.settings.get("show_disabled_only", False):
            filtered_rows = [row for row in filtered_rows if bool(row.get("disabled", False))]

        self._render_table(filtered_rows)

    def _row_matches_query(self, row, query):
        for value in self._gather_searchable_values(row):
            if query in value:
                return True
        return False

    def _gather_searchable_values(self, row):
        values = [
            str(row.get("status", "")),
            str(row.get("group", "")),
            str(row.get("package", "")),
            str(row.get("package_date", "")),
            str(row.get("script", "")),
            str(row.get("script_date", "")),
            str(row.get("version", "")),
            str(row.get("confidence", "")),
        ]
        ignored_value = "oui" if row.get("ignored", False) else "non"
        values.append(ignored_value)
        if row.get("confidence_tooltip"):
            values.append(str(row.get("confidence_tooltip")))
        values.extend(str(candidate) for candidate in row.get("ignore_candidates", []))
        values.extend(str(path) for path in row.get("paths", []))
        return [value.lower() for value in values if value]

    def _render_table(self, rows):
        header = self.table.horizontalHeader()
        sorting_enabled = self.table.isSortingEnabled()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        table = self.table
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        try:
            if table.rowCount():
                table.clearContents()
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                columns = [
                    row.get("status", ""),
                    row.get("group", ""),
                    row.get("package", ""),
                    row.get("package_date", ""),
                    row.get("script", ""),
                    row.get("script_date", ""),
                    row.get("version", ""),
                    row.get("confidence", ""),
                ]
                for col_idx, value in enumerate(columns):
                    item = QtWidgets.QTableWidgetItem(str(value))
                    if col_idx == 0:
                        item.setData(QtCore.Qt.UserRole, tuple(row.get("ignore_candidates") or []))
                        item.setData(QtCore.Qt.UserRole + 1, tuple(row.get("paths") or []))
                    if col_idx == 7:
                        item.setToolTip(row.get("confidence_tooltip", ""))
                    table.setItem(row_index, col_idx, item)

                ignored = row.get("ignored", False)
                ignore_item = QtWidgets.QTableWidgetItem("Oui" if ignored else "Non")
                ignore_item.setData(QtCore.Qt.UserRole, 1 if ignored else 0)
                ignore_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                table.setItem(row_index, 8, ignore_item)

                ignore_checkbox = QtWidgets.QCheckBox()
                ignore_checkbox.stateChanged.connect(
                    partial(self.update_ignore_mod, tuple(row.get("ignore_candidates") or []))
                )
                ignore_checkbox.blockSignals(True)
                ignore_checkbox.setChecked(ignored)
                ignore_checkbox.blockSignals(False)
                table.setCellWidget(row_index, 8, ignore_checkbox)

                # Highlight disabled mods (override)
                if row.get("disabled"):
                    bg = QtGui.QBrush(QtGui.QColor("#8b0000"))
                    fg = QtGui.QBrush(QtGui.QColor("#ffffff"))
                    for c in range(self.table.columnCount()):
                        it = self.table.item(row_index, c)
                        if it is not None:
                            it.setBackground(bg)
                            it.setForeground(fg)
                # Highlight rows installed via Mod Installer (group present)
                elif row.get("group"):
                    bg = QtGui.QBrush(QtGui.QColor("#2e7d32"))
                    fg = QtGui.QBrush(QtGui.QColor("#ffffff"))
                    for c in range(self.table.columnCount()):
                        it = self.table.item(row_index, c)
                        if it is not None:
                            it.setBackground(bg)
                            it.setForeground(fg)

                if row_index % 50 == 0:
                    self._yield_ui_events()
        finally:
            table.setUpdatesEnabled(True)

        table.setSortingEnabled(sorting_enabled)
        if sorting_enabled and rows:
            table.sortByColumn(sort_section, sort_order)
        table.viewport().update()
        self._yield_ui_events()

    def show_context_menu(self, position):
        index = self.table.indexAt(position)
        if not index.isValid():
            return

        row = index.row()
        status_item = self.table.item(row, 0)
        candidates = []
        if status_item is not None:
            stored_candidates = status_item.data(QtCore.Qt.UserRole)
            if stored_candidates:
                candidates = list(stored_candidates)

        menu = QtWidgets.QMenu(self)
        ignore_action = menu.addAction("Ignorer")
        show_in_explorer_action = menu.addAction("Afficher dans l'explorateur")
        delete_action = menu.addAction("Supprimer le mod")
        google_action = menu.addAction("Recherche Google")

        selected_action = menu.exec_(self.table.viewport().mapToGlobal(position))

        if selected_action == ignore_action:
            checkbox = self.table.cellWidget(row, 8)
            if checkbox is not None:
                checkbox.setChecked(not checkbox.isChecked())
        elif selected_action == show_in_explorer_action:
            self.show_in_explorer(row, candidates)
        elif selected_action == delete_action:
            self.delete_mod(row, candidates)
        elif selected_action == google_action:
            self.launch_google_search(row, candidates)

    def _resolve_row_paths(self, row):
        status_item = self.table.item(row, 0)
        if status_item is None:
            return []
        paths = status_item.data(QtCore.Qt.UserRole + 1)
        return list(paths) if paths else []

    def _open_in_file_manager(self, target_path):
        if sys.platform.startswith("win"):
            try:
                os.startfile(target_path)
            except OSError:
                QtWidgets.QMessageBox.warning(self, "Erreur", "Impossible d'ouvrir l'explorateur de fichiers.")
        elif sys.platform == "darwin":
            QtCore.QProcess.startDetached("open", [target_path])
        else:
            QtCore.QProcess.startDetached("xdg-open", [target_path])

    def show_in_explorer(self, row, candidates):
        paths = self._resolve_row_paths(row)
        if not paths:
            return
        target_path = paths[0]
        if not os.path.exists(target_path):
            QtWidgets.QMessageBox.warning(self, "Fichier introuvable", "Le fichier sélectionné est introuvable sur le disque.")
            return

        directory = os.path.dirname(target_path) or target_path
        self._open_in_file_manager(directory)

    def delete_mod(self, row, candidates):
        # Prevent deletion if Sims is running
        try:
            if self._is_sims_running():
                QtWidgets.QMessageBox.warning(self, "Suppression impossible", "TS4_x64.exe est en cours d'exécution. Fermez le jeu avant de supprimer des mods.")
                return
        except Exception:
            pass
        paths = self._resolve_row_paths(row)
        if not paths:
            return

        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirmer la suppression",
            "Supprimer ce mod supprimera définitivement les fichiers associés. Continuer ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )

        if confirm != QtWidgets.QMessageBox.Yes:
            return

        errors = []
        for path in paths:
            if not os.path.exists(path):
                continue
            try:
                os.remove(path)
            except OSError as exc:
                errors.append(str(exc))

        if errors:
            QtWidgets.QMessageBox.warning(
                self,
                "Erreur lors de la suppression",
                "\n".join(errors),
            )

        if candidates:
            for name in candidates:
                self.ignored_mods.discard(name)
            save_ignore_list(self.ignored_mods)
            self.settings["ignored_mods"] = sorted(self.ignored_mods)
            save_settings(self.settings)

        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.refresh_table_only()
        else:
            self.table.removeRow(row)

    def launch_google_search(self, row, candidates):
        file_name = ""
        # columns: 2=package, 4=script after adding group column
        for column in (2, 4):
            item = self.table.item(row, column)
            if item:
                text = item.text().strip()
                if text:
                    file_name = text
                    break

        if not file_name and candidates:
            file_name = candidates[0]

        if not file_name:
            return

        base_name, _ = os.path.splitext(file_name)
        if not base_name:
            return

        search_url = QtCore.QUrl(f"https://www.google.com/search?q={quote_plus(base_name)}")
        QtGui.QDesktopServices.openUrl(search_url)

    def update_ignore_mod(self, candidates, state):
        candidates = [name for name in candidates if name]
        if not candidates:
            return

        canonical_key = candidates[0]
        if state == QtCore.Qt.Checked:
            for name in candidates[1:]:
                self.ignored_mods.discard(name)
            self.ignored_mods.add(canonical_key)
        else:
            for name in candidates:
                self.ignored_mods.discard(name)

        save_ignore_list(self.ignored_mods)
        self.settings["ignored_mods"] = sorted(self.ignored_mods)
        save_settings(self.settings)
        self.refresh_table_only()

    def export_current(self):
        rows = []
        for row in range(self.table.rowCount()):
            row_data = []
            for col in range(self.table.columnCount() - 1):
                item = self.table.item(row, col)
                row_data.append(item.text() if item else "")
            checkbox_widget = self.table.cellWidget(row, self.table.columnCount() - 1)
            row_data.append(checkbox_widget.isChecked() if checkbox_widget else False)  # Ajouter l'état de la case à cocher "Ignoré"
            rows.append(row_data)

        save_path = self.settings.get("xls_file_path", "")
        if not save_path:
            save_path = QtWidgets.QFileDialog.getSaveFileName(self, "Sauvegarder sous", "", "Excel Files (*.xlsx)")[0]
            if not save_path:
                return
            self.settings["xls_file_path"] = save_path
            save_settings(self.settings)

        export_to_excel(save_path, rows)
        QtWidgets.QMessageBox.information(self, "Info", f"Export terminé vers : {save_path}")

    def _show_header_menu(self, pos):
        header = self.table.horizontalHeader()
        global_pos = header.mapToGlobal(pos)
        menu = QtWidgets.QMenu(self)
        labels = [
            "État",
            "Mod (groupe)",
            "Fichier .package",
            "Date .package",
            "Fichier .ts4script",
            "Date .ts4script",
            "Version",
            "Confiance",
            "Ignoré",
        ]
        hidden = set(self.settings.get("hidden_columns", []))
        for col, label in enumerate(labels):
            action = QtWidgets.QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(col not in hidden)
            action.triggered.connect(partial(self._toggle_column_visibility, col))
            menu.addAction(action)
        menu.exec_(global_pos)

    def _toggle_column_visibility(self, col, checked):
        hidden = set(int(c) for c in self.settings.get("hidden_columns", []))
        if checked and col in hidden:
            hidden.remove(col)
        elif not checked:
            hidden.add(col)
        self.settings["hidden_columns"] = sorted(int(c) for c in hidden)
        save_settings(self.settings)
        self.table.setColumnHidden(col, not checked)

    def _apply_hidden_columns(self):
        hidden = set(int(c) for c in self.settings.get("hidden_columns", []))
        for col in range(self.table.columnCount()):
            self.table.setColumnHidden(col, col in hidden)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    # Splash screen at startup
    class StartupSplash(QtWidgets.QSplashScreen):
        def __init__(self, title):
            pix = QtGui.QPixmap(640, 360)
            pix.fill(QtGui.QColor("#263238"))
            super().__init__(pix)
            self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint)
            self._painter = QtGui.QPainter()
            self._title = title
            self._message = ""
            self._draw()

        def _draw(self):
            pix = self.pixmap()
            p = QtGui.QPainter(pix)
            try:
                p.setRenderHint(QtGui.QPainter.Antialiasing)
                # Clear background
                p.fillRect(pix.rect(), QtGui.QColor("#263238"))
                # Title
                font = QtGui.QFont()
                font.setPointSize(16)
                font.setBold(True)
                p.setFont(font)
                p.setPen(QtGui.QColor("#ffffff"))
                title_rect = pix.rect().adjusted(24, 24, -24, -pix.height()//2)
                p.drawText(title_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter | QtCore.Qt.TextWordWrap, self._title)
                # Message
                font2 = QtGui.QFont()
                font2.setPointSize(11)
                p.setFont(font2)
                p.setPen(QtGui.QColor("#cfd8dc"))
                msg_rect = pix.rect().adjusted(24, pix.height()//2 - 20, -24, -24)
                p.drawText(msg_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap, self._message)
            finally:
                p.end()
            self.setPixmap(pix)

        def update_message(self, text):
            self._message = str(text or "")
            self._draw()

    splash = StartupSplash(f"Sims 4 Mod Manager {APP_VERSION}\n{APP_VERSION_DATE}")
    splash.show()
    app.processEvents()

    window = ModManagerApp(splash=splash)
    window.show()
    # Fallback: ensure splash closes eventually
    QtCore.QTimer.singleShot(2000, lambda: splash.finish(window) if splash is not None else None)
    sys.exit(app.exec_())
