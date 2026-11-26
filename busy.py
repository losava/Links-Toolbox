"""A "Working..." window for jobs that take a while (saving mods and building the size table, copying mods, the shared
mods folder...): the job runs on another thread while this small window shows a moving bar, so the toolbox keeps
redrawing instead of looking frozen.

    result = busy.run(parent, 'Saving the mods...', work)     # waits (the window stays alive), then returns or raises

work() must not touch the window (no Tk calls, no message boxes): only files.
"""
import threading
import tkinter as tk
from tkinter import ttk

import theme


def run(parent, text, work, title="Link's Tool Box", delay_ms=250):
    """Runs work() on another thread and waits for it while the window keeps redrawing; a small Working... window shows
    once it takes longer than delay_ms (quick jobs just finish). Returns work()'s result, or raises its error."""
    import gc
    out = {}

    def job():
        try:
            out['result'] = work()
        except BaseException as err:          # (handed to the caller, on the window's thread)
            out['error'] = err
    # (Python's cycle collector would otherwise sometimes run on the job's thread and free window objects there,
    #  which Tk does not allow: collected here before, and on this thread after)
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    thread = threading.Thread(target=job, daemon=True)
    thread.start()
    top = parent.winfo_toplevel()
    done = tk.BooleanVar(master=top, value=False)
    win = {}
    old_cursor = top.cget('cursor')

    def show():
        if not thread.is_alive():
            return
        w = tk.Toplevel(top)
        w.title(title)
        w.transient(top)
        w.resizable(False, False)
        w.protocol('WM_DELETE_WINDOW', lambda: None)       # (the job can't be stopped halfway)
        frm = ttk.Frame(w, padding=(22, 16))
        frm.pack(fill='both', expand=True)
        ttk.Label(frm, text=text, wraplength=360, justify='left').pack(anchor='w')
        bar = ttk.Progressbar(frm, mode='indeterminate', length=360)
        bar.pack(fill='x', pady=(12, 4))
        bar.start(12)
        ttk.Label(frm, text='Please wait...', foreground=theme.MUTED).pack(anchor='w')
        theme.center(w, top)
        try:
            w.grab_set()
        except tk.TclError:
            pass
        win['w'] = w

    def poll():
        if thread.is_alive():
            top.after(80, poll)
        else:
            done.set(True)
    try:
        top.configure(cursor='watch')
    except tk.TclError:
        pass
    show_id = top.after(delay_ms, show)
    top.after(80, poll)
    try:
        top.wait_variable(done)              # (the window keeps redrawing and answering while waiting)
    finally:
        if was_enabled:
            gc.enable()
    try:
        top.after_cancel(show_id)            # (a quick job: the Working... window never shows)
    except tk.TclError:
        pass
    del done
    if 'w' in win:
        try:
            win['w'].grab_release()
            win['w'].destroy()
        except tk.TclError:
            pass
    try:
        top.configure(cursor=old_cursor)
    except tk.TclError:
        pass
    if 'error' in out:
        raise out['error']
    return out.get('result')


# ------------------------------------------------------------------------------------------- the start-up window
# A small green-capped elf running in place (our own pixel art, drawn here: no image files), 12 x 16 pixels.
ELF_COLOURS = {'G': '#3fa34d', 'g': '#2b7a37', 'H': '#e6c35c', 'S': '#f2c79a', 'E': '#1d1d1d', 'T': '#4cb85c',
               'B': '#7a4a22', 'L': '#e8dcc0', 'b': '#5a3518'}
ELF_TOP = ['......GGG...',
           '....GGGGGG..',
           '...GGGGGGGg.',
           '..gGHHHHHGg.',
           '.gg.HSSSSH..',
           'g...SSESSE..',
           '....SSSSSS..',
           '.....SSSS...',
           '....TTTTTT..',
           '...TTTTTTTT.']
ELF_ARMS = ['..STTTTTTTS.', '...TTTTTTTS.', '..STTTTTTTS.', '..STTTTTTT..']
ELF_BODY = ['....BBBBBB..', '....TTTTTT..']
ELF_LEGS = [['...LL...LL..', '..LL.....LL.', '.bb.....bb..'],
            ['.....LLL....', '.....L.L....', '.....bbb....'],
            ['....LL..LL..', '...LL....LL.', '..bb.....bb.'],
            ['.....LLL....', '.....LL.L...', '.....bb.b...']]
ELF_SCALE = 4


def elf_frame(i):
    """The rows of frame i of the run (four frames; the passing frames bob up a pixel)."""
    rows = ELF_TOP + [ELF_ARMS[i % 4]] + ELF_BODY + ELF_LEGS[i % 4]
    return rows[1:] + ['............'] if i % 2 else rows


class Splash:
    """The window shown while the toolbox opens: the running elf, the step it is on and how far it is (percent).
    step() redraws it; the elf runs whenever the window gets a moment (between steps, and while busy.run works)."""

    def __init__(self, root, title="Link's Tool Box"):
        self.win = win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.configure(background=theme.BORDER)
        frm = ttk.Frame(win, padding=(16, 14))
        frm.pack(fill='both', expand=True, padx=1, pady=1)
        self.canvas = tk.Canvas(frm, width=12 * ELF_SCALE, height=16 * ELF_SCALE, background=theme.BG,
                                highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=3, padx=(0, 16))
        ttk.Label(frm, text=title, foreground=theme.GOLD, font=(theme.FAMILY, 11, 'bold')).grid(row=0, column=1,
                                                                                              sticky='w')
        self.text = ttk.Label(frm, text='Starting...', foreground=theme.SOFT)
        self.text.grid(row=1, column=1, sticky='w', pady=(2, 6))
        row = ttk.Frame(frm)
        row.grid(row=2, column=1, sticky='ew')
        self.bar = ttk.Progressbar(row, mode='determinate', maximum=100, length=260)
        self.bar.pack(side='left')
        self.pct = ttk.Label(row, text='0%', width=5, anchor='e')
        self.pct.pack(side='left', padx=(8, 0))
        self.frame = 0
        self.draw()
        theme.center(win, root)
        win.lift()
        win.update()
        self._tick()

    def draw(self):
        c = self.canvas
        c.delete('all')
        for y, line in enumerate(elf_frame(self.frame)):
            for x, ch in enumerate(line):
                if ch in ELF_COLOURS:
                    c.create_rectangle(x * ELF_SCALE, y * ELF_SCALE, (x + 1) * ELF_SCALE, (y + 1) * ELF_SCALE,
                                       fill=ELF_COLOURS[ch], width=0)

    def _tick(self):
        try:
            if self.win.winfo_exists():
                self.frame += 1
                self.draw()
                self.win.after(120, self._tick)
        except tk.TclError:
            pass

    def step(self, pct, text):
        try:
            self.bar['value'] = pct
            self.pct['text'] = f'{pct:.0f}%'
            self.text['text'] = text
            self.win.update()
        except tk.TclError:
            pass

    def close(self):
        try:
            self.win.destroy()
        except tk.TclError:
            pass
