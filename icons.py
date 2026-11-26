"""The toolbox's icon: a default one drawn here (a gold Triforce on dark green), or a square cut from a save slot's
picture; written as icon.ico (for windows and shortcuts) and icon.png next to this file. Also the Windows shortcut
("Link Toolbox.lnk") that shows it, since a .bat file cannot have an icon of its own.

Pure Python (PNG and ICO written and read here); the slot picture is a JPEG, decoded by Windows (jpeg_win).
"""
import os
import struct
import subprocess
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICO = HERE / 'icon.ico'
PNG = HERE / 'icon.png'
SIZES = (256, 64, 48, 32, 24, 16)
SHORTCUT_NAME = "Link's Tool Box.lnk"
OLD_SHORTCUT_NAMES = ('Link Toolbox.lnk',)      # (before v1.1.9: swapped for the new name)


# ------------------------------------------------------------------------------------------------ PNG in and out
def png_encode(w, h, rgba):
    raw = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def png_decode(data):
    """(w, h, RGBA bytes) of an 8-bit, non-interlaced PNG (RGB, RGBA, grey, grey+alpha or palette)."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    pos, idat, plte, trns = 8, [], b'', b''
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b'IHDR':
            w, h, depth, ctype, _c, _f, inter = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            plte = body
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        pos += 12 + n
    if depth != 8 or inter:
        raise ValueError('only 8-bit, non-interlaced PNGs')
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b''.join(idat))
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + ((line[i - ch] if i >= ch else 0) + prev[i]) // 2) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b, c = prev[i], (prev[i - ch] if i >= ch else 0)
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if ch == 4:
        return w, h, bytes(out)
    rgba = bytearray(w * h * 4)
    for i in range(w * h):
        if ctype == 2:
            rgba[i * 4:i * 4 + 4] = out[i * 3:i * 3 + 3] + b'\xff'
        elif ctype == 0:
            g = out[i]
            rgba[i * 4:i * 4 + 4] = bytes((g, g, g, 255))
        elif ctype == 4:
            g, a = out[i * 2], out[i * 2 + 1]
            rgba[i * 4:i * 4 + 4] = bytes((g, g, g, a))
        else:
            k = out[i]
            rgba[i * 4:i * 4 + 4] = plte[k * 3:k * 3 + 3] + bytes((trns[k] if k < len(trns) else 255,))
    return w, h, bytes(rgba)


def resize(w, h, rgba, size, box=None):
    """A size x size image of the part box=(x, y, side) of an image (all of it when None), averaging the pixels each
    new pixel covers (a clean shrink)."""
    x0, y0, side = box or (0, 0, min(w, h))
    out = bytearray(size * size * 4)
    scale = side / size
    for ny in range(size):
        sy0, sy1 = y0 + ny * scale, y0 + (ny + 1) * scale
        ys = range(int(sy0), max(int(sy0) + 1, min(h, int(-(-sy1 // 1)))))
        for nx in range(size):
            sx0, sx1 = x0 + nx * scale, x0 + (nx + 1) * scale
            xs = range(int(sx0), max(int(sx0) + 1, min(w, int(-(-sx1 // 1)))))
            r = g = b = a = n = 0
            for yy in ys:
                row = yy * w
                for xx in xs:
                    i = (row + xx) * 4
                    r += rgba[i]; g += rgba[i + 1]; b += rgba[i + 2]; a += rgba[i + 3]; n += 1
            o = (ny * size + nx) * 4
            out[o:o + 4] = bytes((r // n, g // n, b // n, a // n))
    return bytes(out)


def rounded(size, rgba, radius_frac=0.16):
    """The corners cut round (see-through), like the icons Windows draws."""
    out = bytearray(rgba)
    r = size * radius_frac
    for y in range(size):
        for x in range(size):
            dx = max(r - x - 0.5, 0, x + 0.5 - (size - r))
            dy = max(r - y - 0.5, 0, y + 0.5 - (size - r))
            d = (dx * dx + dy * dy) ** 0.5
            if d > r - 1:
                cover = max(0.0, min(1.0, r - d))
                out[(y * size + x) * 4 + 3] = int(out[(y * size + x) * 4 + 3] * cover)
    return bytes(out)


# --------------------------------------------------------------------------------------------- the drawn icons
class Canvas4x:
    """A square drawn 4 times bigger, then shrunk: smooth edges without an image library."""

    def __init__(self, size, top=(40, 60, 50), bottom=(16, 30, 24)):
        self.size, self.s = size, size * 4
        s = self.s
        self.img = bytearray(s * s * 4)
        for y in range(s):
            t = y / s
            c = bytes(int(a + (b - a) * t) for a, b in zip(top, bottom)) + b'\xff'
            self.img[y * s * 4:(y + 1) * s * 4] = c * s

    def poly(self, pts, color, shade=0.0):
        """Fills a polygon (points 0..1 of the square), darker by shade towards its bottom."""
        s = self.s
        P = [(x * s, y * s) for x, y in pts]
        y0, y1 = max(0, int(min(p[1] for p in P))), min(s, int(max(p[1] for p in P)) + 1)
        for y in range(y0, y1):
            yc = y + 0.5
            xs = []
            for (ax, ay), (bx, by) in zip(P, P[1:] + P[:1]):
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
            xs.sort()
            k = 1.0 - shade * ((y - y0) / max(1, y1 - y0))
            c = bytes(max(0, min(255, int(v * k))) for v in color) + b'\xff'
            for a, b in zip(xs[::2], xs[1::2]):
                xa, xb = max(0, int(a + 0.5)), min(s, int(b + 0.5))
                if xb > xa:
                    self.img[(y * s + xa) * 4:(y * s + xb) * 4] = c * (xb - xa)

    def rect(self, x0, y0, x1, y1, color, shade=0.0, r=0.0):
        """A rectangle (0..1), with round corners of radius r."""
        if not r:
            return self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], color, shade)
        import math
        pts = []
        for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            for k in range(7):
                a = math.radians(a0 + k * 15)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.poly(pts, color, shade)

    def done(self):
        return rounded(self.size, resize(self.s, self.s, bytes(self.img), self.size))


def _triforce(c, cx, top, height, color=(240, 204, 110), gap=0.006):
    w = height * 2 / 3 ** 0.5
    hh, hw = height / 2, w / 2
    c.poly([(cx, top + gap), (cx - hw / 2 + gap, top + hh - gap / 2), (cx + hw / 2 - gap, top + hh - gap / 2)], color, .15)
    c.poly([(cx - hw / 2, top + hh + gap / 2), (cx - hw + gap, top + height - gap), (cx - gap, top + height - gap)],
           color, .15)
    c.poly([(cx + hw / 2, top + hh + gap / 2), (cx + gap, top + height - gap), (cx + hw - gap, top + height - gap)],
           color, .15)


def toolbox_icon(size=256):
    """Link's toolbox: a red toolbox with a gold Triforce on the front, wearing a long green cap."""
    c = Canvas4x(size)
    red, dark_red, steel, green, dark_green = (206, 64, 46), (150, 40, 30), (190, 196, 200), (72, 170, 78), (40, 112, 50)
    c.rect(0.60, 0.27, 0.82, 0.42, steel, .25, r=0.035)         # the handle, on the right
    c.rect(0.645, 0.315, 0.775, 0.42, (34, 54, 44))             # (the hole in it)
    c.rect(0.12, 0.40, 0.88, 0.86, red, .30, r=0.05)            # the box
    c.rect(0.12, 0.40, 0.88, 0.52, dark_red, .1, r=0.05)        # the lid
    c.rect(0.12, 0.50, 0.88, 0.53, (90, 24, 18))                # the lid's edge
    c.rect(0.46, 0.49, 0.54, 0.57, steel, .2, r=0.012)          # the latch
    _triforce(c, 0.5, 0.60, 0.20)                               # the emblem
    # the cap, sitting on the lid's left half: a tall cone whose point flops over to the left
    c.poly([(0.17, 0.42), (0.20, 0.30), (0.27, 0.20), (0.37, 0.14), (0.47, 0.15), (0.54, 0.22), (0.57, 0.33),
            (0.57, 0.42)], green, .28)                          # the cone
    c.poly([(0.30, 0.18), (0.20, 0.17), (0.10, 0.21), (0.04, 0.29), (0.07, 0.31), (0.14, 0.27), (0.22, 0.27),
            (0.27, 0.24)], dark_green, .15)                     # the point, flopped over
    c.poly([(0.36, 0.16), (0.43, 0.15), (0.40, 0.30), (0.35, 0.40), (0.31, 0.40), (0.33, 0.28)],
           (110, 200, 110), .3)                                 # a fold of light
    c.rect(0.15, 0.39, 0.59, 0.45, dark_green, .1, r=0.02)      # the band
    return c.done()


