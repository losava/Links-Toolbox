"""A save editor for the game NX2navi / Triforce runs, a slot at a time, in four tabs:

    Stats        hearts, magic, rupees and wallet, bag and quiver sizes, ammo and other counts, bottles, small keys
    Inventory    every item by the name the game shows: give it or take it away; sort and filter by group, age, have
    Progress     the save's on/off flags (events, talks, items found, places...), sorted and filtered
    All entries  every entry of the slot's files by name, any value changed in place

Hearts, magic and rupees are written to the slot's progress.sav and to its caption.sav (the file-select screen).
Run it with the Python beside this folder:  python\\pythonw.exe save-editor\\save_editor.pyw   (or Save Editor.bat)
Close the game before saving. Every save first copies the files on disk into save-editor\\backups.
"""
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# this Python (an embedded one) does not look for modules next to the script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxsave  # noqa: E402
import oot_catalog as cat  # noqa: E402
import jpeg_win  # noqa: E402
import theme  # noqa: E402

BACKUPS = nxsave.HERE / 'backups'
MAX_ROWS = 20000
H = cat.h


def fmt_item(names, base, v):
    if base == 'Bool':
        return 'On' if v else 'Off'
    if base == 'Enum':
        return names.enum_text(v)
    if base == 'Float':
        return f'{v:.7g}'
    if isinstance(v, tuple):
        return ', '.join(f'{x:.7g}' for x in v)
    return str(v)


def fmt(names, e):
    if e.type == 'Binary':
        return f'({len(e.value)} bytes, not editable)'
    if e.value is None:
        return '(not editable)'
    if e.is_list:
        head = ' | '.join(fmt_item(names, e.base, x) for x in e.value[:6])
        return f'[{len(e.value)}] {head}{" | ..." if len(e.value) > 6 else ""}'
    return fmt_item(names, e.base, e.value)


def parse_item(names, e, base, text):
    text = text.strip()
    if base == 'Bool':
        low = text.lower()
        if low in ('on', 'true', '1', 'yes'):
            return True
        if low in ('off', 'false', '0', 'no'):
            return False
        raise ValueError(f'"{text}" is not On or Off')
    if base == 'Enum':
        v = names.enum_parse(text)
        allowed = names.enums.get(e.hash)
        if allowed and v not in {a for a, _ in allowed}:
            raise ValueError(f'"{text}" is not one of this entry\'s values')
        return v
    if base in nxsave.RANGE:
        try:
            return int(text, 0)
        except ValueError:
            raise ValueError(f'"{text}" is not a whole number') from None
    if base == 'Float':
        try:
            return float(text)
        except ValueError:
            raise ValueError(f'"{text}" is not a number') from None
    if base.startswith('Vector'):
        n = int(base[-1])
        try:
            parts = tuple(float(x) for x in text.replace(',', ' ').split())
        except ValueError:
            raise ValueError(f'"{text}" is not {n} numbers') from None
        if len(parts) != n:
            raise ValueError(f'{n} numbers are needed, separated by commas')
        return parts
    return text     # a text


def sort_key(v):
    """Numbers by size, then texts without case; hashes (#...) after names."""
    if isinstance(v, (int, float)):
        return (0, v, '')
    s = str(v)
    try:
        return (0, float(s), '')
    except ValueError:
        return (2 if s.startswith('#') else 1, 0, s.lower())


class Sorter:
    """Click a column's heading to sort by it, again to reverse; the heading shows which way."""

    def __init__(self, tree, headings, refill, default=None):
        self.tree, self.headings, self.refill = tree, dict(headings), refill
        self.col, self.reverse = default or next(iter(self.headings)), False
        for col in self.headings:
            tree.heading(col, command=lambda c=col: self.click(c))
        self.show()

    def click(self, col):
        self.reverse = not self.reverse if col == self.col else False
        self.col = col
        self.show()
        self.refill()

    def show(self):
        for col, text in self.headings.items():
            self.tree.heading(col, text=text + ((' ▼' if self.reverse else ' ▲') if col == self.col else ''))

    def sort(self, rows, value_of):
        """rows sorted by value_of(row, column) of the column chosen."""
        rows.sort(key=lambda r: sort_key(value_of(r, self.col)), reverse=self.reverse)
        return rows


def make_tree(parent, columns, select='browse'):
    """A Treeview with a scrollbar, in a frame of its own: (frame, tree)."""
    frm = ttk.Frame(parent)
    tree = ttk.Treeview(frm, columns=[c for c, *_ in columns], show='headings', selectmode=select)
    for col, _text, width, stretch in columns:
        tree.column(col, width=width, stretch=stretch, anchor='w')
    sb = ttk.Scrollbar(frm, command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    tree.pack(side='left', fill='both', expand=True)
    tag_tree(tree)
    return frm, tree


def tag_tree(tree):
    tree.tag_configure('changed', foreground=theme.ERROR)
    tree.tag_configure('locked', foreground=theme.DIM)
    tree.tag_configure('missing', foreground=theme.DIM)


class EditDialog(tk.Toplevel):
    """Asks for the new value of one entry; self.result is the parsed value, None when cancelled."""

    def __init__(self, app, sf, e):
        super().__init__(app)
        self.app, self.sf, self.e, self.result = app, sf, e, None
        names = app.names
        self.title('Edit value')
        self.transient(app)
        self.resizable(e.is_list, e.is_list)
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill='both', expand=True)
        ttk.Label(frm, text=app.name(e.hash), font=(theme.FAMILY, 10, 'bold'), wraplength=520).pack(anchor='w')
        hint = e.type
        if e.base in nxsave.RANGE:
            lo, hi = nxsave.RANGE[e.base]
            hint += f'   ({lo} to {hi})'
        elif nxsave._text_size(e.base):
            size, wide = nxsave._text_size(e.base)
            hint += f'   (at most {size // (2 if wide else 1) - 1} characters)'
        elif e.base.startswith('Vector'):
            hint += '   (numbers separated by commas)'
        if e.is_list:
            hint += f'   - {len(e.value)} items, one per line; the count cannot change'
        ttk.Label(frm, text=hint, foreground=theme.MUTED).pack(anchor='w', pady=(2, 8))
        choices = [n for _, n in names.enums.get(e.hash, ())] if e.base == 'Enum' else \
            ['On', 'Off'] if e.base == 'Bool' else None
        self.text = self.var = None
        if e.is_list:
            box = ttk.Frame(frm)
            box.pack(fill='both', expand=True)
            self.text = tk.Text(box, width=60, height=min(24, max(6, len(e.value))), undo=True, wrap='none')
            sb = ttk.Scrollbar(box, command=self.text.yview)
            self.text.configure(yscrollcommand=sb.set)
            sb.pack(side='right', fill='y')
            self.text.pack(side='left', fill='both', expand=True)
            self.text.insert('1.0', '\n'.join(fmt_item(names, e.base, x) for x in e.value))
            if choices:
                ttk.Label(frm, text='Values: ' + ', '.join(choices), foreground=theme.MUTED, wraplength=520,
                          justify='left').pack(anchor='w', pady=(6, 0))
            self.text.focus_set()
        else:
            self.var = tk.StringVar(value=fmt_item(names, e.base, e.value))
            if choices:
                w = ttk.Combobox(frm, textvariable=self.var, values=choices, width=58,
                                 state='readonly' if e.base == 'Bool' else 'normal')
            else:
                w = ttk.Entry(frm, textvariable=self.var, width=60)
                w.selection_range(0, 'end')
            w.pack(fill='x')
            w.focus_set()
            self.bind('<Return>', lambda _e: self.ok())
        btn = ttk.Frame(frm)
        btn.pack(fill='x', pady=(12, 0))
        ttk.Button(btn, text='Cancel', command=self.destroy).pack(side='right')
        ttk.Button(btn, text='OK', command=self.ok).pack(side='right', padx=(0, 8))
        self.bind('<Escape>', lambda _e: self.destroy())
        self.update_idletasks()
        self.geometry(f'+{app.winfo_rootx() + 80}+{app.winfo_rooty() + 80}')
        self.grab_set()
        self.wait_window()

    def ok(self):
        e, names = self.e, self.app.names
        try:
            if e.is_list:
                lines = self.text.get('1.0', 'end').split('\n')
                while lines and not lines[-1].strip():
                    lines.pop()
                if len(lines) != len(e.value):
                    raise ValueError(f'There are {len(lines)} lines; this list has {len(e.value)} items.')
                value = []
                for i, line in enumerate(lines):
                    try:
                        value.append(parse_item(names, e, e.base, line))
                    except ValueError as err:
                        raise ValueError(f'Line {i + 1}: {err}') from None
                value = tuple(value)
            else:
                value = parse_item(names, e, e.base, self.var.get())
            self.sf.set(e, value)
        except ValueError as err:
            messagebox.showerror('Edit value', str(err), parent=self)
            return
        self.result = value
        self.destroy()


