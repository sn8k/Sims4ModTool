import sys
import os
import json
import shutil
import shlex
import re
from functools import partial
from urllib.parse import quote_plus
from PyQt5 import QtWidgets, QtCore, QtGui
from datetime import datetime
from openpyxl import Workbook

SETTINGS_PATH = "settings.json"
IGNORE_LIST_PATH = "ignorelist.txt"
APP_VERSION = "v3.15"
APP_VERSION_DATE = "21/10/2025 16:47 UTC"


VERSION_PATTERN = re.compile(r"_v_([0-9]+(?:[._-][0-9A-Za-z]+)*)$", re.IGNORECASE)


def extract_version_from_script_name(script_name):
    if not script_name:
        return ""
    base_name = os.path.splitext(script_name)[0]
    match = VERSION_PATTERN.search(base_name)
    return match.group(1) if match else ""


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

def get_file_date(file_path):
    timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(timestamp)

def load_settings(path=SETTINGS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {
            "hide_post_118": True,
            "filter_116_to_118": True,
            "filter_package_and_ts4script": False,
            "mod_directory": "",
            "sims_cache_directory": "",
            "backups_directory": "",
            "xls_file_path": "",
            "sims_executable_path": "",
            "sims_executable_arguments": "",
            "log_extra_extensions": [],
            "ignored_mods": [],  # Liste des mods ignorés
            "show_ignored": False  # Contrôle si les mods ignorés doivent être affichés
        }
    defaults = {
        "hide_post_118": True,
        "filter_116_to_118": True,
        "filter_package_and_ts4script": False,
        "mod_directory": "",
        "sims_cache_directory": "",
        "backups_directory": "",
        "xls_file_path": "",
        "sims_executable_path": "",
        "sims_executable_arguments": "",
        "log_extra_extensions": [],
        "ignored_mods": [],
        "show_ignored": False,
    }
    for key, value in defaults.items():
        settings.setdefault(key, value)
    if isinstance(settings.get("log_extra_extensions"), str):
        settings["log_extra_extensions"] = [part.strip() for part in settings["log_extra_extensions"].split(",") if part.strip()]
    extra_extensions = []
    for entry in settings.get("log_extra_extensions", []):
        if not entry:
            continue
        ext = entry if entry.startswith(".") else f".{entry}"
        extra_extensions.append(ext.lower())
    settings["log_extra_extensions"] = sorted(set(extra_extensions))
    ignored_from_file = load_ignore_list()
    if not ignored_from_file and settings.get("ignored_mods"):
        ignored_from_file = settings.get("ignored_mods", [])
        save_ignore_list(ignored_from_file)
    settings["ignored_mods"] = ignored_from_file
    return settings

def save_settings(settings, path=SETTINGS_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)

def scan_directory(directory):
    package_files = {}
    ts4script_files = {}
    for root, dirs, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            if file.lower().endswith(".package"):
                package_files[file] = full_path
            elif file.lower().endswith(".ts4script"):
                ts4script_files[file] = full_path
    return package_files, ts4script_files

def generate_data_rows(directory, settings):
    package_files, ts4script_files = scan_directory(directory)
    filter_post_118_date = datetime(2025, 9, 18)
    filter_116_start_date = datetime(2025, 7, 1)
    filter_118_end_date = datetime(2025, 9, 18)

    data_rows = []
    ignored_mods = set(settings.get("ignored_mods", []))
    show_ignored = settings.get("show_ignored", False)

    # .package files
    for pkg, pkg_path in package_files.items():
        pkg_date = get_file_date(pkg_path)
        base_name = os.path.splitext(pkg)[0]
        script_file = f"{base_name}.ts4script"
        script_path = ts4script_files.get(script_file)
        script_date = get_file_date(script_path) if script_path else None

        # Appliquer filtres
        if settings["hide_post_118"] and pkg_date > filter_post_118_date:
            continue
        if settings["filter_116_to_118"] and not (filter_116_start_date <= pkg_date <= filter_118_end_date):
            continue
        if settings["filter_package_and_ts4script"] and not script_path:
            continue

        candidates = [name for name in (pkg, script_file if script_path else None) if name]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue

        status = "MP"
        if script_path:
            status = "X"
        version = extract_version_from_script_name(script_file if script_path else "")

        data_rows.append({
            "status": status,
            "package": pkg,
            "package_date": format_datetime(pkg_date),
            "script": script_file if script_path else "",
            "script_date": format_datetime(script_date),
            "version": version,
            "ignored": ignored,
            "ignore_candidates": candidates or [pkg],
            "paths": [path for path in (pkg_path, script_path) if path]
        })

    # ts4script orphans
    for script, script_path in ts4script_files.items():
        base_name = os.path.splitext(script)[0]
        pkg_file = f"{base_name}.package"
        if pkg_file in package_files:
            continue

        script_date = get_file_date(script_path)

        if settings["hide_post_118"] and script_date > filter_post_118_date:
            continue
        if settings["filter_116_to_118"] and not (filter_116_start_date <= script_date <= filter_118_end_date):
            continue
        if settings["filter_package_and_ts4script"]:
            continue
        candidates = [script]
        ignored = any(name in ignored_mods for name in candidates)
        if ignored and not show_ignored:
            continue
        status = "MS"

        version = extract_version_from_script_name(script)

        data_rows.append({
            "status": status,
            "package": "",
            "package_date": "",
            "script": script,
            "script_date": format_datetime(script_date),
            "version": version,
            "ignored": ignored,
            "ignore_candidates": candidates,
            "paths": [script_path]
        })

    return data_rows

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
        "Ignoré",
    ]
    for idx, h in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=h)

    for row_idx, row in enumerate(data_rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    wb.save(save_path)


class ConfigurationDialog(QtWidgets.QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setModal(True)
        self._parent = parent

        layout = QtWidgets.QVBoxLayout()

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

        self.log_extensions_edit = QtWidgets.QLineEdit(self)
        extra_extensions = ", ".join(settings.get("log_extra_extensions", []))
        self.log_extensions_edit.setText(extra_extensions)
        self.log_extensions_edit.setPlaceholderText("Extensions supplémentaires (.mdmp, .html, ...)")

        logs_ext_layout = QtWidgets.QHBoxLayout()
        logs_ext_layout.addWidget(QtWidgets.QLabel("Extensions de logs (supplémentaires) :"))
        logs_ext_layout.addWidget(self.log_extensions_edit)
        layout.addLayout(logs_ext_layout)

        button_box = QtWidgets.QDialogButtonBox()
        save_button = button_box.addButton("Sauvegarder", QtWidgets.QDialogButtonBox.AcceptRole)
        cancel_button = button_box.addButton(QtWidgets.QDialogButtonBox.Cancel)
        save_button.clicked.connect(self._save_configuration)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

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

        extra_extensions = []
        if log_extensions_text:
            for part in re.split(r"[,;\s]+", log_extensions_text):
                cleaned = part.strip()
                if not cleaned:
                    continue
                if not cleaned.startswith("."):
                    cleaned = f".{cleaned}"
                extra_extensions.append(cleaned.lower())

        if self._parent is not None:
            self._parent.apply_configuration(
                mod_directory,
                cache_directory,
                backups_directory,
                sims_executable_path,
                sims_executable_arguments,
                sorted(set(extra_extensions)),
            )
        self.accept()


class ModManagerApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"Gestionnaire de Mods Sims 4 – {APP_VERSION} ({APP_VERSION_DATE})")
        self.setGeometry(100, 100, 800, 600)

        self.settings = load_settings()
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = ""
        self.all_data_rows = []

        self.init_ui()

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
        self.hide_post_118_checkbox = QtWidgets.QCheckBox("Masquer mods post‑patch 1.118", self)
        self.hide_post_118_checkbox.setChecked(self.settings.get("hide_post_118", True))
        self.hide_post_118_checkbox.toggled.connect(lambda: self.toggle_setting("hide_post_118"))

        self.filter_116_to_118_checkbox = QtWidgets.QCheckBox("Uniquement entre patch 1.116‑1.118", self)
        self.filter_116_to_118_checkbox.setChecked(self.settings.get("filter_116_to_118", True))
        self.filter_116_to_118_checkbox.toggled.connect(lambda: self.toggle_setting("filter_116_to_118"))

        self.filter_package_and_ts4script_checkbox = QtWidgets.QCheckBox("Uniquement mods avec .package + .ts4script", self)
        self.filter_package_and_ts4script_checkbox.setChecked(self.settings.get("filter_package_and_ts4script", False))
        self.filter_package_and_ts4script_checkbox.toggled.connect(lambda: self.toggle_setting("filter_package_and_ts4script"))

        self.show_ignored_checkbox = QtWidgets.QCheckBox("Afficher les mods ignorés", self)
        self.show_ignored_checkbox.setChecked(self.settings.get("show_ignored", False))
        self.show_ignored_checkbox.toggled.connect(lambda: self.toggle_show_ignored())

        filter_layout = QtWidgets.QVBoxLayout()
        filter_layout.addWidget(self.hide_post_118_checkbox)
        filter_layout.addWidget(self.filter_116_to_118_checkbox)
        filter_layout.addWidget(self.filter_package_and_ts4script_checkbox)
        filter_layout.addWidget(self.show_ignored_checkbox)

        layout.addLayout(filter_layout)

        search_layout = QtWidgets.QHBoxLayout()
        search_layout.addWidget(QtWidgets.QLabel("Recherche mod :"))
        self.search_edit = QtWidgets.QLineEdit(self)
        self.search_edit.setPlaceholderText("Nom du mod à rechercher")
        self.search_edit.textChanged.connect(self.apply_search_filter)
        search_layout.addWidget(self.search_edit)

        layout.addLayout(search_layout)

        # Table des mods
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "État",
            "Fichier .package",
            "Date .package",
            "Fichier .ts4script",
            "Date .ts4script",
            "Version",
            "Ignoré",
        ])
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self.table.horizontalHeader()
        for column in range(self.table.columnCount()):
            resize_mode = QtWidgets.QHeaderView.Stretch
            if column in (0, 2, 4, 5, self.table.columnCount() - 1):
                resize_mode = QtWidgets.QHeaderView.ResizeToContents
            header.setSectionResizeMode(column, resize_mode)
        header.setStretchLastSection(False)
        self.table.setSortingEnabled(True)
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.table, stretch=1)

        # Boutons
        self.configuration_button = QtWidgets.QPushButton("Configuration", self)
        self.configuration_button.clicked.connect(self.open_configuration)

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

        self.tools_button = QtWidgets.QPushButton("Tools", self)
        self.tools_button.clicked.connect(self.open_tools_dialog)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.configuration_button)
        button_layout.addWidget(self.tools_button)
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.clear_cache_button)
        button_layout.addWidget(self.grab_logs_button)
        button_layout.addWidget(self.launch_button)

        layout.addLayout(button_layout)

        # Final
        self.setLayout(layout)
        self.update_launch_button_state()

    def toggle_setting(self, key):
        self.settings[key] = getattr(self, f"{key}_checkbox").isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_ignored(self):
        self.settings["show_ignored"] = self.show_ignored_checkbox.isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def update_mod_directory_label(self):
        directory = self.settings.get("mod_directory", "")
        display_text = directory if directory else "(non défini)"
        self.mod_directory_label.setText(display_text)

    def open_configuration(self):
        dialog = ConfigurationDialog(self, dict(self.settings))
        dialog.exec_()

    def apply_configuration(self, mod_directory, cache_directory, backups_directory, sims_executable_path, sims_executable_arguments, log_extra_extensions):
        previous_mod_directory = self.settings.get("mod_directory", "")
        self.settings["mod_directory"] = mod_directory
        self.settings["sims_cache_directory"] = cache_directory
        self.settings["backups_directory"] = backups_directory
        self.settings["sims_executable_path"] = sims_executable_path
        self.settings["sims_executable_arguments"] = sims_executable_arguments
        self.settings["log_extra_extensions"] = sorted(set(log_extra_extensions))
        save_settings(self.settings)
        self.update_mod_directory_label()
        self.update_launch_button_state()

        if previous_mod_directory != mod_directory:
            self.last_scanned_directory = ""
            if hasattr(self, "table"):
                self.table.setRowCount(0)

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
        rows = generate_data_rows(folder, self.settings)
        self.populate_table(rows)

    def refresh_table_only(self):
        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.ignored_mods = set(self.settings.get("ignored_mods", []))
            rows = generate_data_rows(self.last_scanned_directory, self.settings)
            self.populate_table(rows)

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

        normalized_mod_dir = os.path.normpath(mod_directory)
        backups_directory_norm = os.path.normpath(backups_directory)
        found_logs = []

        for current_root, dirs, files in os.walk(normalized_mod_dir):
            dirs[:] = [d for d in dirs if os.path.normpath(os.path.join(current_root, d)) != backups_directory_norm]
            for file_name in files:
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
            return

        message_lines = [f"{len(moved_files)} fichier(s) de log déplacé(s) vers {destination_root}."]
        if errors:
            message_lines.append("\nErreurs:\n" + "\n".join(errors))
        QtWidgets.QMessageBox.information(self, "Logs sauvegardés", "\n".join(message_lines))
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

    def update_launch_button_state(self):
        if hasattr(self, "launch_button"):
            executable_path = self.settings.get("sims_executable_path", "")
            self.launch_button.setEnabled(bool(executable_path and os.path.isfile(executable_path)))

    def open_tools_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Tools")
        dialog.setModal(True)

        layout = QtWidgets.QVBoxLayout(dialog)
        button_definitions = [
            ("Find dupplicates", "La recherche de doublons n'est pas encore disponible."),
            ("Find non-mods files", "La détection des fichiers non mods sera ajoutée ultérieurement."),
            ("Disable all mods", "La désactivation des mods sera proposée dans une future mise à jour."),
            ("Correct ressource.cfg", "La correction du fichier resource.cfg n'est pas encore implémentée."),
        ]

        for label, message in button_definitions:
            button = QtWidgets.QPushButton(label, dialog)
            button.clicked.connect(partial(self._show_placeholder_message, label, message))
            layout.addWidget(button)

        close_button = QtWidgets.QPushButton("Fermer", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)

        dialog.exec_()

    def _show_placeholder_message(self, title, message):
        QtWidgets.QMessageBox.information(self, title, message)

    def populate_table(self, data_rows):
        self.all_data_rows = list(data_rows)
        self._apply_search_filter()

    def apply_search_filter(self, _text=None):
        self._apply_search_filter()

    def _apply_search_filter(self):
        query = ""
        if hasattr(self, "search_edit"):
            query = self.search_edit.text().strip().lower()

        if not query:
            filtered_rows = list(self.all_data_rows)
        else:
            filtered_rows = [
                row
                for row in self.all_data_rows
                if self._row_matches_query(row, query)
            ]

        self._render_table(filtered_rows)

    def _row_matches_query(self, row, query):
        for value in self._gather_searchable_values(row):
            if query in value:
                return True
        return False

    def _gather_searchable_values(self, row):
        values = [
            str(row.get("status", "")),
            str(row.get("package", "")),
            str(row.get("package_date", "")),
            str(row.get("script", "")),
            str(row.get("script_date", "")),
            str(row.get("version", "")),
        ]
        ignored_value = "oui" if row.get("ignored", False) else "non"
        values.append(ignored_value)
        values.extend(str(candidate) for candidate in row.get("ignore_candidates", []))
        values.extend(str(path) for path in row.get("paths", []))
        return [value.lower() for value in values if value]

    def _render_table(self, rows):
        header = self.table.horizontalHeader()
        sorting_enabled = self.table.isSortingEnabled()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)  # Clear previous data
        for row in rows:
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            columns = [
                row.get("status", ""),
                row.get("package", ""),
                row.get("package_date", ""),
                row.get("script", ""),
                row.get("script_date", ""),
                row.get("version", ""),
            ]
            for col_idx, value in enumerate(columns):
                item = QtWidgets.QTableWidgetItem(str(value))
                if col_idx == 0:
                    item.setData(QtCore.Qt.UserRole, row.get("ignore_candidates", []))
                    item.setData(QtCore.Qt.UserRole + 1, row.get("paths", []))
                self.table.setItem(row_position, col_idx, item)

            # Ajouter la case à cocher dans la colonne "Ignoré"
            ignored = row.get("ignored", False)
            ignore_item = QtWidgets.QTableWidgetItem("Oui" if ignored else "Non")
            ignore_item.setData(QtCore.Qt.UserRole, 1 if ignored else 0)
            ignore_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.table.setItem(row_position, 6, ignore_item)
            ignore_checkbox = QtWidgets.QCheckBox()
            ignore_checkbox.stateChanged.connect(partial(self.update_ignore_mod, row.get("ignore_candidates", [])))
            ignore_checkbox.blockSignals(True)
            ignore_checkbox.setChecked(ignored)
            ignore_checkbox.blockSignals(False)
            self.table.setCellWidget(row_position, 6, ignore_checkbox)
        self.table.setSortingEnabled(sorting_enabled)
        if sorting_enabled:
            self.table.sortByColumn(sort_section, sort_order)

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
            checkbox = self.table.cellWidget(row, 6)
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
        for column in (1, 3):
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
            row_data = [self.table.item(row, col).text() for col in range(self.table.columnCount() - 1)]
            row_data.append(self.table.cellWidget(row, 6).isChecked())  # Ajouter l'état de la case à cocher "Ignoré"
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

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ModManagerApp()
    window.show()
    sys.exit(app.exec_())
