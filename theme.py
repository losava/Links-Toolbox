"""The toolbox's dark theme (deep green and gold), for every ttk and tk widget the tools use, and a dark window title
bar on Windows 10/11.

    import theme; theme.apply(root)        # once, right after tk.Tk()
    theme.MUTED, theme.ERROR, ...           # the colours for text that is not the main text
"""
import ctypes
import os
import tkinter as tk
from tkinter import ttk

BG = '#121c19'          # windows, frames
PANEL = '#18261f'       # boxes, lists, fields
FIELD = '#0f1916'       # where you type
BORDER = '#34503f'
HOVER = '#22382d'
SELECT = '#2f5a45'      # picked rows, picked text
TEXT = '#e9efe6'
SOFT = '#c3d2c8'        # secondary text
MUTED = '#93a89b'       # hints
DIM = '#6f8478'         # off, missing, not editable
FAINT = '#5f7468'       # the watermark
GOLD = '#e4c783'        # the accent: headings, the picked tab
WARN = '#e8c46a'
ERROR = '#ff8f7a'       # edited, clashes, mistakes
FAMILY = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'     # (Linux: a font most desktops have)
FONT = (FAMILY, 9)


# each tab's own colour
DEFAULT_TABS = {'Mods': '#7ccf8a', 'Save editor': '#e4c783', 'Folders': '#7fb3f5', 'Look': '#f58fc8',
                'Updates': '#c9e26b',
                'Stats': '#ff8f8f', 'Inventory': '#f2b25c', 'Progress': '#b79cff', 'All entries': '#63cfc4'}
TAB_COLORS = dict(DEFAULT_TABS)
_count = 0

# the themes the Look tab offers: the base colours (the accent and the tabs' colours are picked apart)
PRESETS = {
    'Dark green': dict(BG='#121c19', PANEL='#18261f', FIELD='#0f1916', BORDER='#34503f', HOVER='#22382d',
                       SELECT='#2f5a45', TEXT='#e9efe6', SOFT='#c3d2c8', MUTED='#93a89b', DIM='#6f8478',
                       FAINT='#5f7468', WARN='#e8c46a', ERROR='#ff8f7a'),
    'Dark grey': dict(BG='#1c1c1e', PANEL='#252528', FIELD='#161618', BORDER='#3d3d42', HOVER='#303035',
                      SELECT='#3e4a5e', TEXT='#ececec', SOFT='#c8c8cc', MUTED='#9a9aa0', DIM='#76767c',
                      FAINT='#66666c', WARN='#e8c46a', ERROR='#ff8f7a'),
    'Dark blue': dict(BG='#10161f', PANEL='#16202c', FIELD='#0c121a', BORDER='#2f4359', HOVER='#1e2c3c',
                      SELECT='#284a6e', TEXT='#e6edf5', SOFT='#c0cddb', MUTED='#8ea2b8', DIM='#6a7d92',
                      FAINT='#5a6b80', WARN='#e8c46a', ERROR='#ff8f7a'),
    'Midnight purple': dict(BG='#17121f', PANEL='#1f1829', FIELD='#120e18', BORDER='#443659', HOVER='#2a2138',
                            SELECT='#4a3570', TEXT='#efe9f5', SOFT='#d0c6dc', MUTED='#a397b4', DIM='#7d7190',
                            FAINT='#6c6080', WARN='#e8c46a', ERROR='#ff8f8f'),
    'Light': dict(BG='#f3f2ee', PANEL='#ffffff', FIELD='#ffffff', BORDER='#c9c6bc', HOVER='#e7e4da',
                  SELECT='#cfe3d6', TEXT='#1d1f1c', SOFT='#3d423c', MUTED='#6b7068', DIM='#9a9e96',
                  FAINT='#a4a89f', WARN='#8a5a00', ERROR='#b3261e'),
}
DEFAULT_PRESET, DEFAULT_ACCENT = 'Dark green', '#e4c783'
PRESET = DEFAULT_PRESET


