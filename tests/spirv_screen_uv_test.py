"""A fragment module through the real spirv_screen_uv (runtime/spirv_screen_uv.c), checked with spirv-val. No Vulkan, GPU
or game runs.

The module has the layout the rewrite expects: two NoPerspective vec4 inputs at Locations 0 and 1 read per component
through access chains, one sampled 2D image, and a c3-style uniform block read at [0][14]. It checks that the four
input reads become OpCopyObject, that FragCoord and one size query are added, that the result passes spirv-val, and
that a 2D-array image and a read outside the entry function are refused. It does not execute the shaders.
"""
import argparse
from pathlib import Path
import struct
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
OP_LOAD, OP_DECORATE, OP_COPY_OBJECT, OP_IMAGE_QUERY_SIZE_LOD = 61, 71, 83, 103
DEC_BUILTIN, BUILTIN_FRAG_COORD = 11, 15


def instr(op, *words):
    return [(len(words) + 1) << 16 | op, *words]


def string(s):
    b = s.encode() + b'\0'
    b += b'\0' * (-len(b) % 4)
    return list(struct.unpack(f'<{len(b) // 4}I', b))


def module(arrayed=False, helper=False):
    """Ids are fixed. With helper, a function ahead of main reads Location 1 through its own access chain."""
    (MAIN, HELPER, VOID, FN, F32, I32, V4, IMG, SIMG, PSIMG, TEX, PIN, UV, RAY, POUT, OUT, ARR, STRUCT, PUNI, UBO, PUF,
     PINF, K0, K1, K14, K32, *V) = range(1, 100)
    w = [0x07230203, 0x00010300, 0, 100, 0]
    w += instr(17, 1) + instr(17, 50)                                    # Shader, ImageQuery
    w += instr(11, 99, *string('GLSL.std.450'))
    w += instr(14, 0, 1)
    w += instr(15, 4, MAIN, *string('main'), UV, RAY, OUT) + instr(16, MAIN, 7)
    w += instr(71, UV, 30, 1) + instr(71, UV, 13) + instr(71, RAY, 30, 0) + instr(71, RAY, 13) + instr(71, OUT, 30, 0)
    w += instr(71, TEX, 34, 0) + instr(71, TEX, 33, 0) + instr(71, UBO, 34, 0) + instr(71, UBO, 33, 1)
    w += instr(71, ARR, 6, 16) + instr(71, STRUCT, 2) + instr(72, STRUCT, 0, 35, 0)
    w += instr(19, VOID) + instr(33, FN, VOID) + instr(22, F32, 32) + instr(21, I32, 32, 1) + instr(23, V4, F32, 4) + instr(23, V[50], F32, 2)
    w += instr(25, IMG, F32, 1, 0, int(arrayed), 0, 1, 0) + instr(27, SIMG, IMG)
    w += instr(32, PSIMG, 0, SIMG) + instr(59, PSIMG, TEX, 0)
    w += instr(32, PIN, 1, V4) + instr(59, PIN, UV, 1) + instr(59, PIN, RAY, 1)
    w += instr(32, POUT, 3, V4) + instr(59, POUT, OUT, 3)
    w += instr(43, I32, K0, 0) + instr(43, I32, K1, 1) + instr(43, I32, K14, 14) + instr(43, I32, K32, 32)
    w += instr(28, ARR, V4, K32) + instr(30, STRUCT, ARR) + instr(32, PUNI, 2, STRUCT) + instr(59, PUNI, UBO, 2)
    w += instr(32, PUF, 2, F32) + instr(32, PINF, 1, F32)
    if helper:
        w += instr(54, VOID, HELPER, 0, FN) + instr(248, V[0])
        w += instr(65, PINF, V[1], UV, K0) + instr(OP_LOAD, F32, V[2], V[1]) + instr(253) + instr(56)
    w += instr(54, VOID, MAIN, 0, FN) + instr(248, V[10])
    loads = []
    for n, (var, k) in enumerate([(UV, K0), (UV, K1), (RAY, K0), (RAY, K1)]):
        w += instr(65, PINF, V[20 + n], var, k) + instr(OP_LOAD, F32, V[30 + n], V[20 + n])
        loads.append(V[30 + n])
    w += instr(65, PUF, V[40], UBO, K0, K14, K0) + instr(OP_LOAD, F32, V[41], V[40])
    w += instr(80, V4, V[42], *loads) + instr(62, OUT, V[42]) + instr(253) + instr(56)
    return w


