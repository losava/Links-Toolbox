"""Code mods for Longshot: mods that change how the game works, not only its files.

Longshot turns the game's code into a PC program when it builds the game, so a code mod goes into Longshot's own
sources and the game is built again (the Longshot Launcher's Build button). This handles the packages made for that the
way the Hyrule HUD Suite makes them (Hyrule Armory, ...), and does what their Install.cmd does:

    <package>\\mod.json            name, family (one edition of a family at a time), files, core_files, romfs
    <package>\\longshot\\...        files copied into each Longshot source folder (host\\*.c, nx2\\*.py ...)
    <package>\\mods\\<folder>\\romfs  game files of its own (pictures...), for the game's mods folder

Each package is remembered in %LOCALAPPDATA%\\HyruleHUDSuite\\installed\\<family> (the same place its Install.cmd uses,
so mods put in either way show up in both), and every remembered package is put into every Longshot source folder
found: after a Longshot update, one "Put them back" (or any Install.cmd) brings them all into the new version.
Every place the suite connects to is checked first: when a Longshot version moved one, nothing is changed.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import nxsave

LOCAL = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
LAUNCHER_DATA = LOCAL / 'LongshotLauncher'
SUITE = LOCAL / 'HyruleHUDSuite'
STORE = SUITE / 'installed'
KNOWN = SUITE / 'longshot-folders.txt'      # (source folders named before, by the suite's installer or here)
STATE = SUITE / 'link-toolbox.json'         # (when the toolbox last changed each source folder: Build needed after)


class CodeModError(Exception):
    """Something that stops an install, said plainly."""


# ---------------------------------------------------------------------------------------------------- Longshot's sources
def _is_root(p):
    return (p / 'nx2' / 'oot_patches.py').is_file() and (p / 'host' / 'hos_wide_ui.c').is_file()


def source_roots(extra=()):
    """Every Longshot source folder (one per Longshot version the launcher has): ...\\tools with nx2\\ and host\\."""
    places = [LAUNCHER_DATA / 'toolchains', LOCAL / 'LongshotBuilder', *extra]
    try:
        places += [Path(x.strip()) for x in KNOWN.read_text(encoding='utf-8-sig').splitlines() if x.strip()]
    except OSError:
        pass
    found = []
    for place in places:
        if not place.is_dir():
            continue
        # (the launcher's layout first: toolchains\<version>\LongshotBuilder\tools; then a short search)
        for pattern in ('', 'tools', 'LongshotBuilder/tools', '*/LongshotBuilder/tools', '*/tools', '*'):
            for p in sorted(place.glob(pattern)) if pattern else [place]:
                if p.is_dir() and _is_root(p) and p.resolve() not in found:
                    found.append(p.resolve())
    return found


def root_version(root):
    """'v3.0.0-rc.5' for a launcher toolchain (its folder name), else the folder's own version.txt, else ''."""
    for part in Path(root).parts[::-1]:
        if re.match(r'v?\d+\.\d+', part) or part.startswith(('nightly', 'rc')):
            return part
    try:
        return (Path(root) / 'version.txt').read_text(encoding='utf-8').strip().splitlines()[0]
    except (OSError, IndexError):
        return ''


def launcher_exe():
    """The Longshot Launcher program (its Build button builds the game again), None when not found."""
    tries = [LOCAL / 'Programs' / 'LongshotLauncher' / 'LongshotLauncher.exe']
    for _app, game in nxsave.all_game_dirs():
        try:
            for line in (Path(game) / 'longshot_version.txt').read_text(encoding='utf-8').splitlines():
                if line.startswith('builder='):
                    tries.insert(0, Path(line.split('=', 1)[1].strip()))
        except OSError:
            pass
    return next((p for p in tries if p.is_file()), None)


def longshot_mods_folders():
    """The mods folder of every Longshot build (once each: with sharing on they are one folder)."""
    out = []
    for app, game in nxsave.all_game_dirs():
        if app == 'Longshot':
            d = Path(nxsave.mods_dir_for(game, app))
            if all(os.path.normcase(str(d.resolve())) != os.path.normcase(str(o.resolve())) for o in out):
                out.append(d)
    return out


