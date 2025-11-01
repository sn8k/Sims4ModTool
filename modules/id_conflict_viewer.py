
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from openpyxl import Workbook

try:  # pragma: no cover - Qt binding selection handled at runtime
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
    QT_LIB = "PyQt5"
except Exception:  # pragma: no cover
    try:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
        QT_LIB = "PySide2"
    except Exception:  # pragma: no cover
        try:
            from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
            QT_LIB = "PySide6"
        except Exception:  # pragma: no cover
            from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
            QT_LIB = "PyQt6"

from concurrent.futures import ThreadPoolExecutor, as_completed


def _format_datetime(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y %H:%M")


# Resource heuristics derived from Sims 4 DBPF type identifiers
RESOURCE_LIBRARY: Dict[int, Dict[str, object]] = {
    0x0166038C: {"category": "Script", "label": "Python Script"},
    0x015A1849: {"category": "Gameplay", "label": "Object Definition"},
    0x01B2D882: {"category": "Gameplay", "label": "Tuning"},
    0x025C95B7: {"category": "Gameplay", "label": "Autonomie"},
    0x00B2D882: {"category": "Gameplay", "label": "Tuning (Legacy)"},
    0x0355E0A6: {"category": "Build/Buy", "label": "Object Catalog"},
    0x319E4F1D: {"category": "Texture", "label": "Diffuse Map"},
    0x0333406C: {"category": "Texture", "label": "Image Resource"},
    0x034AEECB: {"category": "CAS", "label": "CAS Part"},
    0x03555A5D: {"category": "CAS", "label": "CAS Part Thumbnail"},
    0x545AC67A: {"category": "Script", "label": "Binary Script"},
    0x0621661E: {"category": "Audio", "label": "Audio Stream"},
    0x319E4F87: {"category": "Texture", "label": "Normal Map"},
    0x34613C29: {"category": "Texture", "label": "Specular Map"},
    0x5B4D8F8C: {"category": "Gameplay", "label": "Slot"},
    0xE06C2907: {"category": "Gameplay", "label": "Animation Clip"},
}

CRITICAL_TYPES: Set[int] = {
    0x0166038C,
    0x015A1849,
    0x01B2D882,
    0x025C95B7,
    0x5B4D8F8C,
}

HIGH_TYPES: Set[int] = {
    0x0333406C,
    0x034AEECB,
    0x0355E0A6,
    0x545AC67A,
    0x319E4F1D,
    0x319E4F87,
    0x34613C29,
}

CATEGORY_ORDER: Dict[str, int] = {
    "Gameplay": 0,
    "Script": 1,
    "Build/Buy": 2,
    "CAS": 3,
    "Texture": 4,
    "Audio": 5,
    "Autre": 6,
}

SEVERITY_PRIORITY: Dict[str, int] = {
    "Critique": 0,
    "Élevée": 1,
    "Modérée": 2,
    "Faible": 3,
}

SEVERITY_STYLE = {
    "Critique": {
        "bg": QtGui.QColor("#7f1d1d"),
        "fg": QtGui.QColor("#ffffff"),
        "icon": QtWidgets.QStyle.SP_MessageBoxCritical,
    },
    "Élevée": {
        "bg": QtGui.QColor("#b45309"),
        "fg": QtGui.QColor("#000000"),
        "icon": QtWidgets.QStyle.SP_MessageBoxWarning,
    },
    "Modérée": {
        "bg": QtGui.QColor("#fbbf24"),
        "fg": QtGui.QColor("#000000"),
        "icon": QtWidgets.QStyle.SP_DialogApplyButton,
    },
    "Faible": {
        "bg": QtGui.QColor("#e5e7eb"),
        "fg": QtGui.QColor("#111827"),
        "icon": QtWidgets.QStyle.SP_FileIcon,
    },
}

KNOWN_MOD_KEYWORDS: Dict[str, str] = {
    "wickedwhims": "WickedWhims",
    "basemental": "Basemental",
    "mccc": "MC Command Center",
    "slice of life": "Slice of Life",
    "wonderful whims": "WonderfulWhims",
    "turbodriver": "TURBODRIVER",
    "littlemssam": "LittleMsSam",
    "zerobroken": "Zero's Mods",
    "sacrificial": "Sacrificial",
}

SPECIAL_DATE = QtCore.QDate(1970, 1, 1)


def _qt_exec(obj, *args, **kwargs):
    if hasattr(obj, "exec"):
        return obj.exec(*args, **kwargs)
    return obj.exec_(*args, **kwargs)


@dataclass
class ConflictFile:
    path: str
    modified: float
    size: int
    has_ts4script: bool
    keywords: Set[str] = field(default_factory=set)

    @property
    def modified_dt(self) -> Optional[datetime]:
        try:
            return datetime.fromtimestamp(self.modified)
        except (OSError, ValueError):
            return None

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)


