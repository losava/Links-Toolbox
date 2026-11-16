"""A small mod loader for Triforce: switch the mods in game/mods on and off, set their order, then play.

Triforce reads the folders in game/mods by name:
    a folder whose name starts with - or _ is off
    when two mods carry the same file, the folder whose name sorts last wins
This window keeps that in the names: a mod that is on is "NN-<name>" (NN its place, the bottom of the list is the
highest number and wins), a mod that is off is "_<name>". Nothing happens to the folders until Save or Save and play.
Each save also writes "~Size Table" (size_table.py), the resource size table the mods that are on need, which
Triforce does not work out by itself; it sorts after every mod, so its table is the one served.

Run:  python\\pythonw.exe save-editor\\mod_loader.pyw      (or Mod Loader.bat)
"""
import os
import re
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxsave  # noqa: E402
import theme  # noqa: E402

GAME = nxsave.game_dir()
DEFAULT_MODS = nxsave.mods_dir_for(GAME)     # (Longshot with a shared mods folder: that one)
MODS = DEFAULT_MODS
GAME_EXE = nxsave.game_exe(GAME) or GAME / 'Triforce.exe'


def set_mods_dir(path=None):
    """Use another mods folder (the toolbox's Folders tab); None: game/mods. Save and play starts the game program
    (Triforce.exe, or Longshot's longshot.exe) next to that folder when there is one there, else the game's."""
    global MODS, GAME_EXE
    MODS = Path(path) if path else DEFAULT_MODS
    GAME_EXE = nxsave.game_exe(MODS.parent) or nxsave.game_exe(GAME) or GAME / 'Triforce.exe'


set_mods_dir(nxsave.load_settings().get('mods_dir'))
PREFIX = re.compile(r'^(?:[-_]+)?(?:\d+-)?')
RUNNING = nxsave.GAME_PROCESSES
# a short note on mods these scripts made, shown under the list when the mod is picked
NOTES = {
    'Young Link Adult Motions': 'Gives young Link the adult\'s motions (big swords, hookshot, bow, hammer). It carries '
                                'the size table, so Triforce shows the game\'s own button icons in texts while it is on.',
    'Young Link Two-Handed Swords': 'Needs "Young Link Adult Motions". Replaces the same file as "Biggoron One-Handed": '
                                    'have only one of the two on.',
    'Biggoron One-Handed': 'Replaces the same file as "Young Link Two-Handed Swords": have only one of the two on.',
    'Young Link All Items': 'Lets young Link pick the adult\'s items in the menu. Needed for the Mirror Shield, the big '
                            'swords, tunics and boots.',
    'All Items Both Ages': 'Both "Young Link All Items" and "Adult Link All Items" in one: have only one of the three on.',
    'Adult Link All Items': 'Lets adult Link pick the child\'s items in the menu.',
    'Adult Link Child Motions': 'Gives adult Link the child\'s motions (slingshot, boomerang, Deku Stick).',
    'Young Link Swords': 'Older: "Young Link All Items" does all of this and more.',
}


def plain(folder):
    return PREFIX.sub('', folder) or folder


def running():
    """The game programs running now (Windows and Linux)."""
    name = nxsave.game_running()
    return [name] if name else []


class Mod:
    def __init__(self, folder):
        self.folder = folder                      # the name on disk now
        self.name = plain(folder)
        self.on = not folder.startswith(('-', '_'))
        romfs = MODS / folder / 'romfs'
        self.files = set()
        if romfs.is_dir():
            for root, _d, names in os.walk(romfs):
                for n in names:
                    self.files.add((Path(root) / n).relative_to(romfs).as_posix().lower())
        self.loads = romfs.is_dir()               # Triforce loads RomFS mods only

    def target(self, place):
        return f'{place:02d}-{self.name}' if self.on and self.loads else f'_{self.name}'


def scan():
    # (folders starting with ~ are the loader's own, the size table: not listed)
    mods = [Mod(p.name) for p in MODS.iterdir() if p.is_dir() and not p.name.endswith('.old')
            and not p.name.startswith('~')] if MODS.is_dir() else []
    # the order Triforce uses: by folder name; mods that are off go below, by name
    mods.sort(key=lambda m: (not m.on, m.folder.lower() if m.on else m.name.lower()))
    return mods