def load(settings=None):
    """Takes the colours chosen in the Look tab (settings['theme']: preset, accent, tabs) into this module."""
    global PRESET, GOLD
    if settings is None:
        try:
            import nxsave
            settings = nxsave.load_settings()
        except Exception:
            settings = {}
    t = settings.get('theme') or {}
    PRESET = t.get('preset') if t.get('preset') in PRESETS else DEFAULT_PRESET
    globals().update(PRESETS[PRESET])
    GOLD = t.get('accent') or DEFAULT_ACCENT
    TAB_COLORS.clear()
    TAB_COLORS.update(DEFAULT_TABS)
    TAB_COLORS.update({k: v for k, v in (t.get('tabs') or {}).items() if k in DEFAULT_TABS})


def mix(a, b, t):
    """Colour a moved t of the way to colour b."""
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return '#' + ''.join(f'{round(x + (y - x) * t):02x}' for x, y in zip(pa, pb))


def color_tabs(book, names):
    """Gives each tab of a notebook its own colour: a dot of it on the tab, and the open tab's name and background in
    it. names: the tabs' names, in order (their colours come from TAB_COLORS)."""
    global _count
    _count += 1
    style = f'Tabs{_count}.TNotebook'
    s = ttk.Style(book)
    s.configure(style, background=BG, bordercolor=BORDER, tabmargins=(2, 4, 2, 0))
    s.configure(style + '.Tab', background=PANEL, foreground=SOFT, bordercolor=BORDER, padding=(12, 4),
                lightcolor=PANEL, darkcolor=PANEL)
    book.configure(style=style)
    book._dots = []
    for tab, name in zip(book.tabs(), names):
        dot = tk.PhotoImage(master=book, width=10, height=10)
        book._dots.append(dot)
        book.tab(tab, image=dot, compound='left')

    def show(_e=None):
        s.configure(style, background=BG)
        s.configure(style + '.Tab', background=PANEL, foreground=SOFT, bordercolor=BORDER,
                    lightcolor=PANEL, darkcolor=PANEL)
        for dot, name in zip(book._dots, names):
            dot.put(TAB_COLORS.get(name, GOLD), to=(1, 1, 9, 9))
        try:
            name = names[book.index(book.select())]
        except (tk.TclError, IndexError):
            return
        color = TAB_COLORS.get(name, GOLD)
        s.map(style + '.Tab', background=[('selected', mix(BG, color, 0.22)), ('active', HOVER)],
              foreground=[('selected', color), ('active', TEXT)], bordercolor=[('selected', color)],
              lightcolor=[('selected', mix(BG, color, 0.22))], expand=[('selected', (1, 1, 1, 0))])
        s.configure(style, bordercolor=mix(BORDER, color, 0.5))
    book.bind('<<NotebookTabChanged>>', show, add='+')
    _books.append(show)
    show()


_books = []     # (each coloured notebook's redraw, for a change of colours while open)


def refresh(root, settings=None):
    """The Look tab's Apply: the new colours on everything open. (Hint texts take theirs when the tools open again.)"""
    load(settings)
    apply(root, reload=False)
    for show in _books:
        show()


def dark_title_bar(win):
    """Windows 10 (build 18985+) and 11: the window's title bar dark too."""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        on = ctypes.c_int(1)
        for attr in (20, 19):      # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older number)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except (AttributeError, OSError):
        pass


def center(win, over=None):
    """Puts a window in the middle of the window it belongs to (over, else its parent's; the screen's while that one
    is not showing), kept on the screen."""
    try:
        win.update_idletasks()
        top = (over or win.master).winfo_toplevel()
        w, h = max(win.winfo_width(), win.winfo_reqwidth()), max(win.winfo_height(), win.winfo_reqheight())
        if top.winfo_viewable():
            x = top.winfo_rootx() + (top.winfo_width() - w) // 2
            y = top.winfo_rooty() + (top.winfo_height() - h) // 2
        else:
            x, y = (win.winfo_screenwidth() - w) // 2, (win.winfo_screenheight() - h) // 2
        x = min(max(0, x), max(0, win.winfo_screenwidth() - w))
        y = min(max(0, y), max(0, win.winfo_screenheight() - h))
        win.geometry(f'+{x}+{y}')
        win._centered = True
    except (tk.TclError, AttributeError):
        pass


