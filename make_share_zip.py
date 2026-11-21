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
       'size_table.py', 'pack_merge.py', 'theme.py', 'icons.py', 'updater.py', 'install.py', 'builds.py', 'busy.py',
       'code_mods.py', 'code_mods_ui.py', 'dragdrop.py')
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

README = '''Link''s Tool Box - mod loader and save editor for Zelda: Ocarina of Time on Longshot
==============================================================================
Link's Tool Box, by Cum_Dumpster

Start:   unzip this folder anywhere (Desktop, Documents...), then double-click "Link Toolbox.bat".
         Nothing to install: the Python it needs is in the python folder.

The game folder
    The toolbox finds the game where Longshot's launcher built it (Games\\Longshot). If it cannot,
    it asks once: pick the folder that has longshot.exe and the romfs folder in it. To change it later:
    the Folders tab.

Tabs
    Mods         switch the mods in the game's mods folder on and off, set which wins, Save and play.
                 Longshot loads mods from the "mods" folder next to longshot.exe (Triforce works too).
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
# ONLY these mods ever go in the download, whatever else is in (or switched on in) the mods folder: a mod is added to
# this list only when the owner says so. Shipped on, in this order:
SHIP = ('Young Link Mirror Shield', 'Young Link Hylian Shield', 'Young Link All Items', 'Young Link Adult Motions',
        'Biggoron One-Handed')
SHIP_OFF = ('Young Link Two-Handed Swords',)     # shipped switched off (it replaces the same file as One-Handed)
# (no size table: it is built from each player's own game and mods when they press Save)


def share_mods():
    """[(folder, name in the download)]: the SHIP mods (on, numbered in SHIP's order) and the SHIP_OFF mods (off: a
    leading _), taken from the game's mods folder. Nothing else, even if it is on there."""
    sys.path.insert(0, str(HERE))
    import nxsave
    # (from the game the toolbox is set to: the main build, Longshot rc; with sharing on, the shared mods folder;
    #  --mods-from <folder>: a clean set instead, when the player's own copies were changed by other mods' files)
    if '--mods-from' in sys.argv:
        mods = Path(sys.argv[sys.argv.index('--mods-from') + 1])
    else:
        mods = nxsave.mods_dir_for(nxsave.game_dir())
    print('mods from:', mods)
    import re
    plain = lambda name: re.sub(r'^(?:[-_]+)?(?:\d+-)?', '', name)
    found = {}
    for p in sorted(mods.iterdir()) if mods.is_dir() else []:
        if p.is_dir() and (p / 'romfs').is_dir():
            found.setdefault(plain(p.name), p)
    missing = [n for n in SHIP + SHIP_OFF if n not in found]
    if missing:
        sys.exit(f'Not in {mods}: {", ".join(missing)} (the download must have every mod on the SHIP list)')
    left = sorted(n for n in found if n not in SHIP + SHIP_OFF)
    if left:
        print('left out (not on the SHIP list):', ', '.join(left))
    out = [(found[n], f'{i:02d}-{n}') for i, n in enumerate(SHIP, 1)]
    out += [(found[n], f'_{n}') for n in SHIP_OFF]
    return out


LINUX_OUT = HERE / 'share' / 'Link Toolbox (Linux).tar.gz'
SH = '''#!/bin/sh
# Opens Link's Tool Box (mod loader and save editor) with this computer's Python: 3.10 or newer, with Tk. For the
# game's packed files it also needs Zstandard: Python 3.14's own, or the zstandard module on an older Python.
# What goes wrong is shown in a message box (or in the terminal) and kept in "Link Toolbox error.log" here.
cd "$(dirname "$0")" || exit 1
LOG="Link Toolbox error.log"
PYS="python3.17 python3.16 python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3 python"
TK='import sys, tkinter
sys.exit(sys.version_info < (3, 10))'
ZS='import sys, tkinter
try:
    import compression.zstd
except ImportError:
    import zstandard
sys.exit(sys.version_info < (3, 10))'