def clashes(mods):
    """{mod name: [(other name, files both carry, whether this one wins)]} among the mods that are on, in list order:
    the lower in the list wins."""
    on = [m for m in mods if m.on and m.loads]
    out = {m.name: [] for m in on}
    for i, a in enumerate(on):
        for j, b in enumerate(on):
            if a is not b:
                n = len(a.files & b.files)
                if n:
                    out[a.name].append((b.name, n, i > j))
    return out


def apply(mods):
    """Renames the folders to their targets, through temporary names so no two names collide. Returns the renames."""
    on = [m for m in mods if m.on and m.loads]
    plan = []
    for m in mods:
        new = m.target(on.index(m) + 1 if m in on else 0)
        if new != m.folder:
            plan.append((m, new))
    names = {m.name for m in mods}
    if len(names) != len(mods):
        raise ValueError('two folders have the same name once their prefixes are taken off')
    temp = []
    for m, new in plan:
        t = MODS / f'.renaming-{m.name}'
        (MODS / m.folder).rename(t)
        temp.append((m, t, new))
    for m, t, new in temp:
        t.rename(MODS / new)
        m.folder = new
    # Triforce does not raise the size table for mod files that grew: one table for the mods that are on
    import size_table
    size_table.build(MODS, [m.folder for m in on], log=lambda _s: None)
    return [(m.name, new) for m, _t, new in temp]


# the mods that come with the shared toolbox: Link Toolbox\mods, next to its app folder
BUNDLED = Path(__file__).resolve().parent.parent / 'mods'


def mod_folders(src):
    """The mod folders in a folder (a folder with romfs in it is one mod itself)."""
    src = Path(src)
    if (src / 'romfs').is_dir():
        return [src]
    return sorted(p for p in src.iterdir() if p.is_dir() and (p / 'romfs').is_dir()) if src.is_dir() else []


def find_mod_folders(src, depth=4):
    """The mod folders anywhere in a folder, up to depth folders down (a zip's own layout: Mod\\romfs, Mods\\A\\romfs...)."""
    src = Path(src)
    out = []
    for dirpath, dirs, _files in os.walk(src):
        here = Path(dirpath)
        if 'romfs' in dirs:
            out.append(here)
            dirs[:] = []
        elif len(here.relative_to(src).parts) >= depth:
            dirs[:] = []
    return sorted(out, key=lambda p: p.name.lower())


def unpack_mod_zip(zip_path):
    """(temporary folder, folder to add from) for a mod zip; the caller removes the temporary folder. A zip with romfs
    at its top is one mod, named after the zip."""
    import code_mods
    tmp = code_mods.unpack_zip(zip_path)
    if (tmp / 'romfs').is_dir():
        inner = tmp / '_mod' / re.sub(r'[<>:"/\\|?*]', '', zip_path.stem).strip()
        inner.parent.mkdir()
        inner.mkdir()
        for p in list(tmp.iterdir()):
            if p.name != '_mod':
                shutil.move(str(p), str(inner / p.name))
        return tmp, inner.parent
    return tmp, tmp


BUNDLED_LIST = 'bundled.txt'    # (written by make_share_zip: the names of the download's own mods, one a line)


def bundled_mods(folder=None):
    """The mods that came with the toolbox, one per mod: an update copies the new folders in but leaves the old ones
    (renumbered mods, like 04-Biggoron One-Handed now 05-Biggoron One-Handed). The download's bundled.txt says which
    are the current ones; without it (1.2.0 and older), the newest copy of each mod."""
    folder = Path(folder or BUNDLED)
    found = [p for p in mod_folders(folder) if not p.name.startswith('~')]
    listed = folder / BUNDLED_LIST
    try:
        names = [n.strip() for n in listed.read_text(encoding='utf-8').splitlines() if n.strip()]
    except OSError:
        names = None
    if names:
        current = [p for p in found if p.name in names]
        if current:
            return current
    newest = {}
    for p in found:
        key = plain(p.name).lower()
        stamp = max((f.stat().st_mtime for f in p.rglob('*') if f.is_file()), default=0)
        if key not in newest or stamp > newest[key][0]:
            newest[key] = (stamp, p)
    return sorted((p for _s, p in newest.values()), key=lambda p: p.name)


