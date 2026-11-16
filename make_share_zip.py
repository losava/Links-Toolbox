"""Packs the Link toolbox to give to someone else: save-editor\\share\\Link Toolbox.zip, which works from any folder.

    Link Toolbox\\
        Link Toolbox.bat     double-click to open
        README.txt           (save-editor\\README.txt: edit that one)
        app\\                the toolbox's scripts (no backups, settings or names cache: those are made there)
        mods\\               the mods that are on in game\\mods (the Mods tab's "Add mods..." installs them);
                             --no-mods leaves them out
        python\\              the Python beside save-editor, without its site-packages (the toolbox does not use them)

With --linux it makes share\\Link Toolbox (Linux).tar.gz instead: the same scripts and mods, Link Toolbox.sh to start
it (with the system's Python 3.14+ and Tk), and no Python inside.

Run:  python\\python.exe save-editor\\make_share_zip.py                  (inside the Links-Toolbox folder)
      python make_share_zip.py --python "C:\\path\\to\\python314"       (anywhere else)
"""
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = HERE.parent / 'python'
OUT = HERE / 'share' / 'Link Toolbox.zip'
APP = ('toolbox.pyw', 'mod_loader.pyw', 'save_editor.pyw', 'nxsave.py', 'oot_catalog.py', 'jpeg_win.py',
       'size_table.py', 'theme.py', 'icons.py', 'updater.py', 'install.py', 'builds.py', 'busy.py',
       'code_mods.py', 'code_mods_ui.py')
INSTALL_BAT = '''@echo off
rem Installs Link's Tool Box for this user (Start menu, Desktop, Windows Settings > Apps), or upgrades the installed one.
start "" "%~dp0python\\pythonw.exe" "%~dp0app\\install.py"
'''
OPTIONAL = ('icon.ico', 'icon.png')     # the icon picked in the Look tab (made with the default one when missing)
SKIP_PY = ('Lib', '__pycache__')      # (Lib holds only site-packages: 72 MB the toolbox never imports)

BAT = '''@echo off
rem Opens Link's Tool Box (mod loader and save editor) with the Python in this folder.
start "" "%~dp0python\\pythonw.exe" "%~dp0app\\toolbox.pyw"
'''

README = '''Link''s Tool Box - mod loader and save editor for Zelda: Ocarina of Time on Triforce
==============================================================================
Link's Tool Box, by Cum_Dumpster

Start:   unzip this folder anywhere (Desktop, Documents...), then double-click "Link Toolbox.bat".
         Nothing to install: the Python it needs is in the python folder.

The game folder
    The toolbox finds the game where Triforce put it (it reads Triforce's own setup log). If it cannot,
    it asks once: pick the folder that has Triforce.exe and the romfs folder in it. To change it later:
    the Folders tab.

Tabs
    Mods         switch the mods in the game's mods folder on and off, set which wins, Save and play.
                 Triforce only loads mods from the "mods" folder next to Triforce.exe.
    Save editor  pick a slot. Stats (hearts, magic, rupees, bags, ammo, bottles, keys), Inventory (give or take
                 away items), Progress (story flags), All entries (every value). Click a column heading to sort.
    Folders      another game, mods or saves folder.
    Look         the colours: a theme (dark green, grey, blue, purple, light), the accent, each tab's colour.

Before saving a save: CLOSE THE GAME. The game writes over the save files when it saves.
Every save first copies the old files into app\\backups (the "Backups folder" button opens it).

The first time the save editor opens it reads the names from the game files: that takes a little while once.
Needs Windows 10 or 11.
'''


BUNDLED_LIST = 'bundled.txt'    # in the download's mods folder: the names of its mods, one a line
# The download always ships these the same way, whatever is on or off in my own mods folder right now:
SHIP_ON = ('Biggoron One-Handed',)               # (the default way to hold the Biggoron Sword)
SHIP_OFF = ('Young Link Two-Handed Swords',)     # (replaces the same file as Biggoron One-Handed: one or the other)


def share_mods():
    """[(folder, name in the download)]: the mods that are on in the game's mods folder, the size table, the SHIP_ON
    mods (on even when they are off here) and the SHIP_OFF mods (switched off: their name keeps a leading _)."""
    sys.path.insert(0, str(HERE))
    import nxsave
    # (from the game the toolbox is set to: the main build, Longshot rc; with sharing on, the shared mods folder)
    mods = nxsave.mods_dir_for(nxsave.game_dir())
    print('mods from:', mods)
    import re
    plain = lambda name: re.sub(r'^(?:[-_]+)?(?:\d+-)?', '', name)
    out = []
    for p in sorted(mods.iterdir()) if mods.is_dir() else []:
        if not p.is_dir() or not (p / 'romfs').is_dir():
            continue
        name, off = plain(p.name), p.name.startswith(('_', '-'))
        if name in SHIP_OFF:
            out.append((p, f'_{name}'))
        elif name in SHIP_ON:
            out.append((p, p.name if not off else f'90-{name}'))
        elif not off:
            out.append((p, p.name))
    return out


