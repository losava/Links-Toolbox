"""Files dropped on a window from Explorer (Windows only): the window takes WM_DROPFILES, the same message Explorer
sends any program that accepts drops. Tk has no drop support of its own, so this hooks the window's message handler
(ctypes, nothing to install). On other systems enable() does nothing and returns False."""
import os
import sys

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
_hooks = {}        # hwnd -> (the new handler, the old one): kept alive as long as the window


def enable(window, on_drop):
    """on_drop([paths]) runs (in Tk, right after the drop) when files or folders are dropped on window (a Tk or
    Toplevel). True when drops are on."""
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
    setter = getattr(user32, 'SetWindowLongPtrW', None) or user32.SetWindowLongW
    setter.restype = ctypes.c_void_p
    setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    window.update_idletasks()
    hwnd = int(window.wm_frame(), 16)          # (the real top window Tk draws in)
    if hwnd in _hooks:
        return True

    def handler(h, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            paths = []
            try:
                count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                for i in range(count):
                    size = shell32.DragQueryFileW(wparam, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(size)
                    shell32.DragQueryFileW(wparam, i, buf, size)
                    paths.append(buf.value)
            finally:
                shell32.DragFinish(wparam)
            if paths:
                window.after(0, lambda: on_drop(paths))    # (out of the message handler first)
            return 0
        return user32.CallWindowProcW(_hooks[hwnd][1], h, msg, wparam, lparam)

    new = WNDPROC(handler)
    old = setter(hwnd, GWLP_WNDPROC, ctypes.cast(new, ctypes.c_void_p))
    _hooks[hwnd] = (new, old)
    shell32.DragAcceptFiles(hwnd, True)
    return True


if __name__ == '__main__' and '--try' in sys.argv:        # (a window to drop things on, to try it)
    import tkinter as tk
    root = tk.Tk()
    label = tk.Label(root, text='Drop files or folders here', padx=60, pady=60)
    label.pack()
    print('drops on:', enable(root, lambda paths: label.configure(text='\n'.join(paths))))
    root.mainloop()
