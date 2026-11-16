"""Reading and writing the game's save files (account.sav, option.sav, slot_NN/progress.sav, slot_NN/caption.sav).

A save file is a table of (hash, value) pairs grouped by type, then a data section:

    0x00  u32 magic 0x01020304, u32 version, u32 offset of the data section, zeros to 0x20
    0x20  pairs of u32: (0, type number) starts a type's group; (hash, value) is one entry of the current type.
          A small value (on/off, number, float, enum) is the value itself; any other is an offset into the file.
    data  texts are fixed-size and NUL-ended, a list is a u32 count then its items, a binary is a u32 size then bytes.

Nothing is ever moved or resized: an edit overwrites a value in place, so the file keeps its size and layout.

The names of the entries are not in the save (only murmur3 hashes of them). They are recovered from the player's own
game files (game/romfs) the first time and kept in names-cache.json next to this file.
"""
import json
import os
import re
import struct
import time
from pathlib import Path

try:
    import compression.zstd as zstd     # Python 3.14+
except ImportError:                      # pragma: no cover
    zstd = None

VERSION = '1.3.3'        # Link's Tool Box version (the updater compares it with the newest GitHub release)
APP_NAME = "Link's Tool Box"      # the app's name as shown everywhere (file and folder names stay "Link Toolbox":
                                  # the updaters already out there look for those)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MAGIC = 0x01020304
TYPES = ['Bool', 'BoolArray', 'Int', 'IntArray', 'Float', 'FloatArray', 'Enum', 'EnumArray', 'Vector2', 'Vector2Array',
         'Vector3', 'Vector3Array', 'String16', 'String16Array', 'String32', 'String32Array', 'String64',
         'String64Array', 'Binary', 'BinaryArray', 'UInt', 'UIntArray', 'Int64', 'Int64Array', 'UInt64', 'UInt64Array',
         'WString16', 'WString16Array', 'WString32', 'WString32Array', 'WString64', 'WString64Array', 'Bool64bitKey']
INLINE = {'Bool', 'Int', 'UInt', 'Float', 'Enum'}
READ_ONLY = {'Binary', 'BinaryArray', 'Bool64bitKey'}
# an item of the type: (struct format, size in bytes); texts are handled apart
ITEM = {'Int': ('<i', 4), 'UInt': ('<I', 4), 'Float': ('<f', 4), 'Enum': ('<I', 4), 'Int64': ('<q', 8),
        'UInt64': ('<Q', 8), 'Vector2': ('<2f', 8), 'Vector3': ('<3f', 12)}
RANGE = {'Int': (-2**31, 2**31 - 1), 'UInt': (0, 2**32 - 1), 'Int64': (-2**63, 2**63 - 1), 'UInt64': (0, 2**64 - 1)}


def murmur3(b):
    h = 0
    n = len(b) & ~3
    for (k,) in struct.iter_unpack('<I', b[:n]):
        k = (k * 0xcc9e2d51) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = (k * 0x1b873593) & 0xffffffff
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xffffffff
        h = (h * 5 + 0xe6546b64) & 0xffffffff
    if len(b) > n:
        k = int.from_bytes(b[n:], 'little')
        k = (k * 0xcc9e2d51) & 0xffffffff
        k = ((k << 15) | (k >> 17)) & 0xffffffff
        k = (k * 0x1b873593) & 0xffffffff
        h ^= k
    h ^= len(b)
    h ^= h >> 16
    h = (h * 0x85ebca6b) & 0xffffffff
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & 0xffffffff
    return h ^ (h >> 16)


# ---------------------------------------------------------------------------------------------- the save file

def _text_size(t):
    """(bytes of one text, wide) for a text type or a list of them, else None."""
    m = re.match(r'^(W?)String(\d+)(Array)?$', t)
    return (int(m.group(2)) * (2 if m.group(1) else 1), bool(m.group(1))) if m else None


class Entry:
    __slots__ = ('hash', 'type', 'pos', 'raw', 'value', 'original')

    def __init__(self, hash_, type_, pos, raw):
        self.hash, self.type, self.pos, self.raw = hash_, type_, pos, raw
        self.value = self.original = None

    @property
    def is_list(self):
        return self.type.endswith('Array')

    @property
    def base(self):
        return self.type[:-5] if self.is_list else self.type

    @property
    def editable(self):
        return self.type not in READ_ONLY

    @property
    def changed(self):
        return self.value != self.original


