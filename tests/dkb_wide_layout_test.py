"""Synthetic layout/animation regression tests; no extracted game content."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import zstandard
from dkb_wide_layout import HUD_ANCHORS, members, patch_archive, patch_title_effect


def archive(entries):
    names, nodes, payload = bytearray(), bytearray(), bytearray()
    for name, content in entries:
        offset = len(names) // 4
        names.extend(name.encode() + b'\0')
        names.extend(b'\0' * (-len(names) % 4))
        nodes.extend(struct.pack('<4I', 0, 0x1000000 | offset, len(payload), len(payload) + len(content)))
        payload.extend(content)
    start = 20 + 12 + len(nodes) + 8 + len(names)
    header = b'SARC' + struct.pack('<HHIII', 20, 0xfeff, start + len(payload), start, 0x100)
    raw = header + b'SFAT' + struct.pack('<HHI', 12, len(entries), 0x65) + nodes
    raw += b'SFNT' + struct.pack('<HH', 8, 0) + names + payload
    return zstandard.ZstdCompressor().compress(raw)


def layout_header(magic, sections):
    return magic + struct.pack('<HHIIHH', 0xfeff, 20, 0, 20 + sum(map(len, sections)), len(sections), 0) + b''.join(sections)


def pane(name, x):
    p = bytearray(84)
    p[:4] = b'pan1'
    struct.pack_into('<I', p, 4, len(p))
    p[12:12 + len(name)] = name.encode()
    struct.pack_into('<10f', p, 44, x, 472, 0, 0, 0, 0, 1, 1, 100, 100)
    return p


def animation(name):
    section = bytearray(24)
    section[:4] = b'pai1'
    struct.pack_into('<HII', section, 14, 1, 20, 24)
    entry = bytearray(36)
    entry[:len(name)] = name.encode()
    entry[28] = 1
    struct.pack_into('<I', entry, 32, 36)
    tag = bytearray(12)
    tag[:4], tag[4] = b'FLPA', 1
    struct.pack_into('<I', tag, 8, 12)
    curve = bytearray(12)
    curve[2] = 2  # Hermite X translation, two keys with nonzero tangents.
    struct.pack_into('<H', curve, 4, 2)
    struct.pack_into('<I', curve, 8, 12)
    section += entry + tag + curve + struct.pack('<6f', 0, -905, 2, 15, -885, -2)
    struct.pack_into('<I', section, 4, len(section))
    return layout_header(b'FLAN', [section])


def fixture(omit=None, wrong=False):
    panes = [pane('Unrelated', 123)]
    for name, (x, _) in HUD_ANCHORS['HudStatus'].items():
        if name != omit:
            panes.append(pane(name, x + (1 if wrong else 0)))
    return archive([('blyt/HudStatus.bflyt', layout_header(b'FLYT', panes)),
                    ('anim/Appear.bflan', animation('N_Hp_00')),
                    ('untouched.bin', b'opaque data stays identical')])


def unpack(raw):
    d = zstandard.ZstdDecompressor().decompress(raw)
    return {name: d[lo:hi] for name, lo, hi in members(d)}


class LayoutTests(unittest.TestCase):
    def test_edges_translate_without_scaling_or_changing_animation_tangents(self):
        original = unpack(fixture())
        moved = unpack(patch_archive(fixture(), 'HudStatus', 3440 / 1440 / (16 / 9), True))
        before, after = original['blyt/HudStatus.bflyt'], moved['blyt/HudStatus.bflyt']
        self.assertEqual(before[:104], after[:104])  # Header and unrelated pane.
        for at in range(104, len(before), 84):
            self.assertAlmostEqual(struct.unpack_from('<f', after, at + 44)[0],
                                   struct.unpack_from('<f', before, at + 44)[0] - 330)
            self.assertEqual(before[at:at + 44], after[at:at + 44])
            self.assertEqual(before[at + 48:at + 84], after[at + 48:at + 84])
        self.assertEqual(moved['untouched.bin'], original['untouched.bin'])
        self.assertEqual(moved['anim/Appear.bflan'][:-24], original['anim/Appear.bflan'][:-24])
        self.assertEqual(struct.unpack('<6f', moved['anim/Appear.bflan'][-24:]), (0, -1235, 2, 15, -1215, -2))

    def test_centered_and_identity_preserve_every_byte(self):
        original = unpack(fixture())
        self.assertEqual(unpack(patch_archive(fixture(), 'HudStatus', 2, False)), original)
        self.assertEqual(unpack(patch_archive(fixture(), 'HudStatus', 1, True)), original)

    def test_unknown_layout_revision_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'baseline'):
            patch_archive(fixture(wrong=True), 'HudStatus', 2, True)
        with self.assertRaisesRegex(ValueError, 'missing panes'):
            patch_archive(fixture(omit='N_Hp_00'), 'HudStatus', 2, True)

    def test_status_indicators_move_only_final_anchors(self):
        for name in ('Saving', 'Loading'):
            panes = [pane('N_Capture_00', 0), pane('P_IcnSdw_00', 0)]
            panes += [pane(n, x) for n, (x, _) in HUD_ANCHORS[name].items()]
            file = f'blyt/{name}.bflyt'
            raw = archive([(file, layout_header(b'FLYT', panes))])
            before = unpack(raw)[file]
            for factor in (3440 / 2560, 2):
                with self.subTest(layout=name, factor=factor):
                    self.assertEqual(unpack(patch_archive(raw, name, factor, False))[file], before)
                    after = unpack(patch_archive(raw, name, factor, True))[file]
                    expected = bytearray(before)
                    for i, (_, (x, side)) in enumerate(HUD_ANCHORS[name].items()):
                        struct.pack_into('<f', expected, 20 + (i + 2) * 84 + 44,
                                         x + side * 960 * (factor - 1))
                    self.assertEqual(after, expected)


def title_effect():
    # Minimal synthetic container with the same bounded emitter links. Include
    # an unrelated particle and a string-table name to catch overly broad edits.
    data = bytearray(b'YB\x05\x00' + b'BootMenuEnv\0' + bytes(241))
    start = len(data)
    data.extend(bytes(0x80))
    data[start:start + 4] = b'ESET'
    data[start + 0x30:start + 0x3c] = b'BootMenuEnv\0'
    struct.pack_into('<I', data, start + 8, 0x80)
    for i, name in enumerate((b'Wall', b'Debris', b'Atmos')):
        pos = len(data)
        data.extend(bytes(0x1000))
        data[pos:pos + 4] = b'EMTR'
        struct.pack_into('<5I', data, pos + 4, 0x1000, 0xffffffff,
                         0x1000 if i < 2 else 0xffffffff, 0xffffffff, 0x20)
        data[pos + 0x30:pos + 0x30 + len(name)] = name
        struct.pack_into('<3f', data, pos + 0x20 + 0xfa0, 16, 9, 1)
    struct.pack_into('<I', data, start + 4, len(data) - start)
    return data, start


class TitleEffectTests(unittest.TestCase):
    def test_only_wall_and_haze_scale_uniformly(self):
        original, start = title_effect()
        raw = zstandard.ZstdCompressor().compress(original)
        for factor in (1, 3440 / 2560, 2):
            changed = zstandard.ZstdDecompressor().decompress(patch_title_effect(raw, factor))
            expected = original.copy()
            for i in (0, 2):
                struct.pack_into('<2f', expected, start + 0x80 + i * 0x1000 + 0x20 + 0xfa0,
                                 16 * factor, 9 * factor)
            self.assertEqual(changed, expected)

    def test_unknown_and_malformed_emitters_fail_closed(self):
        for fault in ('scale', 'bounds', 'sibling', 'missing'):
            data, start = title_effect()
            first = start + 0x80
            if fault == 'scale':
                struct.pack_into('<f', data, first + 0x20 + 0xfa0, 17)
            elif fault == 'bounds':
                struct.pack_into('<I', data, first + 0x14, 0xfffffff0)
            elif fault == 'sibling':
                struct.pack_into('<I', data, first + 0xc, 0)
            else:
                data[first + 0x2000 + 0x30] = ord('X')
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                patch_title_effect(zstandard.ZstdCompressor().compress(data), 2)


if __name__ == '__main__':
    unittest.main()