def tidy_bundled(folder=None):
    """Removes the old copies an update left in the toolbox's own mods folder (the same mod under an old name). Only
    there, only folders with romfs in them, and only a mod that has a current copy. Returns the names removed."""
    import shutil
    folder = Path(folder or BUNDLED)
    if not folder.is_dir() or nxsave.is_link(folder) or not (folder / BUNDLED_LIST).is_file():
        return []
    try:                               # (never a game's own mods folder)
        games = {nxsave.mods_dir_for(p).resolve() for _a, p in nxsave.all_game_dirs()}
    except Exception:
        games = set()
    if folder.resolve() in games:
        return []
    keep = bundled_mods(folder)
    current = {plain(p.name).lower() for p in keep}
    gone = []
    for p in mod_folders(folder):
        if p in keep or p.name.startswith('~') or plain(p.name).lower() not in current or nxsave.is_link(p):
            continue
        try:
            shutil.rmtree(p)
            gone.append(p.name)
        except OSError:
            pass
    return gone


def install(folders, replace):
    """Copies mod folders into the mods folder. replace(name) says whether to overwrite a mod already there (the same
    name without its NN- / _ prefix). Returns (added, replaced, skipped) names."""
    import shutil
    MODS.mkdir(parents=True, exist_ok=True)
    have = {plain(p.name).lower(): p for p in MODS.iterdir() if p.is_dir()}
    added, replaced, skipped = [], [], []
    for i, src in enumerate(folders):
        name = plain(src.name)
        if src.name.startswith('~'):              # the size table: Save builds it again from this game's own table
            if not (MODS / src.name).exists():
                shutil.copytree(src, MODS / src.name)
            continue
        old = have.get(name.lower())
        if old is not None:
            if Path(old).resolve() == src.resolve() or not replace(name):
                skipped.append(name)
                continue
            shutil.rmtree(old)
            replaced.append(name)
        else:
            added.append(name)
        # (a mod added is on, after the others and in the order it came in: Save numbers it; one that came switched
        #  off, its name starting with _ or -, stays off)
        off = src.name.startswith(('_', '-'))
        shutil.copytree(src, MODS / (f'_{name}' if off else f'9{i:02d}-{name}'))
    return added, replaced, skipped


