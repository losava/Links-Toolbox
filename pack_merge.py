"""Merged .pack.zs files for the mods that are on.

A .pack.zs is a zstd-compressed SARC (with the game's pack.zsdic) of many small files. The game loads one whole
archive per path, so when two mods each replace that path the later folder wins and the earlier mod's files inside
it are lost, even when they touched different members.

On Save this writes one archive per such path, into "~Merged Packs": the game's original members, then every mod's
added and changed members and its removals, in mod order (the later mod wins a member both changed). The folder
sorts after every mod and before "~Size Table", so the merged archive is the one loaded and the size table still
sees it. Packs only one mod carries are left alone. Nothing is written into the player's own mod folders, and the
folder is removed when no pack needs merging.

Run from the mod loader's Save (and when a new build's size table is rebuilt). The list shows a member both mods
changed, in the same place as other clashes.
"""
import os
import shutil
from pathlib import Path

import nxsave
from nxsave import zstd

FOLDER = '~Merged Packs'
LEVEL = 19                    # (the same level the size table and a hand-built pack used)


def game_for(mods_dir, game=None):
    """The game whose files these mods replace: the one asked for, else the game folder that holds the mods, else
    the game the toolbox is using (a shared mods folder lives outside every build)."""
    if game:
        return Path(game)
    parent = Path(mods_dir).parent
    if nxsave.is_game_dir(parent):
        return parent
    return nxsave.game_dir()


def _load_dict(rom):
    """The pack.zsdic the game decompresses .pack.zs with, or None when the game files have none."""
    try:
        raw = zstd.decompress(rom.load('Pack/ZsDic.pack.zs'))
        data = nxsave.sarc_members(raw).get('pack.zsdic')
    except (OSError, ValueError, KeyError, zstd.ZstdError):
        return None
    return zstd.ZstdDict(data) if data else None


def _inspect(raw):
    """(members, alignment, hash multiplier) of a little-endian SARC."""
    if len(raw) < 0x14 or raw[:4] != b'SARC' or raw[6:8] != b'\xff\xfe':
        raise ValueError('not a little-endian SARC')
    mult = nxsave.sarc_multiplier(raw) or nxsave.SARC_HASH
    return nxsave.sarc_members(raw), nxsave.sarc_alignment(raw), mult


def _open_pack(data, dic):
    return _inspect(zstd.decompress(data, zstd_dict=dic))


def merge_members(original, mods):
    """mods: [(label, {name: bytes}), ...] in load order, later wins. A mod adds a member the original lacks, changes
    one whose bytes differ, or removes one by leaving it out; a member it carries unchanged is left to the others.
    Returns (merged, clashes) with clashes (member, loser, winner). Does not mutate its inputs."""
    result = dict(original)
    touched = {}
    for label, members in mods:
        actions = [(name, 'set', data) for name, data in members.items()
                   if name not in original or original[name] != data]
        actions += [(name, 'del', None) for name in original if name not in members]
        for name, kind, data in actions:
            touched.setdefault(name, []).append((label, kind, data))
    clashes = []
    for name, acts in touched.items():
        for _label, kind, data in acts:
            if kind == 'set':
                result[name] = data
            else:
                result.pop(name, None)
        win = acts[-1]
        for label, kind, data in acts[:-1]:
            if (kind, data) != (win[1], win[2]):
                clashes.append((name, label, win[0]))
    clashes.sort()
    return result, clashes


def _shared(mods_dir, folders):
    """{lowercase path: [(folder, real relative path), ...]} for every .pack.zs that two or more of the folders
    carry, in the order the folders were given."""
    found = {}
    for folder in folders:
        if str(folder).startswith('~'):
            continue
        root = Path(mods_dir) / folder / 'romfs'
        if not root.is_dir():
            continue
        for dirpath, _d, names in os.walk(root):
            for name in names:
                rel = (Path(dirpath) / name).relative_to(root).as_posix()
                if rel.lower().endswith('.pack.zs'):
                    found.setdefault(rel.lower(), []).append((str(folder), rel))
    shared = {}
    for key, pairs in found.items():
        owners, seen = [], set()
        for folder, rel in pairs:
            if folder in seen:
                continue
            seen.add(folder)
            owners.append((folder, rel))
        if len(owners) >= 2:
            shared[key] = owners
    return shared