def triforce_icon(size=256):
    """A gold Triforce on dark green."""
    c = Canvas4x(size)
    _triforce(c, 0.5, 0.15, 0.70)
    return c.done()


STYLES = {"Link's Tool Box": toolbox_icon, 'Triforce': triforce_icon}


def default_icon(size=256):
    return toolbox_icon(size)


def old_default_icon(size=256):
    """A gold Triforce on a dark green square with round corners, drawn 4x and shrunk (smooth edges)."""
    s = size * 4
    img = bytearray(s * s * 4)
    top, bottom = (40, 60, 50), (16, 30, 24)
    for y in range(s):
        t = y / s
        c = bytes((int(top[0] + (bottom[0] - top[0]) * t), int(top[1] + (bottom[1] - top[1]) * t),
                   int(top[2] + (bottom[2] - top[2]) * t), 255))
        img[y * s * 4:(y + 1) * s * 4] = c * s
    m = s * 0.14                        # margin
    H = (s - 2 * m) * 0.9               # the whole triangle's height
    W = H * 2 / 3 ** 0.5
    cx, ty = s / 2, (s - H) / 2 + s * 0.01

    def tri(ax, ay, bx, by, cx_, cy, color):
        x0, x1 = int(min(ax, bx, cx_)), int(max(ax, bx, cx_)) + 1
        y0, y1 = int(min(ay, by, cy)), int(max(ay, by, cy)) + 1

        def side(px, py, qx, qy, x, y):
            return (qx - px) * (y - py) - (qy - py) * (x - px)
        for y in range(max(0, y0), min(s, y1)):
            for x in range(max(0, x0), min(s, x1)):
                d1, d2, d3 = side(ax, ay, bx, by, x, y), side(bx, by, cx_, cy, x, y), side(cx_, cy, ax, ay, x, y)
                if (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0):
                    shade = 1.0 - 0.18 * ((y - y0) / max(1, y1 - y0))
                    img[(y * s + x) * 4:(y * s + x) * 4 + 4] = bytes(int(v * shade) for v in color) + b'\xff'
    gold = (240, 204, 110)
    gap = s * 0.012
    hh, hw = H / 2, W / 2
    tri(cx, ty + gap, cx - hw / 2 + gap, ty + hh - gap / 2, cx + hw / 2 - gap, ty + hh - gap / 2, gold)        # top
    tri(cx - hw / 2, ty + hh + gap / 2, cx - hw + gap, ty + H - gap, cx - gap, ty + H - gap, gold)              # left
    tri(cx + hw / 2, ty + hh + gap / 2, cx + gap, ty + H - gap, cx + hw - gap, ty + H - gap, gold)              # right
    return rounded(size, resize(s, s, bytes(img), size))


