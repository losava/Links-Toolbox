"""Reading a small BYML file into a tree that keeps every value's type, and writing such a tree back (version 7,
little-endian, as the game's parameter files are). For files that have to gain entries, where changing bytes in place
is not enough.

A node is (kind, payload):
    ('dict', {key: node})      in the file's order          ('array', [node, ...])
    ('str', text)                                           (type byte, u32) for bool 0xd0, int 0xd1, float 0xd2,
                                                            uint 0xd3 and null 0xff, the value as the file has it
"""
import struct

INLINE = (0xd0, 0xd1, 0xd2, 0xd3, 0xff)


def read(p):
    if bytes(p[:2]) != b'YB':
        raise ValueError('not a little-endian BYML file')
    version, keys_at, strs_at, root = struct.unpack_from('<HIII', p, 2)
    if version != 7:
        raise ValueError(f'BYML version {version}')

    def table(off):
        if not off:
            return []
        n = int.from_bytes(p[off + 1:off + 4], 'little')
        offs = struct.unpack_from(f'<{n}I', p, off + 4)
        return [bytes(p[off + o:p.index(b'\0', off + o)]).decode('utf-8') for o in offs]

    keys, strs = table(keys_at), table(strs_at)

    def node(t, v):
        if t == 0xa0:
            return ('str', strs[v])
        if t in INLINE:
            return (t, v)
        n = int.from_bytes(p[v + 1:v + 4], 'little')
        if t == 0xc1:
            out = {}
            for i in range(n):
                e = v + 4 + 8 * i
                out[keys[int.from_bytes(p[e:e + 3], 'little')]] = node(p[e + 3], struct.unpack_from('<I', p, e + 4)[0])
            return ('dict', out)
        if t == 0xc0:
            vals = struct.unpack_from(f'<{n}I', p, v + 4 + ((n + 3) & ~3))
            return ('array', [node(p[v + 4 + i], vals[i]) for i in range(n)])
        raise ValueError(f'BYML node type {t:#x} is not handled')

    return node(p[root], root)


def _texts(texts):
    head = 4 + 4 * (len(texts) + 1)
    body, offs = b'', []
    for t in texts:
        offs.append(head + len(body))
        body += t.encode('utf-8') + b'\0'
    offs.append(head + len(body))
    out = bytes([0xc2]) + len(texts).to_bytes(3, 'little') + struct.pack(f'<{len(offs)}I', *offs) + body
    return out + bytes(-len(out) % 4)


def write(tree):
    keys, strs = set(), set()

    def collect(n):
        if n[0] == 'dict':
            for k, v in n[1].items():
                keys.add(k)
                collect(v)
        elif n[0] == 'array':
            for v in n[1]:
                collect(v)
        elif n[0] == 'str':
            strs.add(n[1])

    collect(tree)
    keys = sorted(keys, key=lambda s: s.encode('utf-8'))
    strs = sorted(strs, key=lambda s: s.encode('utf-8'))
    ki = {k: i for i, k in enumerate(keys)}
    si = {s: i for i, s in enumerate(strs)}
    kt = _texts(keys) if keys else b''
    st = _texts(strs) if strs else b''
    out = bytearray(b'YB' + struct.pack('<HIII', 7, 16 if keys else 0, 16 + len(kt) if strs else 0, 0) + kt + st)

    def type_of(n):
        return {'dict': 0xc1, 'array': 0xc0, 'str': 0xa0}.get(n[0], n[0])

    def emit(n):
        """A container is written where the file ends now, its own containers after it; its offset comes back."""
        at = len(out)
        if n[0] == 'dict':
            items = sorted(n[1].items(), key=lambda kv: ki[kv[0]])
            out.extend(bytes([0xc1]) + len(items).to_bytes(3, 'little') + bytes(8 * len(items)))
            for i, (k, v) in enumerate(items):
                e = at + 4 + 8 * i
                out[e:e + 4] = ki[k].to_bytes(3, 'little') + bytes([type_of(v)])
                struct.pack_into('<I', out, e + 4, value(v))
        else:
            items = n[1]
            pad = (len(items) + 3) & ~3
            out.extend(bytes([0xc0]) + len(items).to_bytes(3, 'little') + bytes(type_of(v) for v in items)
                       + bytes(pad - len(items)) + bytes(4 * len(items)))
            for i, v in enumerate(items):
                struct.pack_into('<I', out, at + 4 + pad + 4 * i, value(v))
        return at

    def value(n):
        if n[0] in ('dict', 'array'):
            return emit(n)
        if n[0] == 'str':
            return si[n[1]]
        return n[1]

    if tree[0] not in ('dict', 'array'):
        raise ValueError('the root has to be a dictionary or an array')
    struct.pack_into('<I', out, 12, emit(tree))
    return bytes(out)
