"""The resource size table for the mods that are on, for Triforce.

The game sizes the buffer it loads a file into from its resource size table (System/Resource/ResourceSizeTable...).
A mod file larger than the game's, or one the game does not have, needs a larger entry, or the game aborts when it
loads it. NX2navi raised the entries for mod files by itself; Triforce does not: it serves one table, the game's or
the one a mod carries, as it is.

So this writes one table, as a mod of its own that sorts after every other ("~Size Table", made by the mod loader on
each save), from the game's table and, for every mod that is on ("~Merged Packs" sorts first, and is included, so a
merged pack that grew is in the table too):
    the entries of the table it carries, if it carries one (the larger value of each)
    for each of its files the game has: the game's entry raised by twice the growth and a margin, when it grew
    for each of its files the game does not have and no table names: twice its size and a margin
When no mod needs anything, the folder is taken away, so Triforce's own table (with its button icons) is served.

Run:  python\\python.exe save-editor\\size_table.py      (the mod loader does this when it saves)
"""
import os
import shutil
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxsave  # noqa: E402
from nxsave import zstd  # noqa: E402

FOLDER = '~Size Table'
MARGIN = 8192


def entries_of(table):
    if table[:6] != b'RESTBL':
        raise ValueError('not a resource size table')
    ncrc, = struct.unpack_from('<I', table, 14)
    return ncrc, dict(struct.iter_unpack('<II', table[22:22 + ncrc * 8]))


def with_entries(table, entries):
    ncrc, _ = entries_of(table)
    head = bytearray(table[:22])
    struct.pack_into('<I', head, 14, len(entries))
    body = b''.join(struct.pack('<II', k, v) for k, v in sorted(entries.items()))
    return bytes(head) + body + table[22 + ncrc * 8:]


def size_of(data, path, dics):
    """A file's size as the game loads it: decompressed for a .zs file (from the frame's header when it has one)."""
    if not path.endswith('.zs'):
        return len(data)
    try:
        n = zstd.get_frame_info(data).decompressed_size
        if n:
            return n
    except Exception:
        pass
    d = dics['pack.zsdic'] if path.endswith('.pack.zs') else \
        dics['bcett.byml.zsdic'] if path.endswith('.bcett.byml.zs') else dics['zs.zsdic']
    return len(zstd.decompress(data, zstd_dict=d))


def build(mods_dir, mod_folders, log=print, out=None, game=None, rom=None):
    """Writes (or takes away) the size table mod for the given mod folders, in their order. Returns the entries
    changed against the game's table. out: where the mod goes (default: mods_dir / FOLDER). game: the game folder
    (default: the one the toolbox is using). rom: that game's Romfs, when the caller already has it open."""
    out = out or mods_dir / FOLDER
    own = rom is None
    if own:
        rom = nxsave.Romfs(Path(game) if game else nxsave.game_dir())
    try:
        dics = {k: zstd.ZstdDict(v) for k, v in
                nxsave.sarc_members(zstd.decompress(rom.load('Pack/ZsDic.pack.zs'))).items()}
        table_path = [p for p in rom.by_path if p.startswith('System/Resource/ResourceSizeTable.')
                      and p.endswith('.rsizetable.zs')]
        if len(table_path) != 1:
            raise ValueError(f'expected one resource size table in the game, found {table_path}')
        table_path = table_path[0]
        table = zstd.decompress(rom.load(table_path))
        _n, base = entries_of(table)
        entries = dict(base)
        named = set()
        # the tables the mods carry
        for folder in mod_folders:
            t = mods_dir / folder / 'romfs' / table_path
            if t.is_file():
                _n, theirs = entries_of(zstd.decompress(t.read_bytes()))
                for k, v in theirs.items():
                    if v > entries.get(k, 0):
                        entries[k] = v
                    if k not in base:
                        named.add(k)
        # each file of each mod
        for folder in mod_folders:
            root = mods_dir / folder / 'romfs'
            for dirpath, _d, names in os.walk(root):
                for name in names:
                    p = os.path.join(dirpath, name)
                    rel = os.path.relpath(p, root).replace('\\', '/')
                    if rel.lower() == table_path.lower():
                        continue
                    key = zlib.crc32((rel[:-3] if rel.endswith('.zs') else rel).encode())
                    with open(p, 'rb') as fh:
                        new = size_of(fh.read(), rel, dics)
                    if rel in rom.by_path and key in base:
                        old = size_of(rom.load(rel), rel, dics)
                        if new > old:
                            entries[key] = max(entries[key], base[key] + 2 * (new - old) + MARGIN)
                    elif key not in named and key not in base:
                        entries[key] = max(entries.get(key, 0), 2 * new + MARGIN)
        changed = {k: (base.get(k), v) for k, v in entries.items() if base.get(k) != v}
        if out.is_dir():
            shutil.rmtree(out)
        if changed:
            dst = out / 'romfs' / table_path
            dst.parent.mkdir(parents=True)
            dst.write_bytes(zstd.compress(with_entries(table, entries), level=19))
            log(f'size table: {sum(1 for o, _ in changed.values() if o is None)} entries added, '
                f'{sum(1 for o, _ in changed.values() if o is not None)} raised, for {len(mod_folders)} mods')
        else:
            log('size table: no mod that is on needs one; the game\'s own is served')
        return changed
    finally:
        if own:
            rom.close()


def main(argv):
    import pack_merge
    mods = nxsave.game_dir() / 'mods'
    on = sorted(p.name for p in mods.iterdir() if p.is_dir() and not p.name.startswith(('-', '_', '~'))
                and (p / 'romfs').is_dir()) if mods.is_dir() else []
    print('mods that are on:', on)
    pack_merge.refresh(mods, on)          # (merged packs first, so the table counts them; ~ folders are not in on)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
