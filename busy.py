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