@dataclass
class ConflictRecord:
    type_id: int
    group_id: int
    instance_id: int
    files: List[ConflictFile] = field(default_factory=list)
    severity: str = "Modérée"
    category: str = "Autre"
    label: str = "Ressource"
    priority: Tuple[int, int, int] = (2, 6, 0)
    latest_modified: Optional[datetime] = None
    has_script: bool = False
    keywords: Set[str] = field(default_factory=set)

    def refresh_metadata(self) -> None:
        meta = RESOURCE_LIBRARY.get(self.type_id)
        if meta:
            self.category = str(meta.get("category") or "Autre")
            self.label = str(meta.get("label") or "Ressource")
        else:
            self.category = "Autre"
            self.label = "Ressource inconnue"

        self.latest_modified = None
        self.has_script = any(f.has_ts4script for f in self.files)
        latest_ts = 0.0
        all_keywords: Set[str] = set()
        for item in self.files:
            if item.modified and item.modified > latest_ts:
                latest_ts = item.modified
                self.latest_modified = item.modified_dt
            all_keywords.update(item.keywords)
        self.keywords = all_keywords

        severity = "Faible"
        if self.type_id in CRITICAL_TYPES or self.category == "Gameplay":
            severity = "Critique"
        elif self.has_script or self.type_id in HIGH_TYPES:
            severity = "Élevée"
        elif len(self.files) >= 3:
            severity = "Élevée"
        elif self.category in {"CAS", "Texture"}:
            severity = "Modérée"
        else:
            severity = "Faible"

        if self.latest_modified:
            age_days = max(
                0,
                int((datetime.now() - self.latest_modified).total_seconds() // 86400),
            )
            if age_days <= 14 and severity != "Critique":
                severity = "Élevée"

        self.severity = severity
        sev_rank = SEVERITY_PRIORITY.get(self.severity, 3)
        cat_rank = CATEGORY_ORDER.get(self.category, CATEGORY_ORDER["Autre"])
        neg_files = -len(self.files)
        self.priority = (sev_rank, cat_rank, neg_files)

    @property
    def resource_key(self) -> Tuple[int, int, int]:
        return self.type_id, self.group_id, self.instance_id

    @property
    def t_hex(self) -> str:
        return f"0x{self.type_id:08X}"

    @property
    def g_hex(self) -> str:
        return f"0x{self.group_id:08X}"

    @property
    def i_hex(self) -> str:
        return f"0x{self.instance_id:016X}"

    def keyword_summary(self) -> str:
        if not self.keywords:
            return ""
        ordered = sorted(self.keywords, key=str.casefold)
        return ", ".join(ordered)

def _read_le_u32(buffer: bytes, offset: int) -> int:
    try:
        return int.from_bytes(buffer[offset : offset + 4], "little", signed=False)
    except Exception:
        return 0


def _parse_dbpf_table(
    table_bytes: bytes,
    count_hint: Optional[int],
    cancel_event: Optional[threading.Event],
) -> List[Tuple[int, int, int]]:
    best: List[Tuple[int, int, int]] = []
    best_len = 0
    candidates = (16, 24, 28, 32, 36, 40)

    for entry_size in candidates:
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break
        results: List[Tuple[int, int, int]] = []
        if count_hint and count_hint > 0:
            n = min(count_hint, len(table_bytes) // entry_size)
        else:
            n = len(table_bytes) // entry_size
        if n <= 0:
            continue
        valid = 0
        for idx in range(n):
            if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                break
            base = idx * entry_size
            chunk = table_bytes[base : base + 16]
            if len(chunk) < 16:
                break
            t = int.from_bytes(chunk[0:4], "little", signed=False)
            g = int.from_bytes(chunk[4:8], "little", signed=False)
            ih = int.from_bytes(chunk[8:12], "little", signed=False)
            il = int.from_bytes(chunk[12:16], "little", signed=False)
            inst = (ih << 32) | il
            if t == 0 and g == 0 and inst == 0:
                continue
            results.append((t, g, inst))
            valid += 1
        if valid > best_len:
            best = results
            best_len = valid
    return best


def _scan_tail_index(
    file_path: str,
    file_size: int,
    cancel_event: Optional[threading.Event],
) -> List[Tuple[int, int, int]]:
    max_tail = min(8 * 1024 * 1024, file_size)
    try:
        with open(file_path, "rb") as handle:
            handle.seek(file_size - max_tail)
            buffer = handle.read(max_tail)
    except Exception:
        return []

    output: List[Tuple[int, int, int]] = []
    limit = max(0, len(buffer) - 24)
    for pos in range(0, limit, 4):
        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            break
        chunk = buffer[pos : pos + 24]
        if len(chunk) < 24:
            break
        t = int.from_bytes(chunk[0:4], "little", signed=False)
        g = int.from_bytes(chunk[4:8], "little", signed=False)
        ih = int.from_bytes(chunk[8:12], "little", signed=False)
        il = int.from_bytes(chunk[12:16], "little", signed=False)
        inst = (ih << 32) | il
        if (t | g | inst) == 0:
            continue
        off = int.from_bytes(chunk[16:20], "little", signed=False)
        size = int.from_bytes(chunk[20:24], "little", signed=False)
        if size <= 0 or off <= 0 or off >= file_size:
            continue
        if off + size > file_size:
            continue
        output.append((t, g, inst))
    seen: Set[Tuple[int, int, int]] = set()
    unique: List[Tuple[int, int, int]] = []
    for item in output:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _read_tgi_entries_from_dbpf(
    path: str,
    logger: Optional[logging.Logger] = None,
    allow_tail_fallback: bool = True,
    cancel_event: Optional[threading.Event] = None,
) -> List[Tuple[int, int, int]]:
    try:
        with open(path, "rb") as fh:
            header = fh.read(96)
        if len(header) < 96 or header[0:4] != b"DBPF":
            return []
        index_count = _read_le_u32(header, 36)
        index_offset = _read_le_u32(header, 40)
        index_size = _read_le_u32(header, 44)
        file_size = os.path.getsize(path)
        if index_offset + index_size > file_size or index_size <= 0:
            index_count = _read_le_u32(header, 32)
            index_offset = _read_le_u32(header, 48)
            index_size = _read_le_u32(header, 52)
        if index_offset <= 0 or index_offset > file_size:
            index_offset = 0
            index_size = 0
        table_bytes: bytes = b""
        if index_offset > 0 and index_size > 0:
            try:
                with open(path, "rb") as fh:
                    fh.seek(index_offset)
                    table_bytes = fh.read(index_size)
            except Exception:
                table_bytes = b""
        results = _parse_dbpf_table(table_bytes, index_count, cancel_event)
        if results:
            return results
        if not allow_tail_fallback:
            return results
        return _scan_tail_index(path, file_size, cancel_event)
    except Exception as exc:  # pragma: no cover - best effort reader
        if logger:
            logger.debug("IDConflictViewer: DBPF parse failure for %s (%s)", path, exc)
        return []


class IDConflictViewerDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        mods_root: str,
        *,
        id_index_cache_path: str,
        mod_scan_cache_path: str,
        installed_mods_path: str,
        version_releases: Optional[Dict[str, datetime]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ID Conflict Viewer")
        self.setModal(True)
        self.resize(1024, 640)

        self.parent_app = parent
        self.mods_root = os.path.abspath(mods_root)
        self.id_index_cache_path = id_index_cache_path
        self.mod_scan_cache_path = mod_scan_cache_path
        self.installed_mods_path = installed_mods_path
        self.version_releases = version_releases or {}
        self.logger = logging.getLogger("Sims4ModTool")

        self._cancel_event = threading.Event()
        self._conflict_records: List[ConflictRecord] = []
        self._filtered_records: List[ConflictRecord] = []
        self._record_map: Dict[Tuple[int, int, int], ConflictRecord] = {}
        self._last_stats: Dict[str, object] = {}

        main_layout = QtWidgets.QVBoxLayout(self)

        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(QtWidgets.QLabel("Dossier analysé:", self))
        self.path_edit = QtWidgets.QLineEdit(self)
        self.path_edit.setText(self.mods_root)
        self.path_edit.setReadOnly(True)
        path_row.addWidget(self.path_edit, 1)
        self.browse_btn = QtWidgets.QPushButton("Parcourir…", self)
        self.browse_btn.clicked.connect(self._on_browse_root)
        path_row.addWidget(self.browse_btn)
        main_layout.addLayout(path_row)

        options_row = QtWidgets.QHBoxLayout()
        self.recursive_checkbox = QtWidgets.QCheckBox("Récursif", self)
        self.recursive_checkbox.setChecked(True)
        options_row.addWidget(self.recursive_checkbox)
        self.use_scan_cache_checkbox = QtWidgets.QCheckBox("Utiliser cache fichiers", self)
        self.use_scan_cache_checkbox.setChecked(True)
        options_row.addWidget(self.use_scan_cache_checkbox)
        self.fast_mode_checkbox = QtWidgets.QCheckBox("Mode rapide (sans fallback)", self)
        options_row.addWidget(self.fast_mode_checkbox)
        options_row.addStretch(1)
        main_layout.addLayout(options_row)

        filters_group = QtWidgets.QGroupBox("Filtres avancés", self)
        filters_layout = QtWidgets.QGridLayout(filters_group)
        self.category_combo = QtWidgets.QComboBox(self)
        self.category_combo.addItems(["Toutes"] + list(CATEGORY_ORDER.keys()))
        self.category_combo.currentTextChanged.connect(self._apply_filters)
        filters_layout.addWidget(QtWidgets.QLabel("Catégorie:", self), 0, 0)
        filters_layout.addWidget(self.category_combo, 0, 1)

        self.severity_combo = QtWidgets.QComboBox(self)
        self.severity_combo.addItems(["Toutes", "Critique", "Élevée", "Modérée", "Faible"])
        self.severity_combo.currentTextChanged.connect(self._apply_filters)
        filters_layout.addWidget(QtWidgets.QLabel("Sévérité:", self), 0, 2)
        filters_layout.addWidget(self.severity_combo, 0, 3)

        self.keyword_edit = QtWidgets.QLineEdit(self)
        self.keyword_edit.setPlaceholderText("Mots-clés (ex: WickedWhims, Basemental)")
        self.keyword_edit.textChanged.connect(self._apply_filters)
        filters_layout.addWidget(QtWidgets.QLabel("Filtrer:", self), 1, 0)
        filters_layout.addWidget(self.keyword_edit, 1, 1, 1, 3)

        self.script_only_checkbox = QtWidgets.QCheckBox("Uniquement mods avec .ts4script", self)
        self.script_only_checkbox.toggled.connect(self._apply_filters)
        filters_layout.addWidget(self.script_only_checkbox, 2, 0, 1, 2)

        self.date_from_edit = QtWidgets.QDateEdit(self)
        self.date_from_edit.setCalendarPopup(True)
        self.date_from_edit.setMinimumDate(SPECIAL_DATE)
        self.date_from_edit.setDate(SPECIAL_DATE)
        self.date_from_edit.setSpecialValueText("Début (aucun)")
        self.date_from_edit.dateChanged.connect(self._apply_filters)
        filters_layout.addWidget(self.date_from_edit, 2, 2)

        self.date_to_edit = QtWidgets.QDateEdit(self)
        self.date_to_edit.setCalendarPopup(True)
        self.date_to_edit.setMinimumDate(SPECIAL_DATE)
        self.date_to_edit.setDate(SPECIAL_DATE)
        self.date_to_edit.setSpecialValueText("Fin (aucune)")
        self.date_to_edit.dateChanged.connect(self._apply_filters)
        filters_layout.addWidget(self.date_to_edit, 2, 3)

        filters_buttons = QtWidgets.QHBoxLayout()
        filters_buttons.addStretch(1)
        self.reset_filters_btn = QtWidgets.QPushButton("Réinitialiser filtres", self)
        self.reset_filters_btn.clicked.connect(self._reset_filters)
        filters_buttons.addWidget(self.reset_filters_btn)
        filters_layout.addLayout(filters_buttons, 3, 0, 1, 4)

        main_layout.addWidget(filters_group)

        actions_row = QtWidgets.QHBoxLayout()
        self.scan_btn = QtWidgets.QPushButton("Analyser", self)
        self.scan_btn.clicked.connect(self._run_scan)
        actions_row.addWidget(self.scan_btn)
        self.stop_btn = QtWidgets.QPushButton("Stop", self)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._request_cancel)
        actions_row.addWidget(self.stop_btn)
        actions_row.addStretch(1)
        self.disable_btn = QtWidgets.QPushButton("Désactiver les mods conflictuels", self)
        self.disable_btn.clicked.connect(self._disable_conflicting_mods)
        actions_row.addWidget(self.disable_btn)
        self.order_btn = QtWidgets.QPushButton("Réagencer automatiquement", self)
        self.order_btn.clicked.connect(self._suggest_reorder)
        actions_row.addWidget(self.order_btn)
        self.compat_btn = QtWidgets.QPushButton("Vérifier compatibilité", self)
        self.compat_btn.clicked.connect(self._check_mod_updates)
        actions_row.addWidget(self.compat_btn)
        self.export_btn = QtWidgets.QPushButton("Exporter vers Excel", self)
        self.export_btn.clicked.connect(self._export_excel)
        actions_row.addWidget(self.export_btn)
        main_layout.addLayout(actions_row)

        self.progress = QtWidgets.QProgressBar(self)
        self.progress.setVisible(False)
        main_layout.addWidget(self.progress)

        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setHeaderLabels(
            [
                "Sévérité",
                "Ressource / Fichier",
                "Infos",
                "Conflits",
                "Dernière modif.",
                "Mots-clés",
            ]
        )
        header = self.tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        main_layout.addWidget(self.tree, 1)

        footer = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("", self)
        footer.addWidget(self.status_label, 1)
        self.close_btn = QtWidgets.QPushButton("Fermer", self)
        self.close_btn.clicked.connect(self.accept)
        footer.addWidget(self.close_btn)
        main_layout.addLayout(footer)

        QtCore.QTimer.singleShot(0, self._run_scan)
    def _on_browse_root(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choisir un dossier de mods",
            self.mods_root,
        )
        if not directory:
            return
        self.mods_root = os.path.abspath(directory)
        self.path_edit.setText(self.mods_root)
        self._run_scan()

    def _reset_filters(self) -> None:
        self.category_combo.setCurrentIndex(0)
        self.severity_combo.setCurrentIndex(0)
        self.keyword_edit.clear()
        self.script_only_checkbox.setChecked(False)
        self.date_from_edit.blockSignals(True)
        self.date_to_edit.blockSignals(True)
        self.date_from_edit.setDate(SPECIAL_DATE)
        self.date_to_edit.setDate(SPECIAL_DATE)
        self.date_from_edit.blockSignals(False)
        self.date_to_edit.blockSignals(False)
        self._apply_filters()

    def _request_cancel(self) -> None:
        self.logger.info("IDConflictViewer: cancellation requested by user")
        self._cancel_event.set()
        self.status_label.setText("Annulation en cours…")

    def _load_id_index_cache(self) -> Dict[str, Dict[str, object]]:
        try:
            with open(self.id_index_cache_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_id_index_cache(self, cache: Dict[str, Dict[str, object]]) -> None:
        try:
            with open(self.id_index_cache_path, "w", encoding="utf-8") as handle:
                json.dump(cache, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.logger.debug("IDConflictViewer: unable to persist cache (%s)", exc)

    def _iter_packages(self, root: str, *, recursive: bool) -> Iterable[str]:
        if recursive:
            for cur, _dirs, files in os.walk(root):
                for name in files:
                    if name.lower().endswith(".package"):
                        yield os.path.join(cur, name)
        else:
            try:
                for name in os.listdir(root):
                    if name.lower().endswith(".package"):
                        yield os.path.join(root, name)
            except OSError:
                return

    def _list_packages_from_scan_cache(self, root: str) -> Optional[List[str]]:
        try:
            with open(self.mod_scan_cache_path, "r", encoding="utf-8") as handle:
                cache = json.load(handle)
        except Exception:
            return None
        cache_root = str(cache.get("root") or "")
        if not cache_root:
            return None
        if os.path.normcase(os.path.normpath(cache_root)) != os.path.normcase(os.path.normpath(root)):
            return None
        entries = cache.get("entries") or []
        result: List[str] = []
        for entry in entries:
            if str(entry.get("type") or "").lower() != "package":
                continue
            rel = entry.get("path")
            if not rel:
                continue
            full = os.path.join(root, rel)
            if os.path.isfile(full):
                result.append(full)
        return result

    def _collect_keywords(self, path: str) -> Set[str]:
        found: Set[str] = set()
        lower = path.lower()
        for needle, label in KNOWN_MOD_KEYWORDS.items():
            if needle in lower:
                found.add(label)
        return found

    def _folder_has_ts4script(self, package_path: str) -> bool:
        folder = os.path.dirname(package_path)
        try:
            for name in os.listdir(folder):
                if name.lower().endswith(".ts4script"):
                    return True
        except OSError:
            return False
        return False
    def _run_scan(self) -> None:
        root = self.mods_root
        if not root or not os.path.isdir(root):
            QtWidgets.QMessageBox.warning(self, "Dossier invalide", "Définis un dossier de mods valide.")
            return

        self._cancel_event.clear()
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.tree.clear()
        self.status_label.setText("Analyse en cours…")

        files: List[str] = []
        if self.use_scan_cache_checkbox.isChecked():
            files = self._list_packages_from_scan_cache(root) or []
        if not files:
            files = list(self._iter_packages(root, recursive=self.recursive_checkbox.isChecked()))

        self.logger.debug(
            "IDConflictViewer: starting scan root=%s files=%d recursive=%s cache=%s fast=%s",
            root,
            len(files),
            bool(self.recursive_checkbox.isChecked()),
            bool(self.use_scan_cache_checkbox.isChecked()),
            bool(self.fast_mode_checkbox.isChecked()),
        )

        self.progress.setMaximum(max(1, len(files)))
        cache = self._load_id_index_cache()
        new_cache_entries: List[Tuple[str, List[Tuple[int, int, int]]]] = []
        conflicts: Dict[Tuple[int, int, int], ConflictRecord] = {}
        processed = 0
        parsed_files = 0
        total_entries = 0
        cancelled = False
        started_at = datetime.now()

        def _parse_one(path: str) -> Dict[str, object]:
            result: Dict[str, object] = {
                "file": path,
                "tgis": [],
                "cache_used": False,
                "cache_key": path,
            }
            if self._cancel_event.is_set():
                return result
            try:
                stat_info = os.stat(path)
                key = f"{path}|{stat_info.st_size}|{int(stat_info.st_mtime)}"
            except Exception:
                key = path
            result["cache_key"] = key
            entry = cache.get(key) if isinstance(cache, dict) else None
            if entry and isinstance(entry, dict) and isinstance(entry.get("tgis"), list):
                result["tgis"] = [(int(t), int(g), int(i)) for t, g, i in entry["tgis"]]
                result["cache_used"] = True
                return result
            tgis = _read_tgi_entries_from_dbpf(
                path,
                logger=self.logger,
                allow_tail_fallback=not self.fast_mode_checkbox.isChecked(),
                cancel_event=self._cancel_event,
            )
            result["tgis"] = tgis or []
            return result
        if len(files) <= 4:
            for path in files:
                if self._cancel_event.is_set():
                    cancelled = True
                    break
                parsed = _parse_one(path)
                tgis = parsed.get("tgis") or []
                if not parsed.get("cache_used") and parsed.get("cache_key"):
                    new_cache_entries.append((str(parsed["cache_key"]), tgis))
                self._accumulate_conflicts(conflicts, path, tgis)
                if tgis:
                    parsed_files += 1
                    total_entries += len(tgis)
                processed += 1
                self.progress.setValue(processed)
                QtWidgets.QApplication.processEvents()
        else:
            max_workers = max(2, min(8, os.cpu_count() or 4))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_parse_one, path) for path in files]
                for future in as_completed(futures):
                    if self._cancel_event.is_set():
                        cancelled = True
                        for pending in futures:
                            pending.cancel()
                        break
                    parsed = future.result()
                    path = str(parsed.get("file") or "")
                    tgis = parsed.get("tgis") or []
                    if not parsed.get("cache_used") and parsed.get("cache_key"):
                        new_cache_entries.append((str(parsed["cache_key"]), tgis))
                    self._accumulate_conflicts(conflicts, path, tgis)
                    if tgis:
                        parsed_files += 1
                        total_entries += len(tgis)
                    processed += 1
                    if processed % 5 == 0 or processed == len(files):
                        self.progress.setValue(processed)
                        QtWidgets.QApplication.processEvents()

        if not cancelled:
            for key, tgis in new_cache_entries:
                cache[key] = {"tgis": [[t, g, i] for t, g, i in tgis]}
            self._save_id_index_cache(cache)

        elapsed = (datetime.now() - started_at).total_seconds()
        self._last_stats = {
            "total": len(files),
            "parsed_files": parsed_files,
            "total_entries": total_entries,
            "elapsed": elapsed,
            "cancelled": cancelled,
        }

        self._conflict_records = [
            record for record in conflicts.values() if len(record.files) >= 2
        ]
        for record in self._conflict_records:
            record.refresh_metadata()
        self._conflict_records.sort(key=lambda rec: rec.priority)
        self._apply_filters()

        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        if cancelled:
            self.status_label.setText("Analyse annulée")
        else:
            self.status_label.setText(
                f"{len(self._filtered_records)} ressources en conflit • {parsed_files}/{len(files)} fichiers analysés • {total_entries} entrées • {elapsed:.1f}s"
            )

    def _accumulate_conflicts(
        self,
        conflicts: Dict[Tuple[int, int, int], ConflictRecord],
        package_path: str,
        tgis: Sequence[Tuple[int, int, int]],
    ) -> None:
        if not tgis:
            return
        try:
            stats = os.stat(package_path)
        except OSError:
            return
        keywords = self._collect_keywords(package_path)
        has_script = self._folder_has_ts4script(package_path)
        meta = ConflictFile(
            path=package_path,
            modified=stats.st_mtime,
            size=stats.st_size,
            has_ts4script=has_script,
            keywords=keywords,
        )
        for type_id, group_id, instance_id in tgis:
            key = (int(type_id), int(group_id), int(instance_id))
            record = conflicts.get(key)
            if record is None:
                record = ConflictRecord(type_id=int(type_id), group_id=int(group_id), instance_id=int(instance_id))
                conflicts[key] = record
            record.files.append(meta)
    def _apply_filters(self) -> None:
        category = self.category_combo.currentText()
        severity = self.severity_combo.currentText()
        keyword_text = self.keyword_edit.text().strip().lower()
        script_only = self.script_only_checkbox.isChecked()

        date_from = None
        if self.date_from_edit.date() > SPECIAL_DATE:
            qd = self.date_from_edit.date()
            date_from = date(qd.year(), qd.month(), qd.day())
        date_to = None
        if self.date_to_edit.date() > SPECIAL_DATE:
            qd = self.date_to_edit.date()
            date_to = date(qd.year(), qd.month(), qd.day())

        keywords = [chunk.strip() for chunk in re.split(r"[,\s]+", keyword_text) if chunk.strip()]

        filtered: List[ConflictRecord] = []
        for record in self._conflict_records:
            if category != "Toutes" and record.category != category:
                continue
            if severity != "Toutes" and record.severity != severity:
                continue
            if script_only and not record.has_script:
                continue
            if keywords:
                haystacks = [
                    record.t_hex.lower(),
                    record.g_hex.lower(),
                    record.i_hex.lower(),
                    record.keyword_summary().lower(),
                    record.label.lower(),
                ]
                for item in record.files:
                    haystacks.append(item.path.lower())
                if not all(any(word in hay for hay in haystacks) for word in keywords):
                    continue
            if date_from or date_to:
                latest = record.latest_modified.date() if record.latest_modified else None
                if date_from and (latest is None or latest < date_from):
                    continue
                if date_to and (latest is None or latest > date_to):
                    continue
            filtered.append(record)

        filtered.sort(key=lambda rec: rec.priority)
        self._filtered_records = filtered
        self._render_filtered_records()

    def _render_filtered_records(self) -> None:
        self.tree.clear()
        self._record_map = {}
        if not self._filtered_records:
            return
        style = self.style()

        for record in self._filtered_records:
            top = QtWidgets.QTreeWidgetItem(self.tree)
            top.setText(0, record.severity)
            top.setText(1, f"{record.t_hex}:{record.g_hex}:{record.i_hex}")
            top.setText(2, f"{record.category} • {record.label}")
            top.setText(3, str(len(record.files)))
            top.setText(4, _format_datetime(record.latest_modified))
            top.setText(5, record.keyword_summary())
            top.setData(0, QtCore.Qt.UserRole, ("conflict", record.resource_key))

            style_info = SEVERITY_STYLE.get(record.severity, SEVERITY_STYLE["Faible"])
            icon = style.standardIcon(style_info["icon"])
            top.setIcon(0, icon)

            bg_brush = QtGui.QBrush(style_info["bg"])
            fg_brush = QtGui.QBrush(style_info["fg"])
            for column in range(6):
                top.setBackground(column, bg_brush)
                top.setForeground(column, fg_brush)

            for meta in record.files:
                child = QtWidgets.QTreeWidgetItem(top)
                child.setText(0, "")
                child.setIcon(0, style.standardIcon(QtWidgets.QStyle.SP_FileIcon))
                child.setText(1, os.path.basename(meta.path))
                child.setText(2, meta.folder)
                child.setText(3, "")
                child.setText(4, _format_datetime(meta.modified_dt))
                child.setText(5, ", ".join(sorted(meta.keywords)) if meta.keywords else "")
                child.setData(0, QtCore.Qt.UserRole, ("file", meta.path))
            top.setExpanded(True)
            self._record_map[record.resource_key] = record
    def _selected_records(self) -> List[ConflictRecord]:
        selected = self.tree.selectedItems()
        record_keys: Set[Tuple[int, int, int]] = set()
        files: Set[str] = set()
        for item in selected:
            role = item.data(0, QtCore.Qt.UserRole)
            if not role:
                continue
            kind, payload = role
            if kind == "conflict":
                record_keys.add(tuple(payload))
            elif kind == "file":
                files.add(str(payload))
        records: List[ConflictRecord] = []
        for key in record_keys:
            record = self._record_map.get(tuple(key))
            if record:
                records.append(record)
        if files:
            file_records = {meta.path: record for record in self._filtered_records for meta in record.files}
            for path in files:
                record = file_records.get(path)
                if record and record not in records:
                    records.append(record)
        if not records:
            return list(self._filtered_records)
        return records

    def _export_excel(self) -> None:
        if not self._filtered_records:
            QtWidgets.QMessageBox.information(self, "Export", "Aucun conflit à exporter.")
            return
        suggested = Path(self.mods_root) / "id_conflicts.xlsx"
        target, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Exporter vers Excel",
            str(suggested),
            "Fichiers Excel (*.xlsx)",
        )
        if not target:
            return
        rows: List[Dict[str, object]] = []
        for record in self._filtered_records:
            for meta in record.files:
                rows.append(
                    {
                        "severity": record.severity,
                        "resource": f"{record.t_hex}:{record.g_hex}:{record.i_hex}",
                        "category": record.category,
                        "label": record.label,
                        "file": os.path.basename(meta.path),
                        "path": meta.path,
                        "modified": _format_datetime(meta.modified_dt),
                        "has_script": "oui" if meta.has_ts4script else "non",
                        "keywords": ", ".join(sorted(meta.keywords)),
                    }
                )
        if not rows:
            QtWidgets.QMessageBox.information(self, "Export", "Aucun conflit à exporter.")
            return
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "ID Conflicts"
            headers = [
                "Sévérité",
                "Ressource",
                "Catégorie",
                "Libellé",
                "Fichier",
                "Chemin",
                "Modifié",
                "TS4Script",
                "Mots-clés",
            ]
            ws.append(headers)
            for row in rows:
                ws.append(
                    [
                        row["severity"],
                        row["resource"],
                        row["category"],
                        row["label"],
                        row["file"],
                        row["path"],
                        row["modified"],
                        row["has_script"],
                        row["keywords"],
                    ]
                )
            wb.save(target)
            self.logger.info("IDConflictViewer: exporté %s (%d lignes)", target, len(rows))
            QtWidgets.QMessageBox.information(self, "Export", f"Exporté: {target}")
        except Exception as exc:
            self.logger.error("IDConflictViewer: échec export Excel (%s)", exc)
            QtWidgets.QMessageBox.critical(self, "Erreur", f"Échec export Excel: {exc}")
    def _context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QtWidgets.QMenu(self)
        act_open = menu.addAction("Ouvrir le dossier")
        act_prefix = menu.addAction("Préfixer 'zzz_' le fichier")
        act_disable = menu.addAction("Désactiver ce mod")
        chosen = _qt_exec(menu, self.tree.viewport().mapToGlobal(pos))
        if chosen == act_open:
            role = item.data(0, QtCore.Qt.UserRole)
            path = None
            if role and role[0] == "file":
                path = os.path.dirname(role[1])
            elif role and role[0] == "conflict":
                record = self._record_map.get(tuple(role[1]))
                if record and record.files:
                    path = os.path.dirname(record.files[0].path)
            if path and os.path.isdir(path):
                self.logger.debug("IDConflictViewer: open folder %s", path)
                if hasattr(self.parent_app, "_open_in_file_manager"):
                    self.parent_app._open_in_file_manager(path)
                else:
                    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
        elif chosen == act_prefix:
            role = item.data(0, QtCore.Qt.UserRole)
            if not role or role[0] != "file":
                return
            file_path = str(role[1])
            if not os.path.isfile(file_path):
                return
            folder = os.path.dirname(file_path)
            filename = os.path.basename(file_path)
            if filename.lower().startswith("zzz_"):
                return
            target = os.path.join(folder, "zzz_" + filename)
            try:
                os.rename(file_path, target)
                self.logger.info("IDConflictViewer: renommé %s -> %s", file_path, target)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible de renommer: {exc}")
                return
            self._run_scan()
        elif chosen == act_disable:
            records = self._selected_records()
            self._disable_mod_folders(records)

    def _disable_conflicting_mods(self) -> None:
        records = self._selected_records()
        if not records:
            QtWidgets.QMessageBox.information(self, "Désactivation", "Aucun conflit sélectionné.")
            return
        self._disable_mod_folders(records)

    def _disable_mod_folders(self, records: Sequence[ConflictRecord]) -> None:
        parent_settings = getattr(self.parent_app, "settings", {})
        backups_dir = str(parent_settings.get("backups_directory") or "")
        if not backups_dir:
            QtWidgets.QMessageBox.warning(self, "Backups manquant", "Définis un dossier de backups dans la configuration.")
            return
        folders: Set[str] = set()
        for record in records:
            for meta in record.files:
                folders.add(os.path.dirname(meta.path))
        folders = {folder for folder in folders if os.path.isdir(folder)}
        if not folders:
            QtWidgets.QMessageBox.information(self, "Désactivation", "Aucun dossier valide à désactiver.")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Désactivation",
            f"Déplacer {len(folders)} dossier(s) de mod vers le dossier de backup ?",
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        disabled_root = os.path.join(backups_dir, "Disabled Mod")
        os.makedirs(disabled_root, exist_ok=True)
        failures = []
        for folder in sorted(folders):
            dest = os.path.join(disabled_root, os.path.basename(folder))
            final = dest
            suffix = 1
            while os.path.exists(final):
                final = f"{dest}_{suffix}"
                suffix += 1
            try:
                shutil.move(folder, final)
                self.logger.info("IDConflictViewer: désactivé %s -> %s", folder, final)
            except OSError as exc:
                failures.append(f"{folder}: {exc}")
        if failures:
            QtWidgets.QMessageBox.warning(
                self,
                "Désactivation partielle",
                "Certains dossiers n'ont pas pu être déplacés:\n" + "\n".join(failures),
            )
        self._run_scan()
    def _suggest_reorder(self) -> None:
        if not self._filtered_records:
            QtWidgets.QMessageBox.information(self, "Réagencement", "Aucun conflit à analyser.")
            return
        suggestions_path = Path(self.mods_root) / "load_order_suggestion.json"
        load_entries = []
        seen_folders: Set[str] = set()
        for record in self._filtered_records:
            for meta in record.files:
                folder = os.path.dirname(meta.path)
                if folder in seen_folders:
                    continue
                seen_folders.add(folder)
                load_entries.append(
                    {
                        "folder": folder,
                        "severity": record.severity,
                        "category": record.category,
                        "priority": record.priority,
                        "keywords": sorted(meta.keywords),
                    }
                )
        load_entries.sort(key=lambda item: item["priority"])
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "mods_root": self.mods_root,
            "entries": load_entries,
        }
        try:
            with open(suggestions_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            self.logger.info(
                "IDConflictViewer: load order suggestions saved to %s (%d entrées)",
                suggestions_path,
                len(load_entries),
            )
            QtWidgets.QMessageBox.information(
                self,
                "Réagencement",
                f"Suggestion d'ordre de chargement enregistrée dans:\n{suggestions_path}",
            )
        except Exception as exc:
            self.logger.error("IDConflictViewer: échec sauvegarde suggestions (%s)", exc)
            QtWidgets.QMessageBox.critical(self, "Erreur", f"Impossible d'écrire le fichier de suggestion: {exc}")

    def _check_mod_updates(self) -> None:
        if not self._filtered_records:
            QtWidgets.QMessageBox.information(self, "Compatibilité", "Aucun conflit à vérifier.")
            return
        installed = self._load_installed_mods()
        latest_patch_date = None
        if self.version_releases:
            latest_patch_date = max(self.version_releases.values())

        needs_attention: List[str] = []
        for record in self._filtered_records:
            for meta in record.files:
                folder = os.path.dirname(meta.path)
                info = installed.get(folder.lower())
                latest_mod_time = meta.modified_dt
                reason_parts = []
                if info:
                    mod_version = info.get("mod_version") or ""
                    installed_at = self._parse_iso_datetime(info.get("installed_at"))
                    if mod_version:
                        reason_parts.append(f"version installée: {mod_version}")
                    if installed_at:
                        reason_parts.append(f"installé le {installed_at.strftime('%d/%m/%Y')}")
                        if latest_patch_date and installed_at.date() < latest_patch_date.date():
                            reason_parts.append("plus ancien que le dernier patch Sims 4")
                    if info.get("url"):
                        reason_parts.append(f"url: {info['url']}")
                else:
                    reason_parts.append("mod non référencé dans installed_mods.json")
                if latest_patch_date and latest_mod_time and latest_mod_time.date() < latest_patch_date.date():
                    reason_parts.append("fichier plus ancien que le dernier patch connu")
                if reason_parts:
                    text = f"- {os.path.basename(folder)} ({'; '.join(reason_parts)})"
                    needs_attention.append(text)
        if not needs_attention:
            QtWidgets.QMessageBox.information(self, "Compatibilité", "Aucun conflit nécessitant une mise à jour détecté.")
            return
        QtWidgets.QMessageBox.information(
            self,
            "Compatibilité",
            "Vérifier les mises à jour pour:\n" + "\n".join(needs_attention),
        )

    def _load_installed_mods(self) -> Dict[str, Dict[str, object]]:
        try:
            with open(self.installed_mods_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            result: Dict[str, Dict[str, object]] = {}
            if isinstance(data, list):
                for entry in data:
                    path = str(entry.get("target_folder") or "")
                    if path:
                        result[path.lower()] = entry
            return result
        except Exception:
            return {}

    @staticmethod
    def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
