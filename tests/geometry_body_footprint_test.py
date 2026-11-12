"""Original ALD/AST source-scanner tests; no translator, Vulkan or game runs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

import geometry_shader_fixture as original

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import geometry_body_footprint as footprint


def program(words):
    return original.geometry_header('triangle_strip', 1, 1) + original.framed(words)


def scan(words, **changes):
    data = program(words)
    return footprint.analyze(data, code_end=len(data), c1_end=len(data), **changes)


def mask(*components):
    result = [0] * 8
    for component in components:
        result[component // 32] |= 1 << (component % 32)
    return result


class SourceFootprint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = footprint.output_path(args.out)
        cls.out.mkdir(parents=True, exist_ok=False)

    def test_independent_literal_fields_and_combined_masks(self):
        # Independent fixed words, not assembled using the scanner's masks.
        # ALD32 R4, Position.x, vertexRZ; AST32 user31.w fromR8, Ra/Rc=RZ.
        ald = 0xefd87f800707ff04
        ast = 0xeff07f8027c7ff08
        self.assertEqual(original.ald(4, 0x70, 255, 1), ald)
        self.assertEqual(original.ast(8, 0x27c, 1), ast)
        result = scan([ald, ast, original.EXIT])
        self.assertEqual(result['masks']['input_read'], mask(28))
        self.assertEqual(result['masks']['output_write'], mask(159))
        self.assertEqual(result['masks']['output_read'], mask())
        self.assertEqual((result['counts']['ald'], result['counts']['ast']), (1, 1))
        self.assertEqual(result['counts']['zero_vertex_selector_sites'], 1)
        self.assertTrue(result['ald_ast_address_coverage_known'])
        self.assertFalse(result['unsupported'])

    def test_all_four_sizes_position_and_user_domain_crossings(self):
        for words in range(1, 5):
            with self.subTest(words=words):
                result = scan([original.ald(0, 0x70, 255, words)])
                self.assertEqual(result['masks']['input_read'], mask(*range(28, 28 + words)))
        position_user = scan([original.ald(0, 0x7c, 255, 2)])
        self.assertEqual(position_user['masks']['input_read'], mask(31, 32))
        self.assertEqual(position_user['projections']['input_read']['position_components'], 8)
        self.assertEqual(position_user['projections']['input_read']['user_components'][0], 1)
        user_legacy = scan([original.ast(0, 0x27c, 2)])
        self.assertEqual(user_legacy['masks']['output_write'], mask(159, 160))
        self.assertEqual(user_legacy['projections']['output_write']['user_locations'], 1 << 31)

    def test_scheduler_slots_excluded_by_position_not_contents(self):
        words = [original.ald(0, 0x270, 255), original.ast(0, 0x70), original.EXIT, 0,
                 original.ast(0, 0x2c0), original.ald(0, 0xe0, 255), 0, original.EXIT]
        data = original.geometry_header('triangle_strip', 1, 1) + struct.pack('<8Q', *words)
        result = footprint.analyze(data, code_end=len(data), c1_end=len(data))
        self.assertEqual(result['counts']['scheduler_words'], 2)
        self.assertEqual((result['counts']['ald'], result['counts']['ast']), (1, 1))
        self.assertEqual(result['masks']['input_read'], mask(56, 57, 58, 59))
        self.assertEqual(result['masks']['output_write'], mask(28, 29, 30, 31))

    def test_constant_tail_and_bytes_after_declared_end_not_scanned(self):
        code = program([original.EXIT])
        constants = struct.pack('<QQ', 0xefd87f800707ff04, 0xeff07f8027c7ff08)
        data = code + constants + constants
        result = footprint.analyze(data, code_end=len(code), c1_end=len(code) + len(constants), context='original')
        self.assertTrue(all(values == mask() for values in result['masks'].values()))
        self.assertEqual(result['source_sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['declared_source_sha256'], hashlib.sha256(code + constants).hexdigest())
        self.assertEqual(result['bounds']['code_end'], len(code))
        self.assertEqual(result['context'], 'original')

    def test_c1_byte_lengths_are_opaque_and_never_instruction_slots(self):
        code = program([original.EXIT])
        attribute_bytes = struct.pack('<Q', 0xefd87f800707ff04)
        for length in (1, 2, 3, 4, 9):
            with self.subTest(c1_bytes=length):
                constants = (attribute_bytes + b'\x5a')[:length]
                data = code + constants
                result = footprint.analyze(data, code_end=len(code), c1_end=len(data))
                self.assertEqual(result['bounds']['c1_end'], len(data))
                self.assertEqual(result['counts']['ald'], 0)
                self.assertEqual(result['counts']['ast'], 0)
                self.assertTrue(all(values == mask() for values in result['masks'].values()))
                self.assertEqual(result['source_sha256'], hashlib.sha256(data).hexdigest())
        source = self.out / 'original-four-byte-c1.code'
        source.write_bytes(code + struct.pack('<I', 0x12345678))
        destination = self.out / 'four-byte-c1.json'
        run = self.cli(source, destination, '--code-end', hex(len(code)))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(destination.read_text())['bounds']['code_end'], len(code))

    def test_predicated_and_unreachable_words_remain_may_accesses(self):
        predicated = original.ald(0, 0x80, 255, 1) & ~(7 << 16)
        never = original.ast(0, 0x74, 1) | (1 << 19)  # negatedPT
        result = scan([original.EXIT, predicated, never])
        self.assertEqual(result['counts']['predicated_attribute_sites'], 2)
        self.assertEqual(result['masks']['input_read'], mask(32))
        self.assertEqual(result['masks']['output_write'], mask(29))
        self.assertFalse(result['complete_shader_io'])

    def test_vertex_register_is_not_constant_propagated(self):
        result = scan([original.movi(12, 2), original.ald(0, 0x70, 12), original.ald(4, 0x80, 255)])
        self.assertEqual(result['counts']['dynamic_vertex_selector_sites'], 1)
        self.assertEqual(result['counts']['zero_vertex_selector_sites'], 1)
        self.assertEqual(result['counts']['dynamic_attribute_address_sites'], 0)
        self.assertTrue(result['ald_ast_address_coverage_known'])
        invocation = scan([original.ald(0, 0x60, 12, 1)])
        self.assertEqual(invocation['counts']['non_vertex_selector_sites'], 1)
        self.assertEqual(invocation['counts']['dynamic_vertex_selector_sites'], 0)

    def test_output_read_mode_has_its_own_space(self):
        # Literal ALD.O32 Position.x with RZ Ra/vertex selector.
        result = scan([0xefd87f810707ff04])
        self.assertEqual(result['counts']['output_read_sites'], 1)
        self.assertEqual(result['masks']['output_read'], mask(28))
        self.assertEqual(result['masks']['input_read'], mask())
        self.assertEqual(result['counts']['non_vertex_selector_sites'], 1)
        fallback = scan([original.ald(0, 0x2f0, 255, 1) | 1 << 32])
        self.assertTrue(fallback['unsupported'])
        self.assertEqual(fallback['masks']['input_read'], footprint.ALL)
        self.assertEqual(fallback['masks']['output_read'], footprint.ALL)

    def test_physical_and_other_register_addresses_require_all(self):
        for address, physical in ((0, 1), (0x80, 0)):
            with self.subTest(address=address):
                word = original.ald(0, address, 4, 1) & ~(255 << 8) | (3 << 8)
                result = scan([word])
                self.assertEqual(result['counts']['physical_address_sites'], physical)
                self.assertEqual(result['counts']['dynamic_attribute_address_sites'], 1)
                self.assertEqual(result['counts']['dynamic_vertex_selector_sites'], 1)
                self.assertEqual(result['masks']['input_read'], footprint.ALL)
                self.assertTrue(result['unknown']['input_read'])
                self.assertFalse(result['ald_ast_address_coverage_known'])
        store = scan([original.ast(0, 0, 1) & ~(255 << 8) | (3 << 8)])
        self.assertEqual(store['masks']['output_write'], footprint.ALL)
        self.assertEqual(store['masks']['input_read'], mask())

    def test_per_patch_auxiliary_and_data_register_modes_are_explicit(self):
        for word, space in ((original.ald(0, 0x20, 3, 1) | (1 << 31), 'input_read'),
                            (original.ast(0, 0x20, 1) | (1 << 31), 'output_write')):
            result = scan([word])
            self.assertEqual(result['counts']['per_patch_sites'], 1)
            self.assertEqual(result['masks'][space], footprint.ALL)
            self.assertTrue(result['unsupported'])
        auxiliary = scan([original.ast(0, 0x80, 1) & ~(255 << 39) | (3 << 39)])
        self.assertEqual(auxiliary['counts']['unsupported_auxiliary_selector_sites'], 1)
        self.assertEqual(auxiliary['masks']['output_write'], footprint.ALL)
        registers = scan([original.ald(254, 0x80, 255, 4)])
        self.assertEqual(registers['counts']['unsupported_register_span_sites'], 1)
        self.assertEqual(registers['masks']['input_read'], footprint.ALL)

    def test_unaudited_mode_bits_never_claim_known_coverage(self):
        for word, space in ((original.ald(0, 0x70, 255, 1) | 1 << 33, 'input_read'),
                            (original.ast(0, 0x80, 1) | 1 << 32, 'output_write')):
            with self.subTest(space=space):
                result = scan([word])
                self.assertEqual(result['counts']['unrecognized_mode_sites'], 1)
                self.assertTrue(result['unknown'][space])
                self.assertEqual(result['masks'][space], footprint.ALL)
                self.assertFalse(result['ald_ast_address_coverage_known'])

    def test_unaligned_and_out_of_range_spans_cannot_disappear(self):
        for address, words, flag in ((0x71, 1, 'misaligned_address_sites'),
                                      (0x3fc, 2, 'out_of_range_address_sites'),
                                      (0x400, 1, 'out_of_range_address_sites')):
            with self.subTest(address=address, words=words):
                result = scan([original.ald(0, address, 255, words)])
                self.assertEqual(result['counts'][flag], 1)
                self.assertEqual(result['masks']['input_read'], footprint.ALL)
                self.assertTrue(result['unsupported'])
        last = scan([original.ald(0, 0x3fc, 255, 1)])
        self.assertEqual(last['masks']['input_read'], mask(255))

    def test_non_attribute_instructions_do_not_claim_shader_completeness(self):
        result = scan([original.movi(0, 0x12345678), original.EXIT])
        self.assertEqual((result['counts']['ald'], result['counts']['ast']), (0, 0))
        self.assertEqual(result['counts']['other_words'], 3)
        self.assertFalse(result['complete_shader_io'])
        self.assertEqual(result['masks']['input_read'], mask())

    def test_invalid_headers_bounds_and_truncated_words_reject(self):
        data = program([original.EXIT])
        for word0 in (0, 1 | (4 << 5) | (4 << 10), 1 | (3 << 5) | (1 << 10)):
            changed = bytearray(data)
            struct.pack_into('<I', changed, 0, word0)
            with self.subTest(header=word0), self.assertRaises(ValueError):
                footprint.analyze(changed, code_end=len(data), c1_end=len(data))
        for end, c1 in ((80, 80), (len(data) - 1, len(data)), (len(data), len(data) + 8),
                         (len(data), len(data) - 8), (True, len(data)), (len(data), False), (-8, len(data))):
            with self.subTest(code_end=end, c1_end=c1), self.assertRaises(ValueError):
                footprint.analyze(data, code_end=end, c1_end=c1)
        for short in (data[:79], data[:-1]):
            with self.assertRaises(ValueError):
                footprint.analyze(short, code_end=len(data), c1_end=len(data))
        with self.assertRaises(ValueError):
            footprint.analyze(data + bytes(8), code_end=len(data) + 8, c1_end=len(data) + 8)
        with self.assertRaises(ValueError):
            footprint.analyze(data + bytes(9), code_end=len(data) + 1, c1_end=len(data) + 9)

    def test_omission_and_opcode_misdecode_controls_fail_the_same_oracle(self):
        required = mask(56)
        full = scan([original.ald(0, 0xe0, 255, 1)])
        self.assertEqual(full['masks']['input_read'], required)
        for word in (original.EXIT, original.ald(0, 0xe0, 255, 1) ^ (1 << 63)):
            with self.subTest(control=word), self.assertRaises(AssertionError):
                self.assertEqual(scan([word])['masks']['input_read'], required)

    def cli(self, code, out, *extra):
        return subprocess.run([sys.executable, str(ROOT / 'tools/geometry_body_footprint.py'),
                               '--code', str(code), '--code-end', hex(len(code.read_bytes())),
                               '--c1-end', hex(len(code.read_bytes())), '--out', str(out), *extra],
                              capture_output=True, text=True, timeout=15)

    def test_cli_build_only_exclusive_output_and_invalid_input(self):
        source = self.out / 'original.code'
        source.write_bytes(program([original.ald(0, 0x70, 255, 1)]))
        destination = self.out / 'source-metadata.json'
        run = self.cli(source, destination)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(report['masks']['input_read'], mask(28))
        self.assertNotIn('efd8', destination.read_text(encoding='utf-8'))
        saved = destination.read_bytes()
        self.assertEqual(self.cli(source, destination).returncode, 2)
        self.assertEqual(destination.read_bytes(), saved)
        outside = ROOT / 'footprint-output-outside-build.json'
        self.assertEqual(self.cli(source, outside).returncode, 2)
        self.assertFalse(outside.exists())
        native = self.out / 'native-version.code'
        data = bytearray(source.read_bytes())
        struct.pack_into('<I', data, 0, 1 | (4 << 5) | (4 << 10))
        native.write_bytes(data)
        rejected = self.out / 'rejected.json'
        self.assertEqual(self.cli(native, rejected).returncode, 2)
        self.assertFalse(rejected.exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args, rest = parser.parse_known_args()
    result = unittest.main(argv=[__file__] + rest, exit=False).result
    if args.out.is_dir():
        evidence = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                        tool_sha256=hashlib.sha256((ROOT / 'tools/geometry_body_footprint.py').read_bytes()).hexdigest(),
                        test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), gpu_executed=False,
                        scope='Original Maxwell-v3 GS source ALD/AST; no compiler/native/GPU execution.')
        (args.out / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())