def wrapping_label(parent, **kw):
    """A label whose text wraps to the room it has (a long status line takes two lines instead of pushing the
    buttons beside it off the window)."""
    lab = ttk.Label(parent, text='', anchor='w', justify='left', **kw)
    lab.bind('<Configure>', lambda e: lab.configure(wraplength=max(80, e.width - 4)))
    return lab


# -- message boxes in the toolbox's own look, centred on it (Windows places its own boxes where it likes)
def _box(buttons, default, cancel, title, message, parent=None, **_kw):
    """buttons: [(text, value)]; Enter: default, Esc / closing: cancel."""
    root = tk._default_root
    parent = parent or root
    if parent is None:
        return cancel
    win = tk.Toplevel(parent)
    win.title(title or 'Link\'s Tool Box')
    win.resizable(False, False)
    if parent.winfo_toplevel().winfo_viewable():
        win.transient(parent.winfo_toplevel())
    frm = ttk.Frame(win, padding=(18, 14))
    frm.pack(fill='both', expand=True)
    ttk.Label(frm, text=message or '', wraplength=480, justify='left').pack(anchor='w')
    out = {'v': cancel}
    row = ttk.Frame(frm)
    row.pack(fill='x', pady=(14, 0))
    first = None
    for text, value in reversed(buttons):
        b = ttk.Button(row, text=text, command=lambda v=value: (out.update(v=v), win.destroy()))
        b.pack(side='right', padx=(6, 0))
        if value == default:
            first = b
    win.bind('<Return>', lambda _e: (out.update(v=default), win.destroy()))
    win.bind('<Escape>', lambda _e: win.destroy())
    win.protocol('WM_DELETE_WINDOW', win.destroy)
    center(win, parent)
    win.lift()
    (first or win).focus_set()
    try:
        win.grab_set()
    except tk.TclError:
        pass
    win.wait_window()
    return out['v']


def install_message_boxes():
    """Every tkinter.messagebox call in the toolbox shows the toolbox's own box (same answers as before)."""
    from tkinter import messagebox as mb
    ok = [('OK', 'ok')]
    mb.showinfo = lambda title=None, message=None, **kw: _box(ok, 'ok', 'ok', title, message, **kw)
    mb.showwarning = lambda title=None, message=None, **kw: _box(ok, 'ok', 'ok', title, message, **kw)
    mb.showerror = lambda title=None, message=None, **kw: _box(ok, 'ok', 'ok', title, message, **kw)
    mb.askyesno = lambda title=None, message=None, **kw: _box([('Yes', True), ('No', False)], True, False, title,
                                                              message, **kw)
    mb.askyesnocancel = lambda title=None, message=None, **kw: _box(
        [('Yes', True), ('No', False), ('Cancel', None)], True, None, title, message, **kw)
    mb.askokcancel = lambda title=None, message=None, **kw: _box([('OK', True), ('Cancel', False)], True, False,
                                                                 title, message, **kw)
    mb.askretrycancel = lambda title=None, message=None, **kw: _box([('Retry', True), ('Cancel', False)], True, False,
                                                                    title, message, **kw)


def _mapped(e):
    """Every new window: a dark title bar, and centered on the window it belongs to (when it did not do it itself)."""
    w = e.widget
    if not isinstance(w, tk.Toplevel):
        return
    dark_title_bar(w)
    if not getattr(w, '_centered', False) and w.master is not None:
        center(w)


