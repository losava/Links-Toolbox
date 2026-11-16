"""The Code mods window (Mods tab > Code mods...): code mods put into Longshot's sources (code_mods.py), and the Build
they need afterwards (the Longshot Launcher's Build button)."""
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
        self.launcher_btn = ttk.Button(bottom, text='Open the Longshot Launcher (to Build)', command=self.open_launcher)
        self.launcher_btn.pack(side='right', padx=(0, 8))
        self.packages = []
        self.refresh()
        try:
            import icons
            icons.apply(self)
        except Exception:
            pass

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