LINUX_OUT = HERE / 'share' / 'Link Toolbox (Linux).tar.gz'
SH = '''#!/bin/sh
# Opens Link's Tool Box (mod loader and save editor) with this computer's Python: 3.14 or newer, with Tk.
cd "$(dirname "$0")" || exit 1
for py in python3.14 python3.15 python3.16 python3.17 python3 python; do
  if command -v "$py" >/dev/null 2>&1 && \\
     "$py" -c 'import sys, tkinter, compression.zstd; sys.exit(sys.version_info < (3, 14))' 2>/dev/null; then
    exec "$py" app/toolbox.pyw "$@"
  fi
done
msg="Link's Tool Box needs Python 3.14 or newer, with Tk.

Install them, then open Link Toolbox.sh again. For example:
  Ubuntu / Debian:  sudo apt install python3 python3-tk
  Fedora:           sudo dnf install python3 python3-tkinter
  Arch / SteamOS:   sudo pacman -S python tk
(Python 3.14 is needed: older systems may need a newer Python first.)"
if command -v zenity >/dev/null 2>&1; then zenity --error --title="Link's Tool Box" --text="$msg"
elif command -v kdialog >/dev/null 2>&1; then kdialog --title "Link's Tool Box" --error "$msg"
else printf '%s\\n' "$msg" >&2; fi
exit 1
'''


def build_linux():
    """share\\Link Toolbox (Linux).tar.gz: the scripts, the mods and Link Toolbox.sh (runnable), no Python inside."""
    import io
    import tarfile
    import time
    LINUX_OUT.parent.mkdir(exist_ok=True)
    tmp = LINUX_OUT.with_name(LINUX_OUT.name + '.part')
    root = 'Link Toolbox/'
    now = time.time()

    def text(tar, name, body, mode=0o644):
        data = body.replace('\r\n', '\n').encode('utf-8')
        info = tarfile.TarInfo(root + name)
        info.size, info.mode, info.mtime = len(data), mode, now
        tar.addfile(info, io.BytesIO(data))

    def file(tar, src, name):
        info = tar.gettarinfo(str(src), root + name)
        info.mode, info.uid, info.gid, info.uname, info.gname = 0o644, 0, 0, '', ''
        with open(src, 'rb') as f:
            tar.addfile(info, f)
    with tarfile.open(tmp, 'w:gz', compresslevel=9) as tar:
        text(tar, 'Link Toolbox.sh', SH, 0o755)
        readme = (HERE / 'README.txt').read_text(encoding='utf-8') if (HERE / 'README.txt').is_file() else README
        text(tar, 'README.txt', readme)
        if (HERE / 'LICENSE').is_file():
            text(tar, 'LICENSE.txt', (HERE / 'LICENSE').read_text(encoding='utf-8'))
        for name in APP:
            text(tar, 'app/' + name, (HERE / name).read_text(encoding='utf-8'))
        for name in OPTIONAL:
            if (HERE / name).is_file():
                file(tar, HERE / name, 'app/' + name)
        if '--no-mods' not in sys.argv:
            shipped = share_mods()
            for mod, as_name in shipped:
                for p in sorted(mod.rglob('*')):
                    if p.is_file():
                        file(tar, p, 'mods/' + as_name + '/' + p.relative_to(mod).as_posix())
            text(tar, 'mods/' + BUNDLED_LIST, '\n'.join(n for _m, n in shipped) + '\n')
    tmp.replace(LINUX_OUT)
    print(f'{LINUX_OUT}  {LINUX_OUT.stat().st_size / 1e6:.1f} MB')


def main():
    global PYTHON
    if '--linux' in sys.argv:        # the Linux download instead (no Python inside: it uses the system's)
        build_linux()
        return
    if '--python' in sys.argv:       # another Python 3.14 folder (with tkinter) to put in the zip
        PYTHON = Path(sys.argv[sys.argv.index('--python') + 1])
    if not (PYTHON / 'pythonw.exe').is_file():
        sys.exit(f'No Python at {PYTHON}: pass --python "<a Python 3.14 folder with pythonw.exe and tkinter>"')
    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix('.zip.part')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        root = 'Link Toolbox/'
        z.writestr(root + 'Link Toolbox.bat', BAT.replace('\n', '\r\n'))
        z.writestr(root + 'Install Link Toolbox.bat', INSTALL_BAT.replace('\n', '\r\n'))
        readme = (HERE / 'README.txt').read_text(encoding='utf-8') if (HERE / 'README.txt').is_file() else README
        z.writestr(root + 'README.txt', readme.replace('\r\n', '\n').replace('\n', '\r\n'))
        if (HERE / 'LICENSE').is_file():
            z.write(HERE / 'LICENSE', root + 'LICENSE.txt')
        for name in APP:
            z.write(HERE / name, root + 'app/' + name)
        for name in OPTIONAL:
            if (HERE / name).is_file():
                z.write(HERE / name, root + 'app/' + name)
        if '--no-mods' not in sys.argv:
            shared = share_mods()
            for mod, as_name in shared:
                for p in sorted(mod.rglob('*')):
                    if p.is_file():
                        z.write(p, root + 'mods/' + as_name + '/' + p.relative_to(mod).as_posix(),
                                compress_type=zipfile.ZIP_STORED if p.suffix == '.zs' else zipfile.ZIP_DEFLATED)
            # the list of the download's own mods: an updated copy removes bundled folders that are not on it
            z.writestr(root + 'mods/' + BUNDLED_LIST, '\r\n'.join(n for _m, n in shared) + '\r\n')
            print('mods:', ', '.join(n for _m, n in shared) or 'none')
        n = 0
        for p in sorted(PYTHON.rglob('*')):
            rel = p.relative_to(PYTHON)
            if p.is_dir() or rel.parts[0] in SKIP_PY or '__pycache__' in rel.parts:
                continue
            z.write(p, root + 'python/' + rel.as_posix())
            n += 1
    tmp.replace(OUT)
    print(f'{OUT}  {OUT.stat().st_size / 1e6:.1f} MB  ({len(APP)} scripts, {n} Python files)')


if __name__ == '__main__':
    main()