class SaveFile:
    def __init__(self, path):
        self.path = Path(path)
        self.buf = bytearray(self.path.read_bytes())
        self.entries = []
        self._parse()

    def _parse(self):
        b = self.buf
        if len(b) < 0x20:
            raise ValueError('not a save file: too small')
        magic, self.version, self.data_off = struct.unpack_from('<III', b, 0)
        if magic != MAGIC or not 0x20 <= self.data_off <= len(b):
            raise ValueError('not a save file of this game')
        cur = None
        for pos in range(0x20, self.data_off - 7, 8):
            h, v = struct.unpack_from('<II', b, pos)
            if h == 0:
                if v >= len(TYPES):
                    raise ValueError(f'unknown type number {v} at 0x{pos:x}')
                cur = TYPES[v]
                continue
            if cur is None:
                raise ValueError('an entry before any type')
            e = Entry(h, cur, pos + 4, v)
            e.value = e.original = self._read(e)
            self.entries.append(e)

    # -- reading
    def _read_item(self, base, off):
        b = self.buf
        ts = _text_size(base)
        if ts:
            size, wide = ts
            raw = bytes(b[off:off + size])
            if wide:
                return raw.decode('utf-16-le', 'replace').split('\0')[0]
            return raw.split(b'\0')[0].decode('utf-8', 'replace')
        fmt, _ = ITEM[base]
        v = struct.unpack_from(fmt, b, off)
        return v[0] if len(v) == 1 else tuple(v)

    def _item_size(self, base):
        ts = _text_size(base)
        return ts[0] if ts else ITEM[base][1]

    def _read(self, e):
        b, v, t = self.buf, e.raw, e.type
        if t == 'Bool':
            return bool(v)
        if t in INLINE:
            return struct.unpack(ITEM[t][0], struct.pack('<I', v))[0]
        if not self.data_off <= v <= len(b) - 4 and t != 'Bool64bitKey':
            raise ValueError(f'entry {e.hash:08x}: offset 0x{v:x} is outside the file')
        if t == 'Binary':
            n, = struct.unpack_from('<I', b, v)
            return bytes(b[v + 4:v + 4 + n])
        if t in ('BinaryArray', 'Bool64bitKey'):
            return None
        if not e.is_list:
            return self._read_item(t, v)
        n, = struct.unpack_from('<I', b, v)
        if t == 'BoolArray':
            if v + 4 + (n + 7) // 8 > len(b):
                raise ValueError(f'entry {e.hash:08x}: the list runs past the end of the file')
            return tuple(bool(b[v + 4 + i // 8] >> (i % 8) & 1) for i in range(n))
        size = self._item_size(e.base)
        if v + 4 + n * size > len(b):
            raise ValueError(f'entry {e.hash:08x}: the list runs past the end of the file')
        return tuple(self._read_item(e.base, v + 4 + i * size) for i in range(n))

    def extent(self, e):
        """(offset, size) of the entry's bytes in the data section, None for a value kept in the table."""
        if e.type in INLINE or e.type in ('BinaryArray', 'Bool64bitKey'):
            return None
        if e.type == 'Binary':
            return e.raw, 4 + len(e.value)
        if not e.is_list:
            return e.raw, self._item_size(e.type)
        if e.type == 'BoolArray':
            return e.raw, 4 + (len(e.value) + 7) // 8
        return e.raw, 4 + len(e.value) * self._item_size(e.base)

    # -- writing
    def _pack_item(self, base, value):
        ts = _text_size(base)
        if ts:
            size, wide = ts
            raw = value.encode('utf-16-le' if wide else 'utf-8')
            if len(raw) > size - (2 if wide else 1):
                raise ValueError(f'the text is too long: at most {size // (2 if wide else 1) - 1} characters')
            return raw.ljust(size, b'\0')
        fmt, _ = ITEM[base]
        if base in RANGE:
            lo, hi = RANGE[base]
            if not lo <= value <= hi:
                raise ValueError(f'{value} is out of range ({lo} to {hi})')
        return struct.pack(fmt, *value) if isinstance(value, tuple) else struct.pack(fmt, value)

    def set(self, e, value):
        """Change an entry's value in the buffer. A list keeps its length."""
        if not e.editable:
            raise ValueError('this kind of entry cannot be edited')
        b = self.buf
        if e.type == 'Bool':
            struct.pack_into('<I', b, e.pos, 1 if value else 0)
            e.raw = 1 if value else 0
        elif e.type in INLINE:
            raw = self._pack_item(e.type, value)
            b[e.pos:e.pos + 4] = raw
            e.raw, = struct.unpack('<I', raw)
        elif not e.is_list:
            raw = self._pack_item(e.type, value)
            b[e.raw:e.raw + len(raw)] = raw
        else:
            value = tuple(value)
            if len(value) != len(e.value):
                raise ValueError(f'the list must keep its {len(e.value)} items')
            if e.type == 'BoolArray':
                bits = bytearray((len(value) + 7) // 8)
                for i, x in enumerate(value):
                    if x:
                        bits[i // 8] |= 1 << (i % 8)
                b[e.raw + 4:e.raw + 4 + len(bits)] = bits
            else:
                raw = b''.join(self._pack_item(e.base, x) for x in value)
                b[e.raw + 4:e.raw + 4 + len(raw)] = raw
        e.value = self._read(e)

    @property
    def dirty(self):
        return any(e.changed for e in self.entries)

    def save(self, backup_dir=None):
        """Write the file (through a temporary file), after copying the one on disk into backup_dir."""
        if backup_dir:
            dst = Path(backup_dir) / time.strftime('%Y-%m-%d %H%M%S') / self.path.parent.name / self.path.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(self.path.read_bytes())
        tmp = self.path.with_name(self.path.name + '.editing')
        tmp.write_bytes(self.buf)
        tmp.replace(self.path)
        for e in self.entries:
            e.original = e.value


# ------------------------------------------------------------------------------------- the install's folders

GAME_PROCESSES = ('Triforce.exe', 'TriforceSetup.exe', 'ocarina.exe', 'longshot.exe', 'LongshotLauncher.exe')
# the apps that play the game, by the program each puts in the game folder: Triforce; Longshot (another PC port, by
# MagicBeanDev); NX2navi (the older launcher: its ocarina.exe; Triforce may have built into the same folder)
APPS = (('Triforce', 'Triforce.exe'), ('Longshot', 'longshot.exe'), ('NX2navi', 'ocarina.exe'))
GAME_EXES = tuple(exe for _app, exe in APPS)


def apps_in(game):
    """The apps whose program is in a game folder, in the order above."""
    game = Path(game)
    return [app for app, exe in APPS if program(game, exe)]


WINDOWS = os.name == 'nt'
HOME = Path.home()


def program(game, exe):
    """A game program in a folder: 'longshot.exe' on Windows; on Linux also 'longshot' (no .exe, a native build)."""
    for name in (exe,) if WINDOWS else (exe[:-4] if exe.endswith('.exe') else exe, exe):
        p = Path(game) / name
        if p.is_file():
            return p
    return None


def open_folder(path):
    """Shows a folder in the file manager (Explorer on Windows, the desktop's own on Linux)."""
    import subprocess
    Path(path).mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(['xdg-open', str(path)])


def app_of(game=None):
    """The app a game folder is played with: the one picked in the Folders tab when its program is there, else the
    first one there; 'Game files' for a romfs folder without any."""
    game = Path(game or game_dir())
    there = apps_in(game)
    chosen = load_settings().get('game_app')
    if chosen in there:
        return chosen
    return there[0] if there else 'Game files'


def game_exe(game=None):
    """The program that starts the game (the app's: Triforce.exe, longshot.exe or ocarina.exe), None when none."""
    game = Path(game or game_dir())
    exe = dict(APPS).get(app_of(game))
    return program(game, exe) if exe else None


def is_longshot(game=None):
    return app_of(game) == 'Longshot'


def ignore_running():
    """The player chose to save even while the game runs (the "Save while the game runs" checkbox)."""
    return bool(load_settings().get('ignore_running'))


def set_ignore_running(on):
    s = load_settings()
    if on:
        s['ignore_running'] = True
    else:
        s.pop('ignore_running', None)
    save_settings(s)


def blocking_game():
    """The running game that stops saving: '' when none runs, or when the player chose to save anyway."""
    return '' if ignore_running() else game_running()


_ignore_var = None


def ignore_running_var(master):
    """One checkbox value for every tab (ticking it in one tab ticks it in the others)."""
    global _ignore_var
    if _ignore_var is None:
        import tkinter as tk
        _ignore_var = tk.BooleanVar(master, value=ignore_running())
    return _ignore_var


IGNORE_RUNNING_WARNING = (
    'Save even while the game is running?\n\n'
    '  Saves: the game keeps its own copy of the save and writes it back when it saves, so your edits can be '
    'written over. Load the slot again in the game (or restart it) right after saving.\n'
    '  Mods: the game read the mods when it started. Changed mods are used from the next start; files swapped '
    'while it runs can make it crash.\n\n'
    'Backups are still made before every save. The toolbox remembers this choice: untick the box to go back.')


def game_running():
    """The name of the game's program when it is running, else ''."""
    import subprocess
    try:
        if WINDOWS:
            out = subprocess.run(['tasklist', '/NH'], capture_output=True, text=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.lower()
        else:     # (Linux: the programs by name, with or without .exe: native, or Windows ones through Wine/Proton)
            out = subprocess.run(['ps', '-A', '-o', 'args='], capture_output=True, text=True).stdout.lower()
    except OSError:
        return ''
    for n in GAME_PROCESSES:
        stem = n.lower()[:-4] if n.lower().endswith('.exe') else n.lower()
        if n.lower() in out or (not WINDOWS and re.search(rf'(^|/){re.escape(stem)}(\s|$)', out, re.M)):
            return n
    return ''


def is_game_dir(d):
    """The game's folder: the one with Triforce.exe (or Longshot's longshot.exe) and the game's files (romfs)."""
    d = Path(d)
    return d.is_dir() and (any(program(d, n) for n in GAME_EXES) or (d / 'romfs').is_dir())


def _game_dir_candidates():
    yield load_settings().get('game_dir')                   # picked in the toolbox's Folders tab
    try:                                                    # the NX2navi launcher's own setting
        yield json.loads((ROOT / 'data' / 'launcher.json').read_text(encoding='utf-8')).get('game_dir')
    except (OSError, ValueError):
        pass
    yield ROOT / 'game'                                     # (the folder above the toolbox's: NX2navi's game when it ran from there)
    local = os.environ.get('LOCALAPPDATA', '')
    if local:                                               # (Windows)
        try:                                                # Triforce's installer logs where it put the game
            log = Path(local, 'Programs', 'Triforce', 'setup.log').read_text(encoding='utf-8', errors='replace')
            found = re.findall(r'GameFolder=\[([^\]]+)\]', log)
            if found:
                yield found[-1]
        except OSError:
            pass
        yield Path(local, 'Programs', 'NX2navi', 'game')
    # Longshot: its launcher builds the game in Games\Longshot in the home folder (or a folder in it, one per version);
    # on Linux also where it keeps its data
    homes = [HOME / 'Games' / 'Longshot']
    if not WINDOWS:
        homes += [HOME / '.local' / 'share' / 'longshot', HOME / 'Games' / 'longshot']
    for longshot in homes:
        yield longshot
        if longshot.is_dir():
            yield from sorted((p for p in longshot.iterdir() if program(p, 'longshot.exe')),
                              key=lambda p: p.stat().st_mtime, reverse=True)
    yield from remembered('games')     # game folders typed in the Folders tab and kept


# --------------------------------------------------------------------------- Longshot builds, and one shared mods folder
# Longshot's launcher builds every version into a folder of its own (Games\Longshot\rc, ...): a new build starts with
# an empty mods folder. The toolbox spots new builds (and brings the mods along), or points Longshot at one shared mods
# folder for every build (its HOS_MODS setting, a Windows user environment variable).

VERSION_FILES = {'Triforce': 'triforce_version.txt', 'Longshot': 'longshot_version.txt'}


def build_version(build, app=None):
    """'v3.0.0-rc.4' / 'v0.4.0' from a build's version file (Triforce's or Longshot's: 'version=...'), '' when it has
    none (NX2navi and other apps: then the program's date tells which build is newer)."""
    names = [VERSION_FILES[app]] if app in VERSION_FILES else list(VERSION_FILES.values())
    for name in names:
        try:
            for line in (Path(build) / name).read_text(encoding='utf-8', errors='replace').splitlines():
                if line.startswith('version='):
                    return line.split('=', 1)[1].strip()
        except OSError:
            pass
    return ''


def longshot_version(build):
    return build_version(build, 'Longshot')


def builds_of(app):
    """[(version, folder)] of every build of an app found (Triforce, Longshot, NX2navi...), the newest first."""
    exe = dict(APPS).get(app)
    out = [(build_version(d, app), d) for a, d in all_game_dirs() if a == app]
    return sorted(out, key=lambda vb: version_key(vb[0], vb[1], exe), reverse=True)


# -- one shared mods folder for every build of every app: each build's "mods" folder becomes a link to it (a Windows
#    junction, no admin needed; a symlink on Linux), so any app reading its mods folder reads the shared one.
def shared_folder():
    """The shared mods folder set in the Folders tab, None when sharing is off."""
    p = load_settings().get('shared_mods')
    return Path(p) if p else None


def is_link(p):
    p = Path(p)
    try:
        return p.is_symlink() or bool(getattr(os.path, 'isjunction', lambda _x: False)(p))
    except OSError:
        return False


def link_target(p):
    try:
        return Path(os.path.realpath(p))
    except OSError:
        return None


def make_link(link, target):
    """A folder link at link -> target (Windows: a junction, which needs no admin)."""
    import subprocess
    link, target = Path(link), Path(target)
    if WINDOWS:
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True, text=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if r.returncode != 0 or not is_link(link):
            raise OSError(f'the link {link} could not be made: {(r.stdout + r.stderr).strip()}')
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_link(link):
    """Removes a folder link ONLY (never what it points to)."""
    link = Path(link)
    if not is_link(link):
        raise OSError(f'{link} is not a link: not removed')
    if link.is_symlink() and not WINDOWS:
        link.unlink()
    else:
        os.rmdir(link)        # (on a junction: removes the link itself, the folder it points to stays)


def version_key(version, build=None, exe_name='longshot.exe'):
    """Sortable: v3.0.0 > v3.0.0-rc.5 > v3.0.0-rc.4; no version: the date of the build's program."""
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)(?:[-.]?rc\.?(\d+))?', version or '')
    if not m:
        exe = program(build, exe_name or 'longshot.exe') if build else None
        return (0, 0, 0, 0, 0, exe.stat().st_mtime if exe else 0)
    a, b, c, rc = m.groups()
    return (int(a), int(b), int(c), 0 if rc else 1, int(rc or 0), 0)


def longshot_builds():
    return builds_of('Longshot')


def shared_mods():
    """The shared mods folder every Longshot build uses (its HOS_MODS setting), None when it isn't set."""
    value = ''
    if WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:
                value = winreg.QueryValueEx(k, 'HOS_MODS')[0]
        except OSError:
            value = ''
    value = value or os.environ.get('HOS_MODS', '')
    return Path(os.path.expandvars(value)) if value else None


def set_shared_mods(path):
    """Sets (path) or removes (None) Longshot's HOS_MODS for this Windows user, and tells Windows, so programs started
    from now on (Longshot's launcher too) see it. This toolbox's own Save and play gets it straight away."""
    if not WINDOWS:
        raise OSError('the shared mods folder is set up on Windows only (on Linux, set HOS_MODS in your profile)')
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_SET_VALUE) as k:
        if path:
            winreg.SetValueEx(k, 'HOS_MODS', 0, winreg.REG_SZ, str(path))
        else:
            try:
                winreg.DeleteValue(k, 'HOS_MODS')
            except OSError:
                pass
    if path:
        os.environ['HOS_MODS'] = str(path)
    else:
        os.environ.pop('HOS_MODS', None)
    try:      # (WM_SETTINGCHANGE "Environment" to every window: new programs get the new value)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, 'Environment', 2, 3000, ctypes.byref(ctypes.c_size_t()))
    except (AttributeError, OSError):
        pass


def mods_dir_for(game, app=None):
    """A game's mods folder: Longshot's shared one when it is set, else the mods folder in the game folder."""
    app = app or app_of(game)
    shared = shared_mods() if app == 'Longshot' else None
    return shared if shared else Path(game) / 'mods'


def remembered(kind):
    """The folders the player typed in the Folders tab and chose to keep: kind 'games' or 'saves'."""
    return [p for p in load_settings().get(f'remembered_{kind}', []) if isinstance(p, str)]


def remember(kind, path, keep=True):
    """Keeps (or, keep=False, forgets) a folder in the Folders tab's lists."""
    s = load_settings()
    have = [p for p in s.get(f'remembered_{kind}', []) if os.path.normcase(p) != os.path.normcase(str(path))]
    if keep:
        have.append(str(path))
    s[f'remembered_{kind}'] = have
    save_settings(s)


def is_remembered(kind, path):
    return any(os.path.normcase(p) == os.path.normcase(str(path)) for p in remembered(kind))


def all_game_dirs():
    """[(app, folder)] of every game found in the usual places: one row per app whose program a folder has (a folder
    with both Triforce.exe and NX2navi's ocarina.exe gives two), the one the toolbox would use first."""
    out, seen = [], set()
    for d in _game_dir_candidates():
        if not d or not is_game_dir(d):
            continue
        key = os.path.normcase(str(Path(d).resolve()))
        if key in seen:
            continue
        seen.add(key)
        for app in apps_in(d) or ['Game files']:
            out.append((app, Path(d)))
    return out


def find_game_dir():
    """The game's folder, None when none of the places it is usually kept has it."""
    for d in _game_dir_candidates():
        if d and is_game_dir(d):
            return Path(d)
    return None


def game_dir():
    return find_game_dir() or ROOT / 'game'


SAVE_BASES = (('user', 'save'),        # Triforce
              ('profile', 'save'))     # NX2navi before Triforce

# The folders the player chose in the toolbox's Folders tab ({"mods_dir": ..., "save_dir": ...}); empty: the defaults.
SETTINGS = HERE / 'toolbox_settings.json'


SETTINGS_OVERRIDE = None    # (the toolbox sets it for a moment: where would the game be found without its choice)


def load_settings():
    if SETTINGS_OVERRIDE is not None:
        return dict(SETTINGS_OVERRIDE)
    try:
        d = json.loads(SETTINGS.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d):
    SETTINGS.write_text(json.dumps({k: v for k, v in d.items() if v}, indent=1), encoding='utf-8')


def is_account_dir(d):
    """A folder that holds one save: its slot folders or its account/option files."""
    d = Path(d)
    return d.is_dir() and (any(d.glob('slot_[0-9][0-9]')) or (d / 'option.sav').is_file() or (d / 'account.sav').is_file())


def save_dirs_in(folder):
    """The save folders in a folder the player picked: that folder when it is one, else the ones in it, latest first."""
    folder = Path(folder)
    if is_account_dir(folder):
        return [folder]
    found = [d for d in folder.iterdir() if is_account_dir(d)] if folder.is_dir() else []
    return sorted(found, key=lambda d: max((f.stat().st_mtime for f in d.rglob('*.sav')), default=0), reverse=True)


def save_dirs(game=None):
    """The account folders that hold a save: the one chosen in the toolbox's Folders tab when there is one (a save's
    own folder, or a folder of them), else Triforce's (user/save) first, then the old launcher's (profile/save), each
    the latest written first."""
    game = game or game_dir()
    chosen = load_settings().get('save_dir')
    if chosen and Path(chosen).is_dir():
        return save_dirs_in(chosen)
    out = []
    for base in save_bases(game, app_of(game)):
        out += accounts_in(base)
    return out


def longshot_data():
    """Longshot's own data folder (its launcher keeps the saves there): %APPDATA%\\Longshot, or on Linux
    ~/.local/share/longshot."""
    if WINDOWS and os.environ.get('APPDATA'):
        return Path(os.environ['APPDATA']) / 'Longshot'
    return HOME / '.local' / 'share' / 'longshot'


def save_bases(game, app):
    """The folders an app keeps its save accounts in, its own first."""
    game = Path(game)
    bases = [game.joinpath(*parts) for parts in SAVE_BASES]
    if app == 'Longshot':     # Longshot started from its launcher keeps the saves in %APPDATA%\Longshot\save
        bases.insert(0, longshot_data() / 'save')
    elif app == 'NX2navi':    # NX2navi's own saves: profile/save (Triforce moved its copies to user/save)
        bases.reverse()
    return bases


def accounts_in(base):
    """The save accounts (32-hex folders) in a saves folder, the latest written first."""
    base = Path(base)
    found = [d for d in base.iterdir() if d.is_dir() and re.fullmatch(r'[0-9a-fA-F]{32}', d.name)] \
        if base.is_dir() else []
    return sorted(found, key=lambda d: max((f.stat().st_mtime for f in d.rglob('*.sav')), default=0), reverse=True)


def all_mod_locations():
    """[(label, mods folder, program)] of every mods folder: each game's (Triforce and NX2navi share one folder, so
    one row 'Triforce / NX2navi'), the one set in the Folders tab, and those kept from it. program: the game that
    Save and play starts for those mods (None for a kept folder outside any game)."""
    rows, by_key = [], {}

    def add(label, d, exe):
        key = os.path.normcase(str(Path(d).resolve()))
        if key in by_key:
            i = by_key[key]
            if label not in rows[i][0].split(' / '):
                rows[i] = (f'{rows[i][0]} / {label}', rows[i][1], rows[i][2])
            return
        by_key[key] = len(rows)
        rows.append((label, Path(d), exe))
    for app, game in all_game_dirs():
        exe = dict(APPS).get(app)
        label = f'{app} ({Path(game).name})' if is_remembered('games', game) else app
        add(label, mods_dir_for(game, app), program(game, exe) if exe else None)
    for label, d in [('Folders tab', load_settings().get('mods_dir'))] + [('Kept', p) for p in remembered('mods')]:
        if d and Path(d).is_dir():
            add(label, d, game_exe(Path(d).parent) if is_game_dir(Path(d).parent) else None)
    return _tell_apart(rows, lambda d: d.parent.name)


def _tell_apart(rows, where):
    """Rows whose labels repeat get the folder they come from added: 'Triforce (OtherGame)'."""
    counts = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    return [(f'{r[0]} ({where(r[1])})',) + tuple(r[1:]) if counts[r[0]] > 1 else r for r in rows]


def all_save_locations():
    """[(app, account folder)] of every save the toolbox can find: each game's own saves folder (Triforce: user/save,
    NX2navi: profile/save, Longshot: %APPDATA%/Longshot/save or its user/save), and the one set in the Folders tab."""
    out, seen = [], set()

    def add(app, d):
        key = os.path.normcase(str(Path(d).resolve()))
        if key not in seen:
            seen.add(key)
            out.append((app, Path(d)))
    chosen = load_settings().get('save_dir')
    if chosen and Path(chosen).is_dir():
        for d in save_dirs_in(chosen):
            add('Folders tab', d)
    for app, game in all_game_dirs():
        own = save_bases(game, app)
        # each app's own place first; Triforce and NX2navi share a game folder, so each claims only its own
        mine = own[:1] if app in ('Triforce', 'NX2navi') else own[:2]
        for base in mine:
            for d in accounts_in(base):
                add(app, d)
    for kept in remembered('saves'):   # saves folders typed in the Folders tab and kept
        if Path(kept).is_dir():
            for d in save_dirs_in(kept):
                add('Kept', d)
    return out


def save_files(account_dir):
    """[(label, path)] of the save files in an account folder."""
    out = []
    for d in sorted(account_dir.glob('slot_[0-9][0-9]')):
        n = int(d.name[5:])
        for name, what in (('progress.sav', 'progress'), ('caption.sav', 'file-select summary')):
            if (d / name).is_file():
                out.append((f'Slot {n + 1} - {what}', d / name))
    for name, what in (('option.sav', 'Options'), ('account.sav', 'Account')):
        if (account_dir / name).is_file():
            out.append((what, account_dir / name))
    return out


# ------------------------------------------------------------------------------------ names, from the game files

class Romfs:
    """The game's files: either one packed file (romfs/romfs.bin with romfs/index.json, NX2navi before 0.12) or the
    files themselves under romfs/ (NX2navi 0.12 and its Triforce installer)."""

    def __init__(self, game):
        self.folder = folder = Path(game) / 'romfs'
        self.bin = None
        if (folder / 'index.json').is_file():
            index = json.loads((folder / 'index.json').read_text(encoding='utf-8'))
            self.files = index['files']
            self.sha = index.get('romfs_sha256', '')
            self.bin = open(folder / 'romfs.bin', 'rb')
        elif folder.is_dir():
            self.files = []
            for root, _dirs, names in os.walk(folder):
                for n in names:
                    p = Path(root) / n
                    rel = p.relative_to(folder).as_posix()
                    self.files.append({'path': rel, 'size': p.stat().st_size, 'offset': None})
            self.files.sort(key=lambda f: f['path'])
            self.sha = 'loose:' + (romfs_marker(game) or str(len(self.files)))
        else:
            raise FileNotFoundError(f'no game files in {folder}')
        self.by_path = {f['path']: f for f in self.files}

    def load(self, f):
        if isinstance(f, str):
            f = self.by_path[f]
        if self.bin is None:
            return (self.folder / f['path']).read_bytes()
        self.bin.seek(f['offset'])
        return self.bin.read(f['size'])

    def close(self):
        if self.bin:
            self.bin.close()


def sarc_members(p):
    if p[:4] != b'SARC':
        raise ValueError('not an archive')
    head, = struct.unpack_from('<H', p, 4)
    data, = struct.unpack_from('<I', p, 12)
    count, = struct.unpack_from('<H', p, head + 6)
    names = head + 12 + count * 16 + 8
    out = {}
    for i in range(count):
        _, attr, lo, hi = struct.unpack_from('<IIII', p, head + 12 + i * 16)
        s = names + (attr & 0xffffff) * 4
        out[p[s:p.index(b'\0', s)].decode()] = p[data + lo:data + hi]
    return out


def byml(p):
    """A BYML file as Python values (either byte order)."""
    if p[:2] not in (b'YB', b'BY'):
        raise ValueError('not a BYML file')
    E, order = ('<', 'little') if p[:2] == b'YB' else ('>', 'big')
    _, keys, strs, root = struct.unpack_from(E + 'HIII', p, 2)

    def table(off):
        if not off:
            return []
        n = int.from_bytes(p[off + 1:off + 4], order)
        offs = struct.unpack_from(f'{E}{n}I', p, off + 4)
        return [p[off + o:p.index(b'\0', off + o)].decode('utf-8', 'replace') for o in offs]

    K, S = table(keys), table(strs)
    u32 = struct.Struct(E + 'I')

    def node(t, v):
        if t == 0xa0:
            return S[v]
        if t == 0xd0:
            return bool(v)
        if t == 0xd1:
            return v - (1 << 32) if v & 0x80000000 else v
        if t == 0xd2:
            return struct.unpack(E + 'f', u32.pack(v))[0]
        if t == 0xd3:
            return v
        if t == 0xd4:
            return struct.unpack_from(E + 'q', p, v)[0]
        if t == 0xd5:
            return struct.unpack_from(E + 'Q', p, v)[0]
        if t == 0xd6:
            return struct.unpack_from(E + 'd', p, v)[0]
        if t == 0xff:
            return None
        if t in (0xa1, 0xa2):
            n, = u32.unpack_from(p, v)
            return p[v + 4:v + 4 + n] if t == 0xa1 else p[v + 8:v + 8 + n]
        n = int.from_bytes(p[v + 1:v + 4], order)
        if t == 0xc0:
            vo = v + 4 + ((n + 3) & ~3)
            vals = struct.unpack_from(f'{E}{n}I', p, vo)
            return [node(p[v + 4 + i], vals[i]) for i in range(n)]
        if t == 0xc1:
            d = {}
            for i in range(n):
                e = v + 4 + 8 * i
                d[K[int.from_bytes(p[e:e + 3], order)]] = node(p[e + 3], u32.unpack_from(p, e + 4)[0])
            return d
        if t == 0x20:
            d = {}
            for i in range(n):
                k, val = struct.unpack_from(E + 'II', p, v + 4 + 8 * i)
                d[k] = node(p[v + 4 + 8 * n + i], val)
            return d
        raise ValueError(f'BYML node type 0x{t:x}')

    return node(p[root], root)


# Folders of pictures, sound, models and terrain: big, and without names in them.
SKIP_TOP = {'Tex', 'TerrainArc', 'Model', 'Sound', 'Bake', 'Phive', 'PreComputedCulling', 'Foliage', 'Effect', 'Voice',
            'Shader', 'Font2', 'Movie', 'Lib'}
NAME_RUN = re.compile(rb'[A-Za-z0-9_.]{4,96}')
CACHE = HERE / 'names-cache.json'
CACHE_VERSION = 1


def build_names(game=None, progress=lambda text: None):
    """{'names': {hash: name}, 'enums': {flag hash: [[value hash, name], ...]}, 'enum_values': {hash: name}}, read
    from the game's files: the game's list of save entries gives the hashes, and every run of name characters in the
    game's data files is hashed and looked up among them. Grouped entries are named 'Group.Member'."""
    if zstd is None:
        raise RuntimeError('this needs Python 3.14 or later (compression.zstd)')
    rom = Romfs(game or game_dir())
    try:
        progress('Reading the game\'s list of save entries...')
        dics = {k: zstd.ZstdDict(v) for k, v in sarc_members(zstd.decompress(rom.load('Pack/ZsDic.pack.zs'))).items()}
        plain = dics['zs.zsdic']
        lists = sorted(p for p in rom.by_path if re.fullmatch(r'GameData/GameDataList\.Product\.\d+\.byml\.zs', p))
        if not lists:
            raise RuntimeError('the game files have no GameData/GameDataList')
        data = byml(zstd.decompress(rom.load(lists[-1]), zstd_dict=plain))['Data']

        want, structs, enums, enum_values = set(), {}, {}, {}
        for t, entries in data.items():
            if t == 'Bool64bitKey':
                continue
            for e in entries:
                want.add(e['Hash'])
                if t == 'Struct':
                    structs[e['Hash']] = [(m['Hash'], m['Value']) for m in e.get('DefaultValue') or []]
                elif t in ('Enum', 'EnumArray'):
                    vals, raws = e.get('Values') or [], e.get('RawValues') or []
                    pairs = [[v, r] for v, r in zip(vals, raws) if isinstance(v, int) and isinstance(r, str)]
                    enums[e['Hash']] = pairs
                    enum_values.update((v, r) for v, r in pairs)

        runs = set()
        todo = []
        for f in rom.files:
            p = f['path']
            top = p.split('/', 1)[0]
            if top in SKIP_TOP or (top == 'Event' and not p.startswith('Event/EventFlow/')) or f['size'] > 64 << 20:
                continue
            todo.append(f)
        for i, f in enumerate(todo):
            if i % 500 == 0:
                progress(f'Looking for names in the game files... {100 * i // len(todo)}%')
            raw, p = rom.load(f), f['path']
            if p.endswith('.zs'):
                d = (dics.get('pack.zsdic') if p.endswith('.pack.zs') else
                     dics.get('bcett.byml.zsdic') if p.endswith('.bcett.byml.zs') else None) or plain
                try:
                    raw = zstd.decompress(raw, zstd_dict=d)
                except Exception:
                    continue
            runs.update(NAME_RUN.findall(raw))
    finally:
        rom.close()

    progress('Matching names...')
    cands = set(runs)
    for s in runs:
        if b'.' in s:
            cands.update(x for x in s.split(b'.') if len(x) >= 2)
    by_hash = {}
    for s in cands:
        by_hash.setdefault(murmur3(s), s.decode('ascii'))
    names = {h: by_hash[h] for h in want if h in by_hash}

    # A group's member is named 'Group.Member': names spread from a named group to its members, and from a named
    # member back to its group, until nothing new is found. Every name is checked against its hash.
    parents = {}
    for s, members in structs.items():
        for mh, flag in members:
            parents.setdefault(flag, []).append((s, mh))
    changed = True
    while changed:
        changed = False
        for flag, name in list(names.items()):
            if '.' not in name:
                continue
            group, member = name.rsplit('.', 1)
            for s, mh in parents.get(flag, ()):
                if s not in names and murmur3(group.encode()) == s:
                    names[s] = group
                    changed = True
                if mh not in by_hash and murmur3(member.encode()) == mh:
                    by_hash[mh] = member
                    changed = True
        for s, members in structs.items():
            group = names.get(s)
            if not group:
                continue
            for mh, flag in members:
                member = by_hash.get(mh)
                if member and flag not in names and murmur3(f'{group}.{member}'.encode()) == flag:
                    names[flag] = f'{group}.{member}'
                    changed = True
    return {'version': CACHE_VERSION, 'romfs': rom.sha, 'entries': len(want),
            'names': {str(h): n for h, n in names.items()},
            'enums': {str(h): v for h, v in enums.items()},
            'enum_values': {str(h): n for h, n in enum_values.items()}}


class Names:
    def __init__(self, raw=None):
        raw = raw or {}
        self.names = {int(k): v for k, v in raw.get('names', {}).items()}
        self.enums = {int(k): [(int(a), b) for a, b in v] for k, v in raw.get('enums', {}).items()}
        self.enum_values = {int(k): v for k, v in raw.get('enum_values', {}).items()}
        self.total = raw.get('entries', 0)

    def name(self, h):
        return self.names.get(h) or f'#{h:08x}'

    def enum_text(self, value):
        return self.enum_values.get(value) or f'#{value:08x}'

    def enum_parse(self, text):
        text = text.strip()
        if re.fullmatch(r'#[0-9a-fA-F]{1,8}', text):
            return int(text[1:], 16)
        return murmur3(text.encode())


def load_names(game=None, progress=lambda text: None, rebuild=False):
    """The names, from the cache when it was made from the same game files, else read from the game files."""
    game = Path(game or game_dir())
    try:
        if (game / 'romfs' / 'index.json').is_file():
            sha = json.loads((game / 'romfs' / 'index.json').read_text(encoding='utf-8')).get('romfs_sha256', '')
        else:
            if not (game / 'romfs').is_dir():
                return Names()
            text = romfs_marker(game)
            sha = 'loose:' + (text or str(sum(len(f) for _r, _d, f in os.walk(game / 'romfs'))))
    except (OSError, ValueError):
        return Names()                     # no game files: the editor still works, with hashes for names
    mine = cache_file(game)
    if not rebuild:
        # this folder's own list, the one file older versions kept, then any other folder's list made from the same
        # game files (a new Longshot build of the same game: no 4-minute re-read)
        others = [f for f in sorted(HERE.glob('names-cache-*.json')) if f != mine]
        for f in [mine, CACHE] + others:
            try:
                raw = json.loads(f.read_text(encoding='utf-8'))
                if raw.get('version') == CACHE_VERSION and raw.get('romfs') == sha:
                    return Names(raw)
            except (OSError, ValueError):
                pass
    raw = build_names(game, progress)
    try:
        mine.write_text(json.dumps(raw), encoding='utf-8')
    except OSError:
        pass
    return Names(raw)


def romfs_marker(game):
    """The note the builder left next to the game files it unpacked (Triforce's .triforce_romfs, Longshot's
    .longshot_romfs: both name the game file they came from), '' when there is none. The same game file gives the same
    note, so Triforce, Longshot and every new build of it share one names list."""
    for m in ('.triforce_romfs', '.longshot_romfs'):
        try:
            text = (Path(game) / m).read_text(encoding='utf-8', errors='replace').strip()
            if text:
                return text
        except OSError:
            pass
    return ''


def cache_file(game):
    """The names read from one game folder's files: one file per game folder (Triforce and Longshot side by side)."""
    key = str(Path(game).resolve()).lower().encode('utf-8')
    return HERE / f'names-cache-{murmur3(key):08x}.json'


# ------------------------------------------------------------------------------------------------ command line

def _main(argv):
    import collections
    if len(argv) >= 2 and argv[1] == 'names':
        t0 = time.time()
        n = load_names(progress=lambda s: print(s, flush=True), rebuild=True)
        print(f'{len(n.names)} of {n.total} entries named in {time.time() - t0:.0f} s')
        return 0
    if len(argv) >= 2 and argv[1] == 'check':
        names = load_names(progress=lambda s: print(s, flush=True))
        for acc in save_dirs():
            for label, path in save_files(acc):
                s = SaveFile(path)
                ext = sorted(x for x in (s.extent(e) for e in s.entries) if x)
                gaps = overlaps = 0
                at = s.data_off
                for off, size in ext:
                    size = (size + 3) & ~3
                    gaps += off > at
                    overlaps += off < at
                    at = max(at, off + size)
                named = sum(e.hash in names.names for e in s.entries)
                same = bytes(s.buf) == path.read_bytes()
                print(f'{label:32} {len(s.entries):6} entries, {named:6} named, gaps {gaps}, overlaps {overlaps}, '
                      f'data ends 0x{at:x} of 0x{len(s.buf):x}, unchanged {same}')
        return 0
    if len(argv) >= 3 and argv[1] == 'dump':
        names = load_names()
        s = SaveFile(argv[2])
        pat = argv[3].lower() if len(argv) > 3 else ''
        for e in s.entries:
            n = names.name(e.hash)
            if pat in n.lower():
                v = names.enum_text(e.value) if e.type == 'Enum' else e.value
                print(f'{e.type:14} {n} = {str(v)[:120]}')
        return 0
    print('usage: nxsave.py names | check | dump <file.sav> [text]')
    return 2


if __name__ == '__main__':
    import sys
    sys.exit(_main(sys.argv))
