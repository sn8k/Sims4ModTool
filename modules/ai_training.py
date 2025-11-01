import os
import re
import io
import logging
import urllib.request
import csv as _csv
from datetime import datetime
from typing import Dict, List, Tuple
from collections import Counter

# Optional ML stack
try:  # light, optional classic ML (TF‑IDF + LinearSVC)
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore
    from sklearn.svm import LinearSVC  # type: ignore
    from sklearn.pipeline import Pipeline  # type: ignore
    from sklearn.metrics import accuracy_score, f1_score  # type: ignore
    from sklearn.model_selection import StratifiedKFold, cross_val_score  # type: ignore
    from sklearn.preprocessing import StandardScaler  # type: ignore
    from sklearn.decomposition import TruncatedSVD  # type: ignore
    from sklearn.neural_network import MLPClassifier  # type: ignore
    import joblib  # type: ignore
    _SKLEARN_OK = True
except Exception:
    _SKLEARN_OK = False

# Reuse app's Qt + helpers
from main import QtWidgets, QtCore, ModAI, generate_data_rows, analyze_last_exception_html, analyze_generic_log_text
from main import _strip_html_to_text, _normalize_log_level, save_settings  # type: ignore


def get_tools(app):
    def _open_training(app_inst):
        dlg = AITrainingDialog(app_inst)
        dlg.exec_()
    return [("Entrainement A.I.", _open_training)]