# ------------------------------------------------------------------------------------------ from a slot picture
def from_picture(png_bytes, offset=0.5, size=256):
    """A square of a slot picture (PNG): the full height, offset 0..1 from the left edge to the right."""
    w, h, rgba = png_decode(png_bytes)
    side = min(w, h)
    x = int((w - side) * max(0.0, min(1.0, offset)))
    y = int((h - side) * 0.5)
    return rounded(size, resize(w, h, rgba, size, (x, y, side)))


# ---------------------------------------------------------------------------------------- the .ico and its uses
def ico_bytes(rgba256):
    """An .ico with the sizes Windows asks for, each a PNG (Windows Vista and later read those)."""
    images = [(n, png_encode(n, n, rgba256 if n == 256 else resize(256, 256, rgba256, n))) for n in SIZES]
    head = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b'', b''
    for n, data in images:
        entries += struct.pack('<BBBBHHII', 0 if n == 256 else n, 0 if n == 256 else n, 0, 0, 1, 32, len(data),
                               offset + len(blobs))
        blobs += data
    return head + entries + blobs


def save(rgba256, update_shortcuts=True):
    """Writes icon.ico and icon.png, and points the shortcuts that exist at the new icon (Windows keeps icons in a
    cache: a shortcut remade is shown with the new one)."""
    data = ico_bytes(rgba256)
    ICO.write_bytes(data)
    PNG.write_bytes(png_encode(256, 256, rgba256))
    if update_shortcuts:
        for lnk in shortcuts():
            if lnk.exists():
                make_shortcut(lnk)


def ensure():
    """The icon files, made with the default icon the first time."""
    if not ICO.is_file() or not PNG.is_file():
        save(default_icon(), update_shortcuts=False)
    return ICO


# ------------------------------------------------------------------------------------------------- shortcuts
WINDOWS = os.name == 'nt'
if not WINDOWS:
    SHORTCUT_NAME = "Link's Tool Box.desktop"      # (Linux: a desktop launcher instead of a .lnk)
    OLD_SHORTCUT_NAMES = ('Link Toolbox.desktop',)


