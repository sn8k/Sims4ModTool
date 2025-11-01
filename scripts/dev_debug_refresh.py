import os
import sys
import time
import tempfile
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5 import QtWidgets  # type: ignore
import main as appmod


def touch(p, days):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(b'test')
    dt = datetime.now() - timedelta(days=days)
    ts = dt.timestamp()
    os.utime(p, (ts, ts))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        mods = os.path.join(tmp, 'Mods')
        os.makedirs(mods, exist_ok=True)
        touch(os.path.join(mods, 'ModA.package'), 5)
        touch(os.path.join(mods, 'ModA.ts4script'), 4)
        touch(os.path.join(mods, 'ScriptOnly.ts4script'), 3)

        s = appmod.load_settings()
        s['mod_directory'] = mods
        s['enable_version_filters'] = False
        s['file_filter_mode'] = 'both'
        s['show_ignored'] = True
        s['auto_scan_on_start'] = False
        appmod.save_settings(s)

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        win = appmod.ModManagerApp(splash=None)
        win.settings['mod_directory'] = mods
        win.update_mod_directory_label()
        win.refresh_tree()

        deadline = time.time() + 10
        while time.time() < deadline:
            app.processEvents()
            t = getattr(win, '_scan_thread', None)
            if t is not None and not t.is_alive():
                break
            time.sleep(0.05)
        for _ in range(10):
            app.processEvents(); time.sleep(0.01)

        rc = win.table.rowCount()
        print('ROW_COUNT', rc)
        pkgs = [win.table.item(r,2).text() if win.table.item(r,2) else '' for r in range(min(rc, 30))]
        scrs = [win.table.item(r,4).text() if win.table.item(r,4) else '' for r in range(min(rc, 30))]
        print('PKG_HEAD', pkgs)
        print('SCR_HEAD', scrs)


if __name__ == '__main__':
    main()

