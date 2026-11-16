"""Link's Tool Box: the mod loader and the save editor in one window, a tab each.

    Mods          switch the mods in game/mods on and off, set their order, Save and play (mod_loader.pyw)
    Save editor   every entry of a save by name, the Give buttons (save_editor.pyw)
    Folders       use another game, mods or saves folder (kept in toolbox_settings.json, which the two use on
                  their own too)
    Look          the theme, the accent colour and each tab's colour (theme.py)

Run:  python\\pythonw.exe save-editor\\toolbox.pyw      (or Link Toolbox.bat). The two still open on their own too.
"""
import importlib.util
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nxsave  # noqa: E402
import theme  # noqa: E402
import icons  # noqa: E402
import updater  # noqa: E402
import jpeg_win  # noqa: E402
from tkinter import colorchooser  # noqa: E402

BASE_TITLE = nxsave.APP_NAME
CREDIT = 'Cum_Dumpster'      # the watermark along the bottom of the window


def load(name):
    """A .pyw module of this folder (import does not look at .pyw files)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + '.pyw'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod_loader = save_editor = None     # (loaded by main once the game's folder is known: they read it when loaded)


def ask_game_dir(root):
    """On a PC where the game is not where it usually is: ask once for its folder, kept in the settings."""
    messagebox.showinfo(BASE_TITLE, 'Where is the game?\n\nPick the folder that has Triforce.exe (or Longshot\'s longshot.exe) in it: '
                        'the game folder it built, with the romfs folder inside.', parent=root)
    while True:
        path = filedialog.askdirectory(parent=root, title='The game folder (with Triforce.exe or longshot.exe)', mustexist=True)
        if not path:
            return False
        if nxsave.is_game_dir(path):
            nxsave.save_settings({**nxsave.load_settings(), 'game_dir': os.path.normpath(path)})
            return True
        if not messagebox.askretrycancel(BASE_TITLE, f'{path}\n\nhas no Triforce.exe, longshot.exe or romfs folder.', parent=root):
            return False


def load_tools():
    global mod_loader, save_editor
    mod_loader = load('mod_loader')
    save_editor = load('save_editor')



class Toolbox:
    def __init__(self, root):
        self.root = root
        root.title(BASE_TITLE)
        root.geometry('1100x720')
        root.minsize(760, 440)
        self.titles = {}
        ttk.Label(root, text=f"{nxsave.APP_NAME}  ·  by {CREDIT}", foreground=theme.FAINT,
                  font=(theme.FAMILY, 8, 'italic')).pack(side='bottom', anchor='e', padx=10, pady=(0, 4))
        self.book = ttk.Notebook(root)
        self.book.pack(fill='both', expand=True, padx=6, pady=6)
        self.mods = mod_loader.App(self.book, on_title=lambda t: self.set_title('mods', t), after_play=self.after_play)
        self.book.add(self.mods, text='Mods')
        # (Save and play in the save editor: its edits are saved, then the Mods tab saves the mods and starts the game)
        self.saves = save_editor.App(self.book, on_title=lambda t: self.set_title('saves', t),
                                     on_play=lambda: self.mods.play())
        self.book.add(self.saves, text='Save editor')
        # (mods dragged onto the window from Explorer: the Mods tab comes to the front and adds them)
        try:
            import dragdrop
            dragdrop.enable(root, self.dropped)
        except Exception:
            pass
        self.folders = self.make_folders_tab()
        self.book.add(self.folders, text='Folders')
        self.look = self.make_look_tab()
        self.book.add(self.look, text='Look')
        self.updates = self.make_updates_tab()
        self.book.add(self.updates, text='Updates')
        theme.color_tabs(self.book, ['Mods', 'Save editor', 'Folders', 'Look', 'Updates'])
        self.book.bind('<<NotebookTabChanged>>', lambda _e: self.on_tab(), add='+')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.on_tab()

    # -- the Folders tab: where the mods and the saves are, when not the usual places
    def make_folders_tab(self):
        tab = ttk.Frame(self.book, padding=16)
        tab.columnconfigure(1, weight=1)
        settings = nxsave.load_settings()
        self.game_var = tk.StringVar(value=settings.get('game_dir', ''))
        self.mods_var = tk.StringVar(value=settings.get('mods_dir', ''))
        self.save_var = tk.StringVar(value=settings.get('save_dir', ''))
        self.game_at_start = nxsave.game_dir()
        rows = (('Game folder', self.game_var, self.found_game(),
                 'The folder with Triforce.exe (or Longshot\'s longshot.exe) and romfs. Changing it takes effect when the toolbox is opened again.'),
                ('Mods folder', self.mods_var, mod_loader.DEFAULT_MODS,
                 'The folder of mod folders the Mods tab lists and switches on and off.'),
                ('Saves folder', self.save_var, nxsave.game_dir() / 'user' / 'save',
                 "A save's own folder (the one with slot_01, slot_02...), or a folder of those: the latest is used."))
        # every game folder found (Triforce, Longshot...): pick one to use it, its mods and its saves
        ttk.Label(tab, text='Games found', font=(theme.FAMILY, 10, 'bold')).grid(row=0, column=0, sticky='w')
        self.found_var = tk.StringVar()
        box = self.found_box = ttk.Combobox(tab, textvariable=self.found_var, state='readonly')
        box.grid(row=0, column=1, columnspan=2, sticky='ew', padx=8)
        box.bind('<<ComboboxSelected>>', lambda _e: self.pick_found(box.current()))
        self.forget_btn = ttk.Button(tab, text='Forget', command=self.forget_found, state='disabled')
        self.forget_btn.grid(row=0, column=3, padx=(6, 0))
        self.fill_found()
        now = os.path.normcase(str(self.game_at_start.resolve())) if self.game_at_start.exists() else ''
        self.app_at_start = nxsave.app_of(self.game_at_start)
        self.picked_app = settings.get('game_app', '')
        for i, (app, path) in enumerate(self.found):
            if os.path.normcase(str(path.resolve())) == now and app == self.app_at_start:
                box.current(i)
        hint = ('Pick one to play that game: the Game folder below is set to it, and its mods and saves are used.'
                if len(self.found) > 1 else 'Only one game folder was found. Another one can be picked below.')
        ttk.Label(tab, text=f'{hint}  (In use now: {nxsave.app_of(self.game_at_start)}.)',
                  foreground=theme.MUTED).grid(row=1, column=1, columnspan=3, sticky='w', padx=8)
        ttk.Separator(tab).grid(row=2, column=0, columnspan=4, sticky='ew', pady=(12, 0))
        r = 3
        for label, var, default, hint in rows:
            ttk.Label(tab, text=label, font=(theme.FAMILY, 10, 'bold')).grid(row=r, column=0, sticky='w', pady=(10, 0))
            ttk.Entry(tab, textvariable=var).grid(row=r, column=1, sticky='ew', padx=8, pady=(10, 0))
            ttk.Button(tab, text='Browse...', command=lambda v=var, d=default: self.browse(v, d)).grid(
                row=r, column=2, pady=(10, 0))
            ttk.Button(tab, text='Default', command=lambda v=var: v.set('')).grid(row=r, column=3, padx=(6, 0),
                                                                                    pady=(10, 0))
            ttk.Label(tab, text=f'{hint}\nEmpty: the default, {default}', foreground=theme.MUTED).grid(
                row=r + 1, column=1, columnspan=3, sticky='w', padx=8)
            r += 2
        self.keep_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text='Keep the game, mods and saves folders I fill in here as choices (in Games found, '
                                  'and in the Mods and Save editor Game lists)', variable=self.keep_var).grid(
            row=r, column=0, columnspan=4, sticky='w', pady=(14, 0))
        r += 1
        self.kept_box = ttk.LabelFrame(tab, text='Kept choices', padding=(10, 4))
        self.kept_box.grid(row=r, column=0, columnspan=4, sticky='ew', pady=(10, 0))
        self.kept_box.columnconfigure(1, weight=1)
        self.fill_kept()
        r += 1
        # Longshot builds: each one has its own folder (and its own mods folder)
        lb = ttk.LabelFrame(tab, text='Builds (Triforce, Longshot, NX2navi, any app)', padding=(10, 4))
        lb.grid(row=r, column=0, columnspan=4, sticky='ew', pady=(10, 0))
        lb.columnconfigure(1, weight=1)
        self.carry_var = tk.BooleanVar(value=nxsave.load_settings().get('carry_mods') is True)
        ttk.Checkbutton(lb, text='Bring my mods to new builds without asking (when the toolbox finds a newer build of '
                                 'the app you use, it copies the mods across and switches to it)', variable=self.carry_var,
                        command=lambda: nxsave.save_settings({**nxsave.load_settings(),
                                                              'carry_mods': True if self.carry_var.get() else 'off'})
                        ).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(lb, text='Shared mods folder').grid(row=1, column=0, sticky='w', pady=(6, 0))
        self.shared_label = ttk.Label(lb, text='', foreground=theme.SOFT, wraplength=560, justify='left')
        self.shared_label.grid(row=1, column=1, sticky='w', padx=8, pady=(6, 0))
        sb = ttk.Frame(lb)
        sb.grid(row=1, column=2, sticky='e', pady=(6, 0))
        self.share_btn = ttk.Button(sb, text='Use one shared mods folder...', command=self.share_mods)
        self.share_btn.pack(side='left')
        self.unshare_btn = ttk.Button(sb, text='Stop sharing', command=self.unshare_mods)
        self.unshare_btn.pack(side='left', padx=(6, 0))
        # one "user" folder (the saves) for Triforce and Longshot
        ttk.Label(lb, text='Shared saves').grid(row=2, column=0, sticky='w', pady=(8, 0))
        self.saves_label = ttk.Label(lb, text='', foreground=theme.SOFT, wraplength=560, justify='left')
        self.saves_label.grid(row=2, column=1, sticky='w', padx=8, pady=(8, 0))
        ss = ttk.Frame(lb)
        ss.grid(row=2, column=2, sticky='e', pady=(8, 0))
        self.share_saves_btn = ttk.Button(ss, text='Use one shared saves folder...', command=self.share_saves)
        self.share_saves_btn.pack(side='left')
        self.unshare_saves_btn = ttk.Button(ss, text='Stop sharing', command=self.unshare_saves)
        self.unshare_saves_btn.pack(side='left', padx=(6, 0))
        self.show_shared()
        r += 1
        ttk.Label(tab, text='Triforce and Longshot only load mods from the mods folder in the game folder '
                            f'({mod_loader.DEFAULT_MODS}). Mods kept anywhere else can be switched here but '
                            'the game will not see them, unless that folder is next to another game program '
                            '(then Save and play starts that one).',
                  foreground=theme.WARN, wraplength=760, justify='left').grid(row=r, column=0, columnspan=4,
                                                                              sticky='w', pady=(18, 0))
        bar = ttk.Frame(tab)
        bar.grid(row=r + 1, column=0, columnspan=4, sticky='e', pady=(18, 0))
        self.folders_status = ttk.Label(bar, text='', foreground=theme.SOFT)
        self.folders_status.pack(side='left', padx=(0, 12))
        ttk.Button(bar, text='Apply', command=self.apply_folders).pack(side='left')
        return tab

    # -- the Look tab: the theme, the accent colour and each tab's colour
    # -- the Updates tab: this copy's version, the newest on GitHub, and updating to it
    def make_updates_tab(self):
        import queue
        tab = ttk.Frame(self.book, padding=16)
        tab.columnconfigure(0, weight=1)
        kind = 'development copy'
        if os.name == 'nt' and not (updater.APP / '.git').exists():
            try:
                import install
                kind = 'installed app' if install.is_installed_copy() else 'portable'
            except Exception:
                kind = 'portable'
        elif os.name != 'nt':
            kind = 'Linux'
        ttk.Label(tab, text=f"{nxsave.APP_NAME} {nxsave.VERSION}   ({kind})", font=(theme.FAMILY, 12, 'bold')).grid(
            row=0, column=0, sticky='w')
        self.update_status = ttk.Label(tab, text='Not checked yet.', foreground=theme.SOFT, wraplength=900,
                                       justify='left')
        self.update_status.grid(row=1, column=0, sticky='w', pady=(6, 0))
        bar = ttk.Frame(tab)
        bar.grid(row=2, column=0, sticky='w', pady=(12, 0))
        self.check_btn = ttk.Button(bar, text='Check for updates', command=self.check_updates)
        self.check_btn.pack(side='left')
        self.update_btn = ttk.Button(bar, text='Update now', command=self.update_now, state='disabled')
        self.update_btn.pack(side='left', padx=(8, 0))
        ttk.Button(bar, text='Release page', command=lambda: __import__('webbrowser').open(
            self.newest.get('page') or f'https://github.com/{updater.REPO}/releases')).pack(side='left', padx=(8, 0))
        self.auto_check = tk.BooleanVar(value=nxsave.load_settings().get('check_updates', True))
        ttk.Checkbutton(tab, text='Check for updates when the toolbox opens', variable=self.auto_check,
                        command=lambda: nxsave.save_settings({**nxsave.load_settings(),
                                                              'check_updates': self.auto_check.get() or 'off'})).grid(
            row=3, column=0, sticky='w', pady=(10, 0))
        self.update_bar = ttk.Progressbar(tab, mode='determinate', maximum=100)
        self.update_bar.grid(row=4, column=0, sticky='ew', pady=(12, 0))
        self.update_bar.grid_remove()
        ttk.Label(tab, text='What\'s new', font=(theme.FAMILY, 10, 'bold')).grid(row=5, column=0, sticky='w',
                                                                                pady=(14, 4))
        self.update_notes = tk.Text(tab, height=14, wrap='word', relief='flat', padx=8, pady=6, font=theme.FONT)
        self.update_notes.grid(row=6, column=0, sticky='nsew')
        tab.rowconfigure(6, weight=1)
        self.update_notes.insert('1.0', 'The newest release\'s notes show here once checked.')
        self.update_notes.configure(state='disabled')
        why = updater.can_update()
        ttk.Label(tab, text=why or 'Update now downloads the Windows download from GitHub, closes the toolbox, puts '
                  'the new version in and opens it again. Your settings, backups, names lists and icon are kept.',
                  foreground=theme.MUTED, wraplength=900, justify='left').grid(row=7, column=0, sticky='w',
                                                                               pady=(10, 0))
        # uninstalling (an installed copy only: the one Install Link Toolbox.bat put in place)
        row = ttk.Frame(tab)
        row.grid(row=8, column=0, sticky='w', pady=(14, 0))
        mine = False
        if os.name == 'nt':
            try:
                import install
                mine = install.is_installed_copy()
            except Exception:
                pass
        if mine or kind != 'portable':
            ttk.Button(row, text=f"Uninstall {nxsave.APP_NAME} (this app)...", command=self.uninstall,
                       state='normal' if mine else 'disabled').pack(side='left')
            ttk.Label(row, text=(f"Removes only the {nxsave.APP_NAME} app: its folder, shortcuts and Windows Settings > "
                                 'Apps entry. The game, your game saves and your mods are not touched. It asks first.')
                      if mine else 'Uninstalling is for the installed app.',
                      foreground=theme.MUTED, wraplength=640, justify='left').pack(side='left', padx=(10, 0))
        else:                          # (portable: installing is the recommended way, and brings this copy's settings)
            ttk.Button(row, text='Install as an app (recommended)...', command=self.install_app).pack(side='left')
            ttk.Label(row, text=f"This is the portable {nxsave.APP_NAME}. It updates here too, but a new download starts "
                      'from scratch. Installed, it stays in one place and keeps your settings (game, folders, shared '
                      'builds, look) through every update. Your settings and backups from this copy come along. To '
                      'remove the portable copy, delete its folder.',
                      foreground=theme.MUTED, wraplength=640, justify='left').pack(side='left', padx=(10, 0))
        self.newest = {}
        self.update_q = queue.Queue()
        self.root.after(200, self.poll_updates)
        return tab

    def check_updates(self, quiet=False):
        """Asks GitHub for the newest release (on another thread: the window stays usable)."""
        import threading
        self.check_btn['state'] = 'disabled'
        if not quiet:
            self.update_status['text'] = 'Checking GitHub...'

        def work():
            try:
                self.update_q.put(('latest', (updater.latest(), quiet)))
            except Exception as err:      # (offline, GitHub down...)
                self.update_q.put(('error', (str(err), quiet)))
        threading.Thread(target=work, daemon=True).start()

    def poll_updates(self):
        try:
            while True:
                what, (arg, quiet) = self.update_q.get_nowait()
                self.check_btn['state'] = 'normal'
                if what == 'error':
                    if not quiet:
                        self.update_status['text'] = f'Could not reach GitHub: {arg}'
                elif what == 'latest':
                    self.show_latest(arg)
                elif what == 'progress':
                    self.update_bar['value'] = arg
        except Exception:
            pass
        self.root.after(200, self.poll_updates)

    def show_latest(self, rel):
        self.newest = rel
        self.update_notes.configure(state='normal')
        self.update_notes.delete('1.0', 'end')
        import re
        notes = re.sub(r'\*\*|`|^#+\s*', '', rel['notes'], flags=re.M)          # (GitHub's formatting marks)
        notes = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', notes).replace('\r', '')  # ([text](link) -> text)
        notes = re.sub(r'^(\s*)- ', lambda m: m.group(1) + '• ', notes, flags=re.M)
        self.update_notes.insert('1.0', f"{rel['version']}\n\n{notes}")
        self.update_notes.configure(state='disabled')
        newer = updater.is_newer(rel['version']) and rel.get('url')
        if newer:
            size = f" ({rel['size'] / 2**20:.0f} MB)" if rel.get('size') else ''
            self.update_status['text'] = f"{rel['version']} is out{size}: you have {nxsave.VERSION}."
            self.book.tab(self.updates, text='Updates (new)')
        else:
            self.update_status['text'] = f"You have the newest version ({nxsave.VERSION})."
        self.update_btn['state'] = 'normal' if newer and not updater.can_update() else 'disabled'

    def dropped(self, paths):
        self.book.select(self.mods)
        self.root.update_idletasks()
        self.mods.add_paths(paths)

    def install_app(self):
        """Opens the install window of this portable copy (the same one Install Link Toolbox.bat opens)."""
        import subprocess
        script = Path(__file__).resolve().parent / 'install.py'
        py = Path(sys.executable)
        py = py.with_name('pythonw.exe') if py.with_name('pythonw.exe').is_file() else py
        try:
            subprocess.Popen([str(py), str(script)], cwd=str(script.parent))
        except OSError as err:
            messagebox.showerror(nxsave.APP_NAME, f'The installer could not be opened:\n{err}', parent=self.root)
            return
        messagebox.showinfo(nxsave.APP_NAME, 'The install window is opening. Once it is installed, use the new '
                            f'"{nxsave.APP_NAME}" shortcut, and close this portable copy.', parent=self.root)

    def uninstall(self):
        """Asks twice (uninstall? keep backups and settings?), then the toolbox closes and is removed."""
        if not (self.mods.may_close() and self.saves.may_close()):
            return
        import install
        if install.uninstall(parent=self.root):
            self.root.destroy()        # (the uninstall script waits for this window to close)

    def update_now(self):
        rel = self.newest
        if not rel.get('url') or not (self.mods.may_close() and self.saves.may_close()):
            return
        if nxsave.game_running():
            messagebox.showwarning('Update', 'Close the game first, then update.', parent=self.root)
            return
        if not messagebox.askyesno('Update', f"Update to {rel['version']}?\n\nThe toolbox downloads it, closes, puts "
                                   'the new version in and opens again. Your settings, backups and icon are kept.',
                                   parent=self.root):
            return
        import threading
        self.update_btn['state'] = self.check_btn['state'] = 'disabled'
        self.update_bar.grid()
        self.update_status['text'] = f"Downloading {rel['version']}..."

        def work():
            try:
                updater.start(rel['url'], lambda done, total: self.update_q.put(
                    ('progress', (100 * done / total if total else 0, True))))
                self.root.after(0, self.root.destroy)        # the update script waits for this to close
            except Exception as err:
                self.update_q.put(('error', (f'The update failed: {err}', False)))
        threading.Thread(target=work, daemon=True).start()

    def make_look_tab(self):
        tab = ttk.Frame(self.book, padding=16)
        t = nxsave.load_settings().get('theme') or {}
        self.look_preset = tk.StringVar(value=theme.PRESET)
        self.look_accent = t.get('accent') or theme.DEFAULT_ACCENT
        self.look_tabs = dict(theme.TAB_COLORS)
        self.swatches = {}

        top = ttk.LabelFrame(tab, text='Theme', padding=(12, 8))
        top.pack(fill='x')
        ttk.Label(top, text='Colours').grid(row=0, column=0, sticky='w')
        box = ttk.Combobox(top, textvariable=self.look_preset, values=list(theme.PRESETS), state='readonly',
                           width=20)
        box.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=3)
        box.bind('<<ComboboxSelected>>', lambda _e: self.apply_look())
        ttk.Label(top, text='Accent').grid(row=1, column=0, sticky='w')
        self.swatch(top, 1, 'accent', lambda: self.look_accent)
        ttk.Label(top, text='headings, box titles, the buttons\' focus', foreground=theme.MUTED).grid(
            row=1, column=4, sticky='w', padx=(10, 0))

        tabs = ttk.LabelFrame(tab, text='Tab colours', padding=(12, 8))
        tabs.pack(fill='x', pady=(12, 0))
        groups = (('Toolbox', ('Mods', 'Save editor', 'Folders', 'Look', 'Updates')),
                  ('Save editor', ('Stats', 'Inventory', 'Progress', 'All entries')))
        for c, (title, names) in enumerate(groups):
            ttk.Label(tabs, text=title, foreground=theme.MUTED).grid(row=0, column=c * 5, sticky='w', pady=(0, 4))
            for r, name in enumerate(names, 1):
                ttk.Label(tabs, text=name).grid(row=r, column=c * 5, sticky='w', padx=(0, 10))
                self.swatch(tabs, r, name, lambda n=name: self.look_tabs[n], col=c * 5 + 1)
            tabs.columnconfigure(c * 5 + 4, minsize=60)

        self.make_icon_box(tab)

        bar = ttk.Frame(tab)
        bar.pack(fill='x', pady=(16, 0))
        ttk.Button(bar, text='Everything back to default', command=self.reset_look).pack(side='left')
        self.look_status = ttk.Label(bar, text='Changes show at once. A few hint texts take the new colours when '
                                               'the toolbox opens again.', foreground=theme.MUTED)
        self.look_status.pack(side='left', padx=(14, 0))
        return tab

    # -- the icon: drawn ones or a square of a save slot's picture; shortcuts that show it
    def make_icon_box(self, tab):
        box = ttk.LabelFrame(tab, text='Icon', padding=(12, 8))
        box.pack(fill='x', pady=(12, 0))
        self.icon_preview = ttk.Label(box)
        self.icon_preview.grid(row=0, column=0, rowspan=6, sticky='nw', padx=(0, 16))
        self.icon_pixels = None
        self.icon_kind = tk.StringVar(value="Link's Tool Box")
        r = 0
        for name in icons.STYLES:
            ttk.Radiobutton(box, text=name, value=name, variable=self.icon_kind,
                            command=self.preview_icon).grid(row=r, column=1, sticky='w')
            r += 1
        ttk.Radiobutton(box, text='A save slot\'s picture:', value='slot', variable=self.icon_kind,
                        command=self.preview_icon).grid(row=r, column=1, sticky='w')
        self.icon_slot = tk.StringVar()
        slot_box = ttk.Combobox(box, textvariable=self.icon_slot, state='readonly', width=12,
                                values=[label for label, _ in self.saves.slots])
        slot_box.grid(row=r, column=2, sticky='w', padx=(6, 0))
        slot_box.bind('<<ComboboxSelected>>', lambda _e: (self.icon_kind.set('slot'), self.preview_icon()))
        if self.saves.slots:
            slot_box.current(0)
        r += 1
        ttk.Label(box, text='Which part (left to right)', foreground=theme.MUTED).grid(row=r, column=1, sticky='w',
                                                                                      padx=(22, 0))
        self.icon_offset = tk.DoubleVar(value=50)
        ttk.Scale(box, from_=0, to=100, variable=self.icon_offset, length=180,
                  command=lambda _v: self.icon_kind.get() == 'slot' and self.soon_preview()).grid(
            row=r, column=2, sticky='w', padx=(6, 0))
        r += 1
        buttons = ttk.Frame(box)
        buttons.grid(row=r, column=1, columnspan=3, sticky='w', pady=(8, 0))
        ttk.Button(buttons, text='Use this icon', command=self.use_icon).pack(side='left')
        ttk.Button(buttons, text='Shortcut on the Desktop', command=lambda: self.shortcut(1)).pack(side='left',
                                                                                                padx=(14, 0))
        ttk.Button(buttons, text='Shortcut next to Link Toolbox.bat', command=lambda: self.shortcut(0)).pack(
            side='left', padx=(6, 0))
        self.icon_status = ttk.Label(box, text='A .bat file cannot have an icon: start the toolbox from a shortcut '
                                               'to see this one.', foreground=theme.MUTED)
        self.icon_status.grid(row=r + 1, column=1, columnspan=3, sticky='w', pady=(6, 0))
        self._icon_job = None
        self.show_icon_file()

    def show_icon_file(self):
        """The preview: the icon in use."""
        try:
            icons.ensure()
            self._icon_img = tk.PhotoImage(master=self.root, file=str(icons.PNG)).subsample(2)
            self.icon_preview.configure(image=self._icon_img)
        except tk.TclError:
            pass

    def soon_preview(self):
        if self._icon_job:
            self.root.after_cancel(self._icon_job)
        self._icon_job = self.root.after(150, self.preview_icon)

    def slot_picture(self):
        """The PNG of the chosen slot's picture, None when it has none."""
        label = self.icon_slot.get()
        paths = dict(self.saves.slots).get(label, {})
        if 'caption' not in paths:
            return None
        try:
            sf = nxsave.SaveFile(paths['caption'])
        except (OSError, ValueError):
            return None
        e = next((e for e in sf.entries if e.hash == save_editor.cat.PICTURE), None)
        return jpeg_win.jpeg_to_png(e.value) if e is not None and isinstance(e.value, bytes) else None

    def preview_icon(self):
        self._icon_job = None
        kind = self.icon_kind.get()
        if kind == 'slot':
            png = self.slot_picture()
            if not png:
                self.icon_status['text'] = f'{self.icon_slot.get() or "That slot"} has no picture.'
                return
            px = icons.from_picture(png, self.icon_offset.get() / 100)
        else:
            px = icons.STYLES[kind]()
        self.icon_pixels = px
        self._icon_img = tk.PhotoImage(master=self.root, data=icons.png_encode(256, 256, px), format='png'
                                       ).subsample(2)
        self.icon_preview.configure(image=self._icon_img)
        self.icon_status['text'] = 'Preview. "Use this icon" puts it on the window and the shortcuts.'

    def use_icon(self):
        if self.icon_pixels is None:
            self.preview_icon()
        if self.icon_pixels is None:
            return
        try:
            icons.save(self.icon_pixels)
            icons.apply(self.root)
        except OSError as err:
            self.icon_status['text'] = f'The icon could not be written: {err}'
            return
        self.icon_status['text'] = ('Icon saved: on this window now, and on the shortcuts. (Windows may show the old '
                                    'one for a moment.)')

    def shortcut(self, which):
        lnk = icons.shortcuts()[which]
        ok = icons.make_shortcut(lnk)
        self.icon_status['text'] = f'Shortcut made: {lnk}' if ok else f'The shortcut could not be made at {lnk}.'

    def swatch(self, parent, row, key, get, col=1):
        """A square of a colour, a Pick button and a Default button, in a row of a grid."""
        sw = tk.Label(parent, width=4, background=get(), relief='solid', borderwidth=1, cursor='hand2')
        sw.grid(row=row, column=col, sticky='w', padx=(10, 6), pady=3)
        sw.bind('<Button-1>', lambda _e: self.pick_color(key))
        ttk.Button(parent, text='Pick...', command=lambda: self.pick_color(key)).grid(row=row, column=col + 1,
                                                                                     sticky='w')
        ttk.Button(parent, text='Default', command=lambda: self.default_color(key)).grid(row=row, column=col + 2,
                                                                                        sticky='w', padx=(6, 0))
        self.swatches[key] = sw

    def pick_color(self, key):
        now = self.look_accent if key == 'accent' else self.look_tabs[key]
        _rgb, color = colorchooser.askcolor(color=now, parent=self.root,
                                            title='Accent colour' if key == 'accent' else f'Colour of the {key} tab')
        if not color:
            return
        if key == 'accent':
            self.look_accent = color
        else:
            self.look_tabs[key] = color
        self.apply_look()

    def default_color(self, key):
        if key == 'accent':
            self.look_accent = theme.DEFAULT_ACCENT
        else:
            self.look_tabs[key] = theme.DEFAULT_TABS[key]
        self.apply_look()

    def reset_look(self):
        self.look_preset.set(theme.DEFAULT_PRESET)
        self.look_accent = theme.DEFAULT_ACCENT
        self.look_tabs = dict(theme.DEFAULT_TABS)
        self.apply_look()

    def apply_look(self):
        """Keeps the choice in the settings and puts it on everything open."""
        tabs = {k: v for k, v in self.look_tabs.items() if v.lower() != theme.DEFAULT_TABS[k].lower()}
        look = {'preset': self.look_preset.get(), 'accent': self.look_accent, 'tabs': tabs}
        settings = {**nxsave.load_settings(), 'theme': look}
        try:
            nxsave.save_settings(settings)
        except OSError as err:
            self.look_status['text'] = f'Could not keep the choice: {err}'
        theme.refresh(self.root, settings)
        for key, sw in self.swatches.items():
            sw.configure(background=self.look_accent if key == 'accent' else self.look_tabs[key])
        self.saves.restyle()
        self.mods.restyle()

    def reopen(self):
        """Starts the toolbox again (a new game folder is read when it starts) and closes this one."""
        import subprocess
        py = sys.executable
        windowless = os.path.join(os.path.dirname(py), 'pythonw.exe')
        subprocess.Popen([windowless if os.path.isfile(windowless) else py, os.path.join(HERE, 'toolbox.pyw')],
                         cwd=HERE)
        self.root.destroy()

    def fill_found(self):
        """The Games found list: every game found, and the game folders kept from the Folders tab ('(kept)')."""
        self.found = nxsave.all_game_dirs()
        self.found_box['values'] = [f'{app}  —  {path}' + ('   (kept)' if nxsave.is_remembered('games', path)
                                                                else '') for app, path in self.found]
        self.forget_btn['state'] = 'disabled'

    # -- one shared mods folder for every build of every app (each build's mods folder becomes a link to it)
    def show_shared(self):
        shared = nxsave.shared_folder()
        legacy = nxsave.shared_mods() if not shared else None       # (v1.1.7's Longshot-only HOS_MODS)
        if shared:
            n = sum(1 for g in __import__('builds').all_builds() if nxsave.is_link(Path(g) / 'mods'))
            self.shared_label['text'] = (f'On: {shared}\n{n} build{"s" if n != 1 else ""} use it (new builds are '
                                         'linked to it when the toolbox finds them).')
        elif legacy:
            self.shared_label['text'] = f'On for Longshot only (HOS_MODS): {legacy}. Stop sharing turns it off.'
        else:
            self.shared_label['text'] = ('Off: each build uses the mods folder in its own folder. On: one folder for '
                                         'every build of every app, so a new build has your mods straight away.')
        self.share_btn['state'] = 'disabled' if shared or legacy else 'normal'
        self.unshare_btn['state'] = 'normal' if shared or legacy else 'disabled'
        saves = nxsave.load_settings().get('shared_saves')
        if saves:
            import builds
            n = sum(1 for _l, p in builds.save_places() if nxsave.is_link(p))
            self.saves_label['text'] = (f'On: {saves}\nTriforce and Longshot use the same saves ({n} place'
                                        f'{"s" if n != 1 else ""} linked).')
        else:
            self.saves_label['text'] = ('Off: Triforce and Longshot each keep their own saves (Longshot builds already '
                                        'share theirs). On: one "user" folder for both. NX2navi is left out.')
        self.share_saves_btn['state'] = 'disabled' if saves else 'normal'
        self.unshare_saves_btn['state'] = 'normal' if saves else 'disabled'

    def after_shared_change(self):
        mod_loader.DEFAULT_MODS = nxsave.mods_dir_for(mod_loader.GAME)
        if not self.mods.dirty:
            mod_loader.set_mods_dir(nxsave.load_settings().get('mods_dir') or None)
            self.mods.reload()
        self.show_shared()

    def share_mods(self):
        import builds
        if not (self.mods.may_close()):
            return
        if nxsave.game_running():
            messagebox.showwarning('Shared mods folder', 'Close the game first.', parent=self.root)
            return
        suggest = Path.home() / 'Games' / 'Link Toolbox mods'
        games = builds.all_builds()
        answer = messagebox.askyesnocancel(
            'Shared mods folder', 'Use one mods folder for every build of every app (Triforce, Longshot, NX2navi...)?'
            f'\n\nEach build\'s "mods" folder becomes a link to it ({len(games)} found now; new builds are linked when '
            'the toolbox finds them). The mods already in those folders are moved into it. "Stop sharing" undoes it.'
            f'\n\nUse this folder?\n  {suggest}\n\nYes: use it.   No: pick another folder.', parent=self.root)
        if answer is None:
            return
        folder = suggest if answer else Path(filedialog.askdirectory(parent=self.root, mustexist=False,
                                                                       title='The shared mods folder') or '')
        if not str(folder) or str(folder) == '.':
            return
        if any(builds.same(folder, Path(g) / 'mods') or builds.same(folder, g) for g in games):
            messagebox.showerror('Shared mods folder', 'Pick a folder outside the game folders.', parent=self.root)
            return
        import busy
        linked, failed = busy.run(self.root, f'Setting up the shared mods folder:\nmoving the mods into {folder} and '
                                  'linking every build to it...', lambda: builds.start_sharing(folder))
        self.after_shared_change()
        self.fill_found()
        msg = f'Shared mods folder on: {folder}\n\n{len(linked)} build{"s" if len(linked) != 1 else ""} now use it.'
        if failed:
            msg += '\n\nCould not link:\n' + '\n'.join(failed)
        (messagebox.showwarning if failed else messagebox.showinfo)('Shared mods folder', msg, parent=self.root)
        self.folders_status['text'] = f'Shared mods folder on: {folder}'

    def unshare_mods(self):
        import builds
        shared = nxsave.shared_folder() or nxsave.shared_mods()
        if not shared or not self.mods.may_close():
            return
        if nxsave.game_running():
            messagebox.showwarning('Stop sharing', 'Close the game first.', parent=self.root)
            return
        answer = messagebox.askyesnocancel(
            'Stop sharing', f'Stop the shared mods folder?\n  {shared}\n\nEach build gets its own mods folder again '
            '(the shared folder itself is left as it is).\n\nCopy the shared mods into every build\'s own mods '
            'folder?\nYes: copy them.   No: start them empty.', parent=self.root)
        if answer is None:
            return
        import busy
        done = busy.run(self.root, 'Stopping the shared mods folder:\nremoving the links' +
                        (' and copying the mods back into every build...' if answer else '...'),
                        lambda: builds.stop_sharing(copy_back=answer))
        self.after_shared_change()
        self.folders_status['text'] = (f'Shared mods folder off: {len(done)} build{"s" if len(done) != 1 else ""} use '
                                       'their own mods folder again.')

    # -- one shared "user" folder (the saves) for Triforce and Longshot
    def share_saves(self):
        import builds
        import time
        if not self.saves.may_discard():
            return
        busy_game = nxsave.game_running()
        if busy_game:
            messagebox.showwarning('Shared saves', f'Close {busy_game} first: a running game writes the saves.',
                                   parent=self.root)
            return
        places = builds.save_places()
        if len(places) < 2:
            messagebox.showinfo('Shared saves', 'Only one place with saves was found, so there is nothing to share.',
                                parent=self.root)
            return
        shared = Path.home() / 'Games' / 'Link Toolbox saves'
        choices = [(label, p) + builds.saves_summary(p) for label, p in places]
        if shared.is_dir() and builds.saves_summary(shared)[0]:
            choices.insert(0, ('The shared folder (already there)', shared) + builds.saves_summary(shared))
        choices = [c for c in choices if c[2]] or choices[:1]
        # the picker: whose saves the shared folder starts from
        win = tk.Toplevel(self.root)
        win.title('Shared saves')
        win.transient(self.root)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill='both', expand=True)
        ttk.Label(frm, text='One saves folder for Triforce and Longshot', font=(theme.FAMILY, 11, 'bold')).pack(
            anchor='w')
        ttk.Label(frm, text=f'Their "user" folders become links to\n  {shared}\n\nWhose saves should it start from? '
                            'The others are NOT mixed in or deleted: they are kept as they are, renamed '
                            '"... (before sharing)". Every save is also copied into the toolbox\'s backups first.',
                  wraplength=560, justify='left', foreground=theme.SOFT).pack(anchor='w', pady=(6, 10))
        pick = tk.IntVar(value=0)
        for i, (label, p, slots, last) in enumerate(choices):
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(last)) if last else 'no saves'
            ttk.Radiobutton(frm, text=f'{label}:  {slots} slot{"s" if slots != 1 else ""}, last saved {when}\n    {p}',
                            value=i, variable=pick).pack(anchor='w', pady=2)
        ttk.Label(frm, text='NX2navi is left out: its profile folder holds another account and other data.',
                  foreground=theme.MUTED).pack(anchor='w', pady=(8, 0))
        bar = ttk.Frame(frm)
        bar.pack(fill='x', pady=(12, 0))
        answer = {}

        def ok():
            answer['i'] = pick.get()
            win.destroy()
        ttk.Button(bar, text='Cancel', command=win.destroy).pack(side='right')
        ttk.Button(bar, text='Share the saves', command=ok).pack(side='right', padx=(0, 8))
        win.update_idletasks()
        win.geometry(f'+{self.root.winfo_rootx() + 120}+{self.root.winfo_rooty() + 80}')
        win.grab_set()
        self.root.wait_window(win)
        if 'i' not in answer:
            return
        label, source = choices[answer['i']][:2]
        import busy
        try:
            linked, failed, backup = busy.run(self.root, f'Setting up the shared saves from {label}:\nbacking every '
                                              'save up, then linking Triforce and Longshot to it...',
                                              lambda: builds.start_sharing_saves(shared, source))
        except OSError as err:
            messagebox.showerror('Shared saves', f'It could not be set up:\n{err}\n\nYour saves were backed up first, '
                                 'in the toolbox\'s backups folder.', parent=self.root)
            return
        self.saves.load_file_list()
        self.show_shared()
        msg = (f'Shared saves on: {shared}\nStarted from: {label}\n\nLinked: ' + ', '.join(linked) +
               f'\n\nBackup of every save first: {backup}')
        if failed:
            msg += '\n\nCould not link:\n' + '\n'.join(failed)
        (messagebox.showwarning if failed else messagebox.showinfo)('Shared saves', msg, parent=self.root)

    def unshare_saves(self):
        import builds
        shared = nxsave.load_settings().get('shared_saves')
        if not shared or not self.saves.may_discard():
            return
        busy_game = nxsave.game_running()
        if busy_game:
            messagebox.showwarning('Stop sharing saves', f'Close {busy_game} first.', parent=self.root)
            return
        if not messagebox.askyesno('Stop sharing saves', f'Stop the shared saves?\n  {shared}\n\nTriforce and Longshot '
                                   'each get their own saves folder again, with a copy of the shared saves (the '
                                   'shared folder itself is left as it is).', parent=self.root):
            return
        import busy
        done = busy.run(self.root, 'Stopping the shared saves: removing the links and copying the saves back...',
                        builds.stop_sharing_saves)
        self.saves.load_file_list()
        self.show_shared()
        self.folders_status['text'] = f'Shared saves off: {len(done)} place{"s" if len(done) != 1 else ""} use their ' \
                                      'own saves folder again.'

    KEPT_KINDS = (('games', 'Game'), ('mods', 'Mods'), ('saves', 'Saves'))

    def fill_kept(self):
        """The Kept choices list: every kept game, mods and saves folder, each with a Forget button."""
        for w in self.kept_box.winfo_children():
            w.destroy()
        rows = [(kind, label, p) for kind, label in self.KEPT_KINDS for p in nxsave.remembered(kind)]
        if not rows:
            ttk.Label(self.kept_box, text='Nothing kept. Folders you fill in above (that were not found) are kept '
                                          'here when you press Apply.', foreground=theme.MUTED).grid(sticky='w')
            return
        for i, (kind, label, p) in enumerate(rows):
            ttk.Label(self.kept_box, text=label, width=6, foreground=theme.GOLD).grid(row=i, column=0, sticky='w')
            missing = '' if os.path.isdir(p) else '   (not there any more)'
            ttk.Label(self.kept_box, text=p + missing).grid(row=i, column=1, sticky='w', padx=(6, 6))
            ttk.Button(self.kept_box, text='Forget', command=lambda k=kind, q=p: self.forget_kept(k, q)).grid(
                row=i, column=2, pady=1)

    def forget_kept(self, kind, path):
        nxsave.remember(kind, path, keep=False)
        self.fill_kept()
        self.fill_found()
        self.mods.fill_games()
        if kind == 'saves' and self.saves.may_discard():     # (its Game list loses the folder)
            self.saves.load_file_list()
        self.folders_status['text'] = f'Forgotten: {path}'

    def forget_found(self):
        i = self.found_box.current()
        if i < 0:
            return
        _app, path = self.found[i]
        nxsave.remember('games', path, keep=False)
        self.fill_found()
        self.fill_kept()
        self.mods.fill_games()
        self.found_var.set('')
        self.folders_status['text'] = f'Forgotten: {path}'

    def pick_found(self, i):
        """A game picked in Games found: it becomes the Game folder; its own mods and saves folders (the defaults)."""
        if i < 0:
            return
        app, path = self.found[i]
        self.forget_btn['state'] = 'normal' if nxsave.is_remembered('games', path) else 'disabled'
        self.game_var.set(str(path))
        self.picked_app = app if app != 'Game files' else ''
        self.mods_var.set('')
        self.save_var.set('')
        self.folders_status['text'] = f'{app} picked. Press Apply to use it.'

    @staticmethod
    def found_game():
        """Where the game is found when none is picked."""
        saved = nxsave.load_settings()
        nxsave.SETTINGS_OVERRIDE = {k: v for k, v in saved.items() if k != 'game_dir'}
        try:
            return nxsave.find_game_dir() or '(not found)'
        finally:
            nxsave.SETTINGS_OVERRIDE = None

    def browse(self, var, default):
        start = var.get() or str(default)
        path = filedialog.askdirectory(parent=self.root, initialdir=start if os.path.isdir(start) else None,
                                       mustexist=True)
        if path:
            var.set(os.path.normpath(path))

    def apply_folders(self):
        mods_dir, save_dir = self.mods_var.get().strip().strip('"'), self.save_var.get().strip().strip('"')
        game = self.game_var.get().strip().strip('"')
        if game and not nxsave.is_game_dir(game):
            messagebox.showerror('Folders', f'{game}\n\nhas no Triforce.exe, longshot.exe or romfs folder: not the game folder.',
                                 parent=self.root)
            return
        for path, what in ((mods_dir, 'mods'), (save_dir, 'saves')):
            if path and not os.path.isdir(path):
                messagebox.showerror('Folders', f'The {what} folder is not there:\n{path}', parent=self.root)
                return
        if save_dir and not nxsave.save_dirs_in(save_dir):
            if not messagebox.askyesno('Folders', f'No save was found in\n{save_dir}\n\nUse it anyway?',
                                       parent=self.root):
                return
        if not (self.mods.may_close() and self.saves.may_close()):     # (each asks about its changes not saved)
            return
        same = lambda a, b: bool(a) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
        if same(mods_dir, mod_loader.DEFAULT_MODS):
            mods_dir = ''
        if same(save_dir, nxsave.game_dir() / 'user' / 'save'):
            save_dir = ''
        self.mods_var.set(mods_dir)
        self.save_var.set(save_dir)
        nxsave.save_settings({**nxsave.load_settings(), 'mods_dir': mods_dir, 'save_dir': save_dir,
                              'game_dir': os.path.normpath(game) if game else '',
                              'game_app': self.picked_app if game else ''})
        if self.keep_var.get():    # folders filled in by hand, not found by the toolbox: kept as choices
            if game and not any(same(game, p) for _a, p in self.found):
                nxsave.remember('games', os.path.normpath(game))
            if save_dir and not any(same(save_dir, d) or same(save_dir, d.parent)
                                    for a, d in nxsave.all_save_locations() if a != 'Folders tab'):
                nxsave.remember('saves', os.path.normpath(save_dir))
            if mods_dir and not any(same(mods_dir, d) for l, d, _e in nxsave.all_mod_locations()
                                    if l != 'Folders tab'):
                nxsave.remember('mods', os.path.normpath(mods_dir))
            self.fill_found()
            self.fill_kept()
        if not same(str(nxsave.game_dir()), self.game_at_start) or nxsave.app_of() != self.app_at_start:
            self.folders_status['text'] = 'Saved. Open the toolbox again for the new game.'
            if messagebox.askyesno('Folders', f'Now playing {nxsave.app_of()} from\n{nxsave.game_dir()}\n\nThe '
                                   'toolbox needs to open again to use it. Open it again now?', parent=self.root):
                self.reopen()
            return
        mod_loader.set_mods_dir(mods_dir or None)
        self.mods.dirty = False
        self.mods.reload()
        self.saves.load_file_list()
        self.folders_status['text'] = (f'Saved. Mods tab: {len(self.mods.mods)} mods. Save editor: '
                                       f'{self.saves.save_file.path if self.saves.save_file else "no save found"}')

    def current(self):
        sel = self.book.select()
        return ('mods' if sel == str(self.mods) else 'saves' if sel == str(self.saves) else
                'look' if sel == str(getattr(self, 'look', None)) else
                'updates' if sel == str(getattr(self, 'updates', None)) else 'folders')

    def set_title(self, which, text):
        """Each tab says what it would call its window; the window shows the one in front, and a * on a tab's name
        while it has changes not saved."""
        self.titles[which] = text
        tab = getattr(self, which, None)          # (None while that tab is still being made: it reports early)
        if tab is None or str(tab) not in self.book.tabs():
            return
        self.book.tab(tab, text=('* ' if text.startswith('* ') else '') + ('Mods' if which == 'mods' else 'Save editor'))
        if which == self.current():
            self.root.title(f'{BASE_TITLE} - {text.lstrip("* ")}' if not text.startswith('* ')
                            else f'* {BASE_TITLE} - {text[2:]}')

    def on_tab(self):
        which = self.current()
        if which == 'mods':
            self.mods.fill()          # (the game may have been started or closed since)
        if which in ('folders', 'look', 'updates'):
            self.root.title(f'{BASE_TITLE} - {which.title()}')
            return
        self.set_title(which, self.titles.get(which, ''))

    def after_play(self):
        """The game is starting: the toolbox goes, unless the save editor has edits not saved."""
        if self.saves.may_close():
            self.root.destroy()

    def close(self):
        if self.mods.may_close() and self.saves.may_close():
            self.root.destroy()


