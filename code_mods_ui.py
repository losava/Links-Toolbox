"""The Code mods window (Mods tab > Code mods...): code mods put into Longshot's sources (code_mods.py), and the Build
they need afterwards (the Longshot Launcher's Build button)."""
import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import code_mods as cm
import theme

TITLE = 'Code mods'
WHY = ('A code mod changes how the game works, so it goes into Longshot\'s own sources, and the game is built again '
       'with the Longshot Launcher\'s Build button (a full build, about as long as the first one; about 60 GB free '
       'while it runs). Your game, saves and settings stay. Mods that only replace game files go in the list behind '
       'this window (Add mods).')


class CodeMods(tk.Toplevel):
    def __init__(self, parent, on_change=lambda: None):
        super().__init__(parent)
        self.title(TITLE)
        self.transient(parent.winfo_toplevel())
        self.on_change = on_change
        frm = ttk.Frame(self, padding=14)
        frm.pack(fill='both', expand=True)
        ttk.Label(frm, text='Code mods for Longshot', font=(theme.FAMILY, 12, 'bold')).pack(anchor='w')
        ttk.Label(frm, text=WHY, foreground=theme.MUTED, wraplength=720, justify='left').pack(anchor='w', pady=(4, 10))
        self.where = ttk.Label(frm, text='', foreground=theme.SOFT, wraplength=720, justify='left')
        self.where.pack(anchor='w')
        mid = ttk.Frame(frm)
        mid.pack(fill='both', expand=True, pady=(8, 0))
        self.tree = ttk.Treeview(mid, columns=('name', 'edition', 'state'), show='headings', selectmode='browse',
                                 height=7)
        for col, text, width in (('name', 'Code mod', 330), ('edition', 'Edition', 100), ('state', 'In Longshot', 260)):
            self.tree.heading(col, text=text, anchor='w')
            self.tree.column(col, width=width, anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.tag_configure('missing', foreground=theme.ERROR)
        self.tree.bind('<<TreeviewSelect>>', lambda _e: self.show_note())
        side = ttk.Frame(mid, padding=(8, 0, 0, 0))
        side.pack(side='right', fill='y')
        ttk.Button(side, text='Add code mod...', command=self.add).pack(fill='x')
        ttk.Button(side, text='Add from a folder...', command=lambda: self.add(folder=True)).pack(fill='x', pady=(4, 0))
        self.remove_btn = ttk.Button(side, text='Remove', command=self.remove)
        self.remove_btn.pack(fill='x', pady=(12, 0))
        self.back_btn = ttk.Button(side, text='Put them back', command=self.put_back)
        self.back_btn.pack(fill='x', pady=(4, 0))
        self.note = ttk.Label(frm, text='', foreground=theme.SOFT, wraplength=720, justify='left')
        self.note.pack(anchor='w', pady=(8, 0))
        bottom = ttk.Frame(frm)
        bottom.pack(fill='x', pady=(12, 0))
        self.build_note = ttk.Label(bottom, text='', wraplength=520, justify='left')
        self.build_note.pack(side='left', fill='x', expand=True)
        ttk.Button(bottom, text='Close', command=self.destroy).pack(side='right')
        self.launcher_btn = ttk.Button(bottom, text='Open the Longshot Launcher', command=self.open_launcher)
        self.launcher_btn.pack(side='right', padx=(0, 8))
        ttk.Button(bottom, text='Build the game now', command=lambda: build_game(
            self, on_done=lambda _ok: (self.refresh(), self.on_change()))).pack(side='right', padx=(0, 8))
        self.packages = []
        self.refresh()
        try:
            import icons
            icons.apply(self)
        except Exception:
            pass
        theme.center(self, parent)

    # -- the list
    def refresh(self):
        st = cm.status()
        self.packages = st['packages']
        roots = st['roots']
        if roots:
            self.where['text'] = 'Longshot\'s sources: ' + ', '.join(v or str(r) for r, v, _n, _m in roots)
        else:
            self.where['text'] = ('Longshot\'s sources were not found. Install Longshot with the Longshot Launcher and '
                                  'build the game there once (until Play works).')
        self.tree.delete(*self.tree.get_children())
        for i, m in enumerate(self.packages):
            missing = [v for _r, v, _n, miss in roots if m['name'] in miss]
            state = (f'missing in {", ".join(missing)}: Put them back' if missing else
                     'in every version' if roots else '')
            self.tree.insert('', 'end', iid=str(i), values=(m['name'], cm.edition(m), state),
                             tags=('missing',) if missing else ())
        any_missing = any(miss for _r, _v, _n, miss in roots)
        self.back_btn['state'] = 'normal' if any_missing else 'disabled'
        needs = [v for _r, v, n, _m in roots if n]
        if needs:
            self.build_note.configure(text=f'Build needed: open the Longshot Launcher and press Build ({", ".join(needs)}).'
                                      ' Until then the game is the one built before.', foreground=theme.ERROR)
        else:
            self.build_note.configure(text='The game is built with these code mods.' if self.packages and roots else '',
                                      foreground=theme.SOFT)
        self.launcher_btn['state'] = 'normal' if cm.launcher_exe() else 'disabled'
        self.remove_btn['state'] = 'normal' if self.packages else 'disabled'
        self.show_note()

    def selected(self):
        sel = self.tree.selection()
        return self.packages[int(sel[0])] if sel else None

    def show_note(self):
        m = self.selected()
        if not m:
            self.note['text'] = '' if self.packages else 'No code mods yet: Add code mod... takes the mod\'s .zip.'
            return
        opts = cm.options(m)
        self.note['text'] = (('Options (no Build needed: put the line in a text file named longshot_env.txt beside '
                              'longshot.exe, then restart the game):\n' +
                              '\n'.join(f'  {o}   {about}' for o, about in opts)) if opts else '')

    # -- doing
    def run(self, text, work):
        import busy
        lines = []
        try:
            out = busy.run(self, text, lambda: work(lines.append), title=TITLE)
        except cm.CodeModError as err:
            messagebox.showerror(TITLE, str(err), parent=self)
            return None
        except OSError as err:
            messagebox.showerror(TITLE, f'It could not be done:\n{err}', parent=self)
            return None
        finally:
            self.refresh()
            self.on_change()
        return out

    def add(self, folder=False):
        if folder:
            path = filedialog.askdirectory(parent=self, mustexist=True, title='The code mod\'s folder (unzipped)')
        else:
            path = filedialog.askopenfilename(parent=self, title='The code mod (.zip)',
                                              filetypes=[('Zip files', '*.zip'), ('All files', '*.*')])
        if not path:
            return
        names = self.run('Putting the code mod into Longshot\'s sources...', lambda log: cm.install(Path(path), log))
        if names:
            messagebox.showinfo(TITLE, f'Put in: {", ".join(names)}\n\nNow open the Longshot Launcher and press Build. '
                                'When it has finished, press Play.', parent=self)

    def remove(self):
        m = self.selected()
        if not m:
            messagebox.showinfo(TITLE, 'Pick a code mod in the list first.', parent=self)
            return
        if not messagebox.askyesno(TITLE, f'Take "{m["name"]}" out of Longshot\'s sources (and its game files out of '
                                   'the mods folder)?\n\nThen Build again in the Longshot Launcher, so the game is '
                                   'built without it.', parent=self):
            return
        if self.run('Taking the code mod out...', lambda log: cm.uninstall(m['family'], log)):
            messagebox.showinfo(TITLE, f'{m["name"]} is out. Now press Build in the Longshot Launcher.', parent=self)

    def put_back(self):
        if self.run('Putting the code mods back into Longshot\'s sources...', lambda log: cm.apply(log=log)):
            messagebox.showinfo(TITLE, 'They are back in. Now press Build in the Longshot Launcher.', parent=self)

    def open_launcher(self):
        exe = cm.launcher_exe()
        if exe:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))