# ------------------------------------------------------------------------------------------------------------ packages
def read_package(folder):
    """mod.json of a package folder (checked), with 'folder' added."""
    folder = Path(folder)
    try:
        mod = json.loads((folder / 'mod.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as err:
        raise CodeModError(f'{folder} has no readable mod.json: {err}')
    if not isinstance(mod, dict) or not mod.get('name') or not mod.get('family') or not (folder / 'longshot').is_dir():
        raise CodeModError(f'{folder} is not a code mod package (mod.json needs a name and a family, and a '
                           '"longshot" folder beside it).')
    if not re.fullmatch(r'[A-Za-z0-9._ -]{1,60}', str(mod['family'])):
        raise CodeModError(f'{mod["name"]}: its family name "{mod["family"]}" cannot be a folder name.')
    for f in list(mod.get('files', [])) + list(mod.get('core_files', [])):
        if Path(f).is_absolute() or '..' in Path(f).parts:
            raise CodeModError(f'{mod["name"]}: its file "{f}" points outside Longshot\'s sources.')
    mod['folder'] = folder
    return mod


def find_packages(path):
    """The package folders in a folder (a mod.json with a "longshot" folder beside it, up to 4 folders down)."""
    path = Path(path)
    out = []
    for dirpath, dirs, files in os.walk(path):
        depth = len(Path(dirpath).relative_to(path).parts)
        if 'mod.json' in files and 'longshot' in dirs:
            out.append(Path(dirpath))
            dirs[:] = []
        elif depth >= 4:
            dirs[:] = []
    return out


def unpack_zip(zip_path):
    """A zip unpacked into a new temporary folder (the caller removes it); no file may land outside it."""
    tmp = Path(tempfile.mkdtemp(prefix='link-toolbox-zip-'))
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            dest = (tmp / info.filename).resolve()
            if tmp.resolve() not in dest.parents and dest != tmp.resolve():
                shutil.rmtree(tmp, ignore_errors=True)
                raise CodeModError(f'{Path(zip_path).name} has a file that points outside its folder: not used.')
        z.extractall(tmp)
    return tmp


def remembered():
    """The packages put in (by this toolbox or their own Install.cmd), by name."""
    out = []
    for d in sorted(STORE.iterdir()) if STORE.is_dir() else []:
        if (d / 'mod.json').is_file():
            try:
                out.append(read_package(d))
            except CodeModError:
                pass
    return sorted(out, key=lambda m: m['name'].lower())


# ------------------------------------------------------------------------------------------- the suite's 6 core lines
_PATCH_A = '    out = solver{nl}    return out, counts, lines'
_PATCH_B = '        total.update(c){nl}    for what in done:'
_UI_A = 'static volatile float ui_ex, ui_ey, ui_wx = 1.0f, ui_fit = 1.0f;{nl}'


def _nl(text):
    return '\r\n' if '\r\n' in text else '\n'


def core_check(root):
    """'' when the suite can connect to this Longshot version (or already is), else what moved."""
    p = Path(root) / 'nx2' / 'oot_patches.py'
    t = p.read_text(encoding='utf-8')
    nl = _nl(t)
    if 'import hhs_patches' not in t and (t.count(_PATCH_A.format(nl=nl)) != 1 or t.count(_PATCH_B.format(nl=nl)) != 1):
        return f'{root_version(root) or root}: Longshot changed nx2\\oot_patches.py where code mods connect.'
    t = (Path(root) / 'host' / 'hos_wide_ui.c').read_text(encoding='utf-8')
    if 'hos_wide_ui_side_shift' not in t and t.count(_UI_A.format(nl=_nl(t))) != 1:
        return f'{root_version(root) or root}: Longshot changed host\\hos_wide_ui.c where code mods connect.'
    return ''


def _write(p, text):
    with open(p, 'w', encoding='utf-8', newline='') as f:     # (keeps the file's own line ends)
        f.write(text)


def add_core(root):
    """The suite's lines into Longshot's two files, once (the same lines its Install.cmd adds)."""
    p = Path(root) / 'nx2' / 'oot_patches.py'
    t = p.read_text(encoding='utf-8')
    if 'import hhs_patches' not in t:
        nl = _nl(t)
        t = t.replace(_PATCH_A.format(nl=nl),
                      f'    out = solver{nl}    import hhs_patches   # (Hyrule HUD Suite\'s sites: nx2/hhs_patches.py){nl}'
                      f'    out = hhs_patches.patch_file(out, name, protect_hearts, counts, lines){nl}'
                      '    return out, counts, lines')
        t = t.replace(_PATCH_B.format(nl=nl),
                      f'        total.update(c){nl}    import hhs_patches   # (Hyrule HUD Suite: strict, its site found '
                      f'once or the lift stops){nl}    hhs_patches.report(total, protect_hearts){nl}    for what in done:')
        _write(p, t)
    p = Path(root) / 'host' / 'hos_wide_ui.c'
    t = p.read_text(encoding='utf-8')
    if 'hos_wide_ui_side_shift' not in t:
        nl = _nl(t)
        a = _UI_A.format(nl=nl)
        t = t.replace(a, a + f'/* (hhs) read-only: the canvas units the plan moves a side pane out (0 when the HUD stays '
                             f'16:9) */{nl}float hos_wide_ui_side_shift(void) {{ return ui_ex; }}{nl}')
        _write(p, t)


# ------------------------------------------------------------------------------------------------------ putting in
def _changed(roots):
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    now = datetime.now(timezone.utc).isoformat()
    for r in roots:
        state[os.path.normcase(str(r))] = now
    SUITE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding='utf-8')


def apply(roots=None, log=lambda _s: None):
    """Every remembered package into every Longshot source folder (checked first: all or nothing). Returns the roots."""
    roots = source_roots() if roots is None else roots
    packages = remembered()
    if not roots:
        raise CodeModError("Longshot's sources were not found. Install Longshot with the Longshot Launcher and build "
                           'the game there once (until Play works), then try again.')
    problems = [w for w in (core_check(r) for r in roots) if w]
    if problems:
        raise CodeModError('\n'.join(problems) + '\n\nNothing was changed. Build an older Longshot version, or wait '
                           'for an updated mod package.')
    if not packages:
        return roots
    newest = max(packages, key=lambda m: int(m.get('core') or 1))
    core_files = newest.get('core_files') or ['host/hhs.h', 'host/hhs_core.c', 'nx2/hhs_patches.py']
    for root in roots:
        add_core(root)
        for m in packages:
            src = m['folder'] / 'longshot'
            for f in sorted(src.rglob('*')):
                if f.is_file():
                    dest = root / f.relative_to(src)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
        for f in core_files:                     # (the shared core: always the newest any package brings)
            if (newest['folder'] / 'longshot' / f).is_file():
                shutil.copy2(newest['folder'] / 'longshot' / f, root / f)
        log(f'{root_version(root)}: {", ".join(m["name"] for m in packages)}')
    _changed(roots)
    return roots


def _romfs_in(package):
    d = Path(package['folder']) / 'mods'
    return sorted(p for p in d.iterdir() if p.is_dir() and (p / 'romfs').is_dir()) if d.is_dir() else []


def _plain(name):
    return re.sub(r'^(?:[-_]+)?(?:\d+-)?', '', name)


def _put_romfs(package):
    """The package's own game files into every Longshot mods folder (a copy already there, whatever its number or
    on/off mark, is replaced in place). Returns the folders written."""
    out = []
    for mods in longshot_mods_folders():
        for d in _romfs_in(package):
            mods.mkdir(parents=True, exist_ok=True)
            old = next((p for p in mods.iterdir() if p.is_dir() and _plain(p.name) == d.name), None)
            target = old or mods / d.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(d, target)
            out.append(target)
    return out


def install(path, log=lambda _s: None):
    """Puts in the package(s) in a folder or zip: remembered, into every Longshot source folder, its game files into
    the mods folders. Returns the names put in. The game must be closed."""
    if nxsave.blocking_game():
        raise CodeModError('Close the game first.')
    path = Path(path)
    tmp = unpack_zip(path) if path.is_file() and path.suffix.lower() == '.zip' else None
    try:
        found = find_packages(tmp or path)
        if not found:
            raise CodeModError(f'{path.name} has no code mod package in it (a mod.json with a "longshot" folder beside '
                               'it). For mods that only replace game files, use Add mods.')
        packages = [read_package(f) for f in found]
        roots = source_roots()
        apply_check = [w for w in (core_check(r) for r in roots) if w]
        if not roots or apply_check:
            apply(roots)                          # (says what is wrong; nothing is changed)
        STORE.mkdir(parents=True, exist_ok=True)
        kept = {}
        for m in packages:                        # (one edition per family: a new one replaces the other)
            mine = STORE / m['family']
            if mine.exists():
                kept[m['family']] = mine.with_name(mine.name + '.old')
                shutil.rmtree(kept[m['family']], ignore_errors=True)
                mine.rename(kept[m['family']])
            shutil.copytree(m['folder'], mine)
            readme = m['folder'].parent / 'README.txt'      # (the package's README sits one folder up: its options)
            if not (mine / 'README.txt').exists() and readme.is_file():
                shutil.copy2(readme, mine / 'README.txt')
        try:
            apply(roots, log)
        except Exception:
            for m in packages:                    # (as it was)
                shutil.rmtree(STORE / m['family'], ignore_errors=True)
                if m['family'] in kept:
                    kept[m['family']].rename(STORE / m['family'])
            raise
        for old in kept.values():
            shutil.rmtree(old, ignore_errors=True)
        for m in packages:
            for t in _put_romfs(read_package(STORE / m['family'])):
                log(f'game files: {t}')
        return [m['name'] for m in packages]
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def uninstall(family, log=lambda _s: None):
    """Takes a package out of every Longshot source folder, its game files out of the mods folders, and forgets it.
    (The suite's shared core and its 6 lines stay: they do nothing without a mod.) Build again afterwards."""
    if nxsave.blocking_game():
        raise CodeModError('Close the game first.')
    mine = STORE / family
    m = read_package(mine)
    roots = source_roots()
    for root in roots:
        for f in m.get('files', []):
            p = root / f
            if p.is_file():
                p.unlink()
        log(f'{root_version(root)}: {m["name"]} taken out')
    for mods in longshot_mods_folders():
        for d in _romfs_in(m):
            for p in list(mods.iterdir()) if mods.is_dir() else []:
                if p.is_dir() and _plain(p.name) == d.name:
                    shutil.rmtree(p)
                    log(f'game files removed: {p}')
    shutil.rmtree(mine)
    if roots:
        apply(roots, log)                         # (the others stay, with the newest core)
        _changed(roots)
    return m['name']


# ---------------------------------------------------------------------------------------------------------- status
def _built_at(root):
    """When the launcher last built the version these sources are, None when unknown."""
    try:
        builds = json.loads((LAUNCHER_DATA / 'builds.json').read_text(encoding='utf-8-sig')).get('builds', [])
    except (OSError, ValueError):
        return None
    version = root_version(root)
    times = [b.get('updated') for b in builds if b.get('version') == version and b.get('updated')]
    try:
        return max(datetime.fromisoformat(t) for t in times) if times else None
    except ValueError:
        return None


def status():
    """{'roots': [(root, version, needs_build, missing: [names])], 'packages': [mod.json...]}: what each Longshot
    version has. missing: remembered packages whose files are not (all) in that version (a Longshot update)."""
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        state = {}
    packages = remembered()
    rows = []
    for root in source_roots():
        missing = [m['name'] for m in packages
                   if any(not (root / f).is_file() for f in m.get('files', []))]
        changed = state.get(os.path.normcase(str(root)))
        built = _built_at(root)
        needs = bool(changed) and (built is None or datetime.fromisoformat(changed) > built)
        rows.append((root, root_version(root), needs, missing))
    return {'roots': rows, 'packages': packages}


def edition(m):
    """'Nintendo' / 'PlayStation' / ... from a package's config, '' when it has none."""
    for f in Path(m['folder'], 'longshot').rglob('*_config.h'):
        hit = re.search(r'_EDITION\s+"([^"]+)"', f.read_text(encoding='utf-8', errors='replace'))
        if hit:
            return hit.group(1)
    return ''


def options(m):
    """The options a package's README lists (NAME=value lines, set in longshot_env.txt beside longshot.exe)."""
    out = []
    for name in ('README.txt', '../README.txt'):
        try:
            text = (Path(m['folder']) / name).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        out += re.findall(r'^(HOS_[A-Z0-9_]+=\S+)\s+(.*)$', text, flags=re.M)
        if out:
            break
    return out