def _canon(rom, key, owners):
    """The game's own spelling of a path when it has one (the size table's key is that spelling), else the later
    mod's."""
    if rom is not None:
        for path in rom.by_path:
            if path.lower() == key:
                return path
    return owners[-1][1]


def _original(rom, key, dic):
    """(members, alignment, multiplier, path) of the game's pack, or (empty, 8, default, None) when the game has
    no such file (every member a mod carries is then an add)."""
    if rom is not None:
        for path in rom.by_path:
            if path.lower() == key:
                members, align, mult = _open_pack(rom.load(path), dic)
                return members, align, mult, path
    return {}, 8, nxsave.SARC_HASH, None


def build(mods_dir, mod_folders, game=None, log=print, rom=None):
    """Writes (or removes) ~Merged Packs for the mod folders, in their load order. Returns
    {'written': [path], 'clashes': [(path, member, loser, winner)], 'skipped': [(path, why)]}.
    rom: a Romfs to read the game's packs from (tests); otherwise the game's own."""
    mods_dir = Path(mods_dir)
    out = mods_dir / FOLDER
    shared = _shared(mods_dir, mod_folders)
    written, clashes, skipped = [], [], []
    close = False
    if shared:
        if rom is None:
            rom = nxsave.Romfs(game_for(mods_dir, game))
            close = True
        try:
            dic = _load_dict(rom)
            if dic is None:
                raise ValueError('the game files have no pack dictionary (Pack/ZsDic.pack.zs)')
            for key, owners in shared.items():
                try:
                    original, align, mult, _path = _original(rom, key, dic)
                    loaded = []
                    for folder, rel in owners:
                        data = (mods_dir / folder / 'romfs' / rel).read_bytes()
                        members, mod_align, _mod_mult = _open_pack(data, dic)
                        loaded.append((folder, members))
                        align = max(align, mod_align)
                    align = max(align, 8)         # (8 matched the game's packs; higher is kept when the bytes use it)
                    merged, fights = merge_members(original, loaded)
                    rel = _canon(rom, key, owners)
                    for member, loser, winner in fights:
                        clashes.append((rel, member, loser, winner))
                    # the later mod's archive already loads last: write only when the merge is not that archive
                    if merged != loaded[-1][1]:
                        raw = nxsave.write_sarc(merged, alignment=align, multiplier=mult)
                        blob = zstd.compress(raw, level=LEVEL, zstd_dict=dic)
                        written.append((rel, blob))
                except (OSError, ValueError, zstd.ZstdError) as err:
                    skipped.append((owners[-1][1], str(err)))
                    log(f'merged packs: skipped {owners[-1][1]}: {err}')
        finally:
            if close:
                rom.close()
    if out.is_dir():
        shutil.rmtree(out)
    for rel, blob in written:
        dst = out / 'romfs' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(blob)
    if written:
        log(f'merged packs: {len(written)} pack{"s" if len(written) != 1 else ""}, '
            f'{len(clashes)} member clash{"es" if len(clashes) != 1 else ""}')
    elif not skipped:
        log('merged packs: no pack carried by two mods that are on needs one')
    return {'written': [rel for rel, _b in written], 'clashes': clashes, 'skipped': skipped}


def refresh(mods_dir, mod_folders, game=None, log=lambda _s: None, rom=None):
    """Merged packs, then the size table, for the mods that are on. The merged folder is part of the size table, and
    it sorts before ~Size Table so the table is still the one the game loads."""
    import size_table
    mods_dir = Path(mods_dir)
    if game is None and rom is None:
        game = game_for(mods_dir)
    done = build(mods_dir, mod_folders, game=game, log=log, rom=rom)
    folders = [f for f in mod_folders if not str(f).startswith('~')]
    if FOLDER not in folders and (mods_dir / FOLDER).is_dir():
        folders.append(FOLDER)
    size_table.build(mods_dir, folders, log=log, game=game, rom=rom)
    return done


# the list reads the same packs again as the player reorders: keep the members of a file that has not changed
_cache = {}
_rom = {'key': None, 'rom': None, 'dic': None}


