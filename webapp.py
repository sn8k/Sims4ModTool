import os
import io
import shutil
import tempfile
from datetime import datetime
from typing import List

from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, jsonify
import sys
import json

from main import (
    load_settings,
    save_settings,
    load_custom_version_releases,
    merge_version_releases,
    scan_directory,
    generate_data_rows,
    export_to_excel,
    save_ignore_list,
)

try:
    from mod_root_zip import install_zip as mr_install_zip, install_extracted_dir as mr_install_extracted
except Exception:
    mr_install_zip = None
    mr_install_extracted = None


app = Flask(__name__)
app.secret_key = os.environ.get("S4MT_FLASK_SECRET", "dev-secret-key")


def get_version_releases():
    custom = load_custom_version_releases()
    return merge_version_releases(custom)


def _find_7z_executable():
    candidates = [
        "7z",
        os.path.join(os.environ.get("ProgramFiles", r"C:\\Program Files"), "7-Zip", "7z.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)"), "7-Zip", "7z.exe"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            import subprocess

            completed = subprocess.run([path, "-h"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if completed.returncode == 0 or completed.stdout or completed.stderr:
                return path
        except Exception:
            continue
    return None


def build_rows(settings, *, recursive=True):
    directory = settings.get("mod_directory", "")
    if not directory or not os.path.isdir(directory):
        return []
    version_releases = get_version_releases()
    # Scan directory (collect package and ts4script paths) and compute rows
    _pkgs, _scripts, snapshot = scan_directory(directory, recursive=recursive)
    rows, _changed = generate_data_rows(directory, settings, version_releases, recursive=recursive)
    return rows


INDEX_TEMPLATE = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <title>Sims4ModTool — Web</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">
  <style>
    body { padding: 16px; }
    .inst { background: #2e7d32; color: white; }
    .atf { background: #ffc0cb; color: #000; }
    .small { font-size: 12px; color: #666; }
    thead th { position: sticky; top: 0; background: #f8f9fa; }
    .table-container { overflow:auto; max-height: 70vh; }
  </style>
</head>
<body>
  <nav class="navbar navbar-expand-lg navbar-light bg-light mb-3">
    <div class="container-fluid">
      <a class="navbar-brand" href="#">Sims4ModTool</a>
      <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
        <span class="navbar-toggler-icon"></span>
      </button>
      <div class="collapse navbar-collapse" id="navbarNav">
        <ul class="navbar-nav me-auto mb-2 mb-lg-0">
          <li class="nav-item"><a class="nav-link" href="{{ url_for('export') }}">Export Excel</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('compare_view') }}">Comparateur</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('api_rows') }}">API</a></li>
        </ul>
        <form class="d-flex" onsubmit="event.preventDefault(); reloadRows();">
          <input class="form-control me-2" type="search" placeholder="Recherche" aria-label="Search" id="searchInput">
          <button class="btn btn-outline-success" type="submit">Rechercher</button>
        </form>
      </div>
    </div>
  </nav>

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info" role="alert">
        {% for m in messages %}{{ m }}<br/>{% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="card mb-3">
    <div class="card-body">
      <form class="row g-2" onsubmit="event.preventDefault(); applyFilters();">
        <div class="col-md-4">
          <label class="form-label">Dossier Mods</label>
          <input type="text" class="form-control" id="modDir" value="{{ settings.get('mod_directory','') }}">
        </div>
        <div class="col-md-2">
          <label class="form-label">Mode</label>
          <select class="form-select" id="modeSelect">
            <option value="both">Both</option>
            <option value="package">Package</option>
            <option value="ts4script">TS4Script</option>
            <option value="installer_only">Installer Only</option>
          </select>
        </div>
        <div class="col-md-4 align-self-end">
          <div class="form-check form-check-inline">
            <input class="form-check-input" type="checkbox" id="showIgnored">
            <label class="form-check-label" for="showIgnored">Afficher ignorés</label>
          </div>
          <div class="form-check form-check-inline">
            <input class="form-check-input" type="checkbox" id="hideInstaller">
            <label class="form-check-label" for="hideInstaller">Masquer Mod Installer</label>
          </div>
          <div class="form-check form-check-inline">
            <input class="form-check-input" type="checkbox" id="recursive" checked>
            <label class="form-check-label" for="recursive">Récursif</label>
          </div>
        </div>
        <div class="col-md-2 align-self-end text-end">
          <button type="submit" class="btn btn-primary">Appliquer</button>
        </div>
      </form>
      <hr/>
      <form class="row g-2" method="post" action="{{ url_for('install_upload') }}" enctype="multipart/form-data">
        <div class="col-md-6">
          <input class="form-control" type="file" name="file" accept=".zip,.7z,.rar,.ts4script,.package" required>
        </div>
        <div class="col-md-4">
          <div class="form-check">
            <input class="form-check-input" type="checkbox" name="include_extras" id="includeExtras" {% if settings.get('installer_include_extras') %}checked{% endif %}>
            <label class="form-check-label" for="includeExtras">Inclure extras</label>
          </div>
        </div>
        <div class="col-md-2 text-end">
          <button class="btn btn-success" type="submit">Installer</button>
        </div>
      </form>
    </div>
  </div>

  <div class="dropdown mb-2">
    <button class="btn btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown">Colonnes</button>
    <ul class="dropdown-menu" id="columnsMenu"></ul>
  </div>

  <div class="table-container">
    <table class="table table-sm table-striped" id="modsTable">
      <thead>
        <tr id="modsHead"></tr>
      </thead>
      <tbody id="modsBody"></tbody>
    </table>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>
  <script>
    const COLUMNS = [
      { key: '#', label: '#'},
      { key: 'status', label: 'État'},
      { key: 'group', label: 'Mod (groupe)'},
      { key: 'package', label: 'Fichier .package'},
      { key: 'package_date', label: 'Date .package'},
      { key: 'script', label: 'Fichier .ts4script'},
      { key: 'script_date', label: 'Date .ts4script'},
      { key: 'version', label: 'Version'},
      { key: 'confidence', label: 'Confiance'},
      { key: 'installer', label: 'Installer'},
      { key: 'open', label: 'Ouvrir'},
      { key: 'ignored', label: 'Ignoré'},
      { key: 'actions', label: 'Actions'},
    ];
    let rows = [];
    let hiddenCols = new Set();
    let sortKey = 'status';
    let sortAsc = true;

    function buildHead(){
      const tr = document.getElementById('modsHead');
      tr.innerHTML='';
      COLUMNS.forEach((col, idx)=>{
        if(hiddenCols.has(idx)) return;
        const th = document.createElement('th');
        th.textContent = col.label;
        th.style.cursor = 'pointer';
        th.onclick = ()=>{ if(col.key!=='actions' && col.key!=='open'){ sortKey=col.key; sortAsc = sortKey===col.key ? !sortAsc : true; renderRows(); } };
        tr.appendChild(th);
      });
    }
    function renderRows(){
      const q = (document.getElementById('searchInput').value||'').toLowerCase();
      let data = rows.slice();
      if(q){
        data = data.filter(r=>{
          const vals = [r.status, r.group, r.package, r.package_date, r.script, r.script_date, r.version, r.confidence, r.confidence_tooltip].concat(r.ignore_candidates||[]).concat(r.paths||[]);
          return vals.some(v=> (''+v).toLowerCase().includes(q));
        });
      }
      data.sort((a,b)=>{
        const av = (''+(a[sortKey]||''));
        const bv = (''+(b[sortKey]||''));
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      const tb = document.getElementById('modsBody');
      tb.innerHTML='';
      data.forEach((r, i)=>{
        const tr=document.createElement('tr');
        const vals = [
          i+1,
          r.status||'',
          r.group?`<span class=\"badge inst\">${r.group}</span>`:'',
          r.package||'',
          `<span class=\"small\">${r.package_date||''}</span>`,
          r.script||'',
          `<span class=\"small\">${r.script_date||''}</span>`,
          r.version||'',
          `<span title=\"${(r.confidence_tooltip||'').replaceAll('"','&quot;')}\">${r.confidence||''}</span>`,
          (r.group? '✓' : ''),
          (r.paths && r.paths.length? `<button class=\"btn btn-sm btn-outline-primary\" onclick=\"openPath('${encodeURIComponent(r.paths[0])}')\">Ouvrir</button>` : ''),
          (r.ignored? 'Oui' : 'Non'),
          `<button class=\"btn btn-sm btn-outline-secondary me-1\" onclick=\"toggleIgnore(${JSON.stringify(r.ignore_candidates||[]).replaceAll('"','&quot;')}, ${r.ignored? 'false':'true'})\">${r.ignored?'Unignore':'Ignore'}</button>`+
          (r.group? `<button class=\"btn btn-sm btn-outline-warning\" onclick=\"toggleATF('${(r.group||'').replaceAll('"','&quot;')}')\">ATF</button>`:''),
        ];
        let colIndex=0;
        vals.forEach((v, idx)=>{
          if(hiddenCols.has(idx)) { colIndex++; return; }
          const td=document.createElement('td');
          td.innerHTML = v;
          tr.appendChild(td);
          colIndex++;
        });
        tb.appendChild(tr);
      });
    }
    function openPath(p){
      fetch('{{ url_for('open_path') }}', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:`path=${decodeURIComponent(p)}`}).then(()=>{});
    }
    function toggleIgnore(candidates, makeIgnore){
      const form = new URLSearchParams();
      (candidates||[]).forEach(n=> form.append('name', n));
      form.append('action', makeIgnore? 'ignore':'unignore');
      fetch('{{ url_for('toggle_ignore') }}', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:form.toString()}).then(()=> reloadRows());
    }
    function toggleATF(groupName){
      fetch('{{ url_for('api_atf_toggle') }}', {method:'POST', headers:{'Content-Type': 'application/json'}, body: JSON.stringify({name: groupName})}).then(()=> reloadRows());
    }
    function applyFilters(){
      const dir = document.getElementById('modDir').value.trim();
      const params = new URLSearchParams();
      if(dir){ params.set('mod_dir', dir); }
      params.set('mode', document.getElementById('modeSelect').value);
      if(document.getElementById('showIgnored').checked) params.set('show_ignored','1');
      if(document.getElementById('hideInstaller').checked) params.set('hide_installer_mods','1');
      if(document.getElementById('recursive').checked) params.set('recursive','1');
      // Persist mod_dir server-side
      window.location = `/?${params.toString()}`;
    }
    function reloadRows(){
      const params = new URLSearchParams(window.location.search);
      fetch(`/api/rows?${params.toString()}`).then(r=>r.json()).then(data=>{ rows = data.rows||[]; renderRows(); });
      fetch('/api/columns').then(r=>r.json()).then(data=>{ hiddenCols = new Set((data.hidden||[]).map(Number)); buildHead(); buildColumnsMenu(); renderRows(); });
    }
    function buildColumnsMenu(){
      const ul=document.getElementById('columnsMenu');
      ul.innerHTML='';
      COLUMNS.forEach((col, idx)=>{
        const li=document.createElement('li');
        const id=`col_${idx}`;
        li.innerHTML = `<label class=\"dropdown-item\"><input type=\"checkbox\" class=\"form-check-input me-2\" id=\"${id}\" ${hiddenCols.has(idx)?'':'checked'} onchange=\"toggleColumn(${idx}, this.checked)\">${col.label}</label>`;
        ul.appendChild(li);
      });
    }
    function toggleColumn(index, checked){
      if(!checked) hiddenCols.add(index); else hiddenCols.delete(index);
      fetch('/api/columns', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hidden: Array.from(hiddenCols)})}).then(()=>{ buildHead(); renderRows(); });
    }
    document.addEventListener('DOMContentLoaded', ()=>{
      // Initialize controls from query
      const params = new URLSearchParams(window.location.search);
      document.getElementById('modeSelect').value = params.get('mode')||'both';
      document.getElementById('showIgnored').checked = !!params.get('show_ignored');
      document.getElementById('hideInstaller').checked = !!params.get('hide_installer_mods');
      document.getElementById('recursive').checked = params.get('recursive')!== '0';
      reloadRows();
    });
  </script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    settings = load_settings()
    # read filters from query
    mode = (request.args.get("mode") or settings.get("file_filter_mode", "both")).lower()
    show_ignored = bool(request.args.get("show_ignored")) if request.args else bool(settings.get("show_ignored", False))
    hide_installer_mods = bool(request.args.get("hide_installer_mods")) if request.args else bool(settings.get("hide_installer_mods", False))
    recursive = bool(request.args.get("recursive", "1"))
    mod_dir = (request.args.get("mod_dir") or settings.get("mod_directory", "")).strip()
    if mod_dir and mod_dir != settings.get("mod_directory", ""):
        settings["mod_directory"] = mod_dir
        save_settings(settings)
    # apply ephemeral filters on a copy
    effective = dict(settings)
    effective["file_filter_mode"] = mode
    effective["show_ignored"] = show_ignored
    effective["hide_installer_mods"] = hide_installer_mods
    try:
        rows = build_rows(effective, recursive=recursive)
    except Exception as exc:
        rows = []
        flash(f"Erreur lors de l'analyse: {exc}")

    return render_template_string(
        INDEX_TEMPLATE,
        settings=settings,
        mode=mode,
        show_ignored=show_ignored,
        hide_installer_mods=hide_installer_mods,
        recursive=recursive,
        rows=rows,
    )


@app.route("/toggle_ignore", methods=["POST"])
def toggle_ignore():
    settings = load_settings()
    names: List[str] = request.form.getlist("name")
    action = request.form.get("action") or ""
    ignored = set(settings.get("ignored_mods", []))
    if action == "ignore":
        for n in names:
            if n:
                ignored.add(n)
    else:
        for n in names:
            if n:
                ignored.discard(n)
    settings["ignored_mods"] = sorted(ignored)
    save_settings(settings)
    save_ignore_list(settings["ignored_mods"])
    return redirect(url_for("index"))


@app.route("/open", methods=["POST"])
def open_path():
    p = (request.form.get("path") or "").strip()
    if not p or not os.path.exists(p):
        flash("Chemin invalide")
        return redirect(url_for("index"))
    target = p
    if os.path.isfile(target):
        target = os.path.dirname(target) or target
    try:
        if os.name == 'nt':
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', target])
        else:
            import subprocess
            subprocess.Popen(['xdg-open', target])
        flash("Ouverture de l'explorateur")
    except Exception as exc:
        flash(f"Ouverture impossible: {exc}")
    return redirect(url_for("index"))


@app.route("/install", methods=["POST"])
def install_upload():
    settings = load_settings()
    mods_root = settings.get("mod_directory", "")
    if not mods_root or not os.path.isdir(mods_root):
        flash("Définis un dossier des mods valide dans la configuration.")
        return redirect(url_for("index"))
    f = request.files.get("file")
    if not f:
        flash("Aucun fichier fourni")
        return redirect(url_for("index"))
    include_extras = bool(request.form.get("include_extras"))
    # Persist include_extras for consistency with desktop installer
    settings["installer_include_extras"] = include_extras
    save_settings(settings)

    # Save to temp and dispatch
    suffix = os.path.splitext(f.filename)[1].lower()
    tmp_dir = tempfile.mkdtemp(prefix="s4mt_web_")
    tmp_path = os.path.join(tmp_dir, f.filename)
    f.save(tmp_path)
    try:
        if mr_install_zip and suffix == ".zip":
            dest = mr_install_zip(tmp_path, mods_root, include_extras=include_extras)
            flash(f"Installé dans: {dest}")
        elif suffix in {".7z", ".rar"} and mr_install_extracted:
            seven = _find_7z_executable()
            if not seven:
                flash("7-Zip (7z) requis pour ce format.")
                return redirect(url_for("index"))
            extract_dir = tempfile.mkdtemp(prefix="s4mt_webx_")
            try:
                import subprocess

                args = [seven, 'x', '-y', f"-o{extract_dir}", tmp_path]
                completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if completed.returncode != 0:
                    output = (completed.stderr or completed.stdout or "").strip()
                    flash(f"Extraction 7z échouée: {output}")
                    return redirect(url_for("index"))
                base = os.path.splitext(os.path.basename(tmp_path))[0]
                dest = mr_install_extracted(extract_dir, mods_root, base, include_extras=include_extras)
                flash(f"Installé dans: {dest}")
            finally:
                shutil.rmtree(extract_dir, ignore_errors=True)
        elif suffix in {".ts4script", ".package"}:
            dest_dir = os.path.join(mods_root, os.path.splitext(os.path.basename(tmp_path))[0])
            os.makedirs(dest_dir, exist_ok=True)
            target = os.path.join(dest_dir, os.path.basename(tmp_path))
            shutil.copy2(tmp_path, target)
            flash(f"Copié vers: {target}")
        else:
            flash("Format non supporté pour installation")
    except Exception as exc:
        flash(f"Erreur d'installation: {exc}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return redirect(url_for("index"))


@app.route("/export", methods=["GET"]) 
def export():
    settings = load_settings()
    version_releases = get_version_releases()
    directory = settings.get("mod_directory", "")
    if not directory or not os.path.isdir(directory):
        flash("Dossier des mods invalide")
        return redirect(url_for("index"))
    _pkgs, _scripts, _snapshot = scan_directory(directory, recursive=True)
    rows, _changed = generate_data_rows(directory, settings, version_releases, recursive=True)
    # Build a simple, consistent export similar to the desktop table
    headers = [
        "État",
        "Fichier .package",
        "Date .package",
        "Fichier .ts4script",
        "Date .ts4script",
        "Version",
        "Confiance",
        "Ignoré",
    ]
    out_rows = []
    for r in rows:
        out_rows.append([
            r.get('status',''),
            r.get('package',''),
            r.get('package_date',''),
            r.get('script',''),
            r.get('script_date',''),
            r.get('version',''),
            r.get('confidence',''),
            bool(r.get('ignored', False)),
        ])
    out = io.BytesIO()
    path = os.path.join(tempfile.gettempdir(), f"Sims4Mods_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    export_to_excel(path, out_rows, headers)
    with open(path, "rb") as fh:
        out.write(fh.read())
    out.seek(0)
    try:
        os.remove(path)
    except OSError:
        pass
    return send_file(out, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name="Sims4Mods.xlsx")


# --------------- JSON API ---------------

@app.route('/api/rows', methods=['GET'])
def api_rows():
    settings = load_settings()
    mode = (request.args.get("mode") or settings.get("file_filter_mode", "both")).lower()
    show_ignored = request.args.get("show_ignored") in ("1", "true", "on")
    hide_installer_mods = request.args.get("hide_installer_mods") in ("1", "true", "on")
    recursive = request.args.get("recursive", "1") in ("1", "true", "on")
    effective = dict(settings)
    effective["file_filter_mode"] = mode
    effective["show_ignored"] = show_ignored
    effective["hide_installer_mods"] = hide_installer_mods
    try:
        rows = build_rows(effective, recursive=recursive)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"rows": rows})

@app.route('/api/columns', methods=['GET', 'POST'])
def api_columns():
    settings = load_settings()
    if request.method == 'GET':
        hidden = [int(c) for c in settings.get('hidden_columns', [])]
        return jsonify({"hidden": hidden})
    try:
        payload = request.get_json(force=True)
        hidden = [int(c) for c in (payload.get('hidden') or [])]
    except Exception:
        return jsonify({"error": "Bad JSON"}), 400
    settings['hidden_columns'] = hidden
    save_settings(settings)
    return jsonify({"ok": True, "hidden": hidden})

@app.route('/api/atf-toggle', methods=['POST'])
def api_atf_toggle():
    try:
        payload = request.get_json(force=True)
        name = (payload.get('name') or '').strip()
        target = (payload.get('target_folder') or '').strip()
    except Exception:
        return jsonify({"error": "Bad JSON"}), 400
    from main import load_installed_mods, save_installed_mods, MOD_MARKER_FILENAME
    items = load_installed_mods()
    changed = False
    for ent in items:
        if (name and str(ent.get('name','')).strip().casefold() == name.casefold()) or (target and os.path.normcase(ent.get('target_folder','')) == os.path.normcase(target)):
            ent['atf'] = not bool(ent.get('atf', False))
            # Update marker
            folder = ent.get('target_folder') or ''
            marker = os.path.join(folder, MOD_MARKER_FILENAME)
            try:
                with open(marker, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
            except Exception:
                data = {}
            data['atf'] = bool(ent['atf'])
            try:
                with open(marker, 'w', encoding='utf-8') as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
            except Exception:
                pass
            changed = True
            break
    if changed:
        save_installed_mods(items)
        return jsonify({"ok": True})
    return jsonify({"error": "Mod non trouvé"}), 404

@app.route('/api/installer/update', methods=['POST'])
def api_installer_update():
    settings = load_settings()
    mods_root = settings.get('mod_directory', '')
    if not mods_root or not os.path.isdir(mods_root):
        return jsonify({"error": "Dossier des mods invalide"}), 400
    target_folder = (request.form.get('target_folder') or '').strip()
    if not target_folder or not os.path.isdir(target_folder):
        return jsonify({"error": "target_folder invalide"}), 400
    # Ensure target_folder is inside mods_root
    try:
        if os.path.commonpath([os.path.abspath(mods_root), os.path.abspath(target_folder)]) != os.path.abspath(mods_root):
            return jsonify({"error": "target_folder hors Mods"}), 400
    except Exception:
        return jsonify({"error": "Validation chemin"}), 400
    f = request.files.get('file')
    if not f:
        return jsonify({"error": "Aucun fichier"}), 400
    include_extras = (request.form.get('include_extras') in ('1','true','on'))
    suffix = os.path.splitext(f.filename)[1].lower()
    tmp_dir = tempfile.mkdtemp(prefix='s4mt_upd_')
    tmp_path = os.path.join(tmp_dir, f.filename)
    f.save(tmp_path)
    installed = []
    try:
        if suffix == '.zip' and mr_install_zip:
            # Install into specific folder by extracting with mod-root slicing
            import zipfile as _zf
            from mod_root_zip import plan_zip as _plan
            _dest, _type, mod_root, _just = _plan(tmp_path, mods_root)
            mod_root = (mod_root or '').rstrip('/')
            with _zf.ZipFile(tmp_path,'r') as zf:
                for info in zf.infolist():
                    name = info.filename.replace('\\','/')
                    if info.is_dir():
                        continue
                    # noise
                    base = os.path.basename(name).lower()
                    if base in ('thumbs.db', '.ds_store'):
                        continue
                    # filter extras
                    low = base
                    def _is_useful(n):
                        return n.endswith('.package') or n.endswith('.ts4script')
                    if not include_extras and not _is_useful(low):
                        continue
                    rel = name
                    if mod_root and rel.startswith(mod_root + '/'):
                        rel = rel[len(mod_root)+1:]
                    rel = rel.lstrip('/')
                    if not rel:
                        continue
                    out = os.path.join(target_folder, *rel.split('/'))
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with zf.open(info,'r') as src, open(out,'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    installed.append(rel)
        elif suffix in ('.7z','.rar') and mr_install_extracted:
            seven = _find_7z_executable()
            if not seven:
                return jsonify({"error": "7-Zip requis"}), 400
            extract_dir = tempfile.mkdtemp(prefix='s4mt_updx_')
            try:
                import subprocess
                args = [seven, 'x', '-y', f"-o{extract_dir}", tmp_path]
                completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if completed.returncode != 0:
                    output = (completed.stderr or completed.stdout or '').strip()
                    return jsonify({"error": f"Extraction 7z échouée: {output}"}), 400
                from mod_root_zip import plan_extracted_dir as _plan_ex
                _dest, _type, mod_root, _just = _plan_ex(extract_dir, mods_root, os.path.splitext(os.path.basename(tmp_path))[0])
                mod_root = (mod_root or '').rstrip('/')
                root = extract_dir
                for cur, _d, files in os.walk(root):
                    for file in files:
                        full = os.path.join(cur, file)
                        rel = os.path.relpath(full, root).replace('\\','/')
                        if mod_root and rel.startswith(mod_root + '/'):
                            rel = rel[len(mod_root)+1:]
                        base = file.lower()
                        def _is_useful(n):
                            return n.endswith('.package') or n.endswith('.ts4script')
                        if not include_extras and not _is_useful(base):
                            continue
                        out = os.path.join(target_folder, *rel.split('/'))
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        shutil.copy2(full, out)
                        installed.append(rel)
            finally:
                shutil.rmtree(extract_dir, ignore_errors=True)
        elif suffix in ('.package', '.ts4script'):
            out = os.path.join(target_folder, os.path.basename(tmp_path))
            shutil.copy2(tmp_path, out)
            installed.append(os.path.basename(out))
        else:
            return jsonify({"error": "Format non supporté"}), 400
        return jsonify({"ok": True, "installed": installed})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route('/api/install', methods=['POST'])
def api_install():
    settings = load_settings()
    mods_root = settings.get("mod_directory", "")
    if not mods_root or not os.path.isdir(mods_root):
        return jsonify({"error": "Dossier des mods invalide"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Aucun fichier"}), 400
    include_extras = (request.form.get("include_extras") in ("1", "true", "on"))
    suffix = os.path.splitext(f.filename)[1].lower()
    tmp_dir = tempfile.mkdtemp(prefix="s4mt_web_")
    tmp_path = os.path.join(tmp_dir, f.filename)
    f.save(tmp_path)
    try:
        if mr_install_zip and suffix == ".zip":
            dest = mr_install_zip(tmp_path, mods_root, include_extras=include_extras)
        elif suffix in {".7z", ".rar"} and mr_install_extracted:
            seven = _find_7z_executable()
            if not seven:
                return jsonify({"error": "7-Zip requis"}), 400
            extract_dir = tempfile.mkdtemp(prefix="s4mt_webx_")
            try:
                import subprocess
                args = [seven, 'x', '-y', f"-o{extract_dir}", tmp_path]
                completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if completed.returncode != 0:
                    output = (completed.stderr or completed.stdout or "").strip()
                    return jsonify({"error": f"Extraction 7z échouée: {output}"}), 400
                base = os.path.splitext(os.path.basename(tmp_path))[0]
                dest = mr_install_extracted(extract_dir, mods_root, base, include_extras=include_extras)
            finally:
                shutil.rmtree(extract_dir, ignore_errors=True)
        elif suffix in {".ts4script", ".package"}:
            dest_dir = os.path.join(mods_root, os.path.splitext(os.path.basename(tmp_path))[0])
            os.makedirs(dest_dir, exist_ok=True)
            target = os.path.join(dest_dir, os.path.basename(tmp_path))
            shutil.copy2(tmp_path, target)
            dest = target
        else:
            return jsonify({"error": "Format non supporté"}), 400
        return jsonify({"ok": True, "dest": dest})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------- Web Comparator ---------------

COMPARE_TEMPLATE = """
<!doctype html>
<html lang=fr>
<head><meta charset="utf-8"/><title>Comparateur de mods</title></head>
<body>
  <h2>Comparateur de mods</h2>
  <form method="post" action="{{ url_for('compare_do') }}" enctype="multipart/form-data">
    <div>
      <label>Mod A (fichier ou dossier): <input type="text" name="left" size="60"/></label>
      <label>ou fichier: <input type="file" name="left_file"/></label>
    </div>
    <div>
      <label>Mod B (fichier ou dossier): <input type="text" name="right" size="60"/></label>
      <label>ou fichier: <input type="file" name="right_file"/></label>
    </div>
    <div>
      <label><input type="checkbox" name="hash" value="1" checked/> Comparer le contenu (hash)</label>
      <label><input type="checkbox" name="inner" value="1" checked/> Comparer l'intérieur des .ts4script</label>
      <button type="submit">Comparer</button>
    </div>
  </form>
  {% if result %}
    <h3>Résumé</h3>
    <pre>{{ result.summary }}</pre>
    <h3>Diff (JSON)</h3>
    <pre>{{ result.diff }}</pre>
  {% endif %}
  <p><a href="{{ url_for('index') }}">Retour</a></p>
</body>
</html>
"""


def _scan_ts4script_file(path, *, hash_content=True, open_archives=True):
    import zipfile as _zf
    result = {"packages": {}, "scripts": {}, "totals": {"packages": 0, "scripts": 0, "script_entries": 0}, "addons_count": 0}
    name = os.path.basename(path)
    try:
        st = os.stat(path)
    except OSError:
        return result
    info = {"size": int(st.st_size)}
    if hash_content:
        import hashlib as _hl
        h = _hl.sha1()
        with open(path, 'rb') as fh:
            while True:
                ch = fh.read(1024 * 256)
                if not ch: break
                h.update(ch)
        info['hash'] = h.hexdigest()
    if open_archives:
        inner = {}
        try:
            with _zf.ZipFile(path, 'r') as zf:
                for zi in zf.infolist():
                    if zi.is_dir():
                        continue
                    inner[zi.filename.replace('\\','/')] = {"size": zi.file_size, "crc": zi.CRC}
        except Exception:
            pass
        info['inner'] = inner
        result['totals']['script_entries'] = len(inner)
    result['scripts'][name] = info
    result['totals']['scripts'] = 1
    return result


def _diff_dicts(left, right):
    lk = set(left.keys()); rk = set(right.keys())
    added = sorted(rk - lk, key=str.casefold)
    removed = sorted(lk - rk, key=str.casefold)
    common = sorted(lk & rk, key=str.casefold)
    changed = [k for k in common if left[k] != right[k]]
    return added, removed, sorted(changed, key=str.casefold)


def _scan_any(path, *, hash_content=True, open_archives=True):
    p = os.path.abspath(path)
    if os.path.isdir(p):
        # simple directory scan (no trimming here)
        res = {"packages": {}, "scripts": {}, "totals": {"packages": 0, "scripts": 0, "script_entries": 0}, "addons_count": 0}
        for cur, _d, files in os.walk(p):
            for fname in files:
                full = os.path.join(cur, fname)
                rel = os.path.relpath(full, p).replace('\\','/')
                low = fname.lower()
                st = os.stat(full)
                if low.endswith('.package'):
                    info = {"size": int(st.st_size)}
                    if hash_content:
                        import hashlib as _hl
                        h = _hl.sha1()
                        with open(full,'rb') as fh:
                            while True:
                                ch = fh.read(1024*256)
                                if not ch: break
                                h.update(ch)
                        info['hash'] = h.hexdigest()
                    res['packages'][rel] = info
                elif low.endswith('.ts4script'):
                    inner = _scan_ts4script_file(full, hash_content=hash_content, open_archives=open_archives)
                    # merge under rel name (one file)
                    single = next(iter(inner['scripts'].items()))
                    res['scripts'][rel] = single[1]
        res['totals']['packages'] = len(res['packages'])
        res['totals']['scripts'] = len(res['scripts'])
        res['totals']['script_entries'] = sum(len(v.get('inner',{})) for v in res['scripts'].values())
        return res
    ext = os.path.splitext(p)[1].lower()
    if ext == '.package':
        st = os.stat(p)
        info = {"size": int(st.st_size)}
        if hash_content:
            import hashlib as _hl
            h = _hl.sha1();
            with open(p,'rb') as fh:
                while True:
                    ch = fh.read(1024*256)
                    if not ch: break
                    h.update(ch)
            info['hash'] = h.hexdigest()
        return {"packages": {os.path.basename(p): info}, "scripts": {}, "totals": {"packages": 1, "scripts": 0, "script_entries": 0}, "addons_count": 0}
    if ext == '.ts4script':
        return _scan_ts4script_file(p, hash_content=hash_content, open_archives=open_archives)
    if ext == '.zip':
        # treat like ts4script (outer entries)
        import zipfile as _zf
        res = {"packages": {}, "scripts": {}, "totals": {"packages": 0, "scripts": 0, "script_entries": 0}, "addons_count": 0}
        with _zf.ZipFile(p,'r') as zf:
            for zi in zf.infolist():
                if zi.is_dir():
                    continue
                name = zi.filename.replace('\\','/')
                low = name.lower()
                if low.endswith('.package'):
                    res['packages'][name] = {"size": zi.file_size}
                elif low.endswith('.ts4script'):
                    res['scripts'][name] = {"size": zi.file_size}
        res['totals']['packages'] = len(res['packages'])
        res['totals']['scripts'] = len(res['scripts'])
        return res
    return {"packages": {}, "scripts": {}, "totals": {"packages": 0, "scripts": 0, "script_entries": 0}, "addons_count": 0}


@app.route('/compare', methods=['GET'])
def compare_view():
    return render_template_string(COMPARE_TEMPLATE, result=None)


@app.route('/compare', methods=['POST'])
def compare_do():
    left = (request.form.get('left') or '').strip()
    right = (request.form.get('right') or '').strip()
    lf = request.files.get('left_file')
    rf = request.files.get('right_file')
    hash_content = request.form.get('hash') == '1'
    open_arch = request.form.get('inner') == '1'

    temp_dir = tempfile.mkdtemp(prefix='s4mt_cmpw_')
    try:
        if lf and lf.filename:
            left = os.path.join(temp_dir, lf.filename)
            lf.save(left)
        if rf and rf.filename:
            right = os.path.join(temp_dir, rf.filename)
            rf.save(right)
        if not left or not right:
            flash('Entrées invalides')
            return redirect(url_for('compare_view'))
        A = _scan_any(left, hash_content=hash_content, open_archives=open_arch)
        B = _scan_any(right, hash_content=hash_content, open_archives=open_arch)
        pa, pr, pc = _diff_dicts(A['packages'], B['packages'])
        sa, sr, sc = _diff_dicts(A['scripts'], B['scripts'])
        summary = {
            'packages': {'A': len(A['packages']), 'B': len(B['packages'])},
            'scripts': {'A': len(A['scripts']), 'B': len(B['scripts'])},
            'diff': {'packages': {'added': pa, 'removed': pr, 'changed': pc}, 'scripts': {'added': sa, 'removed': sr, 'changed': sc}},
        }
        import json
        return render_template_string(COMPARE_TEMPLATE, result={
            'summary': json.dumps(summary, indent=2, ensure_ascii=False),
            'diff': json.dumps({'A': A, 'B': B}, indent=2, ensure_ascii=False),
        })
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def start_in_thread(host="127.0.0.1", port=5000, debug=False):
    from threading import Thread
    t = Thread(target=lambda: app.run(host=host, port=port, debug=debug, use_reloader=False), daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    host = os.environ.get("S4MT_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("S4MT_WEB_PORT", "5000"))
    debug = bool(int(os.environ.get("S4MT_WEB_DEBUG", "1")))
    app.run(host=host, port=port, debug=debug)