class App(ttk.Frame):
    """The mod loader, as a frame: in a window of its own (main) or as a tab of the Link toolbox (toolbox.pyw).
    on_title(text): the title it would like its window to have; after_play(): what happens once the game is started
    (by default the window closes)."""

    def __init__(self, master=None, on_title=None, after_play=None):
        super().__init__(master)
        self.on_title = on_title or (lambda text: self.winfo_toplevel().title(text))
        self.after_play = after_play or (lambda: self.winfo_toplevel().destroy())
        self.mods = []
        self.dirty = False

        top = ttk.Frame(self, padding=(10, 10, 10, 4))
        top.pack(fill='x')
        # whose mods these are: each game's mods folder (Triforce and NX2navi share one), or one kept in Folders
        ttk.Label(top, text='Game').pack(side='left')
        self.game_var = tk.StringVar()
        self.game_box = ttk.Combobox(top, textvariable=self.game_var, state='readonly', width=20)
        self.game_box.pack(side='left', padx=(6, 12))
        self.game_box.bind('<<ComboboxSelected>>', lambda _e: self.pick_game())
        self.game_rows = []
        self.where = ttk.Label(top, text=f'Mods in {MODS}', foreground=theme.SOFT)
        self.where.pack(side='left')
        ttk.Button(top, text='Open folder', command=lambda: nxsave.open_folder(MODS)).pack(side='right')
        ttk.Button(top, text='Refresh', command=self.reload).pack(side='right', padx=(0, 6))
        ttk.Button(top, text='Add mods...', command=self.add_mods).pack(side='right', padx=(0, 6))
        ttk.Button(top, text='Code mods...', command=self.code_mods).pack(side='right', padx=(0, 6))
        # (code mods changed since the last Build: a line saying so)
        self.code_line = ttk.Label(self, text='', foreground=theme.ERROR, padding=(10, 0, 10, 4), cursor='hand2')
        self.code_line.bind('<Button-1>', lambda _e: self.code_mods())

        mid = ttk.Frame(self, padding=(10, 0))
        mid.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(mid, columns=('on', 'name', 'state'), show='headings', selectmode='browse')
        for col, text, width, stretch, anchor in (('on', 'On', 46, False, 'center'), ('name', 'Mod', 300, True, 'w'),
                                                  ('state', 'Notes', 340, True, 'w')):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, stretch=stretch, anchor=anchor)
        sb = ttk.Scrollbar(mid, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.tag_configure('off', foreground=theme.DIM)
        self.tree.tag_configure('clash', foreground=theme.ERROR)
        self.tree.bind('<Button-1>', self.click)
        self.tree.bind('<space>', lambda _e: self.toggle())
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.show_note())

        side = ttk.Frame(mid, padding=(8, 0, 0, 0))
        side.pack(side='right', fill='y', before=sb)
        ttk.Button(side, text='On / off', command=self.toggle).pack(fill='x')
        ttk.Button(side, text='Up', command=lambda: self.move(-1)).pack(fill='x', pady=(12, 0))
        ttk.Button(side, text='Down', command=lambda: self.move(1)).pack(fill='x', pady=(4, 0))
        ttk.Label(side, text='Lower wins\nwhen two mods\nreplace a file', foreground=theme.MUTED,
                  justify='center').pack(pady=(10, 0))
        if os.name == 'nt':
            ttk.Label(side, text='Drag mods here:\n.zip files or\nfolders, code\nmods too', foreground=theme.MUTED,
                      justify='center').pack(pady=(16, 0))

        self.note = ttk.Label(self, text='', foreground=theme.SOFT, wraplength=720, justify='left', padding=(10, 6, 10, 0))
        self.note.pack(fill='x')
        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill='x')
        self.status = ttk.Label(bottom, text='')
        self.status.pack(side='left', fill='x', expand=True)
        self.play_btn = ttk.Button(bottom, text='Save and play', command=self.play)
        self.play_btn.pack(side='right')
        self.save_btn = ttk.Button(bottom, text='Save', command=self.save)
        self.save_btn.pack(side='right', padx=(0, 6))
        self.reload()

    # -- which game's mods
    def fill_games(self):
        """The Game list: every mods folder found (and the one in use, when it is none of them)."""
        self.game_rows = nxsave.all_mod_locations()
        here = os.path.normcase(str(MODS.resolve())) if MODS.exists() else os.path.normcase(str(MODS))
        if not any(os.path.normcase(str(d.resolve())) == here for _l, d, _e in self.game_rows):
            self.game_rows.insert(0, ('Mods folder', MODS, GAME_EXE))
        self.game_box['values'] = [label for label, _d, _e in self.game_rows]
        for i, (_l, d, _e) in enumerate(self.game_rows):
            if os.path.normcase(str(d.resolve())) == here:
                self.game_box.current(i)

    def pick_game(self):
        global MODS, GAME_EXE
        label, d, exe = self.game_rows[self.game_box.current()]
        if os.path.normcase(str(d)) == os.path.normcase(str(MODS)):
            return
        if self.dirty and not messagebox.askyesno('Mod loader', 'Forget the changes you have not saved?', parent=self):
            self.fill_games()
            return
        MODS = d
        # Save and play: the game in use when it is one of this folder's games (Triforce / NX2navi share one)
        now = nxsave.app_of()
        apps = label.split(' / ')
        game = d.parent
        mine = nxsave.program(game, dict(nxsave.APPS)[now]) if now in apps else None
        GAME_EXE = mine or exe or GAME_EXE
        self.dirty = False
        self.reload()
        self.status['text'] += f'   -   {label}: Save and play starts {GAME_EXE.name}'

    # -- the list
    def reload(self):
        if self.dirty and not messagebox.askyesno('Mod loader', 'Forget the changes you have not saved?', parent=self):
            return
        self.mods = scan()
        self.dirty = False
        self.where['text'] = f'Mods in {MODS}'
        self.fill_games()
        self.fill()
        self.show_code_line()

    # -- code mods (Longshot: built into the game; code_mods.py)
    def show_code_line(self):
        text = ''
        try:
            import code_mods
            st = code_mods.status()
            needs = [v for _r, v, n, _m in st['roots'] if n]
            missing = [v for _r, v, _n, m in st['roots'] if m]
            if missing:
                text = (f'Code mods are missing in Longshot {", ".join(missing)} (a Longshot update): click here, '
                        'then Put them back and Build.')
            elif needs:
                text = 'Code mods changed: press Build in the Longshot Launcher (click here for the Code mods window).'
        except Exception:
            pass
        self.code_line['text'] = text
        if text:
            self.code_line.pack(fill='x', after=self.winfo_children()[0])
        else:
            self.code_line.pack_forget()

    def code_mods(self):
        import code_mods_ui
        win = code_mods_ui.CodeMods(self, on_change=self.after_code_change)
        win.grab_set()

    def after_code_change(self):
        """A code mod's game files go into the mods folder: the list shows them (unless edits are not saved yet)."""
        if not self.dirty:
            self.mods = scan()
            self.fill()
        self.show_code_line()

    def fill(self, keep=None):
        self.tree.delete(*self.tree.get_children())
        cl = clashes(self.mods)
        problems = 0
        for i, m in enumerate(self.mods):
            if not m.loads:
                state, tag = 'not a RomFS mod: the game does not load it', 'off'
            elif not m.on:
                state, tag = '', 'off'
            else:
                lost = [f'{o} wins {n} file{"s" if n > 1 else ""}' for o, n, wins in cl.get(m.name, []) if not wins]
                won = [f'over {o} ({n})' for o, n, wins in cl.get(m.name, []) if wins]
                state = '; '.join(lost + won)
                tag = 'clash' if lost else ''
                problems += bool(lost)
            self.tree.insert('', 'end', iid=str(i), tags=(tag,) if tag else (),
                             values=('☑' if m.on and m.loads else '☐', m.name, state))
        if keep is not None:
            self.tree.selection_set(str(keep))
            self.tree.see(str(keep))
        on = sum(m.on and m.loads for m in self.mods)
        text = f'{on} of {len(self.mods)} mods on'
        if problems:
            text += f'   -   {problems} lose files to another mod (red)'
        if self.dirty:
            text += '   -   not saved'
        busy = running()
        if busy:
            text += f'   -   {", ".join(busy)} is running: close it before saving'
        self.status['text'] = text
        state = 'disabled' if busy else 'normal'
        self.save_btn['state'] = state
        self.play_btn['state'] = state
        self.on_title(('* ' if self.dirty else '') + 'Mod loader')
        self.show_note()

    def selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def show_note(self):
        i = self.selected()
        self.note['text'] = NOTES.get(self.mods[i].name, '') if i is not None and i < len(self.mods) else ''

    def click(self, event):
        if self.tree.identify_region(event.x, event.y) == 'cell' and self.tree.identify_column(event.x) == '#1':
            row = self.tree.identify_row(event.y)
            if row:
                self.tree.selection_set(row)
                self.toggle()
                return 'break'

    def toggle(self):
        i = self.selected()
        if i is None or not self.mods[i].loads:
            return
        m = self.mods[i]
        m.on = not m.on
        if m.on:      # a mod switched on goes to the bottom of the mods that are on: it wins
            self.mods.remove(m)
            self.mods.insert(sum(x.on and x.loads for x in self.mods), m)
        else:
            self.mods.remove(m)
            self.mods.append(m)
        self.dirty = True
        self.fill(self.mods.index(m))

    def move(self, d):
        i = self.selected()
        if i is None:
            return
        j = i + d
        if not 0 <= j < len(self.mods) or self.mods[j].on != self.mods[i].on:
            return
        self.mods[i], self.mods[j] = self.mods[j], self.mods[i]
        self.dirty = True
        self.fill(j)

    # -- adding mods
    def add_mods(self):
        """Copies mods into the mods folder: the ones that came with the toolbox, or any folder picked."""
        from tkinter import filedialog
        busy = running()
        if busy:
            messagebox.showwarning('Add mods', f'Close {", ".join(busy)} first.', parent=self)
            return
        if self.dirty and not messagebox.askyesno('Add mods', 'Forget the changes you have not saved?', parent=self):
            return
        try:
            tidy_bundled()
        except Exception:
            pass
        bundled = bundled_mods()
        src = None
        if bundled:
            answer = messagebox.askyesnocancel(
                'Add mods', f'Add the {len(bundled)} mods that came with the toolbox?\n\n' +
                '\n'.join('  ' + plain(p.name) + ('   (comes switched off)' if p.name.startswith(('_', '-')) else '')
                          for p in bundled) + '\n\nYes: add these.   No: pick another folder.',
                parent=self)
            if answer is None:
                return
            src = BUNDLED if answer else None
        tmp = None
        if src is None:
            kind = messagebox.askyesnocancel(
                'Add mods', 'Is the mod a .zip file?\n\nYes: pick the .zip (from HookyCreator, a download...).   '
                'No: pick a folder.', parent=self)
            if kind is None:
                return
            if kind:
                path = filedialog.askopenfilename(parent=self, title='The mod (.zip)',
                                                  filetypes=[('Zip files', '*.zip'), ('All files', '*.*')])
                if not path:
                    return
                try:
                    tmp, src = unpack_mod_zip(Path(path))
                except Exception as err:
                    messagebox.showerror('Add mods', f'{Path(path).name} could not be opened:\n{err}', parent=self)
                    return
                import code_mods
                if code_mods.find_packages(tmp):          # (a code mod: it goes into Longshot's sources instead)
                    shutil.rmtree(tmp, ignore_errors=True)
                    if messagebox.askyesno('Add mods', f'{Path(path).name} is a code mod: it is built into the game by '
                                           'Longshot, not copied into the mods folder.\n\nOpen the Code mods window '
                                           'to add it there?', parent=self):
                        self.code_mods()
                    return
            else:
                path = filedialog.askdirectory(parent=self, mustexist=True,
                                               title='A mod folder (with romfs inside), or a folder of mods')
                if not path:
                    return
                src = Path(path)
        try:
            self._add_from(src, bundled, deep=tmp is not None)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def _add_from(self, src, bundled, deep=False):
        folders = (bundled + [p for p in mod_folders(BUNDLED) if p.name.startswith('~')] if src == BUNDLED
                   else find_mod_folders(src) if deep else mod_folders(src))
        if not folders:
            messagebox.showinfo('Add mods', f'{src}\n\nhas no mods in it: a mod is a folder with a "romfs" folder '
                                'inside.', parent=self)
            return
        self._add_folders(folders)

    def _add_folders(self, folders):
        # (the questions first: the copying then runs in the background, with the Working... window)
        have = {plain(p.name).lower(): p for p in MODS.iterdir() if p.is_dir()} if MODS.is_dir() else {}
        replace = set()
        for src in folders:
            name = plain(src.name)
            old = have.get(name.lower())
            if src.name.startswith('~') or old is None or Path(old).resolve() == src.resolve():
                continue
            if messagebox.askyesno('Add mods', f'"{name}" is there already. Replace it with this copy?', parent=self):
                replace.add(name)
        try:
            import busy
            added, replaced, skipped = busy.run(self, f'Copying {len(folders)} mod{"s" if len(folders) != 1 else ""} '
                                                f'into\n{MODS}...', lambda: install(folders, lambda n: n in replace))
        except OSError as err:
            messagebox.showerror('Add mods', f'The mods could not be copied:\n{err}', parent=self)
            self.dirty = False
            self.reload()
            return
        self.mods = scan()
        self.dirty = bool(added or replaced)
        self.fill()
        if added or replaced:
            self.status['text'] += f'   -   added {len(added) + len(replaced)}: press Save to use them'
        else:
            self.status['text'] += '   -   nothing new to add'

    # -- dropped on the window (dragdrop.py): each thing dropped is sorted out
    def add_paths(self, paths):
        """Files and folders dragged in: a code mod (a package with mod.json and a "longshot" folder, in a zip or a
        folder) goes into Longshot's sources after asking; any other zip or folder with romfs mods in it is copied into
        the mods folder like Add mods; anything else is said."""
        import code_mods
        if running():
            messagebox.showwarning('Add mods', f'Close {", ".join(running())} first.', parent=self)
            return
        code, normal, bad, tmps = [], [], [], []
        try:
            for p in (Path(x) for x in paths):
                try:
                    if p.is_file() and p.suffix.lower() == '.zip':
                        tmp, src = unpack_mod_zip(p)
                        tmps.append(tmp)
                    elif p.is_dir():
                        src = p
                    else:
                        bad.append(f'{p.name}: not a .zip or a folder')
                        continue
                    if code_mods.find_packages(src):
                        code.append((p, src))
                    elif find_mod_folders(src):
                        normal += find_mod_folders(src)
                    else:
                        bad.append(f'{p.name}: no mod in it (a mod has a "romfs" folder, a code mod a mod.json)')
                except Exception as err:
                    bad.append(f'{p.name}: {err}')
            if bad:
                messagebox.showinfo('Add mods', 'Not added:\n\n' + '\n'.join(bad), parent=self)
            for p, src in code:
                self.add_code_mod(p, src)
            if normal:
                if self.dirty and not messagebox.askyesno('Add mods', 'Forget the changes you have not saved?',
                                                          parent=self):
                    return
                self._add_folders(normal)
        finally:
            for t in tmps:
                shutil.rmtree(t, ignore_errors=True)

    def add_code_mod(self, dropped, src):
        """A code mod dropped in: into Longshot's sources (asked first), then Build."""
        import busy
        import code_mods
        if not messagebox.askyesno('Code mods', f'{dropped.name} is a code mod: it changes how the game works, so it '
                                   'goes into Longshot\'s own sources, and then you press Build in the Longshot '
                                   'Launcher (a full build).\n\nPut it in?', parent=self):
            return
        try:
            names = busy.run(self, 'Putting the code mod into Longshot\'s sources...',
                             lambda: code_mods.install(src), title='Code mods')
        except (code_mods.CodeModError, OSError) as err:
            messagebox.showerror('Code mods', str(err), parent=self)
            return
        finally:
            self.after_code_change()
        if messagebox.askyesno('Code mods', f'Put in: {", ".join(names)}\n\nNow press Build in the Longshot Launcher. '
                               'Open it now?', parent=self):
            exe = code_mods.launcher_exe()
            if exe:
                subprocess.Popen([str(exe)], cwd=str(exe.parent))

    # -- saving and playing
    def save(self):
        busy = running()
        if busy:
            messagebox.showwarning('Mod loader', f'Close {", ".join(busy)} first.', parent=self)
            return False
        try:
            import busy
            mods = list(self.mods)
            done = busy.run(self, 'Saving the mods and building the size table from the game files...',
                            lambda: apply(mods))
        except (OSError, ValueError) as err:
            messagebox.showerror('Mod loader', f'The folders could not be renamed:\n{err}', parent=self)
            self.dirty = False
            self.reload()
            return False
        self.dirty = False
        self.mods = scan()
        self.fill()
        self.status['text'] = (self.status['text'] + f'   -   saved ({len(done)} renamed)')
        return True

    def play(self):
        if not GAME_EXE.is_file():
            messagebox.showerror('Mod loader', f'{GAME_EXE} is not there.', parent=self)
            return
        if self.save():
            subprocess.Popen([str(GAME_EXE)], cwd=str(GAME_EXE.parent))
            self.after_play()

    def restyle(self):
        """New theme colours (the toolbox's Look tab) on what does not follow the ttk styles by itself."""
        self.tree.tag_configure('off', foreground=theme.DIM)
        self.tree.tag_configure('clash', foreground=theme.ERROR)
        self.where.configure(foreground=theme.SOFT)
        self.note.configure(foreground=theme.SOFT)

    def may_close(self):
        """True when the window may close: nothing unsaved, or the player said to drop it."""
        return not self.dirty or messagebox.askyesno('Mod loader', 'Close without saving your mod changes?', parent=self)

    def close(self):
        if self.may_close():
            self.winfo_toplevel().destroy()


def main():
    if '--list' in sys.argv:          # what the window would show, without it
        mods = scan()
        cl = clashes(mods)
        on = [m for m in mods if m.on and m.loads]
        for m in mods:
            print(f'{"on " if m.on and m.loads else "off"}  {m.folder:40} -> {m.target(on.index(m) + 1 if m in on else 0):40}'
                  f' {len(m.files):3} files  {cl.get(m.name, "")}')
        return
    root = tk.Tk()
    theme.apply(root)
    import icons
    icons.apply(root)
    root.geometry('760x520')
    root.minsize(560, 380)
    app = App(root)
    app.pack(fill='both', expand=True)
    root.protocol('WM_DELETE_WINDOW', app.close)
    try:
        import dragdrop
        dragdrop.enable(root, app.add_paths)
    except Exception:
        pass
    root.mainloop()


if __name__ == '__main__':
    main()
