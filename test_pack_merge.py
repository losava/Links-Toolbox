"""Synthetic packs for the merger: no game files needed.  python test_pack_merge.py"""
import importlib.machinery
import importlib.util
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path


def load_pyw(name):
    """toolbox.pyw loads the .pyw tools this way: import does not look at .pyw files."""
    if name in sys.modules:
        return sys.modules[name]
    path = str(Path(__file__).resolve().parent / (name + '.pyw'))
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module

import compression.zstd as zstd

import nxsave
import pack_merge
import size_table

CAFE_HASH = 1813018558          # sarc_hash('café'): signed bytes, not the unsigned 1813044670


def spec_hash(name, multiplier=0x65):
    h = 0
    for b in name.encode():
        c = b - 256 if b >= 128 else b
        h = (h * multiplier + c) & 0xFFFFFFFF
    return h


def file_starts(blob):
    head, = struct.unpack_from('<H', blob, 4)
    data, = struct.unpack_from('<I', blob, 12)
    count, = struct.unpack_from('<H', blob, head + 6)
    out = []
    for i in range(count):
        _h, _attr, lo, _hi = struct.unpack_from('<IIII', blob, head + 12 + i * 16)
        out.append(data + lo)
    return out


def node_hashes(blob):
    head, = struct.unpack_from('<H', blob, 4)
    count, = struct.unpack_from('<H', blob, head + 6)
    return [struct.unpack_from('<I', blob, head + 12 + i * 16)[0] for i in range(count)]


def manual_one():
    """One file 'a' = XYZ at 8-byte alignment, laid out from the format, not from write_sarc."""
    file_size, data_off = 67, 64
    blob = bytearray(file_size)
    blob[0:4] = b'SARC'
    struct.pack_into('<HHIIHH', blob, 4, 0x14, 0xFEFF, file_size, data_off, 0x0100, 0)
    blob[20:24] = b'SFAT'
    struct.pack_into('<HHI', blob, 24, 0x0C, 1, 0x65)
    struct.pack_into('<IIII', blob, 32, 97, (1 << 24), 0, 3)
    blob[48:52] = b'SFNT'
    struct.pack_into('<HH', blob, 52, 8, 0)
    blob[56:60] = b'a\0\0\0'
    blob[64:67] = b'XYZ'
    return bytes(blob)