class Slot:
    """One save slot's files, read together: progress.sav (the game), caption.sav (the file-select summary), and the
    account's option.sav / account.sav for the All entries tab."""
    KINDS = (('progress', 'Progress (progress.sav)'), ('caption', 'File-select summary (caption.sav)'),
             ('option', 'Options (option.sav)'), ('account', 'Account (account.sav)'))

    def __init__(self, label, paths):
        self.label = label
        self.files, self.by_hash, self.errors = {}, {}, []
        for kind, path in paths.items():
            try:
                sf = nxsave.SaveFile(path)
            except (OSError, ValueError) as err:
                self.errors.append(f'{path.name}: {err}')
                continue
            self.files[kind] = sf
            self.by_hash[kind] = {e.hash: e for e in sf.entries}

    def get(self, name, kind='progress'):
        """The entry of that name (or hash), None when the file has none."""
        return self.by_hash.get(kind, {}).get(name if isinstance(name, int) else H(name))

    @property
    def dirty(self):
        return any(sf.dirty for sf in self.files.values())

    def edited(self):
        return sum(e.changed for sf in self.files.values() for e in sf.entries)


def find_slots(account):
    """[Slot labels and their paths] of an account folder."""
    out = []
    shared = {k: account / f'{k}.sav' for k in ('option', 'account') if (account / f'{k}.sav').is_file()}
    for d in sorted(account.glob('slot_[0-9][0-9]')):
        paths = {k: d / f'{k}.sav' for k in ('progress', 'caption') if (d / f'{k}.sav').is_file()}
        if 'progress' in paths:
            out.append((f'Slot {int(d.name[5:]) + 1}', {**paths, **shared}))
    if not out and shared:
        out.append(('Options only', shared))
    return out


