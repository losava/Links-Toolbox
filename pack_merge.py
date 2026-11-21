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

Animation lists that follow a switched model (follow_animation_lists): a costume mod can point an actor's ActorParam
at its own AnimationParam (Malon's costumes point young Link at Player_Malon_Child's list), so sets another mod added
to the actor's own list (Adult Motions' rescaled adult sets) are never used. When the final pack does that, the added
sets go into the list it points at too: first, in the order the mod gave them (the game takes a clip from the later
set when two share a name, so the costume's own clips still win), and retargeted the way that list's own sets are
(IsRetarget / RetargetModel copied from them). Such a pack is written to ~Merged Packs even when only one mod carries
it. Nothing else in the list changes. A retargeted set needs a skeleton file of its own (Model/<set>.Skeleton.bfres.zs:
without one the game never finishes loading the actor, so young Link never appeared); one is written to ~Merged Packs
from the costume's own, renamed, and a set none can be made for is left out of the list.
"""
import os
import shutil
import struct
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


_MISSING = ('missing',)


def _merge_tree(o, a, b):
    """Three-way merge of BYML trees (byml_rw's nodes): o the game's, a what the merge has so far, b the next mod's.
    A dict is merged key by key (each mod's own changes kept); anything else both changed differently: b wins.
    (tree, clash) with clash True when some value was changed both ways."""
    if b == o:
        return a, False
    if a == o or a == b:
        return b, False
    if a[0] == b[0] == 'dict' and (o is _MISSING or o[0] == 'dict'):
        od = {} if o is _MISSING else o[1]
        out, clash = {}, False
        for k in list(a[1]) + [k for k in b[1] if k not in a[1]]:
            v, c = _merge_tree(od.get(k, _MISSING), a[1].get(k, _MISSING), b[1].get(k, _MISSING))
            clash = clash or c
            if v is not _MISSING:
                out[k] = v
        return ('dict', out), clash
    if a[0] == b[0] == 'array' and (o is _MISSING or o[0] == 'array'):
        oa = [] if o is _MISSING else o[1]
        key = _row_key(oa + a[1] + b[1])
        if key:                            # (rows with a name: merged by name, each mod's added and changed rows kept)
            name = lambda n: n[1][key][1]
            od, ad, bd = ({name(n): n for n in rows} for rows in (oa, a[1], b[1]))
            out, clash = [], False
            for n in a[1] + [n for n in b[1] if name(n) not in ad]:
                k = name(n)
                v, c = _merge_tree(od.get(k, _MISSING), ad.get(k, _MISSING), bd.get(k, _MISSING))
                clash = clash or c
                if v is not _MISSING:
                    out.append(v)
            return ('array', out), clash
        if len(oa) == len(a[1]) == len(b[1]):     # (the same length: place by place)
            out, clash = [], False
            for x, y, z in zip(oa, a[1], b[1]):
                v, c = _merge_tree(x, y, z)
                clash = clash or c
                out.append(v)
            return ('array', out), clash
    return b, True


ROW_KEYS = ('__RowId', 'BtnName', 'ActorShort', 'Name', 'ModelProjectName')


def _row_key(rows):
    """The field that names every row of a list (the game's tables: __RowId, BtnName, ActorShort...), None when the
    rows are not dictionaries that all have one such field with a different text in each."""
    if not rows or not all(n[0] == 'dict' for n in rows):
        return None
    for key in ROW_KEYS:
        names = [n[1].get(key) for n in rows]
        if all(v is not None and v[0] == 'str' for v in names):
            return key
    return None


def merge_byml(original, versions):
    """One BYML file (version 7, little-endian) as each mod changed it, merged key by key over the game's: (bytes,
    clash), or None when one of them is not such a file (then the later one wins whole, as before)."""
    import byml_rw
    try:
        o = byml_rw.read(original)
        trees = [byml_rw.read(v) for v in versions]
    except (ValueError, IndexError, KeyError, struct.error, UnicodeDecodeError):
        return None
    tree, clash = trees[0], False
    for t in trees[1:]:
        tree, c = _merge_tree(o, tree, t)
        clash = clash or c
    try:
        return byml_rw.write(tree), clash
    except (ValueError, KeyError, struct.error):
        return None


def merge_members(original, mods):
    """mods: [(label, {name: bytes}), ...] in load order, later wins. A mod adds a member the original lacks, changes
    one whose bytes differ, or removes one by leaving it out; a member it carries unchanged is left to the others.
    A BYML member two mods both changed is merged key by key (Malon's costume switching a player's model and Majora's
    Mask giving the same player its mask AI both change the ActorParam, in different keys): only a key both changed
    is a clash. Returns (merged, clashes) with clashes (member, loser, winner). Does not mutate its inputs."""
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
        sets = [data for _l, kind, data in acts if kind == 'set']
        if len(acts) > 1 and len(sets) == len(acts) and name in original and len(set(sets)) > 1:
            merged = merge_byml(original[name], sets)
            if merged is not None:
                result[name], clash = merged
                if clash:
                    clashes.extend((name, label, acts[-1][0]) for label, _k, _d in acts[:-1])
                continue
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


# ---------------------------------------------------------------------------------- animation lists that follow a model
ANIM_LIST_KEY = 'AnimationResources'


def _text_table(texts):
    """A BYML text table (node 0xc2) of sorted texts."""
    head = 4 + 4 * (len(texts) + 1)
    body, offs = b'', []
    for t in texts:
        offs.append(head + len(body))
        body += t.encode() + b'\0'
    offs.append(head + len(body))
    out = bytes([0xc2]) + len(texts).to_bytes(3, 'little') + struct.pack(f'<{len(offs)}I', *offs) + body
    return out + bytes(-len(out) % 4)


def write_anim_list(entries):
    """An AnimationParam file laid out as the game's own (BYML 7): {AnimationResources: [ {key: text or bool}, ...]},
    keys and texts in sorted tables, the root, the list, then one small dictionary a set. Only text and bool values."""
    keys = sorted({ANIM_LIST_KEY} | {k for e in entries for k in e})
    texts = sorted({v for e in entries for v in e.values() if isinstance(v, str)})
    kt, tt = _text_table(keys), _text_table(texts)
    root = 16 + len(kt) + len(tt)
    array = root + 12
    n = len(entries)
    first = array + 4 + ((n + 3) & ~3) + 4 * n
    out = b'YB' + struct.pack('<HIII', 7, 16, 16 + len(kt), root) + kt + tt
    out += bytes([0xc1, 1, 0, 0]) + keys.index(ANIM_LIST_KEY).to_bytes(3, 'little') + bytes([0xc0])
    out += struct.pack('<I', array)
    out += bytes([0xc0]) + n.to_bytes(3, 'little') + bytes([0xc1] * n) + bytes(-n % 4)
    offs, at = [], first
    for e in entries:
        offs.append(at)
        at += 4 + 8 * len(e)
    out += struct.pack(f'<{n}I', *offs)
    for e in entries:
        out += bytes([0xc1]) + len(e).to_bytes(3, 'little')
        for k in sorted(e, key=keys.index):
            v = e[k]
            if isinstance(v, bool):
                out += keys.index(k).to_bytes(3, 'little') + bytes([0xd0]) + struct.pack('<I', int(v))
            elif isinstance(v, str):
                out += keys.index(k).to_bytes(3, 'little') + bytes([0xa0]) + struct.pack('<I', texts.index(v))
            else:
                raise ValueError(f'{k}: a {type(v).__name__} value in an animation list is not written here')
    return out


def _anim_entries(data):
    doc = nxsave.byml(data)
    if not isinstance(doc, dict) or set(doc) != {ANIM_LIST_KEY} or not isinstance(doc[ANIM_LIST_KEY], list):
        return None
    if not all(isinstance(e, dict) and isinstance(e.get('ModelProjectName'), str) for e in doc[ANIM_LIST_KEY]):
        return None
    return doc[ANIM_LIST_KEY]


def _ref(members, actor_param, key):
    """An ActorParam's component reference ('?Component/...bgyml' -> member name), None when it has none."""
    try:
        doc = nxsave.byml(members[actor_param])
        ref = doc['Components'][key]
    except (KeyError, TypeError, ValueError):
        return None
    return ref.lstrip('?') if isinstance(ref, str) else None


def skeleton_file(name):
    return f'Model/{name}.Skeleton.bfres.zs'


def follow_animation_lists(members, original, skeleton=None, files=None):
    """(members, notes): when an ActorParam in the final pack points its AnimationRef at another list than the game's
    own, the sets mods added to the game's own list go into the list it points at too (see the module notes).
    notes: [(actor param, list now used, [sets added])]. Does not mutate its inputs.
    skeleton(set, [the list's retargeted sets]): a retargeted set needs its own Model/<set>.Skeleton.bfres.zs (the
    game waits for it, and Link never appears): b'' when there is one already, the file's bytes to write (put in
    files), None when none can be made (the set is then left out)."""
    result, notes = dict(members), []
    for ap in sorted(m for m in members if m.endswith('.engine__actor__ActorParam.bgyml')):
        if ap not in original:
            continue
        own, used = _ref(original, ap, 'AnimationRef'), _ref(members, ap, 'AnimationRef')
        if not own or not used or own == used or own not in members or own not in original or used not in result:
            continue
        try:
            game_sets = [e['ModelProjectName'] for e in (_anim_entries(original[own]) or [])]
            modded = _anim_entries(members[own])
            target = _anim_entries(result[used])
        except (ValueError, struct.error):
            continue
        if modded is None or target is None or not game_sets:
            continue
        have = {e['ModelProjectName'] for e in target}
        added = [e['ModelProjectName'] for e in modded
                 if e['ModelProjectName'] not in game_sets and e['ModelProjectName'] not in have]
        if not added:
            continue
        # retargeted the way the list's own sets are (a costume's model plays the player's animations through it)
        style = next(({k: v for k, v in e.items() if k != 'ModelProjectName'} for e in target if e.get('IsRetarget')),
                     {})
        if style.get('IsRetarget') and skeleton:
            sources = [e['ModelProjectName'] for e in target if e.get('IsRetarget')]
            kept = []
            for s in added:
                made = skeleton(s, sources)
                if made is None:
                    continue
                if made and files is not None:
                    files[skeleton_file(s)] = made
                kept.append(s)
            added = kept
            if not added:
                continue
        new = [dict(style, ModelProjectName=s) for s in added]
        # where the mod put them: before the game's own sets (it wants those to win) or after them
        names = [e['ModelProjectName'] for e in modded]
        first_game = min((names.index(s) for s in game_sets if s in names), default=len(names))
        before = all(names.index(s) < first_game for s in added)
        entries = new + list(target) if before else list(target) + new
        result[used] = write_anim_list(entries)
        notes.append((ap, used, added))
    return result, notes


def _skeleton_maker(mods_dir, mod_folders, rom):
    """follow_animation_lists' skeleton(): a set's skeleton file from the mods that are on (the later wins) or the game;
    else one made from a retargeted set's of the same list with the name inside changed (a costume ships one per set,
    byte for byte the same but for that name; a name of the same length only, so nothing in the file moves)."""
    folders = [f for f in mod_folders if not str(f).startswith('~')]
    plain = {}

    def raw(name):
        rel = skeleton_file(name)
        for folder in reversed(folders):
            p = Path(mods_dir) / folder / 'romfs' / rel
            if p.is_file():
                return p.read_bytes()
        for path in rom.by_path:
            if path.lower() == rel.lower():
                return rom.load(path)
        return None

    def make(name, sources):
        if raw(name) is not None:
            return b''
        if 'dic' not in plain:
            try:
                d = nxsave.sarc_members(zstd.decompress(rom.load('Pack/ZsDic.pack.zs'))).get('zs.zsdic')
                plain['dic'] = zstd.ZstdDict(d) if d else None
            except (OSError, ValueError, KeyError, zstd.ZstdError):
                plain['dic'] = None
        if plain['dic'] is None:
            return None
        for src in sources:
            if len(src) != len(name):
                continue
            blob = raw(src)
            if blob is None:
                continue
            try:
                data = zstd.decompress(blob, zstd_dict=plain['dic'])
            except zstd.ZstdError:
                continue
            if data.count(src.encode()) != 1 or name.encode() in data:
                continue
            return zstd.compress(data.replace(src.encode(), name.encode()), level=LEVEL, zstd_dict=plain['dic'])
        return None

    return make


BYML_ENDS = ('.bgyml', '.byml', '.byml.zs')     # (game data the merge combines key by key, as it does pack members)


def _mergeable(low):
    """A path Save merges when two mods that are on carry it: a .pack.zs, or a BYML game data file."""
    return low.endswith('.pack.zs') or low.endswith(BYML_ENDS)


def _zs_dict(rom, low):
    """The dictionary the game decompresses a (non-pack) .zs file with: bcett's own for .bcett.byml.zs, else zs.zsdic."""
    members = nxsave.sarc_members(zstd.decompress(rom.load('Pack/ZsDic.pack.zs')))
    name = 'bcett.byml.zsdic' if low.endswith('.bcett.byml.zs') else 'zs.zsdic'
    return zstd.ZstdDict(members[name]) if name in members else None


def _merge_loose(rom, key, datas):
    """A BYML game file several mods replace, merged over the game's: (bytes as the game reads them, clash) or None
    when it can't be (no game copy, not a BYML file the writer handles)."""
    path = next((p for p in rom.by_path if p.lower() == key), None)
    if path is None:
        return None
    dic = _zs_dict(rom, key) if key.endswith('.zs') else None
    unpack = (lambda b: zstd.decompress(b, zstd_dict=dic)) if key.endswith('.zs') else (lambda b: b)
    merged = merge_byml(unpack(rom.load(path)), [unpack(d) for d in datas])
    if merged is None:
        return None
    data, clash = merged
    return (zstd.compress(data, level=LEVEL, zstd_dict=dic) if key.endswith('.zs') else data), clash


def _carried(mods_dir, folders):
    """{lowercase path: [(folder, real relative path), ...]} for every .pack.zs any of the folders carries."""
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
                    pairs = found.setdefault(rel.lower(), [])
                    if all(f != str(folder) for f, _r in pairs):
                        pairs.append((str(folder), rel))
    return found


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
                if _mergeable(rel.lower()):
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
    # (an actor pack one mod carries can still need its animation lists followed: Pack/Actor/*.pack.zs)
    for key, owners in _carried(mods_dir, mod_folders).items():
        if key not in shared and key.startswith('pack/actor/'):
            shared[key] = owners
    written, clashes, skipped, followed = [], [], [], []
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
                if not key.endswith('.pack.zs'):          # (a BYML game file two mods replace: merged key by key)
                    try:
                        datas = [(mods_dir / folder / 'romfs' / rel).read_bytes() for folder, rel in owners]
                        got = _merge_loose(rom, key, datas)
                    except (OSError, ValueError, KeyError, zstd.ZstdError) as err:
                        got, why = None, str(err)
                    rel = _canon(rom, key, owners)
                    if got is None:
                        continue                          # (the later mod's file wins whole, as before)
                    blob, clash = got
                    if clash:
                        clashes.extend((rel, '(some values both change)', f, owners[-1][0]) for f, _r in owners[:-1])
                    if blob != datas[-1]:
                        written.append((rel, blob))
                    continue
                try:
                    original, align, mult, _path = _original(rom, key, dic)
                    loaded = []
                    for folder, rel in owners:
                        data = (mods_dir / folder / 'romfs' / rel).read_bytes()
                        members, mod_align, _mod_mult = _open_pack(data, dic)
                        loaded.append((folder, members))
                        align = max(align, mod_align)
                    align = max(align, 8)         # (8 matched the game's packs; higher is kept when the bytes use it)
                    merged, fights = merge_members(original, loaded) if len(loaded) > 1 else (loaded[0][1], [])
                    rel = _canon(rom, key, owners)
                    for member, loser, winner in fights:
                        clashes.append((rel, member, loser, winner))
                    extra = {}
                    merged, notes = follow_animation_lists(merged, original, _skeleton_maker(mods_dir, mod_folders, rom),
                                                           extra)
                    written.extend(extra.items())
                    for ap, used, added in notes:
                        followed.append((rel, ap, used, added))
                        log(f'merged packs: {rel}: {Path(used).name} now also lists {", ".join(added)} '
                            f'(its ActorParam uses that list, not its own)')
                    # the later mod's archive already loads last: write only when the merge is not that archive
                    if merged != loaded[-1][1]:
                        raw = nxsave.write_sarc(merged, alignment=align, multiplier=mult)
                        blob = zstd.compress(raw, level=LEVEL, zstd_dict=dic)
                        written.append((rel, blob))
                except (OSError, ValueError, zstd.ZstdError) as err:
                    if len(owners) > 1:          # (one mod's own pack, only looked at for its animation lists: as it is)
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
        packs = sum(1 for rel, _b in written if rel.lower().endswith('.pack.zs'))
        skeletons = len(written) - packs
        log(f'merged packs: {packs} pack{"s" if packs != 1 else ""}, '
            f'{len(clashes)} member clash{"es" if len(clashes) != 1 else ""}'
            + (f', {skeletons} skeleton file{"s" if skeletons != 1 else ""} for added animation sets' if skeletons else ''))
    elif not skipped:
        log('merged packs: no pack carried by two mods that are on needs one')
    return {'written': [rel for rel, _b in written], 'clashes': clashes, 'skipped': skipped, 'followed': followed}


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
    """{lowercase path: [mod, ...]} for .pack.zs (and BYML game files) carried by two or more mods that are on."""
    found = {}
    for m in mods:
        if not (m.on and m.loads):
            continue
        paths = getattr(m, 'paths', None) or {f: f for f in m.files}
        for low, rel in paths.items():
            if _mergeable(low):
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
        if not key.endswith('.pack.zs'):
            try:
                got = _merge_loose(rom, key, [(mods_dir / m.folder / 'romfs' / rel).read_bytes() for m, rel in owners])
            except (OSError, ValueError, KeyError, zstd.ZstdError):
                got = None
            if got is not None:
                merged.add(key)                   # (merged by Save: not a whole file lost)
                if got[1]:
                    a, b = owners[-2][0], owners[-1][0]
                    groups.setdefault((a.name, b.name, Path(owners[-1][1]).name), []).append('some values')
            continue
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
