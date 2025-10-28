import os, sys, json
try:
    from PyQt5 import QtWidgets
except Exception:
    try:
        from PySide2 import QtWidgets
    except Exception:
        from PySide6 import QtWidgets
import main
app = QtWidgets.QApplication([])
# Toggle AI in settings
settings = main.load_settings()
settings['ai_enabled'] = True
settings['ai_auto_train'] = True
main.save_settings(settings)
w = main.ModManagerApp(splash=None)
print('AI loaded:', bool(getattr(w, 'mod_ai', None)))
# Analyze sample log
path = os.path.abspath('mc_lastexception.html')
print('Log path exists:', os.path.exists(path))
dlg = main.LogManagerDialog(w, path)
dlg._open_current()
dlg._analyze()
rows = dlg.analysis.rowCount()
cols = dlg.analysis.columnCount()
print('Analysis rows:', rows, 'cols:', cols)
for r in range(min(3, rows)):
    vals = []
    for c in range(cols):
        it = dlg.analysis.item(r, c)
        vals.append(it.text() if it else '')
    print('ROW', r+1, '|'.join(vals))
app.quit()