def test_sarc_writer():
    made = manual_one()
    assert nxsave.sarc_members(made) == {'a': b'XYZ'}
    assert nxsave.write_sarc({'a': b'XYZ'}) == made
    assert made[6:8] == b'\xff\xfe'                 # little-endian BOM
    assert struct.unpack_from('<H', made, 0x10)[0] == 0x0100
    assert nxsave.sarc_multiplier(made) == 0x65
    assert nxsave.sarc_hash('a') == 97

    members = {f'dir/f{i}.bin': bytes([i]) * (i % 17) for i in range(20)}
    members['empty'] = b''
    members['café'] = b'xyz'
    blob = nxsave.write_sarc(members)
    assert nxsave.sarc_members(blob) == members
    assert node_hashes(blob) == sorted(node_hashes(blob))
    assert all(s % 8 == 0 for s in file_starts(blob))
    assert nxsave.sarc_alignment(blob) >= 8
    # 'café' is stored under the signed-char hash, and the node for it carries that value
    hashes = node_hashes(blob)
    assert CAFE_HASH in hashes and CAFE_HASH == spec_hash('café')
    unsigned = 0
    for b in 'café'.encode():
        unsigned = (unsigned * 0x65 + b) & 0xFFFFFFFF
    assert CAFE_HASH != unsigned

    # hash order is not name order: 'b' hashes below 'ab'
    ordered = nxsave.write_sarc({'ab': b'1', 'b': b'2'})
    assert node_hashes(ordered) == [nxsave.sarc_hash('b'), nxsave.sarc_hash('ab')]
    assert nxsave.sarc_hash('b') < nxsave.sarc_hash('ab')

    tight = nxsave.write_sarc({'a': b'1', 'b': b'2'}, alignment=4)
    assert nxsave.sarc_alignment(tight) == 4
    wide = nxsave.write_sarc({'a': b'1', 'b': b'22'}, alignment=16)
    assert all(s % 16 == 0 for s in file_starts(wide))
    assert nxsave.sarc_members(nxsave.write_sarc({})) == {}
    for bad in ({'a\0b': b'1'},):
        try:
            nxsave.write_sarc(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    try:
        nxsave.write_sarc({'a': b'1'}, alignment=3)
    except ValueError:
        pass
    else:
        raise AssertionError('alignment')
    try:
        nxsave.write_sarc({str(i): b'x' for i in range(0x4000)})
    except ValueError:
        pass
    else:
        raise AssertionError('count')
    try:
        nxsave.sarc_members(b'nope')
    except ValueError:
        pass
    else:
        raise AssertionError('magic')
    odd = nxsave.write_sarc({f'n{i}': b'x' * (i + 1) for i in range(6)}, multiplier=0x67)
    assert nxsave.sarc_multiplier(odd) == 0x67
    assert nxsave.sarc_members(odd) == {f'n{i}': b'x' * (i + 1) for i in range(6)}
    print('ok sarc writer')


def test_merge_members():
    original = {'a': b'1', 'b': b'1', 'c': b'1'}
    snapshot = dict(original)
    # disjoint edits combine; a member carried unchanged is not a vote
    merged, clashes = pack_merge.merge_members(original, [
        ('A', {'a': b'A', 'b': b'1', 'c': b'1'}),
        ('B', {'a': b'1', 'b': b'B', 'c': b'1', 'new': b'N'}),
    ])
    assert merged == {'a': b'A', 'b': b'B', 'c': b'1', 'new': b'N'}
    assert clashes == []
    assert original == snapshot
    # the same member, different bytes: the later mod wins and it is reported
    merged, clashes = pack_merge.merge_members(original, [
        ('A', {'a': b'A', 'b': b'1', 'c': b'1'}),
        ('B', {'a': b'B', 'b': b'1', 'c': b'1'}),
    ])
    assert merged['a'] == b'B' and clashes == [('a', 'A', 'B')]
    # the same bytes are not a clash; a removal stands unless a later mod changes that member
    merged, clashes = pack_merge.merge_members(original, [
        ('A', {'b': b'1', 'c': b'1'}),                       # removes a
        ('B', {'a': b'1', 'b': b'same', 'c': b'1'}),         # a unchanged, b changed the same way A would not
    ])
    assert 'a' not in merged and merged['b'] == b'same' and clashes == []
    merged, clashes = pack_merge.merge_members({'a': b'0'}, [
        ('A', {}),                                           # removes a
        ('B', {'a': b'2'}),                                  # changes a
    ])
    assert merged == {'a': b'2'} and clashes == [('a', 'A', 'B')]
    # an add the later mod does not carry is kept; no original means every member is an add
    merged, clashes = pack_merge.merge_members({}, [
        ('A', {'a': b'1', 'b': b'1'}),
        ('B', {'b': b'2', 'c': b'3'}),
    ])
    assert merged == {'a': b'1', 'b': b'2', 'c': b'3'} and clashes == [('b', 'A', 'B')]
    print('ok merge members')


class Rom:
    def __init__(self, files):
        self._files = dict(files)
        self.by_path = {p: {'path': p, 'size': len(b), 'offset': None} for p, b in files.items()}
        self.sha = 'test'

    def load(self, f):
        return self._files[f if isinstance(f, str) else f['path']]

    def close(self):
        pass


def restbl(entries):
    head = bytearray(22)
    head[:6] = b'RESTBL'
    struct.pack_into('<I', head, 14, len(entries))
    body = b''.join(struct.pack('<II', k, v) for k, v in sorted(entries.items()))
    return bytes(head) + body


def train(blobs):
    samples = [blob * 2 + bytes([n]) for n, blob in enumerate(blobs)]
    samples += [b'pack member padding ' * 20 + bytes([n]) for n in range(40)]
    return zstd.train_dict(samples, 4096)


def zs_pack(members, dic, alignment=8, multiplier=nxsave.SARC_HASH):
    raw = nxsave.write_sarc(members, alignment=alignment, multiplier=multiplier)
    return zstd.compress(raw, level=19, zstd_dict=dic)


def open_pack(data, dic):
    return nxsave.sarc_members(zstd.decompress(data, zstd_dict=dic))


def test_save_merges():
    """The Save path: disjoint edits combine, a conflict is kept for the later mod, an add and a removal are honored,
    a pack only one mod carries is left alone, an off mod is ignored, and the size table counts the merged archive."""
    mod_loader = load_pyw('mod_loader')
    orig = {'keep': b'K' * 20, 'motion': b'M' * 20, 'param': b'P' * 20, 'gone': b'G' * 10, 'same': b'S' * 20}
    a_members = dict(orig)
    a_members['motion'] = b'M' * 2000
    a_members['param'] = b'A' * 80
    del a_members['gone']
    b_members = dict(orig)
    b_members['param'] = b'B' * 80
    b_members['added'] = b'Z' * 4000
    off_members = dict(orig)
    off_members['motion'] = b'NOPE'
    off_members['param'] = b'OFF'
    dic = train(list(orig.values()) + [a_members['motion'], a_members['param'], b_members['param'], b_members['added']])
    dic2 = zstd.ZstdDict(dic.dict_content)
    rel = 'Pack/Actor/Player.pack.zs'
    key = zlib.crc32(rel[:-3].encode())
    files = {
        'Pack/ZsDic.pack.zs': zstd.compress(nxsave.write_sarc({
            'pack.zsdic': dic.dict_content, 'bcett.byml.zsdic': dic.dict_content, 'zs.zsdic': dic.dict_content})),
        rel: zs_pack(orig, dic),
        'System/Resource/ResourceSizeTable.Product.0.rsizetable.zs': zstd.compress(restbl({key: 1000})),
    }
    rom = Rom(files)
    low = 'pack/actor/player.pack.zs'            # the mods spell it differently; the merge uses the game's spelling
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp) / 'game'
        mods = game / 'mods'
        (game / 'romfs').mkdir(parents=True)
        written = {}

        def put(folder, path, data):
            dest = mods / folder / 'romfs' / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            written[(folder, path)] = data

        put('_A', low, zs_pack(a_members, dic))
        put('_A', 'Pack/Only.pack.zs', zs_pack({'only': b'one'}, dic))
        put('_A', 'notes.txt', b'from A')
        put('_B', low, zs_pack(b_members, dic))
        put('_B', 'notes.txt', b'from B')
        put('_Off', low, zs_pack(off_members, dic))
        (mods / pack_merge.FOLDER / 'romfs').mkdir(parents=True)
        (mods / pack_merge.FOLDER / 'romfs' / 'stale.txt').write_bytes(b'stale')
        old_mods, old_rom = mod_loader.MODS, nxsave.Romfs
        mod_loader.MODS = mods
        nxsave.Romfs = lambda _game: rom
        try:
            mod_a, mod_b, mod_off = mod_loader.Mod('_A'), mod_loader.Mod('_B'), mod_loader.Mod('_Off')
            mod_a.on = mod_b.on = True
            pack_merge._cache.clear()
            info, merged_paths = pack_merge.ui_clashes(mods, [mod_a, mod_b, mod_off], rom=rom)
            assert merged_paths == {low}
            assert any('B wins param in Player.pack.zs' == line for line in info['A'][0])
            assert any('param' in line for line in info['B'][1])
            assert 'param' in info['A'][2] and 'Off' not in info['A'][2]
            assert 'Off' not in info
            # whole-file clash ignores the pack that will be merged, and still counts a real shared file
            mod_a.files.add('notes.txt')
            mod_b.files.add('notes.txt')
            plain = mod_loader.clashes([mod_a, mod_b])
            kept = mod_loader.clashes([mod_a, mod_b], merged_paths)
            assert plain['A'][0][1] == 2 and kept['A'][0][1] == 1
            mod_loader.apply([mod_a, mod_b, mod_off])
        finally:
            mod_loader.MODS, nxsave.Romfs = old_mods, old_rom
        merged_file = mods / pack_merge.FOLDER / 'romfs' / rel
        assert merged_file.is_file() and not (mods / pack_merge.FOLDER / 'romfs' / 'stale.txt').exists()
        assert not list((mods / pack_merge.FOLDER).rglob('Only.pack.zs'))
        raw = zstd.decompress(merged_file.read_bytes(), zstd_dict=dic2)
        got = nxsave.sarc_members(raw)
        assert got == {'keep': orig['keep'], 'motion': a_members['motion'], 'param': b_members['param'],
                       'same': orig['same'], 'added': b_members['added']}
        assert all(s % 8 == 0 for s in file_starts(raw))
        info = zstd.get_frame_info(merged_file.read_bytes())
        assert info.dictionary_id == dic.dict_id
        try:
            zstd.decompress(merged_file.read_bytes())
        except zstd.ZstdError:
            pass
        else:
            raise AssertionError('merged pack decompressed without the pack dictionary')
        # the player's own files were not edited (the folders were only renamed)
        for folder, path, data in (('01-A', low, written[('_A', low)]), ('01-A', 'Pack/Only.pack.zs',
                                    written[('_A', 'Pack/Only.pack.zs')]), ('01-A', 'notes.txt', b'from A'),
                                   ('02-B', low, written[('_B', low)]), ('02-B', 'notes.txt', b'from B'),
                                   ('_Off', low, written[('_Off', low)])):
            assert (mods / folder / 'romfs' / path).read_bytes() == data
        assert not list(mods.glob('.renaming-*'))
        old = len(zstd.decompress(files[rel], zstd_dict=dic2))
        new = len(raw)
        a_size = len(zstd.decompress(written[('_A', low)], zstd_dict=dic2))
        b_size = len(zstd.decompress(written[('_B', low)], zstd_dict=dic2))
        assert new > old and new > a_size and new > b_size
        table = zstd.decompress((mods / '~Size Table' / 'romfs' /
                                  'System/Resource/ResourceSizeTable.Product.0.rsizetable.zs').read_bytes())
        _n, entries = size_table.entries_of(table)
        expect = 1000 + 2 * (new - old) + size_table.MARGIN
        assert entries[key] == expect
        assert expect > 1000 + 2 * (b_size - old) + size_table.MARGIN
        # a new build rebuilds both folders from this game's files
        import builds
        nxsave.Romfs = lambda _game: rom
        try:
            builds.rebuild_size_table(game)
        finally:
            nxsave.Romfs = old_rom
        again = open_pack((mods / pack_merge.FOLDER / 'romfs' / rel).read_bytes(), dic2)
        assert again == got
        # nothing left that two mods share: the folder goes, like ~Size Table
        pack_merge.build(mods, ['01-A'], rom=rom, log=lambda _s: None)
        assert not (mods / pack_merge.FOLDER).exists()
    assert pack_merge.FOLDER.startswith('~') and not pack_merge.FOLDER.startswith(('-', '_'))
    assert '99-Z' < pack_merge.FOLDER < size_table.FOLDER
    print('ok save merges')


