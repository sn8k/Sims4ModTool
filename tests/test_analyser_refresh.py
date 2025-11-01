import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

# Ensure we can import from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # type: ignore

import main as appmod


def _touch(path, age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"test")
    if age_days:
        dt = datetime.now() - timedelta(days=age_days)
        ts = dt.timestamp()
        os.utime(path, (ts, ts))


def test_analyser_refresh_populates_table():
    # Build a fake Mods directory with one pair and one script-only
    with tempfile.TemporaryDirectory() as tmp:
        mods = os.path.join(tmp, "Mods")
        os.makedirs(mods, exist_ok=True)
        _touch(os.path.join(mods, "ModA.package"), age_days=5)
        _touch(os.path.join(mods, "ModA.ts4script"), age_days=4)
        _touch(os.path.join(mods, "ScriptOnly.ts4script"), age_days=3)

        # Minimal settings to avoid filtering everything out
        settings = appmod.load_settings()
        settings["mod_directory"] = mods
        settings["enable_version_filters"] = False
        settings["file_filter_mode"] = "both"
        settings["show_ignored"] = True
        settings["auto_scan_on_start"] = False
        appmod.save_settings(settings)

        # Start Qt app headless
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        win = appmod.ModManagerApp(splash=None)

        # Ensure it picks our directory and runs a refresh
        win.settings["mod_directory"] = mods
        win.update_mod_directory_label()
        win.refresh_tree()

        # Pump events until scan thread finishes or timeout
        deadline = time.time() + 10.0
        while time.time() < deadline:
            app.processEvents()
            t = getattr(win, "_scan_thread", None)
            if t is not None and not t.is_alive():
                break
            time.sleep(0.05)
        # Final events drain
        for _ in range(10):
            app.processEvents()
            time.sleep(0.01)

        # Validate rows rendered in the main table
        row_count = win.table.rowCount()
        assert row_count >= 2, f"Expected at least 2 rows (pair + script-only), got {row_count}"

        # Check statuses present; filenames may differ if cache is applied first
        statuses = [win.table.item(r, 0).text() for r in range(row_count)]
        assert any(s == "X" for s in statuses), "Missing paired status 'X'"
        assert any(s == "MP" for s in statuses), "Missing script-only status 'MP'"


def test_generate_data_rows_produces_expected_names():
    with tempfile.TemporaryDirectory() as tmp:
        mods = os.path.join(tmp, "Mods")
        os.makedirs(mods, exist_ok=True)
        _touch(os.path.join(mods, "ModA.package"), age_days=5)
        _touch(os.path.join(mods, "ModA.ts4script"), age_days=4)
        _touch(os.path.join(mods, "ScriptOnly.ts4script"), age_days=3)

        settings = {
            "enable_version_filters": False,
            "file_filter_mode": "both",
            "show_ignored": True,
        }
        vr = appmod.merge_version_releases(appmod.load_custom_version_releases())
        rows, changed = appmod.generate_data_rows(mods, settings, vr)
        assert len(rows) >= 2
        pkgs = [r.get("package") for r in rows]
        scrs = [r.get("script") for r in rows]
        assert "ModA.package" in pkgs
        assert "ScriptOnly.ts4script" in scrs