class App(ttk.Frame):
    """The save editor, as a frame: in a window of its own (main) or as a tab of the Link toolbox (toolbox.pyw).
    on_title(text) gets the title it would like its window to have."""

    def __init__(self, master=None, on_title=None, on_play=None):
        super().__init__(master)
        self.on_title = on_title or (lambda text: self.winfo_toplevel().title(text))
        self.on_play = on_play or self.start_game       # (the toolbox starts the game through its Mods tab)
        self.names = nxsave.Names()
        self.slot = None
        self.slots = []
        self.q = queue.Queue()
        self._jobs = {}
        self._loading = False
        self.inv_rows = self.flag_rows = self.rows = []

        top = ttk.Frame(self, padding=(10, 10, 10, 4))
        top.pack(fill='x')
        # whose save this is: Triforce, NX2navi or Longshot (each keeps its own saves); pick another to edit those
        ttk.Label(top, text='Game').pack(side='left')
        self.game_var = tk.StringVar()
        self.game_box = ttk.Combobox(top, textvariable=self.game_var, state='readonly', width=13)
        self.game_box.pack(side='left', padx=(6, 12))
        self.game_box.bind('<<ComboboxSelected>>', lambda _e: self.pick_location())
        self.locations = []
        ttk.Label(top, text='Save slot').pack(side='left')
        self.slot_var = tk.StringVar()
        self.slot_box = ttk.Combobox(top, textvariable=self.slot_var, state='readonly', width=14)
        self.slot_box.pack(side='left', padx=(6, 12))
        self.slot_box.bind('<<ComboboxSelected>>', lambda _e: self.pick_slot())
        self.summary = ttk.Label(top, text='', foreground=theme.SOFT)
        self.summary.pack(side='left')

        bottom = ttk.Frame(self, padding=(10, 6, 10, 10))
        bottom.pack(side='bottom', fill='x')
        self.status = ttk.Label(bottom, text='', anchor='w')
        self.status.pack(side='left', fill='x', expand=True)
        self.play_btn = ttk.Button(bottom, text='Save and play', command=self.save_and_play)
        self.play_btn.pack(side='right')
        self.save_btn = ttk.Button(bottom, text='Save', command=self.save, state='disabled')
        self.save_btn.pack(side='right', padx=(0, 6))
        ttk.Button(bottom, text='Save to...', command=self.save_to_dialog).pack(side='right', padx=(0, 6))
        ttk.Checkbutton(bottom, text='Save while the game runs', variable=nxsave.ignore_running_var(self),
                        command=self.toggle_ignore_running).pack(side='right', padx=(0, 12))
        self.revert_btn = ttk.Button(bottom, text='Undo all edits', command=self.revert, state='disabled')
        self.revert_btn.pack(side='right', padx=(0, 8))
        ttk.Button(bottom, text='Backups folder', command=self.open_backups).pack(side='right', padx=(0, 8))

        self.book = ttk.Notebook(self)
        self.book.pack(fill='both', expand=True, padx=10)
        self.stats_tab = self.make_stats()
        self.book.add(self.stats_tab, text='Stats')
        self.inv_tab = self.make_inventory()
        self.book.add(self.inv_tab, text='Inventory')
        self.flags_tab = self.make_flags()
        self.book.add(self.flags_tab, text='Progress')
        self.all_tab = self.make_all()
        self.book.add(self.all_tab, text='All entries')
        theme.color_tabs(self.book, ['Stats', 'Inventory', 'Progress', 'All entries'])
        self.book.bind('<<NotebookTabChanged>>', lambda _e: self.refresh_tab(), add='+')

        # (the window's keys: only while this frame is the one shown)
        root = self.winfo_toplevel()
        root.bind('<Control-s>', lambda _e: self.save() if self.winfo_ismapped() else None, add='+')
        root.bind('<Control-f>', lambda _e: self.focus_search() if self.winfo_ismapped() else None, add='+')
        self.on_title('Save editor')

        self.load_file_list()
        self.set_status('Reading the names from the game files (only slow the first time)...')
        threading.Thread(target=self.names_thread, daemon=True).start()
        self.after(100, self.poll)

    # ------------------------------------------------------------------------------------------------ the tabs
    def make_stats(self):
        outer = ttk.Frame(self.book)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(outer, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        tab = ttk.Frame(canvas, padding=(4, 8))
        win = canvas.create_window(0, 0, window=tab, anchor='nw')
        tab.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.bind_all('<MouseWheel>', lambda e: canvas.yview_scroll(-e.delta // 120, 'units')
                        if self.book.select() == str(outer) and self.winfo_ismapped() else None, add='+')
        canvas.configure(background=theme.BG)
        self.stats_canvas = canvas
        for c in range(3):
            tab.columnconfigure(c, weight=1, uniform='col')
        self.vars = {}

        def box(col, row, title):
            f = ttk.LabelFrame(tab, text=title, padding=(10, 6))
            f.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)
            f.columnconfigure(1, weight=1)
            return f

        def spin(frame, r, label, key, lo, hi, step=1, note=''):
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky='w', pady=2)
            var = self.vars[key] = tk.StringVar()
            w = ttk.Spinbox(frame, textvariable=var, from_=lo, to=hi, increment=step, width=8)
            w.grid(row=r, column=1, sticky='w', padx=(8, 0), pady=2)
            var.trace_add('write', lambda *_: self.stat_changed(key))
            lab = ttk.Label(frame, text=note, foreground=theme.MUTED)
            lab.grid(row=r, column=2, sticky='w', padx=(6, 0))
            self.vars[key + ':spin'], self.vars[key + ':note'] = w, lab
            return w

        def combo(frame, r, label, key, values, width=24):
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky='w', pady=2)
            var = self.vars[key] = tk.StringVar()
            w = ttk.Combobox(frame, textvariable=var, values=values, state='readonly', width=width)
            w.grid(row=r, column=1, columnspan=2, sticky='w', padx=(8, 0), pady=2)
            w.bind('<<ComboboxSelected>>', lambda _e: self.stat_changed(key))
            self.vars[key + ':box'] = w
            return w

        def buttons(frame, r, *pairs):
            bar = ttk.Frame(frame)
            bar.grid(row=r, column=0, columnspan=3, sticky='w', pady=(6, 0))
            for text, cmd in pairs:
                ttk.Button(bar, text=text, command=cmd).pack(side='left', padx=(0, 6))

        f = box(0, 0, 'Hearts, magic and rupees')
        spin(f, 0, 'Heart containers', 'max_hearts', 3, 20)
        spin(f, 1, 'Hearts now', 'hearts', 0, 20, 0.25, 'quarter steps')
        combo(f, 2, 'Magic meter', 'meter', [label for _, label, _ in cat.MAGIC_METERS])
        spin(f, 3, 'Magic now', 'magic', 0, 48, 1)
        combo(f, 4, 'Wallet', 'wallet', [f'{label} ({n})' for _, label, n in cat.WALLETS])
        spin(f, 5, 'Rupees', 'rupees', 0, 1000)
        buttons(f, 6, ('Full hearts', lambda: self.fill_stat('hearts')),
                ('Full magic', lambda: self.fill_stat('magic')), ('Full wallet', lambda: self.fill_stat('rupees')))
        age = ttk.Frame(f)
        age.grid(row=7, column=0, columnspan=3, sticky='w', pady=(10, 0))
        ttk.Label(age, text='Age').pack(side='left')
        self.age_label = ttk.Label(age, text='', foreground=theme.GOLD, font=(theme.FAMILY, 9, 'bold'))
        self.age_label.pack(side='left', padx=(8, 6))
        self.age_btn = ttk.Button(age, text='Switch age', command=self.switch_age)
        self.age_btn.pack(side='left')

        f = box(0, 1, 'Slot picture')
        self.picture = ttk.Label(f, text='', foreground=theme.MUTED, cursor='hand2', anchor='center')
        self.picture.grid(row=0, column=0, columnspan=3, sticky='nsew')
        self.picture.bind('<Button-1>', lambda _e: self.show_picture())
        self.picture_png = self.picture_small = None

        f = box(2, 1, 'Bags and quiver')
        for r, (key, label, *_rest) in enumerate(cat.BAGS):
            combo(f, r, label, 'bag:' + key, [], width=18)
        ttk.Label(f, text='Only bigger sizes are offered: the game gives them in order.', foreground=theme.MUTED,
                  wraplength=300, justify='left').grid(row=len(cat.BAGS), column=0, columnspan=3, sticky='w',
                                                       pady=(4, 0))

        f = box(1, 0, 'How many')
        for r, (label, item, _bag, _most) in enumerate(cat.AMOUNTS):
            spin(f, r, label, 'n:' + item, 0, 999)
        buttons(f, len(cat.AMOUNTS), ('Fill all', self.fill_amounts))

        f = box(1, 1, 'Bottles')
        names = ['No bottle'] + [label for _, label in cat.BOTTLE_CONTENTS]
        for r in range(len(cat.BOTTLES)):
            combo(f, r, f'Bottle {r + 1}', f'bottle:{r}', names, width=18)

        f = box(2, 0, 'Small keys held')
        for r, (label, _entry, most) in enumerate(cat.SMALL_KEYS):
            spin(f, r, label, f'key:{r}', 0, most, 1, f'of {most}')
        buttons(f, len(cat.SMALL_KEYS), ('All keys', self.fill_keys))
        self.stats_note = ttk.Label(tab, text='', foreground=theme.ERROR, wraplength=900, justify='left')
        self.stats_note.grid(row=3, column=0, columnspan=3, sticky='w', padx=6, pady=(4, 0))
        tab.rowconfigure(2, weight=1)
        return outer

    def make_inventory(self):
        tab = ttk.Frame(self.book, padding=(0, 8, 0, 0))
        bar = ttk.Frame(tab)
        bar.pack(fill='x', pady=(0, 6))
        ttk.Label(bar, text='Search').pack(side='left')
        self.inv_search = tk.StringVar()
        self.inv_entry = ttk.Entry(bar, textvariable=self.inv_search, width=24)
        self.inv_entry.pack(side='left', padx=(6, 12))
        self.inv_search.trace_add('write', lambda *_: self.soon('inv', self.refill_inventory))
        ttk.Label(bar, text='Show').pack(side='left')
        self.inv_show = tk.StringVar(value='All items')
        w = ttk.Combobox(bar, textvariable=self.inv_show, state='readonly', width=16,
                         values=['All items', 'Have', 'Missing', 'Can be given', 'Edited'])
        w.pack(side='left', padx=(6, 12))
        w.bind('<<ComboboxSelected>>', lambda _e: self.refill_inventory())
        ttk.Label(bar, text='Group').pack(side='left')
        self.inv_group = tk.StringVar(value='All')
        w = ttk.Combobox(bar, textvariable=self.inv_group, state='readonly', width=11, values=['All', *cat.GROUPS])
        w.pack(side='left', padx=(6, 12))
        w.bind('<<ComboboxSelected>>', lambda _e: self.refill_inventory())
        ttk.Label(bar, text='Age').pack(side='left')
        self.inv_age = tk.StringVar(value='All')
        w = ttk.Combobox(bar, textvariable=self.inv_age, state='readonly', width=7, values=['All', 'Young', 'Adult',
                                                                                             'Both'])
        w.pack(side='left', padx=(6, 0))
        w.bind('<<ComboboxSelected>>', lambda _e: self.refill_inventory())

        act = ttk.Frame(tab)
        act.pack(side='bottom', fill='x', pady=(6, 0))
        ttk.Button(act, text='Give', command=lambda: self.give_items(True)).pack(side='left')
        ttk.Button(act, text='Take away', command=lambda: self.give_items(False)).pack(side='left', padx=(6, 0))
        ttk.Button(act, text='Give everything missing', command=self.give_all).pack(side='left', padx=(18, 0))
        self.clear_found = tk.BooleanVar(value=False)
        ttk.Checkbutton(act, text='Taking away also forgets it was found (its "found" flags)',
                        variable=self.clear_found).pack(side='left', padx=(18, 0))
        ttk.Label(act, text='Double-click: give / take away.  Ctrl/Shift-click: pick several.',
                  foreground=theme.MUTED).pack(side='right')

        cols = (('item', 'Item', 240, True), ('group', 'Group', 100, False), ('age', 'Age', 70, False),
                ('have', 'Have', 70, False), ('id', 'Name in the game files', 300, True))
        frm, self.inv_tree = make_tree(tab, cols, select='extended')
        frm.pack(fill='both', expand=True)
        self.inv_sort = Sorter(self.inv_tree, [(c, t) for c, t, *_ in cols], self.refill_inventory, 'group')
        self.inv_tree.bind('<Double-1>', lambda _e: self.toggle_items())
        self.inv_tree.bind('<Return>', lambda _e: self.toggle_items())
        return tab

    def make_flags(self):
        tab = ttk.Frame(self.book, padding=(0, 8, 0, 0))
        bar = ttk.Frame(tab)
        bar.pack(fill='x', pady=(0, 6))
        ttk.Label(bar, text='Search').pack(side='left')
        self.flag_search = tk.StringVar()
        self.flag_entry = ttk.Entry(bar, textvariable=self.flag_search, width=30)
        self.flag_entry.pack(side='left', padx=(6, 12))
        self.flag_search.trace_add('write', lambda *_: self.soon('flags', self.refill_flags))
        ttk.Label(bar, text='Group').pack(side='left')
        self.flag_group = tk.StringVar(value='All')
        w = ttk.Combobox(bar, textvariable=self.flag_group, state='readonly', width=28,
                         values=['All', *cat.FLAG_GROUPS])
        w.pack(side='left', padx=(6, 12))
        w.bind('<<ComboboxSelected>>', lambda _e: self.refill_flags())
        ttk.Label(bar, text='Show').pack(side='left')
        self.flag_show = tk.StringVar(value='All')
        w = ttk.Combobox(bar, textvariable=self.flag_show, state='readonly', width=9,
                         values=['All', 'On', 'Off', 'Edited'])
        w.pack(side='left', padx=(6, 0))
        w.bind('<<ComboboxSelected>>', lambda _e: self.refill_flags())
        act = ttk.Frame(tab)
        act.pack(side='bottom', fill='x', pady=(6, 0))
        ttk.Button(act, text='Set on', command=lambda: self.set_flags(True)).pack(side='left')
        ttk.Button(act, text='Set off', command=lambda: self.set_flags(False)).pack(side='left', padx=(6, 0))
        self.flag_count = ttk.Label(act, text='', foreground=theme.MUTED)
        self.flag_count.pack(side='left', padx=(18, 0))
        ttk.Label(act, text='Double-click or Space: switch.  Some quests need several flags and items together.',
                  foreground=theme.MUTED).pack(side='right')
        cols = (('flag', 'Flag', 560, True), ('group', 'Group', 180, False), ('value', 'Value', 70, False))
        frm, self.flag_tree = make_tree(tab, cols, select='extended')
        frm.pack(fill='both', expand=True)
        self.flag_sort = Sorter(self.flag_tree, [(c, t) for c, t, *_ in cols], self.refill_flags)
        self.flag_tree.bind('<Double-1>', lambda _e: self.set_flags(None))
        self.flag_tree.bind('<space>', lambda _e: self.set_flags(None))
        return tab

    def make_all(self):
        tab = ttk.Frame(self.book, padding=(0, 8, 0, 0))
        bar = ttk.Frame(tab)
        bar.pack(fill='x', pady=(0, 6))
        ttk.Label(bar, text='File').pack(side='left')
        self.kind_var = tk.StringVar()
        self.kind_box = ttk.Combobox(bar, textvariable=self.kind_var, state='readonly', width=30)
        self.kind_box.pack(side='left', padx=(6, 12))
        self.kind_box.bind('<<ComboboxSelected>>', lambda _e: self.refill())
        ttk.Label(bar, text='Search').pack(side='left')
        self.search_var = tk.StringVar()
        self.all_entry = ttk.Entry(bar, textvariable=self.search_var, width=28)
        self.all_entry.pack(side='left', padx=(6, 12))
        self.search_var.trace_add('write', lambda *_: self.soon('all', self.refill))
        ttk.Label(bar, text='Type').pack(side='left')
        self.type_var = tk.StringVar(value='All')
        self.type_box = ttk.Combobox(bar, textvariable=self.type_var, state='readonly', width=14, values=['All'])
        self.type_box.pack(side='left', padx=(6, 12))
        self.type_box.bind('<<ComboboxSelected>>', lambda _e: self.refill())
        self.named_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text='Named only', variable=self.named_var, command=self.refill).pack(side='left')
        self.changed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='Edited only', variable=self.changed_var, command=self.refill).pack(side='left',
                                                                                                    padx=(10, 0))
        cols = (('name', 'Name', 520, True), ('type', 'Type', 110, False), ('value', 'Value', 380, True))
        frm, self.tree = make_tree(tab, cols)
        frm.pack(fill='both', expand=True)
        self.all_sort = Sorter(self.tree, [(c, t) for c, t, *_ in cols], self.refill)
        self.tree.bind('<Double-1>', lambda _e: self.edit_selected())
        self.tree.bind('<Return>', lambda _e: self.edit_selected())
        self.tree.bind('<space>', lambda _e: self.edit_selected(toggle_only=True))
        return tab

    # ------------------------------------------------------------------------------- names, read on another thread
    def names_thread(self):
        try:
            self.q.put(('names', nxsave.load_names(progress=lambda s: self.q.put(('status', s)))))
        except Exception as err:   # the editor works without names
            self.q.put(('names_failed', str(err)))

    def poll(self):
        try:
            while True:
                what, arg = self.q.get_nowait()
                if what == 'status':
                    self.set_status(arg)
                elif what == 'names':
                    self.names = arg
                    self.refresh_tab()
                    self.set_status('Ready. Click a column heading to sort by it.')
                    self.update_state()
                elif what == 'names_failed':
                    self.named_var.set(False)
                    self.refresh_tab()
                    self.set_status(f'The names could not be read from the game files ({arg}); entries show as hashes.')
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def name(self, h):
        return self.names.names.get(h) or cat.EXTRA_NAMES.get(h) or f'#{h:08x}'

    # --------------------------------------------------------------------------------------------------- slots
    @property
    def save_file(self):
        """The open slot's progress.sav (the toolbox's self test reads it)."""
        return self.slot.files.get('progress') if self.slot else None

    def load_file_list(self):
        """The saves of the game in use (or of the folder picked in the Folders tab), and the Game list: every save
        location found, so another game's saves can be edited too."""
        accounts = nxsave.save_dirs()      # the game in use's saves first, or the folder picked
        self.locations = nxsave.all_save_locations()
        current = accounts[0] if accounts else None
        if current is not None and not any(self.same(d, current) for _a, d in self.locations):
            self.locations.insert(0, (nxsave.app_of(), current))
        names, counts = [], {}
        for app, _d in self.locations:      # (two saves folders for one app: 'Longshot', 'Longshot 2')
            counts[app] = counts.get(app, 0) + 1
            names.append(app if counts[app] == 1 else f'{app} {counts[app]}')
        self.location_names = names
        self.game_box['values'] = names
        if current is not None:
            self.game_box.current(next(i for i, (_a, d) in enumerate(self.locations) if self.same(d, current)))
        else:
            self.game_var.set('')
        self.use_account(current)

    @staticmethod
    def same(a, b):
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))

    def location_name(self):
        """'Triforce', 'NX2navi', 'Longshot'... for the save open now."""
        return self.game_var.get() or 'Save'

    def pick_location(self):
        i = self.game_box.current()
        acct = self.locations[i][1]
        if self.account is not None and self.same(acct, self.account):
            return
        if not self.may_discard():
            j = next((k for k, (_a, d) in enumerate(self.locations) if self.account and self.same(d, self.account)), -1)
            if j >= 0:
                self.game_box.current(j)
            return
        self.use_account(acct)
        self.set_status(f'Editing {self.location_name()}\'s saves: {acct}')

    def use_account(self, account):
        self.account = account
        self.slots = find_slots(self.account) if self.account else []
        self.slot_box['values'] = [label for label, _ in self.slots]
        if self.slots:
            # the slot picked last time (the game writes every slot when it saves: the dates do not tell), else Slot 1
            labels = [label for label, _ in self.slots]
            last = nxsave.load_settings().get('last_slot')
            i = labels.index(last) if last in labels else 0
            self.slot_box.current(i)
            self.open_slot(*self.slots[i])
        else:
            self.slot = None
            self.slot_var.set('')
            self.refresh_all()
            chosen = nxsave.load_settings().get('save_dir')
            self.set_status(f'No save found in {chosen}. Pick another folder in the Folders tab.' if chosen else
                            f'No save found in {nxsave.game_dir() / "user" / "save"}. Play the game once first.')

    def pick_slot(self):
        i = self.slot_box.current()
        if self.slot and self.slots[i][0] == self.slot.label:
            return
        if not self.may_discard():
            self.slot_var.set(self.slot.label)
            return
        self.open_slot(*self.slots[i])
        try:
            nxsave.save_settings({**nxsave.load_settings(), 'last_slot': self.slots[i][0]})
        except OSError:
            pass

    def open_slot(self, label, paths):
        self.slot = Slot(label, paths)
        if self.slot.errors:
            messagebox.showerror('Open', '\n'.join(self.slot.errors), parent=self)
        self.load_picture()
        kinds = [(k, text) for k, text in Slot.KINDS if k in self.slot.files]
        self.kind_box['values'] = [text for _, text in kinds]
        if kinds:
            self.kind_box.current(0)
        self.refresh_all()

    # -- the picture the game took when it saved the slot (a JPEG in caption.sav; Windows decodes it, Tk shows PNG)
    def load_picture(self):
        self.picture_png = self.picture_small = None
        e = self.slot.get(cat.PICTURE, 'caption') if self.slot else None
        png = jpeg_win.jpeg_to_png(e.value) if e is not None and isinstance(e.value, bytes) else None
        if png:
            try:
                full = tk.PhotoImage(data=png, format='png')
                step = max(1, -(-full.width() // 300))         # (whole steps: Tk shrinks by 1/2, 1/3...)
                self.picture_small = full.subsample(step, step)
                self.picture_png = png
            except tk.TclError:
                pass
        if self.picture_small:
            self.picture.configure(image=self.picture_small, text='')
        else:
            self.picture.configure(image='', text='No picture in this slot' if self.slot else '')

    def show_picture(self):
        if not self.picture_png:
            return
        win = tk.Toplevel(self)
        win.title(f'{self.slot.label} - picture')
        win.transient(self.winfo_toplevel())
        win.image = tk.PhotoImage(master=win, data=self.picture_png, format='png')
        lab = ttk.Label(win, image=win.image, cursor='hand2')
        lab.pack()
        for w in (win, lab):
            w.bind('<Button-1>', lambda _e: win.destroy())
            w.bind('<Escape>', lambda _e: win.destroy())
        win.focus_set()

    def kind(self):
        text = self.kind_var.get()
        return next((k for k, t in Slot.KINDS if t == text), 'progress')

    def may_discard(self):
        return not (self.slot and self.slot.dirty) or messagebox.askyesno(
            'Unsaved edits', 'Your edits to this slot are not saved. Discard them?', parent=self)

    # ------------------------------------------------------------------------------------------------ refreshing
    def soon(self, which, fn, delay=200):
        if self._jobs.get(which):
            self.after_cancel(self._jobs[which])
        self._jobs[which] = self.after(delay, fn)

    def current_tab(self):
        try:
            return self.book.index(self.book.select())
        except tk.TclError:
            return 0

    def refresh_tab(self):
        (self.fill_stats, self.refill_inventory, self.refill_flags, self.refill)[self.current_tab()]()

    def refresh_all(self):
        self.fill_stats()
        self.refill_inventory()
        self.refill_flags()
        self.refill()
        self.update_state()

    def focus_search(self):
        w = (None, self.inv_entry, self.flag_entry, self.all_entry)[self.current_tab()]
        if w:
            w.focus_set()
            w.selection_range(0, 'end')

    def edited(self):
        """After any edit: the summary, the buttons, the title."""
        self.update_state()

    def update_state(self):
        s = self.slot
        dirty = bool(s and s.dirty)
        self.save_btn['state'] = self.revert_btn['state'] = 'normal' if dirty else 'disabled'
        if not s:
            self.summary['text'] = ''
            self.on_title('Save editor')
            return
        g = lambda name, kind='progress': (s.get(name, kind).value if s.get(name, kind) else None)
        life, rupees, tokens = g('PlayerStatus.MaxLife'), g(cat.RUPEES), g(cat.stock('Item_Token_Gold'))
        bits = []
        if life is not None:
            bits.append(f'{life / 4:g} hearts')
        if rupees is not None:
            bits.append(f'{rupees} rupees')
        if tokens is not None:
            bits.append(f'{tokens} skulltula tokens')
        where = s.files[next(iter(s.files))].path
        acct = where.parent.parent
        self.summary['text'] = '  ·  '.join(bits) + \
            '      ' + os.sep.join((acct.parent.parent.name, acct.parent.name, acct.name[:8] + '...', where.parent.name))
        n = s.edited()
        if n:
            self.set_status(f'{n} value{"s" if n != 1 else ""} edited, not saved yet  -  press Save (with the game '
                            'closed)')
        elif self.status['text'].endswith('not saved yet  -  press Save (with the game closed)'):
            self.set_status('')
        self.on_title(f'{"* " if dirty else ""}Save editor - {self.location_name()}, {s.label}')

    def set_status(self, text):
        self.status['text'] = text

    def restyle(self):
        """New theme colours (the toolbox's Look tab) on what does not follow the ttk styles by itself."""
        self.stats_canvas.configure(background=theme.BG)
        for tree in (self.inv_tree, self.flag_tree, self.tree):
            tag_tree(tree)
        self.summary.configure(foreground=theme.SOFT)
        self.age_label.configure(foreground=theme.GOLD)
        self.stats_note.configure(foreground=theme.ERROR)

    # ------------------------------------------------------------------------------------------------ Stats tab
    def put(self, name, value, kind='progress'):
        """Set an entry when the file has it; True when it is there."""
        e = self.slot.get(name, kind) if self.slot else None
        if e is None:
            return False
        if e.value != value:
            self.slot.files[kind].set(e, value)
        return True

    def val(self, name, kind='progress', default=None):
        e = self.slot.get(name, kind) if self.slot else None
        return default if e is None else e.value

    def bag_sizes(self, key):
        """(size now, [sizes it may take]) of a bag."""
        k, label, size_h, name_h, prefix, sizes = next(b for b in cat.BAGS if b[0] == key)
        now = self.val(size_h, default=0) or 0
        return now, [n for n in sizes if n >= now]

    def limit(self, item):
        _l, _i, bag, most = next(a for a in cat.AMOUNTS if a[1] == item)
        if bag:
            now, _ = self.bag_sizes(bag)
            return now
        return most

    def fill_stats(self):
        self._loading = True
        try:
            v, s = self.vars, self.slot
            on = 'normal' if s else 'disabled'
            for key, w in v.items():
                if key.endswith(':spin'):
                    w['state'] = on
                elif key.endswith(':box'):
                    w['state'] = 'readonly' if s else 'disabled'
            if not s:
                for key, var in v.items():
                    if isinstance(var, tk.StringVar):
                        var.set('')
                return
            for what, prog, _cap, units in cat.VITALS:
                raw = self.val(prog)
                if raw is not None and what != 'max_magic':
                    v[what].set(f'{raw / units:g}')
            max_life = (self.val('PlayerStatus.MaxLife') or 12) / 4
            v['hearts:spin']['to'] = max_life
            mp_max = (self.val('PlayerStatus.MPMax') or 0) / 10
            meter = min(cat.MAGIC_METERS, key=lambda m: abs(m[0] - mp_max))
            v['meter'].set(meter[1])
            v['magic:spin']['to'] = meter[0]
            v['magic:note']['text'] = f'of {meter[0]}' if meter[0] else 'no meter'
            wallet = self.val(cat.WALLET_NAME)
            w = next((w for w in cat.WALLETS if w[0] == wallet), None)
            v['wallet'].set(f'{w[1]} ({w[2]})' if w else (wallet or '?'))
            v['rupees'].set(str(self.val(cat.RUPEES, default='')))
            v['rupees:spin']['to'] = w[2] if w else 9999
            child = self.val(cat.IS_CHILD)
            self.age_label['text'] = '?' if child is None else 'Young Link' if child else 'Adult Link'
            self.age_btn['text'] = 'Switch to adult' if child else 'Switch to young'
            self.age_btn['state'] = 'disabled' if child is None else 'normal'
            here = self.val(cat.CURRENT_MAP)
            if child is not None and cat.other_age_map(here, not child) is None:
                self.age_label['text'] += '  (in a dungeon)' if here and '_' not in here else ''
            for key, label, size_h, name_h, prefix, sizes in cat.BAGS:
                now, may = self.bag_sizes(key)
                box = v[f'bag:{key}:box']
                box['values'] = [('None' if n == 0 else f'{cat.SIZES[sizes.index(n)] if n in sizes else "?"} '
                                  f'({n})') for n in ([now] if now not in sizes else []) + may]
                box.current(0)
            for label, item, bag, most in cat.AMOUNTS:
                n = self.val(cat.stock(item))
                v['n:' + item].set('' if n is None else str(n))
                top = self.limit(item)
                v[f'n:{item}:spin']['to'] = max(top, n or 0)
                v[f'n:{item}:note']['text'] = f'of {top}' if top else 'no bag yet'
            for i, (have, _use, what) in enumerate(cat.BOTTLES):
                if not self.val(have):
                    v[f'bottle:{i}'].set('No bottle')
                else:
                    c = self.val(what)
                    v[f'bottle:{i}'].set(next((label for h, label in cat.BOTTLE_CONTENTS if h == c),
                                              self.names.enum_text(c) if c is not None else '?'))
            for i, (_label, entry, most) in enumerate(cat.SMALL_KEYS):
                n = self.val(entry)
                v[f'key:{i}'].set('' if n is None else str(n))
            self.stats_note['text'] = ''
        finally:
            self._loading = False

    def number(self, key, whole=True):
        text = self.vars[key].get().strip()
        try:
            x = float(text)
        except ValueError:
            raise ValueError(f'"{text}" is not a number.' if text else 'Type a number.') from None
        if whole and x != int(x):
            raise ValueError(f'{text}: a whole number is needed.')
        return int(x) if whole else x

    def stat_changed(self, key):
        if self._loading or not self.slot:
            return
        try:
            self.write_stat(key)
            self.stats_note['text'] = ''
        except ValueError as err:
            self.stats_note['text'] = str(err)
            return
        self.edited()

    def write_vital(self, what, raw):
        _w, prog, cap, _u = next(x for x in cat.VITALS if x[0] == what)
        self.put(prog, raw)
        self.put(cap, raw, 'caption')

    def write_stat(self, key):
        v = self.vars
        if key == 'max_hearts':
            n = self.number(key)
            if not 3 <= n <= 20:
                raise ValueError('Heart containers: 3 to 20.')
            self.write_vital('max_hearts', n * 4)
            v['hearts:spin']['to'] = n
            if (self.val('PlayerStatus.Life') or 0) > n * 4:
                self.write_vital('hearts', n * 4)
                self._set_quiet('hearts', f'{n:g}')
        elif key == 'hearts':
            x = self.number(key, whole=False)
            top = (self.val('PlayerStatus.MaxLife') or 0) / 4
            if x * 4 != int(x * 4) or not 0 <= x <= top:
                raise ValueError(f'Hearts now: 0 to {top:g}, in quarter hearts (like 2.75).')
            self.write_vital('hearts', int(x * 4))
        elif key == 'meter':
            i = v['meter:box'].current()
            most, _label, gifts = cat.MAGIC_METERS[i]
            self.write_vital('max_magic', most * 10)
            for m in cat.MAGIC_METERS:            # the Great Fairy gifts that give the meter go with it
                for gift in m[2]:
                    self.put(cat.stock(gift), 1 if gift in gifts else 0)
            if (self.val('PlayerStatus.MP') or 0) > most * 10:
                self.write_vital('magic', most * 10)
            self.fill_stats()
        elif key == 'magic':
            x = self.number(key, whole=False)
            top = (self.val('PlayerStatus.MPMax') or 0) / 10
            if round(x * 10) != x * 10 or not 0 <= x <= top:
                raise ValueError(f'Magic now: 0 to {top:g}.')
            self.write_vital('magic', round(x * 10))
        elif key == 'wallet':
            item, _label, most = cat.WALLETS[v['wallet:box'].current()]
            self.put(cat.WALLET_NAME, item)
            self.put(cat.RUPEE_LIMIT, most)
            for w in cat.WALLETS:
                self.put(cat.stock(w[0]), 1 if w[0] == item else 0)
            if (self.val(cat.RUPEES) or 0) > most:
                self.put(cat.RUPEES, most)
                self.put(cat.CAPTION_RUPEES, most, 'caption')
            self.fill_stats()
        elif key == 'rupees':
            n = self.number(key)
            most = self.val(cat.RUPEE_LIMIT) or 0
            if not 0 <= n <= most:
                raise ValueError(f'Rupees: 0 to {most} (the wallet\'s size).')
            self.put(cat.RUPEES, n)
            self.put(cat.CAPTION_RUPEES, n, 'caption')
        elif key.startswith('bag:'):
            bag = key[4:]
            k, label, size_h, name_h, prefix, sizes = next(b for b in cat.BAGS if b[0] == bag)
            text = v[key].get()
            n = int(text[text.index('(') + 1:-1])
            if n in sizes:
                tier = sizes.index(n)
                self.put(size_h, n)
                for t in range(tier + 1):            # the smaller bags were found on the way
                    self.put(cat.stock(f'{prefix}_{cat.SIZES[t]}'), 1)
                if name_h:
                    self.put(name_h, f'{prefix}_{cat.SIZES[tier]}')
            self.fill_stats()
        elif key.startswith('n:'):
            item = key[2:]
            n = self.number(key)
            top = max(self.limit(item), self.val(cat.stock(item)) or 0)
            if not 0 <= n <= top:
                label = next(a[0] for a in cat.AMOUNTS if a[1] == item)
                raise ValueError(f'{label}: 0 to {top}' + (' - a bigger bag holds more (Bags and quiver).'
                                                           if top < 999 and any(a[1] == item and a[2] for a in
                                                                                cat.AMOUNTS) else '.'))
            self.put(cat.stock(item), n)
        elif key.startswith('bottle:'):
            i = int(key[7:])
            have, use, what = cat.BOTTLES[i]
            choice = v[key + ':box'].current()
            if choice == 0:
                self.put(have, 0)
                self.put(use, False)
                self.put(what, cat.BOTTLE_CONTENTS[0][0])
            else:
                self.put(have, 1)
                self.put(use, True)
                self.put(what, cat.BOTTLE_CONTENTS[choice - 1][0])
        elif key.startswith('key:'):
            label, entry, most = cat.SMALL_KEYS[int(key[4:])]
            n = self.number(key)
            if not 0 <= n <= most:
                raise ValueError(f'{label} keys: 0 to {most}.')
            self.put(entry, n)

    def _set_quiet(self, key, text):
        self._loading = True
        try:
            self.vars[key].set(text)
        finally:
            self._loading = False

    def fill_stat(self, what):
        if not self.slot:
            return
        if what == 'hearts':
            self.write_vital('hearts', self.val('PlayerStatus.MaxLife') or 0)
        elif what == 'magic':
            self.write_vital('magic', self.val('PlayerStatus.MPMax') or 0)
        elif what == 'rupees':
            most = self.val(cat.RUPEE_LIMIT) or 0
            self.put(cat.RUPEES, most)
            self.put(cat.CAPTION_RUPEES, most, 'caption')
        self.fill_stats()
        self.edited()

    def switch_age(self):
        """Young to adult or back: the map Link is saved on goes to the other age's version of it (that is what the
        game goes by), with 'is a child' and the file-select screen's map to match. Only outdoors, where each area has
        a map for each age; in a dungeon both ages share one map. Held items stay: each age keeps what it had."""
        if not self.slot or self.val(cat.IS_CHILD) is None:
            return
        to_child = not self.val(cat.IS_CHILD)
        here = self.val(cat.CURRENT_MAP)
        there = cat.other_age_map(here, to_child)
        if there is None:
            messagebox.showinfo('Switch age', f'Link is saved in {here or "a place"}, which has one map for both ages '
                                '(a dungeon or a house), so his age cannot be changed here.\n\nIn the game, go outside '
                                '(Kakariko, Hyrule Field, Kokiri Forest, the Market...), save there, then switch.',
                                parent=self)
            return
        self.put(cat.CURRENT_MAP, there)
        caption = self.val(cat.CAPTION_MAP, 'caption')
        if caption:
            self.put(cat.CAPTION_MAP, caption.replace(here, there), 'caption')
        self.put(cat.IS_CHILD, to_child)
        self.fill_stats()
        self.edited()
        self.set_status(f'Link is {"young" if to_child else "an adult"} now ({there})  -  press Save (with the game '
                        'closed), then load the slot.')

    def fill_amounts(self):
        if not self.slot:
            return
        for _label, item, _bag, _most in cat.AMOUNTS:
            if item == 'Obj_Heart_Piece':      # (four make a heart container: three is the most)
                continue
            top = self.limit(item)
            if top and (self.val(cat.stock(item)) or 0) < top:
                self.put(cat.stock(item), top)
        self.fill_stats()
        self.edited()

    def fill_keys(self):
        if not self.slot:
            return
        for _label, entry, most in cat.SMALL_KEYS:
            self.put(entry, most)
        self.fill_stats()
        self.edited()

    # -------------------------------------------------------------------------------------------- Inventory tab
    def item_state(self, item):
        """(count or None when the save has no such item, edited)"""
        e = self.slot.get(cat.stock(item)) if self.slot else None
        if e is None:
            return None, False
        flags = [self.slot.get(f) for f in cat.got_flags(item)]
        return e.value, e.changed or any(f is not None and f.changed for f in flags)

    def refill_inventory(self):
        self._jobs['inv'] = None
        tree = self.inv_tree
        sel = set(tree.selection())
        tree.delete(*tree.get_children())
        if not self.slot:
            return
        words = self.inv_search.get().lower().split()
        show, group, age = self.inv_show.get(), self.inv_group.get(), self.inv_age.get()
        rows = []
        for item, label, grp, item_age, givable in cat.ITEMS:
            n, changed = self.item_state(item)
            if n is None:
                continue
            if group != 'All' and grp != group or age != 'All' and item_age != age:
                continue
            if show == 'Have' and not n or show == 'Missing' and n or show == 'Edited' and not changed \
                    or show == 'Can be given' and not (givable and not n):
                continue
            if words and not all(w in f'{label} {item} {grp}'.lower() for w in words):
                continue
            have = ('Yes' if n == 1 else str(n)) if givable else str(n)
            if not n:
                have = 'No'
            rows.append((item, label, grp, item_age, have, changed, n))
        col_of = {'item': 1, 'group': 2, 'age': 3, 'have': 4, 'id': 0}
        group_order = {g: i for i, g in enumerate(cat.GROUPS)}
        self.inv_sort.sort(rows, lambda r, c: (group_order[r[2]] * 1000 + [x[0] for x in cat.ITEMS].index(r[0]))
                           if c == 'group' else r[col_of[c]])
        for item, label, grp, item_age, have, changed, n in rows:
            tree.insert('', 'end', iid=item, values=(label, grp, item_age, have, item),
                        tags=('changed',) if changed else ('missing',) if not n else ())
        keep = [i for i in sel if tree.exists(i)]
        if keep:
            tree.selection_set(keep)
        self.inv_rows = rows

    def picked_items(self):
        return [i for i in self.inv_tree.selection()]

    def give(self, item):
        """Have it: one of it, and the flags that say it was found and its get scene seen (else the game may give it
        again or play the scene)."""
        if not self.slot.get(cat.stock(item)):
            return False
        if (self.val(cat.stock(item)) or 0) < 1:
            self.put(cat.stock(item), 1)
        for f in cat.got_flags(item):
            self.put(f, True)
        return True

    def take(self, item, forget):
        """Not have it; refuses when it is worn or held. Returns why not, or ''."""
        label = next(x[1] for x in cat.ITEMS if x[0] == item)
        if item in cat.DEFAULT_CLOTHES:
            return f'{label}: the default clothes stay.'
        for slot_entry in cat.EQUIPPED:
            if self.val(slot_entry) == item:
                return f'{label} is equipped ({slot_entry.split(".")[-1]}): equip something else in the game first.'
        self.put(cat.stock(item), 0)
        if forget:
            for f in cat.got_flags(item):
                self.put(f, False)
        return ''

    def give_items(self, giving):
        if not self.slot:
            return
        items = self.picked_items()
        if not items:
            self.set_status('Pick an item in the list first (Ctrl/Shift-click for several).')
            return
        problems, done = [], 0
        for item in items:
            label, givable = next((x[1], x[4]) for x in cat.ITEMS if x[0] == item)
            if not givable:
                problems.append(f'{label}: set it in the Stats tab (sizes and counts).')
                continue
            if giving:
                done += self.give(item)
            else:
                why = self.take(item, self.clear_found.get())
                if why:
                    problems.append(why)
                else:
                    done += 1
        self.refill_inventory()
        self.edited()
        if problems:
            messagebox.showinfo('Inventory', '\n'.join(problems), parent=self)
        if done:
            self.set_status(f'{"Given" if giving else "Taken away"}: {done} item{"s" if done != 1 else ""}  -  '
                            'press Save (with the game closed)')

    def toggle_items(self):
        sel = self.picked_items()
        if len(sel) == 1:
            n, _ = self.item_state(sel[0])
            self.give_items(not n)

    def give_all(self):
        if not self.slot:
            return
        missing = [x for x in cat.ITEMS if x[4] and self.slot.get(cat.stock(x[0])) and not self.val(cat.stock(x[0]))]
        if not missing:
            self.set_status('This slot has every item that can be given.')
            return
        if not messagebox.askyesno('Give everything missing', f'Give {len(missing)} items?\n\n' +
                                   ', '.join(x[1] for x in missing[:40]) + (' ...' if len(missing) > 40 else '') +
                                   '\n\nQuest items (medallions, stones) can change what the story does next.',
                                   parent=self):
            return
        for x in missing:
            self.give(x[0])
        self.refill_inventory()
        self.edited()
        self.set_status(f'Given: {len(missing)} items  -  press Save (with the game closed)')

    # ---------------------------------------------------------------------------------------------- Progress tab
    def refill_flags(self):
        self._jobs['flags'] = None
        tree = self.flag_tree
        sel = set(tree.selection())
        tree.delete(*tree.get_children())
        sf = self.save_file
        if not sf:
            self.flag_count['text'] = ''
            return
        words = self.flag_search.get().lower().split()
        group, show = self.flag_group.get(), self.flag_show.get()
        known = self.names.names
        rows, total = [], 0
        for i, e in enumerate(sf.entries):
            if e.type != 'Bool':
                continue
            name = known.get(e.hash)
            if not name:
                continue
            total += 1
            g = cat.flag_group(name)
            if group != 'All' and g != group:
                continue
            if show == 'On' and not e.value or show == 'Off' and e.value or show == 'Edited' and not e.changed:
                continue
            if words and not all(w in name.lower() for w in words):
                continue
            rows.append((name, g, 'On' if e.value else 'Off', i, e))
        self.flag_sort.sort(rows, lambda r, c: r[{'flag': 0, 'group': 1, 'value': 2}[c]])
        for name, g, value, i, e in rows[:MAX_ROWS]:
            tree.insert('', 'end', iid=str(i), values=(name, g, value), tags=('changed',) if e.changed else ())
        keep = [i for i in sel if tree.exists(i)]
        if keep:
            tree.selection_set(keep)
        self.flag_rows = rows
        self.flag_count['text'] = (f'{len(rows)} of {total} flags shown' if known else
                                   'The flag names are still being read...')

    def set_flags(self, to):
        sf = self.save_file
        sel = self.flag_tree.selection()
        if not sf or not sel:
            return
        for iid in sel:
            e = sf.entries[int(iid)]
            sf.set(e, (not e.value) if to is None else to)
            self.flag_tree.item(iid, values=(self.name(e.hash), cat.flag_group(self.name(e.hash)),
                                             'On' if e.value else 'Off'), tags=('changed',) if e.changed else ())
        self.edited()

    # ------------------------------------------------------------------------------------------- All entries tab
    def refill(self):
        self._jobs['all'] = None
        tree = self.tree
        tree.delete(*tree.get_children())
        self.rows = []
        sf = self.slot.files.get(self.kind()) if self.slot else None
        if not sf:
            return
        types = sorted({e.type for e in sf.entries})
        self.type_box['values'] = ['All'] + types
        if self.type_var.get() not in types:
            self.type_var.set('All')
        words = self.search_var.get().lower().split()
        kind, named_only, changed_only = self.type_var.get(), self.named_var.get(), self.changed_var.get()
        rows = []
        for i, e in enumerate(sf.entries):
            if kind != 'All' and e.type != kind:
                continue
            if changed_only and not e.changed:
                continue
            name = self.names.names.get(e.hash) or cat.EXTRA_NAMES.get(e.hash)
            if named_only and not name:
                continue
            name = name or f'#{e.hash:08x}'
            if words and not all(w in name.lower() for w in words):
                continue
            rows.append((name, e.type, i, e))
        value_of = {'name': lambda r: r[0], 'type': lambda r: r[1],
                    'value': lambda r: r[3].value if isinstance(r[3].value, (int, float)) else fmt(self.names, r[3])}
        self.all_sort.sort(rows, lambda r, c: value_of[c](r))
        for name, _t, i, e in rows[:MAX_ROWS]:
            tree.insert('', 'end', iid=str(i), values=(name, e.type, fmt(self.names, e)), tags=self.tags(e))
        self.rows = rows

    def tags(self, e):
        return ('changed',) if e.changed else () if e.editable else ('locked',)

    def edit_selected(self, toggle_only=False):
        sel = self.tree.selection()
        sf = self.slot.files.get(self.kind()) if self.slot else None
        if not sel or not sf:
            return
        e = sf.entries[int(sel[0])]
        if not e.editable:
            self.set_status('This kind of entry cannot be edited.')
            return
        if e.type == 'Bool':
            sf.set(e, not e.value)
        elif toggle_only or EditDialog(self, sf, e).result is None:
            return
        self.tree.item(sel[0], values=(self.name(e.hash), e.type, fmt(self.names, e)), tags=self.tags(e))
        self.edited()

    # ------------------------------------------------------------------------------------------- saving, undoing
    def revert(self):
        if not self.slot:
            return
        for sf in self.slot.files.values():
            for e in sf.entries:
                if e.changed:
                    sf.set(e, e.original)
        self.refresh_all()
        self.set_status('Every edit undone.')

    def save(self):
        """Writes the slot's edited files. True when they are written (or there was nothing to write)."""
        s = self.slot
        if not s or not s.dirty:
            return True
        files = [sf for sf in s.files.values() if sf.dirty]
        n = s.edited()
        if not messagebox.askokcancel(
                'Save', f'Write {n} edited value{"s" if n != 1 else ""} to\n' + '\n'.join(str(sf.path) for sf in files)
                + '?\n\nClose the game first: a running game overwrites the files when it saves.\nThe files are '
                'copied into the backups folder before they are replaced.', parent=self):
            return False
        def write():          # (in the background, with the Working... window: files only)
            for sf in files:
                try:
                    sf.save(BACKUPS)
                except OSError as err:
                    return f'{sf.path} could not be written:\n{err}'
            return ''
        import busy
        problem = busy.run(self, f'Saving {s.label}...', write)
        ok = not problem
        if problem:
            messagebox.showerror('Save', problem, parent=self)
        self.refresh_all()
        if ok:
            self.set_status(f'Saved. The previous files are in {BACKUPS}')
        return ok

    # -- Save to...: this slot (with its edits) written to other save locations (each game's saves) and slots
    def save_to_dialog(self):
        s = self.slot
        if not s or 'progress' not in s.files:
            return
        busy = nxsave.blocking_game()
        if busy:
            messagebox.showwarning('Save to', f'{busy} is running: close it first, so it does not write over the '
                                   'saves (or tick Save while the game runs).', parent=self)
            return
        here = s.files['progress'].path.parent.parent
        places = nxsave.all_save_locations()
        if not any(os.path.normcase(str(d)) == os.path.normcase(str(here)) for _a, d in places):
            places.insert(0, ('This save', here))
        win = tk.Toplevel(self)
        win.title(f'Save {s.label} to...')
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill='both', expand=True)
        ttk.Label(frm, text=f'Write {s.label}' + (f' with its {s.edited()} edits' if s.dirty else '') +
                  ' to these save locations:', font=(theme.FAMILY, 10, 'bold')).pack(anchor='w')
        checks = []
        for app, d in places:
            var = tk.BooleanVar(value=True)
            mark = '   (this one)' if os.path.normcase(str(d)) == os.path.normcase(str(here)) else ''
            ttk.Checkbutton(frm, text=f'{app}  —  {d}{mark}', variable=var).pack(anchor='w', pady=(4, 0))
            checks.append((var, app, d))
        row = ttk.Frame(frm)
        row.pack(fill='x', pady=(12, 0))
        ttk.Label(row, text='Into slot').pack(side='left')
        slot_var = tk.StringVar(value=s.label)
        ttk.Combobox(row, textvariable=slot_var, state='readonly', width=10,
                     values=[f'Slot {n}' for n in range(1, 7)]).pack(side='left', padx=(8, 12))
        ttk.Button(row, text='All', command=lambda: [v.set(True) for v, *_ in checks]).pack(side='left')
        ttk.Button(row, text='None', command=lambda: [v.set(False) for v, *_ in checks]).pack(side='left',
                                                                                         padx=(6, 0))
        ttk.Label(frm, text='What is in that slot now is copied into the backups folder first. Close every game '
                            'before saving.', foreground=theme.MUTED, wraplength=560, justify='left').pack(
            anchor='w', pady=(10, 0))
        bar = ttk.Frame(frm)
        bar.pack(fill='x', pady=(12, 0))
        ttk.Button(bar, text='Cancel', command=win.destroy).pack(side='right')

        def go():
            targets = [(app, d) for v, app, d in checks if v.get()]
            if not targets:
                return
            n = int(slot_var.get().split()[-1]) - 1
            win.destroy()
            self.save_to(targets, n)
        ttk.Button(bar, text='Save', command=go).pack(side='right', padx=(0, 8))
        win.bind('<Escape>', lambda _e: win.destroy())
        win.update_idletasks()
        win.geometry(f'+{self.winfo_rootx() + 120}+{self.winfo_rooty() + 100}')
        win.grab_set()

    def save_to(self, targets, n):
        """Writes this slot's progress.sav and caption.sav, as edited, into slot n of each account folder in targets
        [(app, folder)]; what was there goes to the backups folder first. The open slot itself counts as saved when
        it is one of them."""
        import shutil
        s = self.slot
        here = s.files['progress'].path.parent
        stamp = time.strftime('%Y-%m-%d %H%M%S')
        files = [(name, s.files[kind]) for kind, name in (('progress', 'progress.sav'), ('caption', 'caption.sav'))
                 if kind in s.files]
        done, failed, state = [], [], {'here': False}

        def write():          # (in the background, with the Working... window: files only)
            for app, acct in targets:
                dest = Path(acct) / f'slot_{n:02d}'
                try:
                    if os.path.normcase(str(dest)) == os.path.normcase(str(here)):
                        for _name, sf in files:
                            if sf.dirty:
                                sf.save(BACKUPS)
                        state['here'] = True
                    else:
                        dest.mkdir(parents=True, exist_ok=True)
                        keep = BACKUPS / stamp / f'{app} {Path(acct).name[:8]}' / dest.name
                        for name, sf in files:
                            old = dest / name
                            if old.is_file():
                                keep.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(old, keep / name)
                            tmp = dest / (name + '.editing')
                            tmp.write_bytes(sf.buf)
                            tmp.replace(old)
                    done.append(f'{app}: {dest}')
                except OSError as err:
                    failed.append(f'{app}: {dest}\n   {err}')
        import busy
        busy.run(self, f'Writing {s.label} to {len(targets)} save location{"s" if len(targets) != 1 else ""}...', write)
        saved_here = state['here']
        self.refresh_all()
        msg = f'{s.label} written to slot {n + 1} in {len(done)} place{"s" if len(done) != 1 else ""}:\n\n' + \
              '\n'.join(done)
        if failed:
            msg += '\n\nCould not write:\n' + '\n'.join(failed)
        if not saved_here and s.dirty:
            msg += '\n\n(The open slot itself was not among them: its edits are still not saved here.)'
        (messagebox.showwarning if failed else messagebox.showinfo)('Save to', msg, parent=self)
        self.set_status(f'Written to {len(done)} save location{"s" if len(done) != 1 else ""}. Old files are in '
                        f'{BACKUPS}')

    def save_and_play(self):
        """Saves the edits (asking, as Save does), then starts the game."""
        busy = nxsave.blocking_game()
        if busy:
            messagebox.showwarning('Save and play', f'{busy} is running already: close it first, so it does not '
                                   'write over the save, then press Save and play again (or tick Save while the '
                                   'game runs).', parent=self)
            return
        if self.save():
            self.on_play()

    def toggle_ignore_running(self):
        """The "Save while the game runs" checkbox (the same one as the Mods tab's): asked once when ticked."""
        var = nxsave.ignore_running_var(self)
        if var.get() and not messagebox.askyesno('Save while the game runs', nxsave.IGNORE_RUNNING_WARNING,
                                                 icon='warning', parent=self):
            var.set(False)
        nxsave.set_ignore_running(var.get())

    def start_game(self):
        """On its own (not in the toolbox): start the game (Triforce.exe or longshot.exe) and close this window."""
        exe = nxsave.game_exe()
        if exe is None:
            messagebox.showerror('Save and play', f'No Triforce.exe or longshot.exe in {nxsave.game_dir()}.',
                                 parent=self)
            return
        import subprocess
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        self.winfo_toplevel().destroy()

    def open_backups(self):
        nxsave.open_folder(BACKUPS)

    def may_close(self):
        """True when the window may close: nothing unsaved, or the player said to drop it."""
        return self.may_discard()

    def close(self):
        if self.may_close():
            self.winfo_toplevel().destroy()


def main():
    root = tk.Tk()
    theme.apply(root)
    import icons
    icons.apply(root)
    root.geometry('1150x720')
    root.minsize(860, 460)
    app = App(root)
    app.pack(fill='both', expand=True)
    root.protocol('WM_DELETE_WINDOW', app.close)
    if '--selftest' in sys.argv:     # open, go through the tabs, sort, filter, and close without writing a file
        def step():
            if not app.names.names:
                app.after(200, step)
                return
            for t in range(4):
                app.book.select(t)
                app.update()
            app.inv_sort.click('have')
            app.flag_sort.click('value')
            app.all_sort.click('value')
            app.search_var.set('rupee')
            app.inv_search.set('sword')
            app.after(600, lambda: (print('slot', app.slot.label, '| files', list(app.slot.files), '| items',
                                          len(app.inv_rows), '| flags', len(app.flag_rows), '| rupee rows',
                                          len(app.rows), '| summary', app.summary['text'], '| status',
                                          app.status['text']), root.destroy()))
        root.report_callback_exception = lambda *a: (print('ERROR', a[1], a[2].tb_frame.f_code.co_name,
                                                           a[2].tb_lineno), root.destroy())
        app.after(200, step)
    root.mainloop()


if __name__ == '__main__':
    main()