def _put(mods, folder, rel, data):
    dest = Path(mods) / folder / 'romfs' / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _dict_rom(dic, packs):
    files = {path: zs_pack(members, dic) for path, members in packs.items()}
    files['Pack/ZsDic.pack.zs'] = zstd.compress(nxsave.write_sarc({'pack.zsdic': dic.dict_content,
                                                                    'zs.zsdic': dic.dict_content}))
    return Rom(files)


def test_skip_remove_order():
    dic = train([b'alpha' * 30, b'beta' * 30, b'gamma' * 40])
    orig = {'a': b'alpha' * 10, 'b': b'beta' * 10}
    rel = 'Pack/Actor/P.pack.zs'
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp)
        # list order, not folder-name order: the later argument wins a member both changed, and the earlier
        # mod's other edit is kept, so the merge is not the later archive and a file is written
        _put(mods, '02-B', rel, zs_pack({'a': b'BBB', 'b': b'FROM-B'}, dic))
        _put(mods, '01-A', rel, zs_pack({'a': b'AAA', 'b': orig['b']}, dic))
        done = pack_merge.build(mods, ['02-B', '01-A'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert done['clashes'] == [(rel, 'a', '02-B', '01-A')]
        got = open_pack((mods / pack_merge.FOLDER / 'romfs' / rel).read_bytes(), dic)
        assert got['a'] == b'AAA' and got['b'] == b'FROM-B'
        # the later archive already has every surviving byte: nothing is written, but the clash is still reported
        shutil.rmtree(mods / pack_merge.FOLDER)
        _put(mods, '01-A', rel, zs_pack({'a': b'AAA', 'b': orig['b']}, dic))
        _put(mods, '02-B', rel, zs_pack({'a': b'BBB', 'b': orig['b']}, dic))
        done = pack_merge.build(mods, ['01-A', '02-B'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert done['written'] == [] and done['clashes'] == [(rel, 'a', '01-A', '02-B')]
        assert not (mods / pack_merge.FOLDER).exists()
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp)
        good, bad = 'Pack/Good.pack.zs', 'Pack/Bad.pack.zs'
        base = {'a': orig['a'], 'b': orig['b']}
        _put(mods, '01-A', good, zs_pack({'a': b'AAA', 'b': orig['b']}, dic))
        _put(mods, '02-B', good, zs_pack({'a': orig['a'], 'b': b'BBB'}, dic))
        _put(mods, '01-A', bad, b'not a pack')
        _put(mods, '02-B', bad, b'also not')
        done = pack_merge.build(mods, ['01-A', '02-B'], rom=_dict_rom(dic, {good: base}), log=lambda _s: None)
        assert done['written'] == [good]
        assert any(path == bad for path, _why in done['skipped'])
        assert open_pack((mods / pack_merge.FOLDER / 'romfs' / good).read_bytes(), dic) == {'a': b'AAA', 'b': b'BBB'}
        # no dictionary: Save fails, and a merged folder already there is left untouched
        junk = mods / pack_merge.FOLDER / 'romfs' / 'junk.txt'
        junk.write_bytes(b'keep')
        bare = Rom({good: zs_pack(base, dic)})
        try:
            pack_merge.build(mods, ['01-A', '02-B'], rom=bare, log=lambda _s: None)
        except ValueError as err:
            assert 'dictionary' in str(err)
        else:
            raise AssertionError('missing dictionary')
        assert junk.read_bytes() == b'keep'
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp)
        # measured alignment below 8 is raised to 8, which still satisfies a 4-byte start
        four = nxsave.write_sarc({'a': b'1', 'b': b'22'}, alignment=4)
        assert nxsave.sarc_alignment(four) == 4
        _put(mods, '01-A', rel, zstd.compress(nxsave.write_sarc({'a': b'ZZ', 'b': b'22'}, alignment=4),
                                              level=19, zstd_dict=dic))
        _put(mods, '02-B', rel, zstd.compress(nxsave.write_sarc({'a': b'1', 'b': b'22'}, alignment=4),
                                              level=19, zstd_dict=dic))
        files = {rel: zstd.compress(four, level=19, zstd_dict=dic),
                 'Pack/ZsDic.pack.zs': zstd.compress(nxsave.write_sarc({'pack.zsdic': dic.dict_content}))}
        pack_merge.build(mods, ['01-A', '02-B'], rom=Rom(files), log=lambda _s: None)
        raw = zstd.decompress((mods / pack_merge.FOLDER / 'romfs' / rel).read_bytes(), zstd_dict=dic)
        assert all(s % 8 == 0 for s in file_starts(raw))
        # B still has the original 'a', so A's change is the one that survives
        assert nxsave.sarc_members(raw)['a'] == b'ZZ'
    print('ok skip, remove, order')


def test_list_hides_loader_folders():
    mod_loader = load_pyw('mod_loader')
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp)
        for name in ('01-A', '_B', '~Merged Packs', '~Size Table', '03-C.old'):
            (mods / name / 'romfs').mkdir(parents=True)
        old = mod_loader.MODS
        mod_loader.MODS = mods
        try:
            assert [m.folder for m in mod_loader.scan()] == ['01-A', '_B']
        finally:
            mod_loader.MODS = old
    assert nxsave.VERSION == '1.4.0'
    print('ok list')


def byml_doc(obj):
    """A small BYML 7 writer for the tests (dicts, lists, texts, bools), laid out root first, children after."""
    keys, texts = set(), set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                keys.add(k)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            texts.add(o)
    walk(obj)
    keys, texts = sorted(keys), sorted(texts)
    kt, tt = pack_merge._text_table(keys), pack_merge._text_table(texts)
    out = bytearray(b'YB' + struct.pack('<HIII', 7, 16, 16 + len(kt), 16 + len(kt) + len(tt)) + kt + tt)

    def value(v):
        if isinstance(v, dict):
            return 0xc1, put(v)
        if isinstance(v, list):
            return 0xc0, put(v)
        if isinstance(v, bool):
            return 0xd0, int(v)
        return 0xa0, texts.index(v)

    def put(o):
        at = len(out)
        if isinstance(o, dict):
            items = sorted(o.items(), key=lambda kv: keys.index(kv[0]))
            out.extend(bytes([0xc1]) + len(items).to_bytes(3, 'little') + bytes(8 * len(items)))
            for i, (k, v) in enumerate(items):
                t, val = value(v)
                p = at + 4 + 8 * i
                out[p:p + 8] = keys.index(k).to_bytes(3, 'little') + bytes([t]) + struct.pack('<I', val)
        else:
            n = len(o)
            vals_at = at + 4 + ((n + 3) & ~3)
            out.extend(bytes([0xc0]) + n.to_bytes(3, 'little') + bytes(((n + 3) & ~3) + 4 * n))
            for i, v in enumerate(o):
                t, val = value(v)
                out[at + 4 + i] = t
                struct.pack_into('<I', out, vals_at + 4 * i, val)
        return at
    put(obj)
    return bytes(out)


def test_follow_animation_lists():
    """A costume mod points the actor at its own animation list; another mod added sets to the actor's own list:
    the added sets go into the list now used (first, retargeted like that list's own), merged or not."""
    AP = 'Actor/P.engine__actor__ActorParam.bgyml'
    OWN = 'Component/AnimationParam/P.engine__component__AnimationParam.bgyml'
    COS = 'Component/AnimationParam/P_Cos.engine__component__AnimationParam.bgyml'
    actor = lambda ref: byml_doc({'Components': {'AnimationRef': '?' + ref, 'ModelInfoRef': '?Component/M.bgyml'}})
    sets = lambda *names: pack_merge.write_anim_list([{'ModelProjectName': n} for n in names])
    cos = pack_merge.write_anim_list([{'IsRetarget': True, 'ModelProjectName': 'Cos_01', 'RetargetModel': 'Skeleton'},
                                      {'ModelProjectName': 'Cos_Npc'}])
    assert nxsave.byml(actor(OWN)) == {'Components': {'AnimationRef': '?' + OWN, 'ModelInfoRef': '?Component/M.bgyml'}}
    assert [e['ModelProjectName'] for e in nxsave.byml(cos)['AnimationResources']] == ['Cos_01', 'Cos_Npc']
    orig = {AP: actor(OWN), OWN: sets('G_01', 'G_02'), 'x': b'game x'}
    adult = {AP: actor(OWN), OWN: sets('Adu_01', 'Adu_02', 'G_01', 'G_02'), 'x': b'game x'}   # (adult sets first)
    costume = {AP: actor(COS), OWN: sets('G_01', 'G_02'), COS: cos, 'x': b'game x'}
    # the function alone: first, retargeted like Cos_01; the list's own entries kept as they were
    both = {AP: actor(COS), OWN: adult[OWN], COS: cos, 'x': b'game x'}
    got, notes = pack_merge.follow_animation_lists(both, orig)
    assert notes == [(AP, COS, ['Adu_01', 'Adu_02'])], notes
    assert nxsave.byml(got[COS])['AnimationResources'] == [
        {'IsRetarget': True, 'ModelProjectName': 'Adu_01', 'RetargetModel': 'Skeleton'},
        {'IsRetarget': True, 'ModelProjectName': 'Adu_02', 'RetargetModel': 'Skeleton'},
        {'IsRetarget': True, 'ModelProjectName': 'Cos_01', 'RetargetModel': 'Skeleton'},
        {'ModelProjectName': 'Cos_Npc'}]
    assert {k: v for k, v in got.items() if k != COS} == {k: v for k, v in both.items() if k != COS}
    # sets a mod put after the game's own go after the list's own; nothing to do when the actor keeps its own list
    after = dict(both, **{OWN: sets('G_01', 'G_02', 'Adu_01')})
    got, _n = pack_merge.follow_animation_lists(after, orig)
    assert [e['ModelProjectName'] for e in nxsave.byml(got[COS])['AnimationResources']] == ['Cos_01', 'Cos_Npc', 'Adu_01']
    assert pack_merge.follow_animation_lists(adult, orig) == (adult, [])
    assert pack_merge.follow_animation_lists(got, orig)[1] == []          # (done once: not added twice)
    dic = train([b'alpha' * 30, b'beta' * 30, OWN.encode() * 20, b'Skeleton' * 20])
    rel = 'Pack/Actor/P.pack.zs'
    skel = lambda name: zstd.compress(b'FRES skeleton of ' + name.encode() + b' bones' * 20, level=19, zstd_dict=dic)
    sk = lambda name: pack_merge.skeleton_file(name)
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp)
        # two mods, separate packs: merged (adult's list, costume's switch) and followed; each added set gets a
        # skeleton file of its own, the costume's renamed (the game never finishes loading Link without one)
        _put(mods, '01-Costume', rel, zs_pack(costume, dic))
        _put(mods, '01-Costume', sk('Cos_01'), skel('Cos_01'))
        _put(mods, '02-Adult', rel, zs_pack(adult, dic))
        done = pack_merge.build(mods, ['01-Costume', '02-Adult'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert done['clashes'] == [] and sorted(done['written']) == sorted([rel, sk('Adu_01'), sk('Adu_02')]), done
        assert [(f[2], f[3]) for f in done['followed']] == [(COS, ['Adu_01', 'Adu_02'])]
        m = open_pack((mods / pack_merge.FOLDER / 'romfs' / rel).read_bytes(), dic)
        assert m[AP] == costume[AP] and m[OWN] == adult[OWN]
        assert [e['ModelProjectName'] for e in nxsave.byml(m[COS])['AnimationResources']] == [
            'Adu_01', 'Adu_02', 'Cos_01', 'Cos_Npc']
        made = zstd.decompress((mods / pack_merge.FOLDER / 'romfs' / sk('Adu_02')).read_bytes(), zstd_dict=dic)
        assert made == b'FRES skeleton of Adu_02' + b' bones' * 20, made
    with tempfile.TemporaryDirectory() as tmp:
        mods = Path(tmp)
        # one mod already carrying both changes (one combined pack): written although nothing else needs a merge
        _put(mods, '01-Both', rel, zs_pack(both, dic))
        _put(mods, '01-Both', sk('Cos_01'), skel('Cos_01'))
        done = pack_merge.build(mods, ['01-Both'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert rel in done['written'] and done['clashes'] == []
        # and a pack one mod carries that is not readable is left as it is, quietly
        _put(mods, '02-Odd', 'Pack/Actor/Q.pack.zs', b'not a pack')
        done = pack_merge.build(mods, ['01-Both', '02-Odd'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert done['skipped'] == [] and rel in done['written']
        # a set that has a skeleton already (the game's here): listed, no file made for it
        rom = _dict_rom(dic, {rel: orig})
        rom = Rom(dict(rom._files, **{sk('Adu_01'): skel('Adu_01')}))
        done = pack_merge.build(mods, ['01-Both'], rom=rom, log=lambda _s: None)
        assert sorted(done['written']) == sorted([rel, sk('Adu_02')]), done
        # no skeleton to make one from (a name of another length, or none at all): the set is left out, so the
        # list stays as the costume's and nothing is written
        (mods / '01-Both' / 'romfs' / sk('Cos_01')).unlink()
        done = pack_merge.build(mods, ['01-Both'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert done['written'] == [] and done['followed'] == [], done
        # an actor that keeps its own list: nothing written, no folder
        shutil.rmtree(mods)
        mods.mkdir()
        _put(mods, '01-Adult', rel, zs_pack(adult, dic))
        done = pack_merge.build(mods, ['01-Adult'], rom=_dict_rom(dic, {rel: orig}), log=lambda _s: None)
        assert done['written'] == [] and not (mods / pack_merge.FOLDER).exists()
    print('ok animation lists follow a switched model')


def main():
    test_sarc_writer()
    test_merge_members()
    test_save_merges()
    test_skip_remove_order()
    test_list_hides_loader_folders()
    test_follow_animation_lists()
    print('all pack merge tests passed')


if __name__ == '__main__':
    main()
