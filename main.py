import sys
import os
import json
from PyQt5 import QtWidgets, QtCore
from datetime import datetime
from openpyxl import Workbook

SETTINGS_PATH = "settings.json"

def get_file_date(file_path):
    timestamp = os.path.getmtime(file_path)
    return datetime.fromtimestamp(timestamp)

def load_settings(path=SETTINGS_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "hide_post_118": True,
            "filter_116_to_118": True,
            "filter_package_and_ts4script": False,
            "mod_directory": "",
            "xls_file_path": "",
            "ignored_mods": [],  # Liste des mods ignorés
            "show_ignored": False  # Contrôle si les mods ignorés doivent être affichés
        }

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
        ignored = pkg in ignored_mods

        status = "MP"
        if script_path:
            status = "X"

        data_rows.append([status, pkg, pkg_date, script_file if script_path else "", script_date, ignored])

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
        ignored = script in ignored_mods
        status = "MS"

        data_rows.append([status, "", "", script, script_date, ignored])

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

        self.setWindowTitle("Gestionnaire de Mods Sims 4 – v3.2")
        self.setGeometry(100, 100, 800, 600)

        self.settings = load_settings()

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

        layout.addWidget(self.table)

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

    def toggle_show_ignored(self):
        self.settings["show_ignored"] = self.show_ignored_checkbox.isChecked()
        save_settings(self.settings)

    def refresh_tree(self):
        folder = self.mod_directory_input.text()
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.critical(self, "Erreur", "Sélectionne un dossier valide.")
            return
        self.settings["mod_directory"] = folder
        save_settings(self.settings)
        rows = generate_data_rows(folder, self.settings)
        self.populate_table(rows)

    def populate_table(self, data_rows):
        self.table.setRowCount(0)  # Clear previous data
        for row in data_rows:
            self.table.insertRow(self.table.rowCount())
            for col in range(len(row) - 1):  # Exclure la colonne "Ignoré"
                self.table.setItem(self.table.rowCount() - 1, col, QtWidgets.QTableWidgetItem(str(row[col])))

            # Ajouter la case à cocher dans la colonne "Ignoré"
            ignore_checkbox = QtWidgets.QCheckBox()
            ignore_checkbox.setChecked(row[5])  # Marquer comme "ignorer" si la valeur est True
            ignore_checkbox.stateChanged.connect(lambda state, row_id=row[0]: self.update_ignore_mod(state, row_id))
            self.table.setCellWidget(self.table.rowCount() - 1, 5, ignore_checkbox)

    def update_ignore_mod(self, state, row_id):
        ignored_mods = self.settings.get("ignored_mods", [])
        if state == QtCore.Qt.Checked:
            ignored_mods.append(row_id)
        else:
            ignored_mods.remove(row_id)
        self.settings["ignored_mods"] = ignored_mods
        save_settings(self.settings)

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