def launcher():
    """(program, arguments, folder) that start the toolbox: the Python next to it, without a console window
    (Windows); on Linux the Python running now."""
    import sys
    if not WINDOWS:
        return Path(sys.executable), f'"{HERE / "toolbox.pyw"}"', HERE
    root = HERE.parent
    for py in (root / 'python' / 'pythonw.exe', root.parent / 'python' / 'pythonw.exe'):
        if py.is_file():
            return py, f'"{HERE / "toolbox.pyw"}"', HERE
    return Path('pythonw.exe'), f'"{HERE / "toolbox.pyw"}"', HERE


def desktop_folder():
    if WINDOWS:
        desktop = Path(os.environ.get('USERPROFILE', '~')).expanduser() / 'Desktop'
        try:   # (the Desktop folder may be moved, for example into OneDrive)
            out = subprocess.run(['powershell', '-NoProfile', '-Command', "[Environment]::GetFolderPath('Desktop')"],
                                 capture_output=True, text=True, timeout=15,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.strip()
            return Path(out) if out else desktop
        except (OSError, subprocess.SubprocessError):
            return desktop
    try:       # (Linux: the desktop's own name for it, for example in another language)
        out = subprocess.run(['xdg-user-dir', 'DESKTOP'], capture_output=True, text=True, timeout=10).stdout.strip()
        return Path(out) if out else Path.home() / 'Desktop'
    except (OSError, subprocess.SubprocessError):
        return Path.home() / 'Desktop'


def shortcuts():
    """Where the shortcuts go: next to the .bat / .sh (the toolbox's own folder), and on the Desktop (Linux: also in
    the app menu)."""
    out = [bat_folder() / SHORTCUT_NAME, desktop_folder() / SHORTCUT_NAME]
    if not WINDOWS:
        out.append(Path.home() / '.local' / 'share' / 'applications' / 'link-toolbox.desktop')
    return out


def bat_folder():
    """The folder with Link Toolbox.bat (or .sh): this one (the toolbox inside NX2navi) or the one above (the zip)."""
    return HERE if any((HERE / n).is_file() for n in ('Link Toolbox.bat', 'Link Toolbox.sh')) else HERE.parent


def first_run():
    """The icon, and a shortcut next to Link Toolbox.bat, made once (on its own thread: PowerShell is slow to start)."""
    ensure()
    lnk = bat_folder() / SHORTCUT_NAME
    if not lnk.exists() or any((f / o).exists() for f in (bat_folder(),) for o in OLD_SHORTCUT_NAMES):
        import threading

        def work():
            swap_old_shortcuts()
            if not lnk.exists():
                make_shortcut(lnk)
        threading.Thread(target=work, daemon=True).start()


def swap_old_shortcuts():
    """Shortcuts made under the old name ("Link Toolbox") are made again under the new one, and the old ones removed:
    next to the .bat, and on the Desktop."""
    for folder in (bat_folder(), desktop_folder()):
        for old in OLD_SHORTCUT_NAMES:
            if (folder / old).exists() and make_shortcut(folder / SHORTCUT_NAME):
                try:
                    (folder / old).unlink()
                except OSError:
                    pass


def make_shortcut(path, extra='', name="Link's Tool Box",
                  description="Link's Tool Box - mod loader and save editor"):
    """A shortcut that starts the toolbox, with its icon (Windows: a .lnk; Linux: a .desktop launcher). extra: more
    arguments for the toolbox ('--play': only start the game). True when made."""
    ensure()
    program, args, folder = launcher()
    args = f'{args} {extra}'.strip()
    if not WINDOWS:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(f'[Desktop Entry]\nType=Application\nName={name}\n'
                                  f"Comment={description}\n"
                                  f'Exec="{program}" {args}\nPath={folder}\nIcon={PNG}\nTerminal=false\n'
                                  'Categories=Game;Utility;\n', encoding='utf-8')
            os.chmod(path, 0o755)
            return True
        except OSError:
            return False
    q = lambda s: str(s).replace("'", "''")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(path)}'); $s.TargetPath='{q(program)}'; "
          f"$s.Arguments='{q(args)}'; $s.WorkingDirectory='{q(folder)}'; $s.IconLocation='{q(ICO)},0'; "
          f"$s.Description='{q(description)}'; $s.Save()")
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return r.returncode == 0 and Path(path).exists()
    except (OSError, subprocess.SubprocessError):
        return False


# ----------------------------------------------------------------------------------------------- on windows
def apply(root):
    """The icon on a Tk window (and every window it opens): title bar and taskbar."""
    try:
        ensure()
        if WINDOWS:
            root.iconbitmap(default=str(ICO))
        else:          # (Linux: Tk takes a picture, not an .ico)
            import tkinter as tk
            root._icon_photo = tk.PhotoImage(master=root, file=str(PNG))
            root.iconphoto(True, root._icon_photo)
    except Exception:
        pass