class AITrainingDialog(QtWidgets.QDialog):
    def __init__(self, app):
        super().__init__(app)
        self.parent_app = app
        self.setWindowTitle("Entrainement A.I.")
        self.setModal(True)
        try:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
            self.setSizeGripEnabled(True)
        except Exception:
            pass
        self.resize(820, 540)

        root = QtWidgets.QVBoxLayout(self)

        # Source folder picker
        src_gb = QtWidgets.QGroupBox("Sources", self)
        src_v = QtWidgets.QVBoxLayout(src_gb)
        src_row = QtWidgets.QHBoxLayout()
        src_row.addWidget(QtWidgets.QLabel("Dossier à analyser:", self))
        self.path_edit = QtWidgets.QLineEdit(self)
        try:
            self.path_edit.setText(str(getattr(self.parent_app, 'settings', {}).get('mod_directory', '') or ''))
        except Exception:
            pass
        src_row.addWidget(self.path_edit, 1)
        btn_browse_src = QtWidgets.QPushButton("Parcourir…", self)
        btn_browse_src.clicked.connect(self._browse_src)
        src_row.addWidget(btn_browse_src)
        src_v.addLayout(src_row)

        self.chk_use_rows = QtWidgets.QCheckBox("Inclure mods scannés (fichiers .package/.ts4script)", self)
        self.chk_use_rows.setChecked(bool(getattr(self.parent_app, 'settings', {}).get('ai_train_use_rows', True)))
        self.chk_use_logs = QtWidgets.QCheckBox("Inclure journaux (logs, txt, html)", self)
        self.chk_use_logs.setChecked(bool(getattr(self.parent_app, 'settings', {}).get('ai_train_use_logs', True)))
        self.chk_use_index = QtWidgets.QCheckBox("Inclure index Updates Checker (CSV en ligne)", self)
        self.chk_use_index.setChecked(bool(getattr(self.parent_app, 'settings', {}).get('ai_train_use_index', True)))
        src_v.addWidget(self.chk_use_rows)
        src_v.addWidget(self.chk_use_logs)
        src_v.addWidget(self.chk_use_index)
        root.addWidget(src_gb)

        # Options
        opt_gb = QtWidgets.QGroupBox("Options d'apprentissage", self)
        opt_f = QtWidgets.QFormLayout(opt_gb)
        self.batch = QtWidgets.QSpinBox(self)
        self.batch.setRange(50, 20000)
        try:
            self.batch.setValue(int(getattr(self.parent_app, 'settings', {}).get('ai_train_batch', 500)))
        except Exception:
            self.batch.setValue(500)
        opt_f.addRow("Taille de lot (token model)", self.batch)

        self.engine = QtWidgets.QComboBox(self)
        self.engine.addItem("Basique (bag‑of‑tokens)", "basic")
        self.engine.addItem("Classifieur TF‑IDF (LinearSVC)", "tfidf")
        self.engine.addItem("Réseau neuronal léger (MLP)", "mlp")
        if not _SKLEARN_OK:
            idx = self.engine.findData("tfidf")
            if idx >= 0:
                self.engine.model().item(idx).setEnabled(False)  # type: ignore
            idx = self.engine.findData("mlp")
            if idx >= 0:
                self.engine.model().item(idx).setEnabled(False)  # type: ignore
        # restore engine
        try:
            eng = str(getattr(self.parent_app, 'settings', {}).get('ai_train_engine', 'basic'))
            idx = self.engine.findData(eng)
            if idx >= 0:
                self.engine.setCurrentIndex(idx)
        except Exception:
            pass
        opt_f.addRow("Moteur d'entrainement", self.engine)

        self.val_split = QtWidgets.QDoubleSpinBox(self)
        self.val_split.setRange(0.0, 0.9)
        self.val_split.setSingleStep(0.05)
        try:
            self.val_split.setValue(float(getattr(self.parent_app, 'settings', {}).get('ai_train_val_split', 0.2)))
        except Exception:
            self.val_split.setValue(0.2)
        opt_f.addRow("Taille validation (0=aucune)", self.val_split)

        self.max_features = QtWidgets.QSpinBox(self)
        self.max_features.setRange(1000, 200000)
        try:
            self.max_features.setValue(int(getattr(self.parent_app, 'settings', {}).get('ai_train_max_features', 50000)))
        except Exception:
            self.max_features.setValue(50000)
        opt_f.addRow("Max features TF‑IDF", self.max_features)

        self.ngram = QtWidgets.QComboBox(self)
        self.ngram.addItems(["1-1", "1-2", "1-3"])
        try:
            ng = str(getattr(self.parent_app, 'settings', {}).get('ai_train_ngram', '1-2'))
            i = self.ngram.findText(ng)
            if i >= 0:
                self.ngram.setCurrentIndex(i)
        except Exception:
            pass
        opt_f.addRow("N‑gram range", self.ngram)

        self.min_class_samples = QtWidgets.QSpinBox(self)
        self.min_class_samples.setRange(1, 20)
        try:
            self.min_class_samples.setValue(int(getattr(self.parent_app, 'settings', {}).get('ai_train_min_samples', 2)))
        except Exception:
            self.min_class_samples.setValue(2)
        opt_f.addRow("Min échantillons / classe", self.min_class_samples)

        self.rare_strategy = QtWidgets.QComboBox(self)
        self.rare_strategy.addItem("Supprimer les classes rares", "drop")
        self.rare_strategy.addItem("Fusionner dans 'Rare'", "merge")
        try:
            rs = str(getattr(self.parent_app, 'settings', {}).get('ai_train_rare_strategy', 'drop'))
            idx = self.rare_strategy.findData(rs)
            if idx >= 0:
                self.rare_strategy.setCurrentIndex(idx)
        except Exception:
            pass
        opt_f.addRow("Gestion classes rares", self.rare_strategy)

        self.class_weight_balanced = QtWidgets.QCheckBox("Utiliser class_weight='balanced'", self)
        self.class_weight_balanced.setChecked(bool(getattr(self.parent_app, 'settings', {}).get('ai_train_class_weight_balanced', True)))
        opt_f.addRow("Équilibrage", self.class_weight_balanced)

        self.cv_folds = QtWidgets.QSpinBox(self)
        self.cv_folds.setRange(0, 5)
        try:
            self.cv_folds.setValue(int(getattr(self.parent_app, 'settings', {}).get('ai_train_cv_folds', 0)))
        except Exception:
            self.cv_folds.setValue(0)
        opt_f.addRow("Validation croisée (k-folds)", self.cv_folds)

        self.mlp_hidden = QtWidgets.QSpinBox(self)
        self.mlp_hidden.setRange(16, 1024)
        self.mlp_hidden.setSingleStep(16)
        try:
            self.mlp_hidden.setValue(int(getattr(self.parent_app, 'settings', {}).get('ai_train_mlp_hidden', 128)))
        except Exception:
            self.mlp_hidden.setValue(128)
        opt_f.addRow("Unités cachées (MLP)", self.mlp_hidden)

        self.mlp_epochs = QtWidgets.QSpinBox(self)
        self.mlp_epochs.setRange(5, 200)
        self.mlp_epochs.setSingleStep(5)
        try:
            self.mlp_epochs.setValue(int(getattr(self.parent_app, 'settings', {}).get('ai_train_mlp_epochs', 30)))
        except Exception:
            self.mlp_epochs.setValue(30)
        opt_f.addRow("Époques (MLP)", self.mlp_epochs)
        root.addWidget(opt_gb)

        # Status + progress
        self.status = QtWidgets.QLabel("En attente…", self)
        root.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar(self)
        root.addWidget(self.progress)

        # Results pane
        res_gb = QtWidgets.QGroupBox("Résultats", self)
        res_l = QtWidgets.QVBoxLayout(res_gb)
        self.res_grid = QtWidgets.QFormLayout()
        self.lbl_counts = QtWidgets.QLabel("—", self)
        self.lbl_vocab = QtWidgets.QLabel("—", self)
        self.lbl_top_tokens = QtWidgets.QLabel("—", self)
        self.lbl_top_mods = QtWidgets.QLabel("—", self)
        self.lbl_metrics = QtWidgets.QLabel("—", self)
        for w in (self.lbl_counts, self.lbl_vocab, self.lbl_top_tokens, self.lbl_top_mods, self.lbl_metrics):
            try:
                w.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)  # type: ignore
            except Exception:
                pass
        self.res_grid.addRow("Taille (mods/logs/index)", self.lbl_counts)
        self.res_grid.addRow("Vocabulaire (tokens)", self.lbl_vocab)
        self.res_grid.addRow("Top tokens", self.lbl_top_tokens)
        self.res_grid.addRow("Top mods", self.lbl_top_mods)
        self.res_grid.addRow("Métriques classifieur", self.lbl_metrics)
        res_l.addLayout(self.res_grid)
        self.log = QtWidgets.QPlainTextEdit(self)
        self.log.setReadOnly(True)
        res_l.addWidget(self.log, 1)
        row_exp = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Exporter résumé…", self)
        self.btn_export.clicked.connect(self._export_summary)
        row_exp.addStretch(1)
        row_exp.addWidget(self.btn_export)
        res_l.addLayout(row_exp)
        root.addWidget(res_gb, 1)

        # Controls
        row = QtWidgets.QHBoxLayout()
        self.check_btn = QtWidgets.QPushButton("Vérifier modèle", self)
        self.check_btn.clicked.connect(self._check_model_integrity)
        row.addWidget(self.check_btn)
        btn = QtWidgets.QPushButton("Démarrer", self)
        btn.clicked.connect(self._start)
        row.addWidget(btn)
        self.cancel_btn = QtWidgets.QPushButton("Annuler", self)
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.cancel_btn)
        root.addLayout(row)

        try:
            QtWidgets.QMessageBox.information(self, "Entrainement A.I.", "L'entraînement construit un modèle simple à partir des noms de fichiers, logs et index public pour suggérer un mod probable.")
        except Exception:
            pass
        self._cancel_requested = False
        self._finished = False

        # Logging/verbosity setup based on Configuration > log_level
        try:
            configured = getattr(self.parent_app, 'settings', {}).get('log_level', 'DEBUG')
        except Exception:
            configured = 'DEBUG'
        try:
            self._log_threshold = int(_normalize_log_level(configured))
        except Exception:
            self._log_threshold = logging.DEBUG
        self._logger = logging.getLogger("Sims4ModTool.AI.Training")

    def _browse_src(self):
        base = self.path_edit.text() or os.getcwd()
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choisir un dossier", base)
        if d:
            self.path_edit.setText(d)

    def _load_updates_index(self, settings):
        default_csv = (
            "https://docs.google.com/spreadsheets/d/e/"
            "2PACX-1vRexBc8fcYyfsjbGRo3sH18jj9DuwKH8J7_SvQvpK_fvjsnILKRz1xGOwYz-xtG0wIKQcs1eDN1yw9V/"
            "pub?gid=119778444" + "&" + "single=true" + "&" + "range=A:I" + "&" + "output=csv"
        )
        csv_url = str(settings.get('updates_checker_csv_url', default_csv))
        entries = []
        try:
            req = urllib.request.Request(csv_url, headers={"User-Agent": "Sims4ModTool/3.40"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                text = resp.read().decode('utf-8', errors='ignore')
            buf = io.StringIO(text)
            reader = _csv.reader(buf)
            for row in reader:
                if not row or len(row) < 4:
                    continue
                if row[0] and not str(row[0]).strip().isdigit() and len(row) > 1 and str(row[1]).lower().startswith('name'):
                    continue
                name = (row[1] or '').strip()
                if not name:
                    continue
                creator = (row[2] or '').strip() if len(row) > 2 else ''
                link = (row[3] or '').strip() if len(row) > 3 else ''
                status = (row[4] or '').strip() if len(row) > 4 else ''
                date_pretty = (row[5] or '').strip() if len(row) > 5 else ''
                date_iso = (row[6] or '').strip() if len(row) > 6 else ''
                entries.append({'title': name, 'creator': creator, 'url': link, 'status': status, 'date': (date_iso or date_pretty)})
        except Exception:
            entries = []
        return entries

    def _start(self):
        if self._finished:
            self.accept()
            return
        self._vlog(logging.INFO, "Démarrage de l'entraînement IA…")
        self._persist_options()
        # Ensure model
        if getattr(self.parent_app, 'mod_ai', None) is None:
            self.parent_app.mod_ai = ModAI.load(str(self.parent_app.settings.get("ai_model_path", "mod_ai.json")))

        mod_dir = str(self.path_edit.text() or getattr(self.parent_app, 'settings', {}).get('mod_directory', '') or '')
        if not (mod_dir and os.path.isdir(mod_dir)):
            QtWidgets.QMessageBox.information(self, "Dossier invalide", "Configure un dossier de mods valide dans la Configuration.")
            self._vlog(logging.WARNING, "Arrêt: dossier des mods invalide.")
            return

        version_releases = getattr(self.parent_app, 'version_releases', {})
        base_settings = dict(getattr(self.parent_app, 'settings', {}))
        base_settings["enable_version_filters"] = False
        base_settings["file_filter_mode"] = "both"
        base_settings["show_ignored"] = True
        base_settings["hide_installer_mods"] = False
        base_settings["show_disabled_only"] = False

        try:
            rows, _ = generate_data_rows(mod_dir, base_settings, version_releases, recursive=True)
        except Exception:
            rows = []
        self._vlog(logging.INFO, f"Mods (rows): {len(rows)} éléments collectés.")

        # Logs learning
        exts = {".log", ".txt", ".html", ".htm"}
        exts.update(set(base_settings.get("log_extra_extensions", []) or []))
        log_results: List[Dict[str, object]] = []
        try:
            if self.chk_use_logs.isChecked():
                self._vlog(logging.INFO, "Analyse des journaux (logs/txt/html)…")
                for rootd, _dirs, files in os.walk(mod_dir):
                    for fn in files:
                        lf = fn.lower()
                        if os.path.splitext(lf)[1] in exts:
                            path = os.path.join(rootd, fn)
                            try:
                                content = open(path, "r", encoding="utf-8", errors="replace").read()
                            except Exception:
                                continue
                            if lf.endswith(".html") or lf.endswith(".htm"):
                                parsed = analyze_last_exception_html(content)
                                res = list(parsed.get("results") or [])
                                text = _strip_html_to_text(content)
                                res += analyze_generic_log_text(text)
                            else:
                                res = analyze_generic_log_text(content)
                            seen = set((it.get('type'), it.get('message'), (it.get('paths') or [None])[0]) for it in log_results)
                            for it in res:
                                key = (it.get('type'), it.get('message'), (it.get('paths') or [None])[0])
                                if key not in seen:
                                    log_results.append(it)
                                    seen.add(key)
        except Exception:
            pass
        self._vlog(logging.INFO, f"Journaux: {len(log_results)} entrées uniques.")

        # CSV index
        index_entries = self._load_updates_index(base_settings) if self.chk_use_index.isChecked() else []
        self._vlog(logging.INFO, f"Index Updates Checker: {len(index_entries)} entrées.")

        total_items = len(rows) if self.chk_use_rows.isChecked() else 0
        total_logs = len(log_results)
        total_index = len(index_entries)
        engine_key = str(self.engine.currentData() or "basic")
        ml_selected = (not self._cancel_requested and _SKLEARN_OK and engine_key in {"tfidf", "mlp"})
        engine_label = {"tfidf": "TF‑IDF", "mlp": "MLP"}.get(engine_key, "")
        suffix = f" + {engine_label}" if ml_selected and engine_label else ""
        ml_units = 100 if ml_selected else 0
        self.status.setText(
            f"Entraînement: {total_items} éléments (mods) + {total_logs} éléments (logs) + {total_index} éléments (index){suffix}…"
        )
        grand_total = total_items + total_logs + total_index + ml_units
        self.progress.setRange(0, max(1, grand_total))
        step = int(self.batch.value())
        processed = 0

        # Train from rows
        if self.chk_use_rows.isChecked():
            self._vlog(logging.INFO, "Apprentissage (tokens) depuis les mods…")
            while processed < total_items:
                chunk = rows[processed:processed+step]
                self.parent_app.mod_ai.update_from_rows(chunk)
                processed += len(chunk)
                self.progress.setValue(min(processed, total_items + total_logs + total_index))
                QtWidgets.QApplication.processEvents()
                if self._cancel_requested:
                    break
                self._vlog_chunk(logging.DEBUG, processed, total_items + total_logs + total_index, phase="mods")

        # Train from logs
        if not self._cancel_requested and total_logs:
            start = 0
            while start < total_logs:
                chunk = log_results[start:start+step]
                self.parent_app.mod_ai.update_from_log_results(chunk)
                start += len(chunk)
                processed = total_items + start
                self.progress.setValue(min(processed, total_items + total_logs + total_index))
                QtWidgets.QApplication.processEvents()
                if self._cancel_requested:
                    break
                self._vlog_chunk(logging.DEBUG, processed, total_items + total_logs + total_index, phase="logs")

        # Train from index
        if not self._cancel_requested and total_index:
            start = 0
            while start < total_index:
                chunk = index_entries[start:start+step]
                # ensure ModAI has this helper (added in main)
                if hasattr(self.parent_app.mod_ai, 'update_from_index_entries'):
                    self.parent_app.mod_ai.update_from_index_entries(chunk)
                start += len(chunk)
                processed = total_items + total_logs + start
                self.progress.setValue(min(processed, total_items + total_logs + total_index))
                QtWidgets.QApplication.processEvents()
                if self._cancel_requested:
                    break
                self._vlog_chunk(logging.DEBUG, processed, total_items + total_logs + total_index, phase="index")

        # Optional: train ML classifier (TF‑IDF / MLP) if selected and available
        clf_metrics = "—"
        ml_success = True
        if ml_selected:
            clf_metrics, ml_success = self._train_ml_engine(
                engine_key,
                rows if self.chk_use_rows.isChecked() else [],
                log_results,
                index_entries,
                total_items,
                total_logs,
                total_index,
                grand_total,
            )

        # Save model + summary
        try:
            engine_used = engine_key if ml_selected else "tokens"
            meta = self.parent_app.mod_ai.data.setdefault("metadata", {})
            meta.update({
                "trained_at": datetime.utcnow().isoformat(),
                "engine": engine_used,
                "mods_trained": int(total_items),
                "logs_trained": int(total_logs),
                "index_trained": int(total_index),
                "last_metrics": clf_metrics,
                "needs_training": False if (not ml_selected or ml_success) else True,
            })
            if ml_selected and not ml_success:
                meta['needs_training'] = True
            if self._cancel_requested:
                meta['needs_training'] = True
                meta['status'] = 'interrupted'
            else:
                meta['status'] = 'ok' if not meta.get('needs_training') else 'invalid'
        except Exception:
            pass
        self.parent_app.mod_ai.save(str(self.parent_app.settings.get("ai_model_path", "mod_ai.json")))
        self._vlog(logging.INFO, "Modèle de tokens sauvegardé (JSON).")
        try:
            data = dict(getattr(self.parent_app.mod_ai, 'data', {}) or {})
            mods = data.get('mods', {}) or {}
            token_to_mod = data.get('token_to_mod', {}) or {}
            token_scores = [(tok, sum(d.values())) for tok, d in token_to_mod.items()]
            token_scores.sort(key=lambda kv: kv[1], reverse=True)
            top_tokens = ", ".join(f"{t}:{c}" for t, c in token_scores[:10]) if token_scores else "—"
            mod_scores = []
            for name, meta in mods.items():
                cnt = sum((meta.get('tokens') or {}).values())
                mod_scores.append((name, cnt))
            mod_scores.sort(key=lambda kv: kv[1], reverse=True)
            top_mods = ", ".join(f"{m}:{c}" for m, c in mod_scores[:10]) if mod_scores else "—"
            lines = [
                f"Apprentissage {'interrompu' if self._cancel_requested else 'terminé'}.",
                f"Mods: {total_items} • Logs: {total_logs} • Index: {total_index}",
                f"Mods connus: {len(mods)} • Tokens: {len(token_to_mod)}",
                f"Top tokens: {top_tokens}",
                f"Top mods: {top_mods}",
            ]
            self.log.appendPlainText("\n".join(lines))

            # Update result labels
            self.lbl_counts.setText(f"{total_items} / {total_logs} / {total_index}")
            self.lbl_vocab.setText(str(len(token_to_mod)))
            self.lbl_top_tokens.setText(top_tokens)
            self.lbl_top_mods.setText(top_mods)
            self.lbl_metrics.setText(clf_metrics)
        except Exception:
            pass

        # Finish state: turn cancel into close
        try:
            self._finished = True
            self.cancel_btn.setText("Terminer")
            try:
                self.cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.cancel_btn.clicked.connect(self.accept)
        except Exception:
            pass

        if hasattr(self.parent_app, '_update_ai_mode_label'):
            try:
                self.parent_app._update_ai_mode_label()
            except Exception:
                pass

    def _persist_options(self):
        try:
            s = getattr(self.parent_app, 'settings', None)
            if not isinstance(s, dict):
                return
            s['ai_train_use_rows'] = bool(self.chk_use_rows.isChecked())
            s['ai_train_use_logs'] = bool(self.chk_use_logs.isChecked())
            s['ai_train_use_index'] = bool(self.chk_use_index.isChecked())
            s['ai_train_engine'] = str(self.engine.currentData() or 'basic')
            try:
                s['ai_train_val_split'] = float(self.val_split.value())
            except Exception:
                s['ai_train_val_split'] = 0.2
            try:
                s['ai_train_max_features'] = int(self.max_features.value())
            except Exception:
                s['ai_train_max_features'] = 50000
            s['ai_train_ngram'] = str(self.ngram.currentText() or '1-2')
            try:
                s['ai_train_batch'] = int(self.batch.value())
            except Exception:
                s['ai_train_batch'] = 500
            try:
                s['ai_train_min_samples'] = int(self.min_class_samples.value())
            except Exception:
                s['ai_train_min_samples'] = 2
            s['ai_train_rare_strategy'] = str(self.rare_strategy.currentData() or 'drop')
            s['ai_train_class_weight_balanced'] = bool(self.class_weight_balanced.isChecked())
            try:
                s['ai_train_cv_folds'] = int(self.cv_folds.value())
            except Exception:
                s['ai_train_cv_folds'] = 0
            try:
                s['ai_train_mlp_hidden'] = int(self.mlp_hidden.value())
            except Exception:
                s['ai_train_mlp_hidden'] = 128
            try:
                s['ai_train_mlp_epochs'] = int(self.mlp_epochs.value())
            except Exception:
                s['ai_train_mlp_epochs'] = 30
            save_settings(s)
        except Exception:
            pass

    def _cancel(self):
        self._cancel_requested = True

    def _build_corpus(self, rows: List[Dict[str, object]], log_results: List[Dict[str, object]], index_entries: List[Dict[str, object]]) -> Tuple[List[str], List[str]]:
        X: List[str] = []
        y: List[str] = []
        # rows → label: group; text: filenames + group
        for row in rows or []:
            label = str(row.get("group") or "").strip()
            if not label:
                continue
            pkg = str(row.get("package") or "").strip()
            sc = str(row.get("script") or "").strip()
            text = " ".join([label, os.path.basename(pkg), os.path.basename(sc)]).strip()
            if text:
                X.append(text)
                y.append(label)
        # logs → label: mod; text: type + message + first path
        for it in log_results or []:
            label = str(it.get("mod") or "").strip()
            if not label:
                continue
            msg = f"{it.get('type') or ''} {it.get('message') or ''}"
            p0 = (it.get("paths") or [""])[0] or ""
            text = " ".join([label, msg, os.path.basename(str(p0))]).strip()
            if text:
                X.append(text)
                y.append(label)
        # index → label: title; text: title + creator
        for ent in index_entries or []:
            label = str(ent.get("title") or "").strip()
            if not label:
                continue
            creator = str(ent.get("creator") or "").strip()
            text = (label + (" " + creator if creator else "")).strip()
            if text:
                X.append(text)
                y.append(label)
        return X, y

    def _export_summary(self):
        # Simple export of text box + key labels
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Exporter le résumé", "ai_training_summary.txt", "Text (*.txt)")
        if not path:
            return
        try:
            lines = []
            lines.append(f"{self.lbl_counts.text()}")
            lines.append(f"Vocab: {self.lbl_vocab.text()}")
            lines.append(f"Top tokens: {self.lbl_top_tokens.text()}")
            lines.append(f"Top mods: {self.lbl_top_mods.text()}")
            lines.append(f"Métriques: {self.lbl_metrics.text()}")
            lines.append("")
            lines.append(self.log.toPlainText())
            with open(path, "w", encoding="utf-8", errors="replace") as f:
                f.write("\n".join(lines))
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Export", "Impossible d'exporter le résumé.")

    def _check_model_integrity(self):
        settings = getattr(self.parent_app, 'settings', {}) if hasattr(self.parent_app, 'settings') else {}
        model_path = str(settings.get('ai_model_path', 'mod_ai.json') or 'mod_ai.json')
        issues = []
        ok = True
        ai_instance = None
        if not os.path.isfile(model_path):
            issues.append(f"Fichier absent: {model_path}")
            ok = False
        else:
            try:
                ai_instance = ModAI.load(model_path)
            except Exception as exc:
                issues.append(f"Chargement JSON impossible: {exc}")
                ok = False

        joblib_missing = False
        if ai_instance is not None:
            data = ai_instance.data or {}
            metadata = data.setdefault('metadata', {})
            ml_data = data.get('ml', {}) or {}
            engine = metadata.get('engine') or ml_data.get('last_engine') or 'tokens'
            tokens_map = data.get('token_to_mod', {}) or {}
            if not tokens_map:
                issues.append("Aucun token appris (modèle vide)")
                ok = False
            if engine == 'tfidf':
                tfidf_path = str(ml_data.get('tfidf_model_path') or '').strip()
                if not tfidf_path or not os.path.isfile(tfidf_path):
                    issues.append("Fichier TF‑IDF (.joblib) introuvable")
                    joblib_missing = True
            elif engine == 'mlp':
                mlp_path = str(ml_data.get('mlp_model_path') or '').strip()
                if not mlp_path or not os.path.isfile(mlp_path):
                    issues.append("Fichier MLP (.joblib) introuvable")
                    joblib_missing = True

            metadata['checked_at'] = datetime.utcnow().isoformat()
            metadata['needs_training'] = bool(joblib_missing or not ok)
            metadata.setdefault('engine', engine)
            metadata['status'] = 'ok' if not metadata['needs_training'] else 'invalid'
            try:
                ai_instance.save(model_path)
            except Exception:
                pass
            try:
                self.parent_app.mod_ai = ai_instance
            except Exception:
                pass
            if metadata['needs_training'] and engine in {'tfidf', 'mlp'}:
                ok = False
            if joblib_missing:
                ok = False

        message = "Modèle IA valide." if ok else "Anomalies détectées:\n- " + "\n- ".join(issues or ["Entraînement recommandé"])
        level = logging.INFO if ok else logging.WARNING
        self._vlog(level, message)
        msg_func = QtWidgets.QMessageBox.information if ok else QtWidgets.QMessageBox.warning
        msg_func(
            self,
            "Vérification modèle" if ok else "Vérification modèle — anomalies",
            message,
        )
        if hasattr(self.parent_app, '_update_ai_mode_label'):
            try:
                self.parent_app._update_ai_mode_label()
            except Exception:
                pass

    # Verbose log helpers
    def _vlog(self, level_no: int, message: str):
        try:
            self._logger.log(level_no, message)
        except Exception:
            pass
        try:
            if int(level_no) >= int(self._log_threshold):
                ts = datetime.now().strftime('%H:%M:%S')
                self.log.appendPlainText(f"[{ts}] {message}")
        except Exception:
            pass

    def _vlog_chunk(self, level_no: int, processed: int, total: int, *, phase: str):
        try:
            if int(level_no) < int(self._log_threshold):
                return
            # Only emit every ~3 UI updates to reduce noise
            if processed % max(1, int(self.batch.value())) == 0:
                pct = 0 if total <= 0 else int((processed / total) * 100)
                self._vlog(level_no, f"Progression {phase}: {processed}/{total} ({pct}%)")
        except Exception:
            pass

    def _adjust_training_samples(self, texts: List[str], labels: List[str]):
        if not texts or not labels or len(texts) != len(labels):
            return texts, labels, {"dropped": 0, "merged": 0, "initial_classes": 0, "final_classes": 0}
        min_samples = max(1, int(self.min_class_samples.value()))
        strategy = str(self.rare_strategy.currentData() or "drop")
        counts = Counter(labels)
        kept_texts: List[str] = []
        kept_labels: List[str] = []
        rare_buffer: List[Tuple[str, str]] = []
        dropped = 0
        for text, label in zip(texts, labels):
            if counts[label] >= min_samples:
                kept_texts.append(text)
                kept_labels.append(label)
            else:
                if strategy == "merge":
                    rare_buffer.append((text, label))
                else:
                    dropped += 1
        merged = 0
        if strategy == "merge" and rare_buffer:
            if len(rare_buffer) >= min_samples:
                for text, _label in rare_buffer:
                    kept_texts.append(text)
                    kept_labels.append("__rare__")
                merged = len(rare_buffer)
            else:
                dropped += len(rare_buffer)
        summary = {
            "dropped": dropped,
            "merged": merged,
            "initial_classes": len(counts),
            "final_classes": len(set(kept_labels)),
            "min_samples": min_samples,
            "strategy": strategy,
        }
        return kept_texts, kept_labels, summary

    def _train_ml_engine(
        self,
        engine_key: str,
        rows: List[Dict[str, object]],
        log_results: List[Dict[str, object]],
        index_entries: List[Dict[str, object]],
        total_items: int,
        total_logs: int,
        total_index: int,
        grand_total: int,
    ) -> Tuple[str, bool]:
        engine_label = "TF‑IDF" if engine_key == "tfidf" else "MLP"
        try:
            self._vlog(logging.INFO, f"Apprentissage classifieur {engine_label}…")
            X_raw, y_raw = self._build_corpus(rows, log_results, index_entries)
            self._vlog(logging.DEBUG, f"Corpus brut: {len(X_raw)} échantillons, {len(set(y_raw))} classes.")
            if len(X_raw) < 10 or len(set(y_raw)) < 2:
                msg = "Jeu de données insuffisant pour un classifieur (≥2 classes et ≥10 échantillons requis)."
                self._vlog(logging.WARNING, msg)
                self.progress.setValue(grand_total)
                QtWidgets.QApplication.processEvents()
                return msg, False

            X_texts, y_labels, rare_summary = self._adjust_training_samples(X_raw, y_raw)
            self._vlog(logging.INFO, (
                "Classes ajustées: initiales=%d, finales=%d, supprimées=%d, fusionnées=%d (min=%d, stratégie=%s)"
            ) % (
                rare_summary.get('initial_classes', 0),
                rare_summary.get('final_classes', 0),
                rare_summary.get('dropped', 0),
                rare_summary.get('merged', 0),
                rare_summary.get('min_samples', 0),
                rare_summary.get('strategy', 'drop'),
            ))
            self._vlog(logging.DEBUG, f"Corpus ajusté: {len(X_texts)} échantillons, {len(set(y_labels))} classes.")
            if len(X_texts) < 10 or len(set(y_labels)) < 2:
                msg = "Données ajustées insuffisantes après traitement des classes rares."
                self._vlog(logging.WARNING, msg)
                self.progress.setValue(grand_total)
                QtWidgets.QApplication.processEvents()
                return msg, False

            class_counts = Counter(y_labels)
            ngram_text = self.ngram.currentText()
            ngram = (1, int(ngram_text.split("-")[1])) if "-" in ngram_text else (1, 1)
            max_features = int(self.max_features.value())
            metrics_parts = [
                f"classes={len(set(y_labels))}",
                f"samples={len(X_texts)}",
            ]
            if rare_summary.get('dropped', 0):
                metrics_parts.append(f"dropped={rare_summary['dropped']}")
            if rare_summary.get('merged', 0):
                metrics_parts.append(f"merged={rare_summary['merged']}")

            cv_note = ""
            pipe = None
            class_weight = None
            hidden = int(self.mlp_hidden.value())
            epochs = int(self.mlp_epochs.value())

            if engine_key == "tfidf":
                class_weight = 'balanced' if self.class_weight_balanced.isChecked() else None
                vec = TfidfVectorizer(
                    lowercase=True,
                    token_pattern=r"[A-Za-z0-9_\-]{2,}",
                    max_features=max_features,
                    ngram_range=ngram,
                )
                clf = LinearSVC(class_weight=class_weight)
                pipe = Pipeline([( "vec", vec), ("clf", clf)])
                if class_weight:
                    metrics_parts.append("cw=balanced")
            else:
                # Limit features for neural network to control memory usage
                max_feat = min(max_features, 15000)
                vec = TfidfVectorizer(
                    lowercase=True,
                    token_pattern=r"[A-Za-z0-9_\-]{2,}",
                    max_features=max_feat,
                    ngram_range=ngram,
                )
                components = max(16, min(256, max_feat - 1 if max_feat > 1 else 16))
                svd = TruncatedSVD(n_components=components, random_state=42)
                scaler = StandardScaler()
                clf = MLPClassifier(
                    hidden_layer_sizes=(hidden,),
                    max_iter=epochs,
                    random_state=42,
                    learning_rate="adaptive",
                    batch_size=256,
                )
                pipe = Pipeline([( "vec", vec), ("svd", svd), ("scaler", scaler), ("clf", clf)])
                metrics_parts.extend([f"hidden={hidden}", f"epochs={epochs}", f"svd={components}"])

            # Pre-fit progress tick
            self.progress.setValue(total_items + total_logs + total_index + 10)
            QtWidgets.QApplication.processEvents()

            cv_folds = int(self.cv_folds.value())
            if cv_folds >= 2:
                if len(set(y_labels)) >= cv_folds and min(class_counts.values()) >= cv_folds:
                    try:
                        self.progress.setValue(total_items + total_logs + total_index + 25)
                        QtWidgets.QApplication.processEvents()
                        skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
                        scores = cross_val_score(pipe, X_texts, y_labels, cv=skf, scoring='f1_macro')
                        cv_mean = float(scores.mean())
                        cv_std = float(scores.std())
                        cv_note = f"CV F1={cv_mean:.3f}±{cv_std:.3f} (k={cv_folds})"
                        metrics_parts.append(cv_note)
                        self._vlog(logging.INFO, f"Validation croisée: F1_macro={cv_mean:.3f} (±{cv_std:.3f}) sur {cv_folds} folds")
                    except Exception as exc:
                        self._vlog(logging.WARNING, f"Validation croisée ignorée (erreur): {exc}")
                else:
                    self._vlog(logging.WARNING, "Validation croisée ignorée: classes insuffisantes pour k-folds.")

            val = float(self.val_split.value())
            use_val = val > 0.0 and val < 0.9
            if use_val and min(class_counts.values()) < 2:
                use_val = False
                val_note = " (validation désactivée: classes rares)"
                self._vlog(logging.WARNING, "Validation désactivée: certaines classes sont trop rares (<2).")
            else:
                val_note = ""

            fitted_full = False
            if use_val:
                try:
                    X_train, X_val, y_train, y_val = train_test_split(
                        X_texts,
                        y_labels,
                        test_size=val,
                        random_state=42,
                        stratify=y_labels if len(set(y_labels)) > 1 else None,
                    )
                    QtWidgets.QApplication.processEvents()
                    pipe.fit(X_train, y_train)
                    self.progress.setValue(total_items + total_logs + total_index + 80)
                    QtWidgets.QApplication.processEvents()
                    y_pred = pipe.predict(X_val)
                    acc = accuracy_score(y_val, y_pred)
                    f1 = f1_score(y_val, y_pred, average="macro")
                    metrics_parts.append(f"val={len(X_val)}")
                    metrics_parts.append(f"acc={acc:.3f}")
                    metrics_parts.append(f"F1={f1:.3f}")
                    metrics_parts.append(f"train_split={len(X_train)}")
                    self._vlog(logging.INFO, f"{engine_label}: acc={acc:.3f}, F1={f1:.3f} ({len(X_train)} train / {len(X_val)} val)")
                except Exception as exc:
                    pipe.fit(X_texts, y_labels)
                    self.progress.setValue(total_items + total_logs + total_index + 80)
                    QtWidgets.QApplication.processEvents()
                    metrics_parts.append(f"train={len(X_texts)}")
                    metrics_parts.append("fallback sans validation")
                    self._vlog(logging.WARNING, f"Validation impossible, entraînement sur la totalité. Détail: {exc}")
                    fitted_full = True
            else:
                pipe.fit(X_texts, y_labels)
                self.progress.setValue(total_items + total_logs + total_index + 80)
                QtWidgets.QApplication.processEvents()
                metrics_parts.append(f"train={len(X_texts)}{val_note}")
                self._vlog(logging.INFO, f"{engine_label}: entraînement complet ({len(X_texts)} échantillons){val_note}")
                fitted_full = True

            # Re-fit sur l'ensemble complet pour sauvegarde fiable
            if not fitted_full:
                try:
                    pipe.fit(X_texts, y_labels)
                except Exception:
                    pass
            self.progress.setValue(total_items + total_logs + total_index + 90)
            QtWidgets.QApplication.processEvents()

            base = str(self.parent_app.settings.get("ai_model_path", "mod_ai.json"))
            suffix = "_tfidf.joblib" if engine_key == "tfidf" else "_mlp.joblib"
            model_path = os.path.splitext(base)[0] + suffix
            joblib.dump(pipe, model_path)
            self._vlog(logging.INFO, f"Modèle {engine_label} sauvegardé: {model_path}")
            self.progress.setValue(total_items + total_logs + total_index + 95)
            QtWidgets.QApplication.processEvents()

            if getattr(self.parent_app, 'mod_ai', None) is not None:
                try:
                    ml_data = self.parent_app.mod_ai.data.setdefault("ml", {})
                    ml_data["last_engine"] = engine_key
                    ml_data["last_trained"] = datetime.utcnow().isoformat()
                    if engine_key == "tfidf":
                        ml_data["tfidf_model_path"] = model_path
                        ml_data["tfidf_params"] = {
                            "max_features": max_features,
                            "ngram_range": ngram,
                            "val_split": float(self.val_split.value()),
                            "class_weight": class_weight or "none",
                            "cv_note": cv_note,
                            "min_class_samples": int(self.min_class_samples.value()),
                            "rare_strategy": str(self.rare_strategy.currentData() or 'drop'),
                        }
                        self.parent_app.mod_ai._tfidf_model = None
                        if hasattr(self.parent_app.mod_ai, "_tfidf_loaded_path"):
                            self.parent_app.mod_ai._tfidf_loaded_path = None
                    else:
                        ml_data["mlp_model_path"] = model_path
                        ml_data["mlp_params"] = {
                            "max_features": max_feat,
                            "ngram_range": ngram,
                            "svd_components": components,
                            "hidden_units": hidden,
                            "epochs": epochs,
                            "min_class_samples": int(self.min_class_samples.value()),
                            "rare_strategy": str(self.rare_strategy.currentData() or 'drop'),
                            "cv_note": cv_note,
                        }
                        if hasattr(self.parent_app.mod_ai, '_mlp_model'):
                            self.parent_app.mod_ai._mlp_model = None
                        if hasattr(self.parent_app.mod_ai, '_mlp_loaded_path'):
                            self.parent_app.mod_ai._mlp_loaded_path = None
                except Exception:
                    pass

            # Ensure progress reaches 100%
            self.progress.setValue(grand_total)
            QtWidgets.QApplication.processEvents()
            return " • ".join(metrics_parts), True
        except Exception as exc:
            msg = f"{engine_label}: erreur {exc}"
            self._vlog(logging.ERROR, msg)
            self.progress.setValue(grand_total)
            QtWidgets.QApplication.processEvents()
            return msg, False
