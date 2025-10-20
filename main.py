import sys
import os
import json
from functools import partial
from PyQt5 import QtWidgets, QtCore
from datetime import datetime
from openpyxl import Workbook

SETTINGS_PATH = "settings.json"
IGNORE_LIST_PATH = "ignorelist.txt"
APP_VERSION = "v3.6"
APP_VERSION_DATE = "20/10/2025"


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
            "xls_file_path": "",
            "ignored_mods": [],  # Liste des mods ignorés
            "show_ignored": False  # Contrôle si les mods ignorés doivent être affichés
        }
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
        data_rows.append({
            "status": status,
            "package": pkg,
            "package_date": format_datetime(pkg_date),
            "script": script_file if script_path else "",
            "script_date": format_datetime(script_date),
            "ignored": ignored,
            "ignore_candidates": candidates or [pkg]
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

        data_rows.append({
            "status": status,
            "package": "",
            "package_date": "",
            "script": script,
            "script_date": format_datetime(script_date),
            "ignored": ignored,
            "ignore_candidates": candidates
        })

    return data_rows

def export_to_excel(save_path, data_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Mods"

    headers = ["État", "Fichier .package", "Date .package", "Fichier .ts4script", "Date .ts4script", "Ignoré"]
    for idx, h in enumerate(headers, start=1):
        ws.cell(row=1, column=idx, value=h)

    for row_idx, row in enumerate(data_rows, start=2):
        for col_idx, value in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    wb.save(save_path)

class ModManagerApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"Gestionnaire de Mods Sims 4 – {APP_VERSION} ({APP_VERSION_DATE})")
        self.setGeometry(100, 100, 800, 600)

        self.settings = load_settings()
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = ""

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

        # Dossier des mods
        self.mod_directory_input = QtWidgets.QLineEdit(self)
        self.mod_directory_input.setText(self.settings.get("mod_directory", ""))
        browse_button = QtWidgets.QPushButton("Parcourir...", self)
        browse_button.clicked.connect(self.browse_directory)

        mod_dir_layout = QtWidgets.QHBoxLayout()
        mod_dir_layout.addWidget(QtWidgets.QLabel("Dossier des mods :"))
        mod_dir_layout.addWidget(self.mod_directory_input)
        mod_dir_layout.addWidget(browse_button)

        layout.addLayout(mod_dir_layout)

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

        # Table des mods
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["État", "Fichier .package", "Date .package", "Fichier .ts4script", "Date .ts4script", "Ignoré"])
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self.table.horizontalHeader()
        for column in range(self.table.columnCount()):
            resize_mode = QtWidgets.QHeaderView.Stretch
            if column in (0, self.table.columnCount() - 1):
                resize_mode = QtWidgets.QHeaderView.ResizeToContents
            header.setSectionResizeMode(column, resize_mode)
        header.setStretchLastSection(False)
        self.table.setSortingEnabled(True)
        self.table.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        layout.addWidget(self.table, stretch=1)

        # Boutons
        self.refresh_button = QtWidgets.QPushButton("Analyser / Rafraîchir", self)
        self.refresh_button.clicked.connect(self.refresh_tree)

        self.export_button = QtWidgets.QPushButton("Exporter vers Excel", self)
        self.export_button.clicked.connect(self.export_current)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.export_button)

        layout.addLayout(button_layout)

        # Final
        self.setLayout(layout)

    def browse_directory(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if folder:
            self.mod_directory_input.setText(folder)
            self.settings["mod_directory"] = folder
            save_settings(self.settings)

    def toggle_setting(self, key):
        self.settings[key] = getattr(self, f"{key}_checkbox").isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def toggle_show_ignored(self):
        self.settings["show_ignored"] = self.show_ignored_checkbox.isChecked()
        save_settings(self.settings)
        self.refresh_table_only()

    def refresh_tree(self):
        folder = self.mod_directory_input.text()
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.critical(self, "Erreur", "Sélectionne un dossier valide.")
            return
        self.settings["mod_directory"] = folder
        save_settings(self.settings)
        self.ignored_mods = set(self.settings.get("ignored_mods", []))
        self.last_scanned_directory = folder
        rows = generate_data_rows(folder, self.settings)
        self.populate_table(rows)

    def refresh_table_only(self):
        if self.last_scanned_directory and os.path.isdir(self.last_scanned_directory):
            self.ignored_mods = set(self.settings.get("ignored_mods", []))
            rows = generate_data_rows(self.last_scanned_directory, self.settings)
            self.populate_table(rows)

    def populate_table(self, data_rows):
        header = self.table.horizontalHeader()
        sorting_enabled = self.table.isSortingEnabled()
        sort_section = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)  # Clear previous data
        for row in data_rows:
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            columns = [
                row.get("status", ""),
                row.get("package", ""),
                row.get("package_date", ""),
                row.get("script", ""),
                row.get("script_date", "")
            ]
            for col_idx, value in enumerate(columns):
                item = QtWidgets.QTableWidgetItem(str(value))
                if col_idx == 0:
                    item.setData(QtCore.Qt.UserRole, row.get("ignore_candidates", []))
                self.table.setItem(row_position, col_idx, item)

            # Ajouter la case à cocher dans la colonne "Ignoré"
            ignored = row.get("ignored", False)
            ignore_item = QtWidgets.QTableWidgetItem("Oui" if ignored else "Non")
            ignore_item.setData(QtCore.Qt.UserRole, 1 if ignored else 0)
            ignore_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.table.setItem(row_position, 5, ignore_item)
            ignore_checkbox = QtWidgets.QCheckBox()
            ignore_checkbox.stateChanged.connect(partial(self.update_ignore_mod, row.get("ignore_candidates", [])))
            ignore_checkbox.blockSignals(True)
            ignore_checkbox.setChecked(ignored)
            ignore_checkbox.blockSignals(False)
            self.table.setCellWidget(row_position, 5, ignore_checkbox)
        self.table.setSortingEnabled(sorting_enabled)
        if sorting_enabled:
            self.table.sortByColumn(sort_section, sort_order)

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
            row_data.append(self.table.cellWidget(row, 5).isChecked())  # Ajouter l'état de la case à cocher "Ignoré"
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