def ops(words):
    i, out = 5, []
    while i < len(words):
        n = words[i] >> 16
        out.append((words[i] & 0xffff, words[i + 1:i + n]))
        i += n
    return out


class ScreenUv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        args.out.mkdir(parents=True, exist_ok=False)
        harness = args.out / 'harness.c'
        harness.write_text(r'''#include <stdio.h>
#include <stdlib.h>
#include "spirv_screen_uv.h"
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    static uint32_t w[1 << 20];
    FILE *f = fopen(argv[1], "rb");
    size_t n = fread(w, 4, 1 << 20, f);
    fclose(f);
    uint64_t out_n = 0;
    uint32_t *o = spirv_screen_uv(w, n, &out_n);
    if (!o) return 3;
    f = fopen(argv[2], "wb");
    fwrite(o, 4, out_n, f);
    fclose(f);
    free(o);
    return 0;
}
''', encoding='utf-8')
        cls.exe = args.out / 'harness.exe'
        subprocess.run([str(args.cc), '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'runtime'), str(harness),
                        str(ROOT / 'runtime/spirv_screen_uv.c'), '-o', str(cls.exe)], check=True, capture_output=True,
                       text=True, timeout=120)

    def rewrite(self, name, words, validate=True):
        src = args.out / (name + '.in.spv')
        dst = args.out / (name + '.out.spv')
        src.write_bytes(struct.pack(f'<{len(words)}I', *words))
        if validate:
            pre = subprocess.run([str(args.spirv_val), '--target-env', 'vulkan1.3', str(src)], capture_output=True, text=True, timeout=30)
            self.assertEqual(pre.returncode, 0, name + ' input: ' + pre.stdout + pre.stderr)
        run = subprocess.run([str(self.exe), str(src), str(dst)], capture_output=True, text=True, timeout=30)
        if run.returncode == 3:
            return None
        self.assertEqual(run.returncode, 0, run.stderr)
        data = dst.read_bytes()
        check = subprocess.run([str(args.spirv_val), '--target-env', 'vulkan1.3', str(dst)], capture_output=True, text=True, timeout=30)
        self.assertEqual(check.returncode, 0, name + ': ' + check.stdout + check.stderr)
        return ops(list(struct.unpack(f'<{len(data) // 4}I', data)))

    def test_the_four_input_reads_are_replaced(self):
        before = ops(module())
        after = self.rewrite('plain', module())
        count = lambda found, op: sum(o == op for o, _ in found)
        self.assertEqual(count(after, OP_COPY_OBJECT), 4)
        self.assertEqual(count(after, OP_IMAGE_QUERY_SIZE_LOD), 1)
        self.assertEqual(count(after, OP_LOAD) - count(before, OP_LOAD), 0)   # -4 input reads, +FragCoord, +image, +2 c3 reads
        self.assertTrue(any(o == OP_DECORATE and a[1:] == [DEC_BUILTIN, BUILTIN_FRAG_COORD] for o, a in after))

    def test_an_arrayed_image_is_refused(self):
        self.assertIsNone(self.rewrite('arrayed', module(arrayed=True)))

    def test_a_read_outside_the_entry_function_is_refused(self):
        self.assertIsNone(self.rewrite('helper', module(helper=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', type=Path, required=True)
    parser.add_argument('--spirv-val', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args, rest = parser.parse_known_args()
    raise SystemExit(not unittest.main(argv=[__file__] + rest, exit=False).result.wasSuccessful())