pick() {     # the first Python that runs the check $1
  for p in $PYS; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c "$1" >/dev/null 2>&1; then echo "$p"; return 0; fi
  done
  return 1
}

say() {      # a message where it can be seen: a dialog, the terminal, and the log
  printf '%s\\n' "$1" >&2
  printf '%s  Link Toolbox.sh\\n%s\\n\\n' "--- $(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG" 2>/dev/null
  if [ -t 0 ] && [ -t 1 ]; then
    printf '\\nPress Enter to close.' >&2; read -r _
  elif command -v zenity >/dev/null 2>&1; then zenity --error --title="Link's Tool Box" --text="$1"
  elif command -v kdialog >/dev/null 2>&1; then kdialog --title "Link's Tool Box" --error "$1"
  elif command -v xmessage >/dev/null 2>&1; then printf '%s\\n' "$1" | xmessage -center -file -
  elif command -v notify-send >/dev/null 2>&1; then notify-send "Link's Tool Box" "$1"
  fi
}

py=$(pick "$ZS") || py=$(pick "$TK")
if [ -n "$py" ]; then
  "$py" app/toolbox.pyw "$@"
  status=$?
  # (the toolbox shows and logs its own errors; in a terminal, keep it open to read them)
  if [ "$status" -ne 0 ] && [ -t 0 ] && [ -t 1 ]; then
    printf '\\nLink'"'"'s Tool Box stopped (exit code %s). The details are in "%s".\\nPress Enter to close.' \\
      "$status" "$PWD/$LOG" >&2
    read -r _
  fi
  exit "$status"
fi

found=''
for p in $PYS; do
  if command -v "$p" >/dev/null 2>&1; then
    v=$("$p" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null)
    if "$p" -c 'import tkinter' >/dev/null 2>&1; then t='with Tk'; else t='no Tk'; fi
    found="$found
  $p ($(command -v "$p")): ${v:-?}, $t"
  fi
done
say "Link's Tool Box needs Python 3.10 or newer, with Tk.

Found on this computer:${found:-
  no Python}

Install them, then open Link Toolbox.sh again. For example:
  Ubuntu / Debian / Mint:  sudo apt install python3 python3-tk python3-zstandard
  Fedora:                  sudo dnf install python3 python3-tkinter python3-zstandard
  Arch / Manjaro:          sudo pacman -S python tk python-zstandard
(zstandard is needed on Pythons older than 3.14, to read the game's packed files.)"
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


MOD_ZIPS = HERE / 'share' / 'mods'


def mod_asset(name):
    """The release file name of one mod's own zip: 'Mod.Young.Link.Mirror.Shield.zip' (GitHub turns spaces into dots
    anyway)."""
    return 'Mod.' + '.'.join(name.replace('-', ' - ').split()).replace('.-.', '-') + '.zip'


def build_mod_zips():
    """share\\mods\\<asset>.zip: each mod of the download on its own (one folder with its plain name and romfs), to
    download separately. The same files as the download's mods."""
    import re
    MOD_ZIPS.mkdir(parents=True, exist_ok=True)
    for old in MOD_ZIPS.glob('*.zip'):
        old.unlink()
    for mod, as_name in share_mods():
        plain = re.sub(r'^(?:[-_]+)?(?:\d+-)?', '', as_name)
        out = MOD_ZIPS / mod_asset(plain)
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(mod.rglob('*')):
                if p.is_file():
                    z.write(p, plain + '/' + p.relative_to(mod).as_posix(),
                            compress_type=zipfile.ZIP_STORED if p.suffix == '.zs' else zipfile.ZIP_DEFLATED)
        print(f'{out}  {out.stat().st_size / 1e6:.2f} MB')


def main():
    global PYTHON
    if '--linux' in sys.argv:        # the Linux download instead (no Python inside: it uses the system's)
        build_linux()
        return
    if '--mod-zips' in sys.argv:     # each bundled mod on its own, for downloading separately
        build_mod_zips()
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
