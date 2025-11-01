from __future__ import annotations

import os
import queue
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Set
import logging

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from watchdog.events import FileSystemEventHandler  # type: ignore
    from watchdog.observers import Observer  # type: ignore
except Exception:  # pragma: no cover - watchdog optional
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore

SUPPORTED_LOG_EXTENSIONS = {".log", ".txt", ".html", ".htm"}


@dataclass
class LogAnalyzerHooks:
    strip_html: Callable[[str], str]
    analyze_html: Callable[[str], Dict[str, object]]
    analyze_generic: Callable[[str], List[Dict[str, object]]]
    normalize_basename: Callable[[str], str]
    save_settings: Optional[Callable[[Dict[str, object]], None]] = None


@dataclass
class LogFileMeta:
    path: str
    modified: datetime
    size: int
    source: str


@dataclass
class LogAnalysisContext:
    meta: LogFileMeta
    text: str
    sims_version: str = ""
    summary: List[str] = field(default_factory=list)
    entries: List[Dict[str, object]] = field(default_factory=list)


class LogTroubleshooter:
    """Compute severity, hints, and aggregated summary for log entries."""

    _SEVERITY_RULES = [
        (re.compile(r"last ?exception", re.I), "Critique", "Derniere exception detectee."),
        (re.compile(r"script call failed", re.I), "Critique", "Script Call Failed emis par un mod."),
        (re.compile(r"(\bexception\b|\berror\b|stack trace)", re.I), "Erreur", "Exception detectee dans le log."),
        (re.compile(r"tuning (?:not|cannot) be found", re.I), "Erreur", "Ressource tuning introuvable."),
        (re.compile(r"(missing|introuvable|absent)", re.I), "Avertissement", "Ressource signalee comme manquante."),
        (re.compile(r"warning", re.I), "Avertissement", "Avertissement signale dans le log."),
    ]

    _SUGGESTION_RULES = [
        (re.compile(r"script call failed", re.I), "Mettre a jour ou retirer les mods de script recents."),
        (re.compile(r"last ?exception", re.I), "Consulter mc_lastexception.html pour obtenir le detail complet."),
        (re.compile(r"tuning (?:not|cannot) be found", re.I), "Verifier que les fichiers .package requis sont presents."),
        (re.compile(r"module '.*' has no attribute", re.I), "Un script .ts4script est obsolete; telecharger la derniere version."),
        (re.compile(r"resource\\.key", re.I), "Verifier que les ressources references sont chargees correctement."),
    ]

    @classmethod
    def classify_entry(cls, entry: Dict[str, object], hooks: LogAnalyzerHooks) -> Tuple[str, List[str], List[str]]:
        """Return severity, hints and affected mods for a parsed entry."""
        text = f"{entry.get('type', '')} {entry.get('message', '')}"
        lower_text = text.lower()
        severity = "Info"
        hints: List[str] = []

        for pattern, sev, tag_hint in cls._SEVERITY_RULES:
            if pattern.search(text):
                severity = sev
                if tag_hint:
                    hints.append(tag_hint)
                break

        for pattern, suggestion in cls._SUGGESTION_RULES:
            if pattern.search(text):
                hints.append(suggestion)

        if severity == "Info" and ("error" in lower_text or "exception" in lower_text):
            severity = "Erreur"

        affected: List[str] = []
        for raw_path in entry.get("paths") or []:
            base = os.path.basename(str(raw_path) or "")
            if not base:
                continue
            normalized = hooks.normalize_basename(os.path.splitext(base)[0])
            if normalized and normalized not in affected:
                affected.append(normalized)
        if affected:
            hints.append("Mods suspects: " + ", ".join(affected))
        return severity, hints, affected

    @classmethod
    def build_summary(cls, contexts: Sequence[LogAnalysisContext], entries: Sequence[Dict[str, object]]) -> List[str]:
        lines: List[str] = []
        if not entries:
            lines.append("Aucun evenement critique detecte dans la plage selectionnee.")
            return lines
        lines.append(f"Entrees analysees: {len(entries)}")
        by_severity: Dict[str, int] = {}
        by_mod: Dict[str, int] = {}
        for item in entries:
            sev = item.get("severity") or "Info"
            by_severity[sev] = by_severity.get(sev, 0) + 1
            for mod in item.get("affected_mods") or []:
                by_mod[mod] = by_mod.get(mod, 0) + 1
        if by_severity:
            lines.append("Repartition par gravite:")
            order = ("Critique", "Erreur", "Avertissement", "Info")
            for severity, count in sorted(by_severity.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99):
                lines.append(f"  - {severity}: {count}")
        if by_mod:
            lines.append("Mods suspects recurrents:")
            for mod, count in sorted(by_mod.items(), key=lambda kv: kv[1], reverse=True)[:5]:
                lines.append(f"  - {mod}: {count}")
        latest = max((ctx.meta.modified for ctx in contexts), default=None)
        if latest:
            lines.append("Derniere modification: " + latest.strftime("%Y-%m-%d %H:%M:%S"))
        actions: List[str] = []
        for item in entries:
            primary = item.get("primary_hint")
            if primary and primary not in actions and item.get("severity") in ("Critique", "Erreur"):
                actions.append(primary)
        if actions:
            lines.append("Actions suggerees:")
            for action in actions:
                lines.append(f"  - {action}")
        sources = {ctx.meta.source for ctx in contexts}
        if sources:
            lines.append("Repertoires analyses: " + ", ".join(sorted(sources)))
        return lines


