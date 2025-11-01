"""
TS4Script search dialog.

Provides an enhanced interface to locate resources inside Sims 4 .ts4script
archives while honouring the application's logging configuration.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import zipfile
from datetime import datetime
from typing import Callable, Iterable, List, Optional, Sequence
from urllib.parse import quote_plus

from PyQt5 import QtCore, QtGui, QtWidgets

LOGGER = logging.getLogger("Sims4ModTool.Ts4ScriptSearch")


def _default_datetime_formatter(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y %H:%M")


def _resolve_flag(name: str):
    """Resolve a Qt window flag across PyQt5/PyQt6/PySide variants."""
    qt = QtCore.Qt
    if hasattr(qt, name):
        return getattr(qt, name)
    if hasattr(qt, "WindowType") and hasattr(qt.WindowType, name):
        return getattr(qt.WindowType, name)
    if hasattr(qt, "WindowFlags") and hasattr(qt.WindowFlags, name):
        return getattr(qt.WindowFlags, name)
    return None


class Ts4ScriptSearchDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget],
        start_directory: str,
        datetime_formatter: Optional[Callable[[Optional[datetime]], str]] = None,
    ) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.scan_directory = os.path.abspath(start_directory) if start_directory else ""
        self._format_datetime = datetime_formatter or _default_datetime_formatter
        self.logger = LOGGER
        self.logger.debug("Initializing Ts4ScriptSearchDialog (start_dir=%s)", self.scan_directory)

        self.setWindowTitle("Find in ts4script")
        self.setModal(True)
        self._apply_window_buttons()
        self.resize(960, 600)

        self._build_ui()

        # Auto-run if path present
        if self.scan_directory and os.path.isdir(self.scan_directory):
            QtCore.QTimer.singleShot(0, self._run_search)

    # ------------------------------------------------------------------ UI ---
    def _apply_window_buttons(self) -> None:
        try:
            flags = self.windowFlags()
            for flag_name in (
                "Window",
                "WindowSystemMenuHint",
                "WindowMinimizeButtonHint",
                "WindowMaximizeButtonHint",
                "WindowCloseButtonHint",
            ):
                flag = _resolve_flag(flag_name)
                if flag is not None:
                    flags |= flag
            self.setWindowFlags(flags)
            self.setSizeGripEnabled(True)
        except Exception:
            self.logger.debug("Unable to apply window button hints", exc_info=True)

    def _build_ui(self) -> None:
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Analyse des fichiers .ts4script pour retrouver rapidement des ressources."
            " Utilise des motifs génériques (wildcards).",
            self,
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #d4d4d4; font-weight: 500;")
        main_layout.addWidget(intro)

        controls_group = QtWidgets.QGroupBox("Paramètres de recherche", self)
        controls_layout = QtWidgets.QGridLayout(controls_group)
        controls_layout.setColumnStretch(1, 1)

        self.path_edit = QtWidgets.QLineEdit(self)
        self.path_edit.setText(self.scan_directory)
        self.path_edit.setPlaceholderText("Sélectionne un dossier de mods…")
        browse_btn = QtWidgets.QToolButton(self)
        browse_btn.setText("…")
        browse_btn.setToolTip("Choisir un dossier à analyser")
        browse_btn.clicked.connect(self._browse)

        use_mods_btn = QtWidgets.QToolButton(self)
        use_mods_btn.setText("Mods")
        use_mods_btn.setToolTip("Utiliser le dossier des mods configuré")
        use_mods_btn.clicked.connect(self._apply_parent_mod_directory)

        controls_layout.addWidget(QtWidgets.QLabel("Dossier source :", self), 0, 0)
        controls_layout.addWidget(self.path_edit, 0, 1)
        helper_layout = QtWidgets.QHBoxLayout()
        helper_layout.setContentsMargins(0, 0, 0, 0)
        helper_layout.addWidget(browse_btn)
        helper_layout.addWidget(use_mods_btn)
        helper_layout.addStretch(1)
        controls_layout.addLayout(helper_layout, 0, 2)

        self.patterns_edit = QtWidgets.QLineEdit(self)
        self.patterns_edit.setPlaceholderText("ex: *_Tuning.xml, *Interactions*.py; tuning_*.xml")
        self.patterns_edit.returnPressed.connect(self._run_search)
        clear_btn = QtWidgets.QToolButton(self)
        clear_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogResetButton))
        clear_btn.setToolTip("Effacer les résultats")
        clear_btn.clicked.connect(self._clear_results)

        controls_layout.addWidget(QtWidgets.QLabel("Motifs à rechercher :", self), 1, 0)
        controls_layout.addWidget(self.patterns_edit, 1, 1)
        controls_layout.addWidget(clear_btn, 1, 2)

        options_layout = QtWidgets.QHBoxLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        self.recursive_checkbox = QtWidgets.QCheckBox("Inclure les sous-dossiers", self)
        self.recursive_checkbox.setChecked(True)
        self.case_insensitive_label = QtWidgets.QLabel("Comparaison insensible à la casse", self)
        self.case_insensitive_label.setStyleSheet("color: #9e9e9e; font-style: italic;")
        options_layout.addWidget(self.recursive_checkbox)
        options_layout.addStretch(1)
        options_layout.addWidget(self.case_insensitive_label)

        controls_layout.addLayout(options_layout, 2, 0, 1, 2)

        self.run_btn = QtWidgets.QPushButton("Analyser", self)
        self.run_btn.clicked.connect(self._run_search)
        self.run_btn.setDefault(True)
        controls_layout.addWidget(self.run_btn, 2, 2)

        main_layout.addWidget(controls_group)

        # Splitter with table and detail panel
        splitter = QtWidgets.QSplitter(self)
        splitter.setOrientation(QtCore.Qt.Vertical)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Occurrence", "Fichier", "Chemin", "Date"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemSelectionChanged.connect(self._update_details_panel)
        self.table.doubleClicked.connect(self._open_current_in_explorer)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        try:
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
            header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
            header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        except Exception:
            self.logger.debug("Unable to configure header resize modes", exc_info=True)
        header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)

        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        splitter.addWidget(self.table)

        self.details = QtWidgets.QTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Sélectionne une ligne pour afficher les détails…")
        self.details.setMinimumHeight(120)
        splitter.addWidget(self.details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, stretch=1)

        footer = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("", self)
        footer.addWidget(self.status_label)

        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(1)
        self.progress_bar.setValue(0)
        footer.addWidget(self.progress_bar, stretch=1)

        close_btn = QtWidgets.QPushButton("Fermer", self)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        main_layout.addLayout(footer)

    # ------------------------------------------------------------ callbacks ---
    def _apply_parent_mod_directory(self) -> None:
        directory = ""
        if hasattr(self.parent_app, "settings"):
            directory = self.parent_app.settings.get("mod_directory", "") or ""
        if directory and os.path.isdir(directory):
            self.scan_directory = directory
            self.path_edit.setText(directory)
            self.logger.info("Mod directory applied to ts4script search: %s", directory)
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Dossier introuvable",
                "Aucun dossier de mods valide n'est configuré.",
            )

    def _open_current_in_explorer(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        path = self._resolve_row_path(row)
        if path and os.path.exists(path):
            if self.parent_app and hasattr(self.parent_app, "_open_in_file_manager"):
                self.parent_app._open_in_file_manager(os.path.dirname(path) or path)

    def _clear_results(self) -> None:
        self.table.setRowCount(0)
        self.details.clear()
        self.status_label.setText("")
        self.progress_bar.setVisible(False)
        self.logger.debug("TS4Script search results cleared by user")

    def _browse(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "Choisir un dossier à scanner")
        if selected:
            self.scan_directory = selected
            self.path_edit.setText(selected)
            self.logger.info("TS4Script search directory updated: %s", selected)

    # ------------------------------------------------------------ helpers ---
    @staticmethod
    def _parse_patterns(text: str) -> List[str]:
        raw = re.split(r"[,;\s]+", text or "")
        patterns = [p.strip() for p in raw if p and p.strip()]
        seen = set()
        ordered: List[str] = []
        for p in patterns:
            key = p.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(p)
        return ordered

    @staticmethod
    def _iter_ts4scripts(root: str, recursive: bool = True) -> Iterable[str]:
        if not recursive:
            try:
                for file_name in os.listdir(root):
                    full = os.path.join(root, file_name)
                    if os.path.isfile(full) and file_name.lower().endswith(".ts4script"):
                        yield full
            except OSError:
                LOGGER.warning("Impossible de lister le dossier %s", root, exc_info=True)
            return

        for current_root, _dirs, files in os.walk(root):
            for file_name in files:
                if file_name.lower().endswith(".ts4script"):
                    yield os.path.join(current_root, file_name)

    # --------------------------------------------------------------- search ---
    def _run_search(self) -> None:
        directory = self.path_edit.text().strip()
        if not directory or not os.path.isdir(directory):
            QtWidgets.QMessageBox.warning(self, "Dossier invalide", "Sélectionne un dossier existant à analyser.")
            return

        patterns = self._parse_patterns(self.patterns_edit.text())
        if not patterns:
            QtWidgets.QMessageBox.information(
                self,
                "Recherche",
                "Saisis au moins un nom de fichier (wildcards autorisés).",
            )
            return

        recursive = bool(self.recursive_checkbox.isChecked())
        self.logger.info(
            "Recherche TS4Script lancée (directory=%s, recursive=%s, patterns=%s)",
            directory,
            recursive,
            patterns,
        )

        lowered = [p.casefold() for p in patterns]

        self.table.setRowCount(0)
        self.status_label.setText("Analyse en cours…")
        self.progress_bar.setVisible(True)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setValue(0)
        QtWidgets.QApplication.processEvents()

        files = list(self._iter_ts4scripts(directory, recursive=recursive))
        total = len(files)
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(0)
        self.logger.debug("Fichiers .ts4script candidats: %s", total)

        rows: List[dict] = []
        processed = 0

        for ts4_path in files:
            ts4_name = os.path.basename(ts4_path)
            file_dt: Optional[datetime] = None
            try:
                st = os.stat(ts4_path)
                file_dt = datetime.fromtimestamp(st.st_mtime)
            except OSError:
                self.logger.debug("Impossible de récupérer la date du fichier %s", ts4_path, exc_info=True)

            try:
                with zipfile.ZipFile(ts4_path, "r") as zf:
                    for info in zf.infolist():
                        member = info.filename
                        base = os.path.basename(member)
                        m_low = member.casefold()
                        b_low = base.casefold()
                        if self._matches_any(lowered, m_low, b_low):
                            rows.append(
                                {
                                    "occurence": member,
                                    "filename": ts4_name,
                                    "chemin": ts4_path,
                                    "date": self._format_datetime(file_dt),
                                }
                            )
            except zipfile.BadZipFile:
                self.logger.warning("Archive .ts4script invalide ignorée: %s", ts4_path)
            except Exception:
                self.logger.debug("Erreur inattendue lors de la lecture %s", ts4_path, exc_info=True)

            processed += 1
            if processed % 5 == 0 or processed == total:
                self.progress_bar.setValue(processed)
                QtWidgets.QApplication.processEvents()

        self._render(rows)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"{len(rows)} correspondance(s)")
        self.logger.info(
            "Recherche TS4Script terminée (matches=%s, files_scanned=%s)", len(rows), total
        )

    @staticmethod
    def _matches_any(patterns: Sequence[str], candidate: str, basename: str) -> bool:
        for pat in patterns:
            if ("*" in pat) or ("?" in pat):
                if fnmatch.fnmatch(candidate, pat) or fnmatch.fnmatch(basename, pat):
                    return True
            else:
                if pat in candidate or pat in basename:
                    return True
        return False

    # ------------------------------------------------------------ rendering ---
    def _render(self, rows: List[dict]) -> None:
        self.table.setSortingEnabled(False)
        try:
            self.table.clearContents()
        except Exception:
            self.logger.debug("Impossible de vider la table TS4Script", exc_info=True)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = [
                row.get("occurence", ""),
                row.get("filename", ""),
                row.get("chemin", ""),
                row.get("date", ""),
            ]
            for c, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(QtCore.Qt.UserRole, row.get("chemin", ""))
                    item.setToolTip(str(value))
                if c == 2:
                    item.setToolTip(str(value))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, QtCore.Qt.AscendingOrder)
        self._update_details_panel()

    def _update_details_panel(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.details.clear()
            return

        occurrence = self.table.item(row, 0)
        filename = self.table.item(row, 1)
        path = self.table.item(row, 2)
        date_value = self.table.item(row, 3)

        info_lines = [
            f"Occurrence : {occurrence.text() if occurrence else ''}",
            f"Archive    : {filename.text() if filename else ''}",
            f"Chemin     : {path.text() if path else ''}",
            f"Date       : {date_value.text() if date_value else ''}",
        ]
        self.details.setPlainText("\n".join(info_lines))

    # ------------------------------------------------------- interactions ---
    def _resolve_row_path(self, row_index: int) -> str:
        item = self.table.item(row_index, 0)
        if item is None:
            return ""
        path = item.data(QtCore.Qt.UserRole) or ""
        return str(path)

    def show_context_menu(self, position: QtCore.QPoint) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return

        row = index.row()
        menu = QtWidgets.QMenu(self)
        show_in_explorer_action = menu.addAction("Afficher dans l'explorateur")
        copy_path_action = menu.addAction("Copier le chemin complet")
        delete_action = menu.addAction("Supprimer le fichier")
        menu.addSeparator()
        google_action = menu.addAction("Recherche Google")
        patreon_action = menu.addAction("Chercher sur Patreon")

        selected = menu.exec_(self.table.viewport().mapToGlobal(position))

        if selected == show_in_explorer_action:
            self._open_selected_in_explorer(row)
        elif selected == copy_path_action:
            self._copy_path_to_clipboard(row)
        elif selected == delete_action:
            self._delete_row(row)
        elif selected == google_action:
            self._search_web(row, restrict_site=None)
        elif selected == patreon_action:
            self._search_web(row, restrict_site="patreon.com")

    def _open_selected_in_explorer(self, row: int) -> None:
        path = self._resolve_row_path(row)
        if path and os.path.exists(path):
            if self.parent_app and hasattr(self.parent_app, "_open_in_file_manager"):
                self.parent_app._open_in_file_manager(os.path.dirname(path) or path)

    def _copy_path_to_clipboard(self, row: int) -> None:
        path = self._resolve_row_path(row)
        if not path:
            return
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(path)
        self.logger.debug("Chemin copié dans le presse-papiers: %s", path)

    def _delete_row(self, row: int) -> None:
        path = self._resolve_row_path(row)
        if not path:
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Confirmer la suppression",
            "Supprimer ce fichier .ts4script ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
            self.table.removeRow(row)
            self.details.clear()
            self.logger.info("Fichier .ts4script supprimé: %s", path)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Erreur lors de la suppression", str(exc))
            self.logger.warning("Suppression impossible pour %s", path, exc_info=True)

    def _search_web(self, row: int, restrict_site: Optional[str]) -> None:
        base = ""
        item = self.table.item(row, 0)
        if item and item.text().strip():
            base = os.path.splitext(os.path.basename(item.text().strip()))[0]
        if not base:
            item2 = self.table.item(row, 1)
            if item2 and item2.text().strip():
                base = os.path.splitext(item2.text().strip())[0]
        if base:
            query = base if not restrict_site else f"site:{restrict_site} {base}"
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(f"https://www.google.com/search?q={quote_plus(query)}"))

    def _show_header_menu(self, pos: QtCore.QPoint) -> None:
        header = self.table.horizontalHeader()
        global_pos = header.mapToGlobal(pos)
        menu = QtWidgets.QMenu(self)
        labels = ["Occurrence", "Fichier", "Chemin", "Date"]
        for col, label in enumerate(labels):
            action = QtWidgets.QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(col))
            action.triggered.connect(lambda checked, c=col: self.table.setColumnHidden(c, not checked))
            menu.addAction(action)
        menu.exec_(global_pos)