def apply(root, reload=True):
    if reload:
        load()
    s = ttk.Style(root)
    s.theme_use('clam')            # (the one built-in theme whose colours can all be changed)
    s.configure('.', background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=BORDER,
                darkcolor=PANEL, lightcolor=PANEL, troughcolor=FIELD, selectbackground=SELECT,
                selectforeground=TEXT, insertcolor=TEXT, focuscolor=GOLD, font=FONT)
    s.map('.', foreground=[('disabled', DIM)], background=[('disabled', BG)])
    s.configure('TFrame', background=BG)
    s.configure('TLabel', background=BG, foreground=TEXT)
    s.configure('TLabelframe', background=BG, bordercolor=BORDER, relief='solid', borderwidth=1)
    s.configure('TLabelframe.Label', background=BG, foreground=GOLD, font=(FAMILY, 9, 'bold'))
    s.configure('TButton', background=PANEL, foreground=TEXT, bordercolor=BORDER, padding=(10, 3),
                lightcolor=PANEL, darkcolor=PANEL, focusthickness=1)
    s.map('TButton', background=[('disabled', BG), ('pressed', SELECT), ('active', HOVER)],
          foreground=[('disabled', DIM)], bordercolor=[('active', GOLD), ('focus', GOLD)])
    s.configure('TCheckbutton', background=BG, foreground=TEXT, indicatorbackground=FIELD,
                indicatorforeground=GOLD, upperbordercolor=BORDER, lowerbordercolor=BORDER)
    s.map('TCheckbutton', background=[('active', BG)], indicatorbackground=[('selected', FIELD), ('active', HOVER)])
    s.configure('TRadiobutton', background=BG, foreground=TEXT, indicatorbackground=FIELD,
                indicatorforeground=GOLD, upperbordercolor=BORDER, lowerbordercolor=BORDER)
    s.map('TRadiobutton', background=[('active', BG)], indicatorbackground=[('selected', FIELD), ('active', HOVER)])
    s.configure('Horizontal.TScale', background=GOLD, troughcolor=FIELD, bordercolor=BORDER,
                lightcolor=GOLD, darkcolor=GOLD)
    s.configure('Horizontal.TProgressbar', background=GOLD, troughcolor=FIELD, bordercolor=BORDER,
                lightcolor=GOLD, darkcolor=GOLD, thickness=10)
    for w in ('TEntry', 'TCombobox', 'TSpinbox'):
        s.configure(w, fieldbackground=FIELD, foreground=TEXT, background=PANEL, bordercolor=BORDER,
                    arrowcolor=GOLD, insertcolor=TEXT, lightcolor=FIELD, darkcolor=FIELD, padding=(4, 2))
        s.map(w, fieldbackground=[('readonly', FIELD), ('disabled', BG)], foreground=[('disabled', DIM)],
              bordercolor=[('focus', GOLD)], background=[('active', HOVER)], arrowcolor=[('disabled', DIM)],
              selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TEXT)])
    s.configure('TNotebook', background=BG, bordercolor=BORDER, tabmargins=(2, 4, 2, 0))
    s.configure('TNotebook.Tab', background=PANEL, foreground=SOFT, bordercolor=BORDER, padding=(12, 4),
                lightcolor=PANEL, darkcolor=PANEL)
    s.map('TNotebook.Tab', background=[('selected', BG), ('active', HOVER)],
          foreground=[('selected', GOLD), ('active', TEXT)], expand=[('selected', (1, 1, 1, 0))])
    s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, bordercolor=BORDER,
                rowheight=20, lightcolor=PANEL, darkcolor=PANEL)
    s.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', TEXT)])
    s.configure('Treeview.Heading', background=BG, foreground=GOLD, bordercolor=BORDER, relief='flat',
                font=(FAMILY, 9, 'bold'), lightcolor=BG, darkcolor=BG, padding=(4, 3))
    s.map('Treeview.Heading', background=[('active', HOVER)])
    for w in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        s.configure(w, background=PANEL, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                    lightcolor=PANEL, darkcolor=PANEL, gripcount=0)
        s.map(w, background=[('active', HOVER)])
    # plain tk widgets and the lists the comboboxes drop down
    root.configure(background=BG)
    for pattern, value in (('*Toplevel.background', BG), ('*Text.background', FIELD), ('*Text.foreground', TEXT),
                           ('*Text.insertBackground', TEXT), ('*Text.selectBackground', SELECT),
                           ('*Text.highlightThickness', 1), ('*Text.highlightColor', GOLD),
                           ('*Text.highlightBackground', BORDER), ('*Text.relief', 'flat'),
                           ('*Canvas.background', BG), ('*TCombobox*Listbox.background', PANEL),
                           ('*TCombobox*Listbox.foreground', TEXT),
                           ('*TCombobox*Listbox.selectBackground', SELECT),
                           ('*TCombobox*Listbox.selectForeground', TEXT), ('*TCombobox*Listbox.font', FONT)):
        root.option_add(pattern, value)
    s.configure('Swatch.TLabel', relief='solid', borderwidth=1, width=4)
    dark_title_bar(root)
    root.bind_class('Toplevel', '<Map>', _mapped, add='+')
    install_message_boxes()