class _LogEventHandler(FileSystemEventHandler):  # type: ignore
    def __init__(self, path_queue: "queue.Queue[str]"):
        super().__init__()
        self._queue = path_queue

    def on_created(self, event):  # pragma: no cover - triggered by watchdog
        self._handle_event(event)

    def on_modified(self, event):  # pragma: no cover - triggered by watchdog
        self._handle_event(event)

    def _handle_event(self, event):
        try:
            is_directory = bool(event.is_directory)
            path = str(event.src_path)
        except Exception:
            return
        if is_directory:
            return
        self._queue.put(path)


class LogWatcher(QtCore.QObject):
    """Convert watchdog events into Qt signals."""

    logDetected = QtCore.pyqtSignal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._observer: Optional[Observer] = None
        self._handler: Optional[_LogEventHandler] = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._process_queue)

    def start(self, directories: Sequence[str]) -> bool:
        if Observer is None:
            return False
        self.stop()
        valid_dirs = [d for d in directories if d and os.path.isdir(d)]
        if not valid_dirs:
            return False
        observer = Observer()
        handler = _LogEventHandler(self._queue)
        scheduled = False
        for path in valid_dirs:
            try:
                observer.schedule(handler, path, recursive=True)
                scheduled = True
            except Exception:
                continue
        if not scheduled:
            return False
        observer.start()
        self._observer = observer
        self._handler = handler
        self._timer.start()
        return True

    def stop(self):
        self._timer.stop()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
        self._observer = None
        self._handler = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break

    def _process_queue(self):
        while not self._queue.empty():
            try:
                path = self._queue.get_nowait()
            except Exception:
                break
            ext = os.path.splitext(path)[1].lower()
            if ext not in SUPPORTED_LOG_EXTENSIONS:
                continue
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                continue
            self.logDetected.emit(path, mtime)

    def __del__(self):  # pragma: no cover - defensive cleanup
        try:
            self.stop()
        except Exception:
            pass