# ------------------------------------------------------------------------------- Build the game (the launcher's builder)
def build_progress(lines):
    """(percent, step) from the builder's newest progress line ("progress 0.420 Translating..."), (None, '') when it
    has sent none."""
    for text in reversed(lines[-50:]):
        parts = text.split(None, 2)
        if len(parts) >= 2 and parts[0] == 'progress':
            try:
                f = float(parts[1])
            except ValueError:
                continue
            return max(0.0, min(100.0, f * 100)), (parts[2] if len(parts) > 2 else '')
    return None, ''


def build_game(parent, game=None, on_done=lambda ok: None):
    """Builds the game folder again with the launcher's own builder (code patches and code mods go in at a build), in
    a window that shows how far it is. Asks first; refuses while the game runs."""
    import nxsave
    import threading
    game = Path(game or nxsave.game_dir())
    try:
        cmd = cm.build_command(game)
    except cm.CodeModError as err:
        messagebox.showerror('Build the game', str(err), parent=parent)
        return
    running = nxsave.game_running()
    if running and running.lower() != 'longshotlauncher.exe':
        messagebox.showwarning('Build the game', f'Close {running} first: the build rewrites the game\'s files.',
                               parent=parent)
        return
    version = nxsave.longshot_version(game)
    msg = (f'Build Longshot {version} again now?\n\n{game}\n\nIt puts your code patches and code mods into the game. '
           'It takes a few minutes (15 to 30 the first time); your saves, settings and mods stay.')
    if running:
        msg += '\n\nThe Longshot Launcher is open: don\'t start a build in it at the same time.'
    if not messagebox.askyesno('Build the game', msg, parent=parent):
        return
    win = tk.Toplevel(parent)
    win.title(f'Building Longshot {version}')
    win.transient(parent.winfo_toplevel())
    win.resizable(False, False)
    frm = ttk.Frame(win, padding=(18, 14))
    frm.pack(fill='both', expand=True)
    head = ttk.Label(frm, text=f'Building Longshot {version}...', font=(theme.FAMILY, 10, 'bold'))
    head.pack(anchor='w')
    bar = ttk.Progressbar(frm, mode='indeterminate', length=520)
    bar.pack(fill='x', pady=(10, 6))
    bar.start(12)
    line = ttk.Label(frm, text='Starting...', foreground=theme.SOFT, wraplength=520, justify='left')
    line.pack(anchor='w')
    row = ttk.Frame(frm)
    row.pack(fill='x', pady=(12, 0))
    close = ttk.Button(row, text='Close', command=win.destroy, state='disabled')
    close.pack(side='right')
    win.protocol('WM_DELETE_WINDOW', lambda: None if str(close['state']) == 'disabled' else win.destroy())
    theme.center(win, parent)
    log_path = game / 'logs' / 'link-toolbox-build.log'
    lines, state = [], {}

    def job():
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, 'w', encoding='utf-8', errors='replace', buffering=1) as log:
                env = dict(os.environ, PYTHONUNBUFFERED='1')     # (its Python steps: lines as they happen)
                p = subprocess.Popen(cmd, cwd=str(Path(cmd[0]).parent), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                     env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                for text in p.stdout:
                    log.write(text)
                    if text.strip():
                        lines.append(text.strip())
                state['code'] = p.wait()
        except OSError as err:
            lines.append(str(err))
            state['code'] = -1

    def poll():
        if not win.winfo_exists():
            return
        if lines:
            # the builder's own progress ("progress 0.420 Translating the game to PC code"): a real bar and a percent
            pct, step = build_progress(lines)
            if pct is not None:
                if str(bar['mode']) != 'determinate':
                    bar.stop()
                    bar.configure(mode='determinate', maximum=100)
                bar['value'] = pct
                head['text'] = f'Building Longshot {version}...  {pct:.0f}%'
                line['text'] = step
            else:
                line['text'] = lines[-1][:300]
        if 'code' not in state:
            win.after(400, poll)
            return
        bar.stop()
        ok = state['code'] == 0
        bar.configure(mode='determinate', maximum=100, value=100 if ok else 0)
        if ok:
            cm.mark_built(game)
            head['text'] = f'Longshot {version} is built.'
            line['text'] = 'Your code patches and code mods are in the game. Start it to play.'
        else:
            head['text'] = f'The build stopped (code {state["code"]}).'
            line['text'] = ((lines[-1][:300] + '\n\n') if lines else '') + f'The whole log: {log_path}'
        close['state'] = 'normal'
        close.focus_set()
        on_done(ok)

    threading.Thread(target=job, daemon=True).start()
    win.after(400, poll)