def main():
    root = tk.Tk()
    theme.apply(root)
    icons.apply(root)
    if '--selftest' not in sys.argv:
        icons.first_run()
        if os.name == 'nt':
            try:                      # (installed copy: Windows Settings > Apps shows the version after an update)
                import install
                install.refresh_version()
            except Exception:
                pass
    if nxsave.find_game_dir() is None and '--selftest' not in sys.argv:
        root.withdraw()
        if not ask_game_dir(root):
            root.destroy()
            return
        root.deiconify()
    if '--selftest' not in sys.argv:  # a newer Longshot build: bring the mods along and switch (asks first)
        try:
            import builds
            builds.check(root)
        except Exception:
            pass
    load_tools()
    if '--selftest' not in sys.argv:  # (old copies of the toolbox's own mods an update left behind)
        try:
            mod_loader.tidy_bundled()
        except Exception:
            pass
    box = Toolbox(root)
    if '--selftest' not in sys.argv and nxsave.load_settings().get('check_updates', True) is True:
        root.after(1500, lambda: box.check_updates(quiet=True))    # (quiet: no message when offline)
    if '--selftest' in sys.argv:      # open both tabs, switch between them, close: nothing is written
        def done():
            print('tabs:', [box.book.tab(t, 'text') for t in box.book.tabs()], '| title:', root.title(),
                  '| mods listed:', len(box.mods.mods), '| save file:', box.saves.save_file.path if box.saves.save_file else None)
            root.destroy()
        root.report_callback_exception = lambda *a: (print('ERROR', a[1]), root.destroy())
        root.after(300, lambda: box.book.select(box.saves))
        root.after(900, lambda: box.book.select(box.folders))
        root.after(1200, lambda: box.book.select(box.mods))
        root.after(1800, done)
    root.mainloop()


if __name__ == '__main__':
    main()