class LogAnalyzer:
    """Scan and analyse Sims 4 logs across directories."""

    def __init__(
        self,
        hooks: LogAnalyzerHooks,
        script_directories: Optional[Sequence[str]] = None,
        ai_helper: Optional[Callable[[Sequence[str], str], Tuple[str, float]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.hooks = hooks
        self.logger = logger or logging.getLogger("Sims4ModTool.LogAnalyzer")
        self._ai_helper = ai_helper
        self._ts4script_index: Optional[Dict[str, List[str]]] = None
        self._script_directories = self._normalize_script_dirs(script_directories or [])

    def _normalize_script_dirs(self, directories: Sequence[str]) -> List[str]:
        normalized: List[str] = []
        seen: Set[str] = set()
        for path in directories:
            if not path:
                continue
            try:
                norm = os.path.abspath(os.path.expanduser(os.path.expandvars(path)))
            except Exception:
                norm = os.path.abspath(path)
            if os.path.isdir(norm) and norm not in seen:
                normalized.append(norm)
                seen.add(norm)
        if self.logger:
            self.logger.debug("Script directories normalized: %s", normalized)
        return normalized

    def set_script_directories(self, directories: Sequence[str]):
        self._script_directories = self._normalize_script_dirs(directories or [])
        self._ts4script_index = None
        if self.logger:
            self.logger.debug("Script directories updated; cache invalidated.")

    def _ensure_script_index(self) -> Dict[str, List[str]]:
        if self._ts4script_index is not None:
            return self._ts4script_index
        if not self._script_directories:
            self._ts4script_index = {}
            return self._ts4script_index
        index: Dict[str, List[str]] = {}
        for root_dir in self._script_directories:
            for root, _dirs, files in os.walk(root_dir):
                for name in files:
                    if not name.lower().endswith(".ts4script"):
                        continue
                    path = os.path.join(root, name)
                    base = os.path.splitext(name)[0]
                    keys = set()
                    if base:
                        keys.add(base.lower())
                    try:
                        norm = self.hooks.normalize_basename(base)
                        if norm:
                            keys.add(norm)
                    except Exception:
                        pass
                    for key in {k for k in keys if k}:
                        index.setdefault(key, []).append(path)
        self._ts4script_index = index
        if self.logger:
            self.logger.debug("Script index built with %d entries.", len(index))
        return self._ts4script_index

    def _augment_entry_with_scripts(self, entry: Dict[str, object]):
        mod_name = str(entry.get("mod") or "").strip()
        search_keys: Set[str] = set()
        if mod_name:
            mod_lower = mod_name.lower()
            if mod_lower:
                search_keys.add(mod_lower)
            try:
                normalized = self.hooks.normalize_basename(mod_name)
                if normalized:
                    search_keys.add(normalized)
            except Exception:
                pass
        existing_paths_raw = list(entry.get("paths") or [])
        if search_keys:
            for existing in existing_paths_raw:
                base_name = os.path.splitext(os.path.basename(str(existing) or ""))[0]
                if not base_name:
                    continue
                candidate_keys = {base_name.lower()}
                try:
                    candidate_norm = self.hooks.normalize_basename(base_name)
                    if candidate_norm:
                        candidate_keys.add(candidate_norm)
                except Exception:
                    pass
                if any(key and key in search_keys for key in candidate_keys):
                    return
        existing_paths = {
            os.path.abspath(str(p))
            for p in existing_paths_raw
            if isinstance(p, str) and p
        }
        ai_guess = ""
        ai_conf = 0.0
        if self._ai_helper:
            text = f"{entry.get('type') or ''} {entry.get('message') or ''}"
            try:
                ai_guess, ai_conf = self._ai_helper(existing_paths_raw, text)
            except Exception:
                ai_guess, ai_conf = "", 0.0
        if ai_guess and ai_conf >= 0.2:
            search_keys.add(ai_guess.lower())
            try:
                search_keys.add(self.hooks.normalize_basename(ai_guess))
            except Exception:
                pass
            if not mod_name:
                entry["mod"] = ai_guess
        if not search_keys:
            return
        index = self._ensure_script_index()
        matches: List[str] = []
        for key in search_keys:
            if not key:
                continue
            for path in index.get(key, []):
                abs_path = os.path.abspath(path)
                if abs_path not in existing_paths and path not in matches:
                    matches.append(path)
        if not matches:
            for key, paths in index.items():
                if any(k and k in key for k in search_keys if k):
                    for path in paths:
                        abs_path = os.path.abspath(path)
                        if abs_path not in existing_paths and path not in matches:
                            matches.append(path)
        if not matches:
            return
        entry.setdefault("paths", [])
        for path in matches:
            entry["paths"].append(path)
        if ai_guess and "ai_guess" not in entry:
            entry["ai_guess"] = ai_guess
            entry["ai_confidence"] = ai_conf
        if self.logger and matches:
            self.logger.debug(
                "Entry %s enriched with %d script paths (AI guess=%s, conf=%.2f)",
                entry.get("message", "")[:60],
                len(matches),
                ai_guess,
                ai_conf,
            )

    def scan_directories(self, directories: Sequence[str]) -> List[LogFileMeta]:
        if self.logger:
            self.logger.info("Scanning log directories: %s", directories)
        files: List[LogFileMeta] = []
        seen: Set[str] = set()
        for source_dir in directories:
            if not source_dir or not os.path.isdir(source_dir):
                continue
            for root, _dirs, filenames in os.walk(source_dir):
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext not in SUPPORTED_LOG_EXTENSIONS:
                        continue
                    path = os.path.join(root, filename)
                    if path in seen:
                        continue
                    seen.add(path)
                    try:
                        stat = os.stat(path)
                    except OSError:
                        continue
                    files.append(
                        LogFileMeta(
                            path=path,
                            modified=datetime.fromtimestamp(stat.st_mtime),
                            size=stat.st_size,
                            source=source_dir,
                        )
                    )
        if self.logger:
            self.logger.debug("Scan completed. Found %d log files.", len(files))
        files.sort(key=lambda meta: meta.modified, reverse=True)
        return files

    def read_log_text(self, path: str) -> Tuple[str, str]:
        try:
            raw = open(path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            raw = ""
        plain = raw
        if path.lower().endswith((".html", ".htm")):
            plain = self.hooks.strip_html(raw)
        return raw, plain

    def analyse_log(self, meta: LogFileMeta) -> LogAnalysisContext:
        if self.logger:
            self.logger.info("Analysing log file: %s", meta.path)
        raw, text = self.read_log_text(meta.path)
        sims_version = ""
        entries: List[Dict[str, object]] = []
        if meta.path.lower().endswith((".html", ".htm")):
            try:
                parsed_html = self.hooks.analyze_html(raw)
            except Exception:
                parsed_html = {}
            sims_version = str(parsed_html.get("sims_version") or "")
            entries.extend(parsed_html.get("results") or [])
        if self.logger:
            self.logger.debug("HTML entries parsed: %d", len(entries))
        try:
            entries.extend(self.hooks.analyze_generic(text))
        except Exception:
            pass
        enriched: List[Dict[str, object]] = []
        for entry in entries:
            self._augment_entry_with_scripts(entry)
            severity, hints, affected = LogTroubleshooter.classify_entry(entry, self.hooks)
            enriched_entry = dict(entry)
            enriched_entry["severity"] = severity
            enriched_entry["hints"] = hints
            enriched_entry["primary_hint"] = hints[0] if hints else ""
            enriched_entry["affected_mods"] = affected
            enriched_entry["source_log"] = meta.path
            enriched_entry["timestamp"] = meta.modified
            enriched.append(enriched_entry)
        if self.logger:
            self.logger.debug("Log analysis produced %d entries.", len(enriched))
        context = LogAnalysisContext(meta=meta, text=text, sims_version=sims_version, summary=[], entries=enriched)
        context.summary = self._build_log_summary(meta, enriched)
        return context

    def _build_log_summary(self, meta: LogFileMeta, entries: Sequence[Dict[str, object]]) -> List[str]:
        lines = [
            f"Log: {os.path.basename(meta.path)}",
            f"Derniere modification: {meta.modified.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Taille: {meta.size} octets",
        ]
        if not entries:
            lines.append("Aucun evenement notable dans ce log.")
            return lines
        counts: Dict[str, int] = {}
        for entry in entries:
            kind = str(entry.get("type") or "").strip() or "(inconnu)"
            counts[kind] = counts.get(kind, 0) + 1
        lines.append("Types rencontrees:")
        for kind, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]:
            lines.append(f"  - {kind}: {count}")
        return lines


class LogManagerDialog(QtWidgets.QDialog):
    """Dialog that provides log exploration, analytics, and real-time monitoring."""

    def __init__(
        self,
        parent=None,
        initial_path: str = "",
        hooks: Optional[LogAnalyzerHooks] = None,
    ):
        super().__init__(parent)
        if hooks is None:
            raise ValueError("LogManagerDialog requires LogAnalyzerHooks.")
        self.hooks = hooks
        self.parent_app = parent
        self.logger = getattr(self.parent_app, "logger", None)
        if self.logger is None:
            self.logger = logging.getLogger("Sims4ModTool.LogManager")
        self.setWindowTitle("Log Manager")
        self.setModal(True)
        try:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
            self.setSizeGripEnabled(True)
            self.setWindowFlag(QtCore.Qt.WindowMinimizeButtonHint, True)
            self.setWindowFlag(QtCore.Qt.WindowMaximizeButtonHint, True)
            self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, True)
        except Exception:
            pass
        self.resize(1280, 820)

        settings_snapshot = getattr(self.parent_app, "settings", {}) or {}
        initial_script_dirs: List[str] = []
        mod_dir_hint = settings_snapshot.get("mod_directory", "") if isinstance(settings_snapshot, dict) else ""
        if mod_dir_hint and os.path.isdir(mod_dir_hint):
            initial_script_dirs.append(mod_dir_hint)

        self.analyzer = LogAnalyzer(
            self.hooks,
            script_directories=initial_script_dirs,
            ai_helper=self._ai_guess,
            logger=self.logger,
        )
        self._watcher = LogWatcher(self)
        self._watcher.logDetected.connect(self._handle_new_log)
        self._current_logs: List[LogFileMeta] = []
        self._log_text_cache: Dict[str, str] = {}
        self._last_results: List[Dict[str, object]] = []
        self._last_contexts: List[LogAnalysisContext] = []
        self._summary_lines: List[str] = []
        self._original_text = ""
        self._filtered_text = ""
        self._initial_path = initial_path

        self._build_ui()

        if initial_path:
            QtCore.QTimer.singleShot(0, lambda: self._add_manual_file(initial_path))

    # ------------------------------------------------------------------ UI building

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        splitter = QtWidgets.QSplitter(self)
        splitter.setOrientation(QtCore.Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        splitter.addWidget(left)

        sources_group = QtWidgets.QGroupBox("Sources", left)
        sources_layout = QtWidgets.QVBoxLayout(sources_group)
        left_layout.addWidget(sources_group)

        settings = getattr(self.parent_app, "settings", {}) or {}
        mod_dir = settings.get("mod_directory", "")
        cache_dir = settings.get("sims_cache_directory", "")

        mod_row = QtWidgets.QHBoxLayout()
        self.mods_cb = QtWidgets.QCheckBox("Inclure dossier des mods", sources_group)
        self.mods_cb.setChecked(bool(mod_dir))
        self.mods_path_label = QtWidgets.QLabel(mod_dir or "(non defini)", sources_group)
        self.mods_path_label.setWordWrap(True)
        mod_row.addWidget(self.mods_cb)
        mod_row.addWidget(self.mods_path_label, 1)
        sources_layout.addLayout(mod_row)

        cache_row = QtWidgets.QHBoxLayout()
        self.cache_cb = QtWidgets.QCheckBox("Inclure dossier cache", sources_group)
        self.cache_cb.setChecked(bool(cache_dir))
        self.cache_path_label = QtWidgets.QLabel(cache_dir or "(non defini)", sources_group)
        self.cache_path_label.setWordWrap(True)
        cache_row.addWidget(self.cache_cb)
        cache_row.addWidget(self.cache_path_label, 1)
        sources_layout.addLayout(cache_row)

        extra_row = QtWidgets.QHBoxLayout()
        self.extra_dir_edit = QtWidgets.QLineEdit(sources_group)
        self.extra_dir_edit.setPlaceholderText("Ajouter un dossier supplementaire...")
        btn_add_dir = QtWidgets.QPushButton("Ajouter", sources_group)
        btn_add_dir.clicked.connect(self._browse_extra_directory)
        extra_row.addWidget(self.extra_dir_edit, 1)
        extra_row.addWidget(btn_add_dir)
        sources_layout.addLayout(extra_row)

        self.extra_dirs_list = QtWidgets.QListWidget(sources_group)
        self.extra_dirs_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        sources_layout.addWidget(self.extra_dirs_list, 1)

        btn_remove_dir = QtWidgets.QPushButton("Retirer le dossier selectionne", sources_group)
        btn_remove_dir.clicked.connect(self._remove_selected_extra_directory)
        sources_layout.addWidget(btn_remove_dir)

        files_group = QtWidgets.QGroupBox("Fichiers detectes", left)
        files_layout = QtWidgets.QVBoxLayout(files_group)
        left_layout.addWidget(files_group, 1)

        period_row = QtWidgets.QHBoxLayout()
        self.start_dt = QtWidgets.QDateTimeEdit(files_group)
        self.start_dt.setCalendarPopup(True)
        now = QtCore.QDateTime.currentDateTime()
        self.start_dt.setDateTime(now.addSecs(-6 * 3600))
        self.end_dt_cb = QtWidgets.QCheckBox("Utiliser borne haute", files_group)
        self.end_dt_cb.setChecked(True)
        self.end_dt = QtWidgets.QDateTimeEdit(files_group)
        self.end_dt.setCalendarPopup(True)
        self.end_dt.setDateTime(now)
        period_row.addWidget(QtWidgets.QLabel("Depuis:", files_group))
        period_row.addWidget(self.start_dt)
        period_row.addWidget(self.end_dt_cb)
        period_row.addWidget(self.end_dt)
        files_layout.addLayout(period_row)

        actions_row = QtWidgets.QHBoxLayout()
        self.scan_btn = QtWidgets.QPushButton("Scanner les logs", files_group)
        self.scan_btn.clicked.connect(self._scan_logs)
        self.analyze_selected_btn = QtWidgets.QPushButton("Analyser la selection", files_group)
        self.analyze_selected_btn.clicked.connect(self._analyze_selected)
        self.analyze_all_btn = QtWidgets.QPushButton("Analyser tous les logs filtres", files_group)
        self.analyze_all_btn.clicked.connect(self._analyze_all_visible)
        actions_row.addWidget(self.scan_btn)
        actions_row.addWidget(self.analyze_selected_btn)
        actions_row.addWidget(self.analyze_all_btn)
        files_layout.addLayout(actions_row)

        self.log_list = QtWidgets.QListWidget(files_group)
        self.log_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.log_list.itemSelectionChanged.connect(self._preview_selection)
        self.log_list.itemDoubleClicked.connect(lambda _: self._analyze_selected())
        files_layout.addWidget(self.log_list, 1)

        realtime_row = QtWidgets.QHBoxLayout()
        self.realtime_cb = QtWidgets.QCheckBox("Surveiller en temps reel", files_group)
        self.realtime_cb.toggled.connect(self._toggle_realtime)
        self.realtime_status = QtWidgets.QLabel("Inactif", files_group)
        realtime_row.addWidget(self.realtime_cb)
        realtime_row.addWidget(self.realtime_status, 1)
        files_layout.addLayout(realtime_row)

        manual_row = QtWidgets.QHBoxLayout()
        manual_btn = QtWidgets.QPushButton("Ajouter un fichier...", files_group)
        manual_btn.clicked.connect(self._browse_file)
        manual_row.addWidget(manual_btn)
        files_layout.addLayout(manual_row)

        splitter.addWidget(left)

        right = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QLabel("Filtre texte:", right))
        self.filter_edit = QtWidgets.QLineEdit(right)
        self.filter_edit.setPlaceholderText("Mot-cle ou regex...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.regex_cb = QtWidgets.QCheckBox("Regex", right)
        self.regex_cb.toggled.connect(self._apply_filter)
        self.case_cb = QtWidgets.QCheckBox("Casse", right)
        self.case_cb.toggled.connect(self._apply_filter)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.regex_cb)
        filter_row.addWidget(self.case_cb)
        right_layout.addLayout(filter_row)

        self.viewer = QtWidgets.QPlainTextEdit(right)
        self.viewer.setReadOnly(True)
        right_layout.addWidget(self.viewer, 2)

        ai_enabled = bool(getattr(self.parent_app, "settings", {}).get("ai_enabled", False)) if self.parent_app else False
        headers = ["#", "Type", "Message", "Mod", "Fichiers", "Gravite", "Suggestion"]
        if ai_enabled:
            headers.append("IA Mod (conf.)")
        self.table = QtWidgets.QTableWidget(0, len(headers), right)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self.table, 1)

        buttons_row = QtWidgets.QHBoxLayout()
        self.export_btn = QtWidgets.QPushButton("Exporter le rapport (.xlsx)", right)
        self.export_btn.clicked.connect(self._export_to_excel)
        buttons_row.addWidget(self.export_btn)
        buttons_row.addStretch(1)
        right_layout.addLayout(buttons_row)

        right_layout.addWidget(QtWidgets.QLabel("Resume", right))
        self.summary = QtWidgets.QPlainTextEdit(right)
        self.summary.setReadOnly(True)
        right_layout.addWidget(self.summary, 1)

    # ---------------------------------------------------------------- source utils

    def _collect_directories(self) -> List[str]:
        directories: List[str] = []
        settings = getattr(self.parent_app, "settings", {}) or {}
        mod_dir = settings.get("mod_directory", "")
        cache_dir = settings.get("sims_cache_directory", "")
        if self.mods_cb.isChecked() and mod_dir and os.path.isdir(mod_dir):
            directories.append(mod_dir)
        if self.cache_cb.isChecked() and cache_dir and os.path.isdir(cache_dir):
            directories.append(cache_dir)
        for index in range(self.extra_dirs_list.count()):
            item = self.extra_dirs_list.item(index)
            path = item.data(QtCore.Qt.UserRole) or item.text()
            if path and os.path.isdir(path):
                directories.append(path)
        if self.logger:
            self.logger.debug("Directories selected for scanning: %s", directories)
        return directories

    def _script_search_directories(self) -> List[str]:
        directories: List[str] = []
        seen: Set[str] = set()
        settings = getattr(self.parent_app, "settings", {}) or {}
        mod_dir = settings.get("mod_directory", "")
        if mod_dir:
            try:
                norm = os.path.abspath(mod_dir)
            except Exception:
                norm = mod_dir
            if os.path.isdir(norm):
                directories.append(norm)
                seen.add(norm)
        for index in range(self.extra_dirs_list.count()):
            item = self.extra_dirs_list.item(index)
            path = item.data(QtCore.Qt.UserRole) or item.text()
            if not path:
                continue
            try:
                norm = os.path.abspath(path)
            except Exception:
                norm = path
            if os.path.isdir(norm) and norm not in seen:
                directories.append(norm)
                seen.add(norm)
        if self.logger:
            self.logger.debug("Directories selected for script lookup: %s", directories)
        return directories

    def _browse_extra_directory(self):
        current = self.extra_dir_edit.text().strip()
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Selectionner un dossier de logs", current or os.getcwd())
        if not folder:
            return
        self.extra_dir_edit.setText(folder)
        self._append_extra_directory(folder)

    def _append_extra_directory(self, folder: str):
        folder = os.path.normpath(folder)
        for index in range(self.extra_dirs_list.count()):
            if self.extra_dirs_list.item(index).data(QtCore.Qt.UserRole) == folder:
                return
        item = QtWidgets.QListWidgetItem(folder)
        item.setData(QtCore.Qt.UserRole, folder)
        item.setToolTip(folder)
        self.extra_dirs_list.addItem(item)

    def _remove_selected_extra_directory(self):
        row = self.extra_dirs_list.currentRow()
        if row >= 0:
            self.extra_dirs_list.takeItem(row)

    def _browse_file(self):
        settings = getattr(self.parent_app, "settings", {}) or {}
        start_dir = settings.get("last_log_path") or settings.get("mod_directory") or settings.get("sims_cache_directory") or os.getcwd()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choisir un fichier log",
            start_dir,
            "Logs (*.log *.txt *.html *.htm);;Tous les fichiers (*.*)",
        )
        if not file_path:
            return
        self._add_manual_file(file_path)

    def _add_manual_file(self, path: str):
        path = os.path.normpath(path)
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "Fichier introuvable", f"Impossible de trouver {path}")
            return
        meta = LogFileMeta(
            path=path,
            modified=datetime.fromtimestamp(os.path.getmtime(path)),
            size=os.path.getsize(path),
            source=os.path.dirname(path),
        )
        self._current_logs = [meta] + [m for m in self._current_logs if m.path != meta.path]
        self._populate_log_list()
        self._select_log(meta.path)
        self._load_preview(meta)

    def _select_log(self, path: str):
        for index in range(self.log_list.count()):
            item = self.log_list.item(index)
            meta = item.data(QtCore.Qt.UserRole)
            if meta and meta.path == path:
                item.setSelected(True)
                self.log_list.scrollToItem(item)
                break

    # ------------------------------------------------------------------- scanning

    def _scan_logs(self):
        directories = self._collect_directories()
        if not directories:
            QtWidgets.QMessageBox.information(self, "Aucun dossier", "Selectionnez au moins un dossier valide.")
            return
        if self.logger:
            self.logger.info("Scanning logs in %d directories.", len(directories))
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            all_logs = self.analyzer.scan_directories(directories)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        since = self.start_dt.dateTime().toPyDateTime()
        until = self.end_dt.dateTime().toPyDateTime() if self.end_dt_cb.isChecked() else since + timedelta(days=1)
        filtered = [meta for meta in all_logs if since <= meta.modified <= until]
        if not filtered:
            QtWidgets.QMessageBox.information(self, "Aucun log", "Aucun log trouve pour la plage choisie.")
            if self.logger:
                self.logger.info("No logs found in window %s - %s.", since, until)
        self._current_logs = filtered
        self._populate_log_list()
        if self.logger:
            self.logger.info("Scan complete; %d logs available after filtering.", len(filtered))

    def _populate_log_list(self):
        self.log_list.clear()
        for meta in self._current_logs:
            label = f"{meta.modified.strftime('%Y-%m-%d %H:%M:%S')} - {os.path.basename(meta.path)}"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, meta)
            item.setToolTip(f"{meta.path}\n{meta.size} octets")
            self.log_list.addItem(item)
        if self.logger:
            self.logger.debug("Log list populated with %d items.", len(self._current_logs))

    def _preview_selection(self):
        items = self.log_list.selectedItems()
        if not items:
            return
        meta = items[-1].data(QtCore.Qt.UserRole)
        if meta:
            self._load_preview(meta)

    def _load_preview(self, meta: LogFileMeta):
        if meta.path in self._log_text_cache:
            text = self._log_text_cache[meta.path]
        else:
            _, text = self.analyzer.read_log_text(meta.path)
            self._log_text_cache[meta.path] = text
        self.viewer.setPlainText(text)
        self._original_text = text
        self._filtered_text = text
        if self.parent_app and hasattr(self.parent_app, "settings"):
            self.parent_app.settings["last_log_path"] = meta.path
            if self.hooks.save_settings:
                try:
                    self.hooks.save_settings(self.parent_app.settings)
                except Exception:
                    pass

    # -------------------------------------------------------------------- analysis

    def _selected_metas(self) -> List[LogFileMeta]:
        metas: List[LogFileMeta] = []
        items = self.log_list.selectedItems()
        for item in items:
            meta = item.data(QtCore.Qt.UserRole)
            if meta:
                metas.append(meta)
        return metas

    def _analyze_selected(self):
        metas = self._selected_metas()
        if not metas and self._current_logs:
            metas = [self._current_logs[0]]
        if not metas:
            QtWidgets.QMessageBox.information(self, "Aucun fichier", "Selectionnez au moins un log a analyser.")
            return
        self._run_analysis(metas)

    def _analyze_all_visible(self):
        if not self._current_logs:
            QtWidgets.QMessageBox.information(self, "Aucun log", "Aucun log n'est disponible.")
            return
        self._run_analysis(self._current_logs)

    def _run_analysis(self, metas: Sequence[LogFileMeta]):
        try:
            self.analyzer.set_script_directories(self._script_search_directories())
        except Exception:
            pass
        if self.logger:
            self.logger.info("Running analysis for %d log files.", len(metas))
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        contexts: List[LogAnalysisContext] = []
        entries: List[Dict[str, object]] = []
        try:
            for meta in metas:
                ctx = self.analyzer.analyse_log(meta)
                contexts.append(ctx)
                entries.extend(ctx.entries)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if self.logger:
            self.logger.info("Analysis complete: %d entries extracted from %d logs.", len(entries), len(contexts))
        self._last_contexts = contexts
        self._last_results = entries
        self._summary_lines = LogTroubleshooter.build_summary(contexts, entries)
        combined_text = "\n\n".join(ctx.text for ctx in contexts if ctx.text)
        if combined_text:
            self._original_text = combined_text
            self._filtered_text = combined_text
            self.viewer.setPlainText(combined_text)
        self.summary.setPlainText("\n".join(self._summary_lines))
        self._render(entries)
        sims_versions = [ctx.sims_version for ctx in contexts if ctx.sims_version]
        if sims_versions:
            try:
                title = "Log Manager - Sims " + ", ".join(sorted(set(sims_versions)))
                self.setWindowTitle(title)
            except Exception:
                pass
        self._auto_train_ai(entries)

    def _ensure_ai(self, load_if_missing: bool = False):
        if not self.parent_app:
            return None
        ai = getattr(self.parent_app, "mod_ai", None)
        if ai is None and load_if_missing:
            loader = getattr(self.parent_app, "load_or_create_ai", None)
            if callable(loader):
                try:
                    ai = loader()
                    try:
                        self.parent_app.mod_ai = ai
                    except Exception:
                        pass
                except Exception as exc:
                    ai = None
                    if self.logger:
                        self.logger.debug("AI loading failed: %s", exc)
        return ai

    def _ai_guess(self, paths: Sequence[str], text: str) -> Tuple[str, float]:
        settings = getattr(self.parent_app, "settings", {}) or {}
        if not settings.get("ai_enabled"):
            return "", 0.0
        ai = self._ensure_ai(load_if_missing=True)
        if ai is None:
            return "", 0.0
        try:
            guess, conf = ai.guess_from_paths_and_text(paths or [], text)
            if self.logger:
                self.logger.debug("AI guess: %s (%.2f)", guess, conf or 0.0)
            return (guess or "").strip(), float(conf or 0.0)
        except Exception as exc:
            if self.logger:
                self.logger.debug("AI guess failed: %s", exc)
            return "", 0.0

    def _render(self, results: List[Dict[str, object]]):
        ai_enabled = bool(getattr(self.parent_app, "settings", {}).get("ai_enabled", False)) if self.parent_app else False
        ai = self._ensure_ai(load_if_missing=ai_enabled) if ai_enabled else None
        self.table.setRowCount(0)
        for index, item in enumerate(results, start=1):
            self.table.insertRow(self.table.rowCount())
            message = str(item.get("message") or "")
            message_short = message[:160] + ("..." if len(message) > 160 else "")
            mod_label = ", ".join(item.get("affected_mods") or []) or str(item.get("mod") or "")
            file_label = ", ".join(os.path.basename(str(p) or "") for p in item.get("paths") or [])
            suggestion = item.get("primary_hint") or ", ".join(item.get("hints") or [])
            row = [
                str(index),
                str(item.get("type") or ""),
                message_short,
                mod_label,
                file_label,
                str(item.get("severity") or ""),
                suggestion,
            ]
            if ai_enabled and ai is not None:
                guess, conf = "", 0.0
                try:
                    guess, conf = ai.guess_from_paths_and_text(item.get("paths") or [], f"{item.get('type') or ''} {message}")
                except Exception:
                    guess, conf = "", 0.0
                row.append(f"{guess} ({int(conf * 100)}%)" if guess else "")
                item["ai_guess"] = guess
                item["ai_confidence"] = conf
            for col, value in enumerate(row):
                self.table.setItem(self.table.rowCount() - 1, col, QtWidgets.QTableWidgetItem(value))

    def _auto_train_ai(self, results: Sequence[Dict[str, object]]):
        if not self.parent_app:
            return
        settings = getattr(self.parent_app, "settings", {}) or {}
        if not settings.get("ai_enabled") or not settings.get("ai_auto_train", True):
            return
        ai = self._ensure_ai(load_if_missing=True)
        if ai is None:
            return
        try:
            ai.update_from_log_results(list(results))
            ai.save(str(settings.get("ai_model_path", "mod_ai.json")))
            if self.logger:
                self.logger.debug("AI auto-trained with %d log entries.", len(results))
        except Exception:
            pass

    # ---------------------------------------------------------------------- export

    def _export_to_excel(self):
        if not self._last_results:
            QtWidgets.QMessageBox.information(self, "Aucune donnee", "Analysez des logs avant d'exporter.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Enregistrer l'analyse",
            "log_analysis.xlsx",
            "Fichier Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            from openpyxl import Workbook  # type: ignore
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export impossible", f"openpyxl est requis: {exc}")
            return
        wb = Workbook()
        ws = wb.active
        ws.title = "Logs analyses"
        headers = ["#", "Type", "Message", "Mod", "Fichiers", "Gravite", "Suggestion", "Log", "Horodatage"]
        ws.append(headers)
        for index, item in enumerate(self._last_results, start=1):
            ws.append(
                [
                    index,
                    item.get("type") or "",
                    item.get("message") or "",
                    ", ".join(item.get("affected_mods") or []) or item.get("mod") or "",
                    ", ".join(item.get("paths") or []),
                    item.get("severity") or "",
                    item.get("primary_hint") or ", ".join(item.get("hints") or []),
                    item.get("source_log") or "",
                    item.get("timestamp") or "",
                ]
            )
        try:
            wb.save(path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export impossible", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Export reussi", f"Analyse sauvegardee dans {path}")

    # --------------------------------------------------------------------- filtering

    def _apply_filter(self):
        text = self._original_text or ""
        term = self.filter_edit.text().strip()
        if not term:
            self._filtered_text = text
            self.viewer.setPlainText(text)
            return
        flags = 0 if self.case_cb.isChecked() else re.IGNORECASE
        lines: List[str] = []
        try:
            if self.regex_cb.isChecked():
                pattern = re.compile(term, flags)
                lines = [line for line in text.splitlines() if pattern.search(line)]
            else:
                needle = term if self.case_cb.isChecked() else term.lower()
                for line in text.splitlines():
                    hay = line if self.case_cb.isChecked() else line.lower()
                    if needle in hay:
                        lines.append(line)
        except re.error:
            lines = [text]
        filtered = "\n".join(lines)
        self._filtered_text = filtered
        self.viewer.setPlainText(filtered)

    # ------------------------------------------------------------------ real-time

    def _toggle_realtime(self, enabled: bool):
        if enabled:
            directories = self._collect_directories()
            if not directories:
                QtWidgets.QMessageBox.information(self, "Aucun dossier", "Selectionnez au moins un dossier avant d'activer la surveillance.")
                self.realtime_cb.setChecked(False)
                return
            started = self._watcher.start(directories)
            if not started:
                QtWidgets.QMessageBox.warning(self, "Surveillance indisponible", "watchdog n'est pas disponible ou aucun dossier valide n'a ete trouve.")
                self.realtime_cb.setChecked(False)
                return
            self.realtime_status.setText("Surveillance active...")
        else:
            self._watcher.stop()
            self.realtime_status.setText("Inactif")

    def _handle_new_log(self, path: str, mtime: float):
        meta = LogFileMeta(
            path=os.path.normpath(path),
            modified=datetime.fromtimestamp(mtime),
            size=os.path.getsize(path) if os.path.exists(path) else 0,
            source=os.path.dirname(path),
        )
        self._current_logs = [meta] + [m for m in self._current_logs if m.path != meta.path]
        self._populate_log_list()
        if self.logger:
            self.logger.info("New log detected: %s", path)
        if self.realtime_cb.isChecked():
            self.realtime_status.setText(f"Nouveau log: {os.path.basename(path)}")
            QtWidgets.QMessageBox.information(self, "Nouveau log detecte", f"Nouveau log detecte: {path}")

    # ------------------------------------------------------------------- lifecycle

    def closeEvent(self, event: QtGui.QCloseEvent):
        try:
            self._watcher.stop()
        except Exception:
            pass
        super().closeEvent(event)