def _cached_rom(game):
    game = Path(game)
    idx = game / 'romfs' / 'index.json'
    try:
        mark = idx.stat().st_mtime_ns if idx.is_file() else (game / 'romfs').stat().st_mtime_ns
    except OSError:
        mark = None
    key = (str(game), mark)
    if _rom['key'] != key or _rom['rom'] is None:
        if _rom['rom'] is not None:
            _rom['rom'].close()
            _rom['rom'] = None
        _cache.clear()
        try:
            _rom['rom'] = nxsave.Romfs(game)
            _rom['dic'] = _load_dict(_rom['rom'])
        except (OSError, ValueError):
            _rom['rom'] = _rom['dic'] = None
        _rom['key'] = key
    return _rom['rom'], _rom['dic']


def _cached_pack(path, dic):
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size, getattr(dic, 'dict_id', None))
    hit = _cache.get(key)
    if hit is None:
        hit = _open_pack(path.read_bytes(), dic)[0]
        _cache[key] = hit
    return hit


def _cached_original(rom, key, dic):
    for path, f in rom.by_path.items():
        if path.lower() != key:
            continue
        mark = ('rom', path, f.get('size'), f.get('offset'), getattr(dic, 'dict_id', None))
        hit = _cache.get(mark)
        if hit is None:
            hit = _open_pack(rom.load(path), dic)[0]
            _cache[mark] = hit
        return hit
    return {}


def _owners_of(mods):
    """{lowercase path: [mod, ...]} for .pack.zs carried by two or more mods that are on, in list order."""
    found = {}
    for m in mods:
        if not (m.on and m.loads):
            continue
        paths = getattr(m, 'paths', None) or {f: f for f in m.files}
        for low, rel in paths.items():
            if low.endswith('.pack.zs'):
                found.setdefault(low, []).append((m, rel))
    shared = {}
    for key, pairs in found.items():
        owners, seen = [], set()
        for mod, rel in pairs:
            if mod.folder in seen:
                continue
            seen.add(mod.folder)
            owners.append((mod, rel))
        if len(owners) >= 2:
            shared[key] = owners
    return shared


def ui_clashes(mods_dir, mods, rom=None):
    """({name: (lost lines, won lines, note)}, merged paths) for the Mods list. merged paths are lowercase .pack.zs
    that were compared, so those are not also shown as a whole file lost. Read-only; empty when the packs cannot be
    read, and the list then keeps the whole-file clash."""
    shared = _owners_of(mods)
    if not shared:
        return {}, set()
    if rom is None:
        rom, dic = _cached_rom(game_for(mods_dir))
    else:
        dic = _load_dict(rom)
    if rom is None or dic is None:
        return {}, set()
    groups, merged = {}, set()
    mods_dir = Path(mods_dir)
    for key, owners in shared.items():
        try:
            original = _cached_original(rom, key, dic)
            loaded = [(m, _cached_pack(mods_dir / m.folder / 'romfs' / rel, dic)) for m, rel in owners]
        except (OSError, ValueError, zstd.ZstdError):
            continue
        merged.add(key)
        _merged, fights = merge_members(original, [(m.folder, members) for m, members in loaded])
        by_folder = {m.folder: m for m, _members in loaded}
        base = Path(_canon(rom, key, [(m.folder, rel) for m, rel in owners])).name
        for member, loser, winner in fights:
            a, b = by_folder.get(loser), by_folder.get(winner)
            if a is None or b is None:
                continue
            groups.setdefault((a.name, b.name, base), []).append(member)
    per = {}
    for (loser, winner, base), members in sorted(groups.items()):
        members = sorted(set(members))
        n = len(members)
        slot = per.setdefault(loser, ([], [], []))
        other = per.setdefault(winner, ([], [], []))
        if n == 1:
            slot[0].append(f'{winner} wins {members[0]} in {base}')
            other[1].append(f'over {loser}: {members[0]} in {base}')
        else:
            slot[0].append(f'{winner} wins {n} members in {base}')
            other[1].append(f'over {loser}: {n} members in {base}')
        shown = ', '.join(members[:8]) + (f' and {n - 8} more' if n > 8 else '')
        line = f'In {base}, {winner} wins {shown} (both changed them; the lower mod wins).'
        slot[2].append(line)
        other[2].append(line)
    info = {name: (lost, won, '\n'.join(lines)) for name, (lost, won, lines) in per.items()}
    return info, merged
