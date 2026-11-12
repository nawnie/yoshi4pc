"""Translate an owned Maxwell fragment shader with 8-bit F2I destinations and execute the emitted conversions.

runtime/third_party/eglantine/shader_recompiler/frontend/ampere/lower_to_maxwell.h (F2I byte mode) lowers Ampere
F2I.S8 and F2I.U8 to a Maxwell F2I with the 8-bit destination (size 0), signed by bit 12. Without byte handling the
translator read that destination as unsigned and stored every negative component as 0: Bananza packs skinned
tangents as SNORM bytes through F2I.S8, so whole tangents became zero vectors and their normalisation NaN
(tools/xlate/patches/0017-f2i-byte-destination.patch). The patch saturates in the floating-point domain before the
conversion, with NaN as 0, so inputs beyond the 32-bit intermediate and infinities saturate too.

The fixture loads c[0][0] (dynamic, so nothing folds) and converts it four ways, as lower_to_maxwell.h encodes them:
R0 F2I.S8, R1 F2I.U8, R2 F2I.S16 and R3 F2I.S32, all truncating. The test executes the emitted SPIR-V for each input
with a small evaluator of exactly the operations it uses, and compares the four integer results with the
saturating conversions of the Ampere instructions. No game data or GPU is used.

Usage: python tests/f2i_byte_test.py --translator build/xlate/totk_xlate.exe [--spirv-val PATH]
"""
import argparse
import json
import math
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def fragment(instructions):
    header = [0] * 20
    header[0] = 5 << 10   # fragment stage
    header[18] = 15       # render target 0: R0, R1, R2, R3
    words = []
    for index in range(0, len(instructions), 3):
        words.extend([0, *instructions[index:index + 3]])   # Maxwell scheduling words
    return struct.pack('<20I', *header) + struct.pack('<' + 'Q' * len(words), *words) + bytes(256)


def f2i(dest, src, size, signed):
    # As lower_to_maxwell.h emits it: F2I Rd, Rb; destination size bits 8-9, source F32 (2 << 10), sign bit 12,
    # rounding bits 39-40 (3: truncate), FTZ bit 44; predicate PT.
    return (0x5cb0000000000000 | (size << 8) | (2 << 10) | (signed << 12) | (src << 20) | (3 << 39) | (1 << 44) |
            (7 << 16) | dest)


def shader():
    ldc = 0xef90000000000000 | (4 << 48) | (0 << 20) | (255 << 8) | (7 << 16) | 4   # LDC.32 R4, c[0][0]
    return fragment([ldc, f2i(0, 4, 0, 1), f2i(1, 4, 0, 0), f2i(2, 4, 1, 1), f2i(3, 4, 2, 1),
                     0xe30000000007000f])   # EXIT


def module(path):
    data = path.read_bytes()
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    assert words[0] == 0x07230203
    out, i = [], 5
    while i < len(words):
        n, op = words[i] >> 16, words[i] & 0xffff
        assert n and i + n <= len(words)
        out.append((op, list(words[i + 1:i + n])))
        i += n
    return out


def f32(u):
    return struct.unpack('<f', struct.pack('<I', u & 0xffffffff))[0]


def u32(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def s32(u):
    return u - (1 << 32) if u & 0x80000000 else u


def evaluate(code, c0):
    """Run the straight-line fragment body on raw 32-bit words; returns the four output words. Booleans are 0 or 1.
    A float-to-integer conversion of a NaN or of a value outside its 32-bit result range is undefined in SPIR-V: it
    yields None, which every later operation carries, so a result built on one cannot pass for a defined value.
    Covers the default translator and --defined-float-minmax, whose patch 0014 emits float minimum and maximum as
    integer selection."""
    consts, var_storage, values, outputs = {}, {}, {}, {}
    glsl, chains, body = None, {}, False

    def val(x):
        return values[x] if x in values else consts[x]

    def put(result, args, fn):
        values[result] = None if any(v is None for v in args) else fn(*args)

    for op, a in code:
        if op == 11 and bytes(struct.pack('<%dI' % (len(a) - 1), *a[1:])).rstrip(b'\0') == b'GLSL.std.450':
            glsl = a[0]
        elif op == 43:
            consts[a[1]] = a[2]
        elif op == 59:
            var_storage[a[1]] = a[2]
        elif op == 54:
            body = True
        elif not body:
            continue
        elif op == 65:   # OpAccessChain: remember the root variable and the constant indices
            chains[a[1]] = (a[2], [consts.get(x) for x in a[3:]])
        elif op == 61:   # OpLoad
            root, _ = chains.get(a[2], (a[2], []))
            sc = var_storage.get(root)
            if sc == 2:      # Uniform: the only one is c[0]; the fixture reads its first word
                values[a[1]] = u32(c0)
            elif sc == 7:    # Function variable
                values[a[1]] = values.get(('var', a[2]), 0)
            else:
                raise AssertionError('load from storage class %s' % sc)
        elif op == 62:   # OpStore
            root, idx = chains.get(a[0], (a[0], []))
            if var_storage.get(root) == 3:
                outputs[idx[-1] if idx else len(outputs)] = values[a[1]]
            else:
                values[('var', a[0])] = values[a[1]]
        elif op == 124:  # OpBitcast keeps the bits
            put(a[1], [val(a[2])], lambda v: v)
        elif op == 110:  # OpConvertFToS
            put(a[1], [val(a[2])], lambda v: None if math.isnan(f32(v)) or not -2 ** 31 <= f32(v) < 2 ** 31
                else int(f32(v)) & 0xffffffff)
        elif op == 109:  # OpConvertFToU
            put(a[1], [val(a[2])], lambda v: None if math.isnan(f32(v)) or not 0 <= f32(v) < 2 ** 32 else int(f32(v)))
        elif op == 156:  # OpIsNan
            put(a[1], [val(a[2])], lambda v: int(math.isnan(f32(v))))
        elif op == 169:  # OpSelect
            put(a[1], [val(a[2])], lambda c: val(a[3]) if c else val(a[4]))
        elif 170 <= op <= 179:   # OpIEqual, OpINotEqual, then unsigned/signed >, >=, <, <=
            compare = {170: lambda x, y: x == y, 171: lambda x, y: x != y,
                       172: lambda x, y: x > y, 173: lambda x, y: s32(x) > s32(y),
                       174: lambda x, y: x >= y, 175: lambda x, y: s32(x) >= s32(y),
                       176: lambda x, y: x < y, 177: lambda x, y: s32(x) < s32(y),
                       178: lambda x, y: x <= y, 179: lambda x, y: s32(x) <= s32(y)}[op]
            put(a[1], [val(a[2]), val(a[3])], lambda x, y: int(compare(x, y)))
        elif op in (197, 198, 199):   # OpBitwiseOr, OpBitwiseXor, OpBitwiseAnd
            put(a[1], [val(a[2]), val(a[3])], lambda x, y: x | y if op == 197 else x ^ y if op == 198 else x & y)
        elif op == 200:  # OpNot
            put(a[1], [val(a[2])], lambda v: ~v & 0xffffffff)
        elif op == 12 and a[2] == glsl:
            inst, args = a[3], [val(x) for x in a[4:]]
            if inst == 3:      # Trunc
                put(a[1], args, lambda v: u32(math.trunc(f32(v))) if math.isfinite(f32(v)) else v)
            elif inst in (37, 40):   # FMin, FMax: undefined with a NaN operand
                put(a[1], args, lambda x, y: None if math.isnan(f32(x)) or math.isnan(f32(y)) else
                    u32((min if inst == 37 else max)(f32(x), f32(y))))
            elif inst == 43:   # FClamp: undefined with a NaN operand
                put(a[1], args, lambda x, lo, hi: None if any(math.isnan(f32(v)) for v in (x, lo, hi)) else
                    u32(min(max(f32(x), f32(lo)), f32(hi))))
            elif inst == 45:   # SClamp
                put(a[1], args, lambda x, lo, hi: min(max(s32(x), s32(lo)), s32(hi)) & 0xffffffff)
            elif inst == 44:   # UClamp
                put(a[1], args, lambda x, lo, hi: min(max(x, lo), hi))
            else:
                raise AssertionError('unsupported GLSL.std.450 instruction %d' % inst)
        elif op in (248, 253, 56, 249):   # OpLabel, OpReturn, OpFunctionEnd, OpBranch
            pass
        else:
            raise AssertionError('unsupported shader-body opcode %d' % op)
    assert set(outputs) == {0, 1, 2, 3}, outputs
    return [outputs[i] for i in range(4)]


def saturate(x, lo, hi):
    """The Ampere conversion: truncate, saturate to [lo, hi]; NaN gives 0."""
    if math.isnan(x):
        return 0
    if math.isinf(x):
        return hi if x > 0 else lo
    return max(lo, min(hi, math.trunc(x)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--translator', required=True, type=Path)
    parser.add_argument('--spirv-val', type=Path)
    args = parser.parse_args()
    out = ROOT / 'build/test/f2i-byte'
    out.mkdir(parents=True, exist_ok=True)
    code = out / 'f2i_byte.bin'
    code.write_bytes(shader())
    jobs = out / 'jobs.json'
    jobs.write_text(json.dumps([{'key': 'f2i_byte', 'stage': 'ps', 'code': str(code.resolve()), 'debug': False}]))
    run = subprocess.run([str(args.translator.resolve()), str(jobs.resolve()), str(out.resolve())],
                         capture_output=True, encoding='utf-8')
    if run.returncode:
        raise AssertionError('translator failed: ' + run.stderr.encode('ascii', 'backslashreplace').decode())
    spirv = out / 'f2i_byte.spv'
    if args.spirv_val:
        subprocess.run([str(args.spirv_val.resolve()), '--target-env', 'vulkan1.2', str(spirv)], check=True)
    code = module(spirv)
    failures, checks, skipped = 0, 0, 0
    # Tangent-like values (component x 127, truncated), zero, the ends of each range, beyond them, beyond the 32-bit
    # intermediate (2^31, 2^32, 1e20), infinities and NaN. Every byte result must be defined and saturated. The S16
    # and S32 controls are compared only where their conversion is defined (finite and inside the 32-bit range):
    # this patch does not change them.
    for x in (-63.5, -127.0, -1.0, -0.75, 0.0, 0.5, 1.0, 63.5, 127.0, 128.0, 200.0, -129.0, -300.0, 255.0, 256.0,
              40000.0, -40000.0, 2.0 ** 31, 2.0 ** 32, 1e20, -1e20, math.inf, -math.inf, math.nan):
        got = evaluate(code, x)
        want = [saturate(x, -128, 127) & 0xffffffff, saturate(x, 0, 255), saturate(x, -32768, 32767) & 0xffffffff,
                saturate(x, -2 ** 31, 2 ** 31 - 1) & 0xffffffff]
        defined32 = math.isfinite(x) and -2 ** 31 <= x < 2 ** 31
        for name, g, w in zip(('S8', 'U8', 'S16', 'S32'), got, want):
            if name in ('S16', 'S32') and not defined32:
                skipped += 1
                continue
            checks += 1
            if g != w:
                failures += 1
                print('FAIL F2I.%s(%r): got %s, want %d' % (name, x, 'an undefined conversion' if g is None
                                                              else s32(g), s32(w)))
    print('f2i byte: %d checks, %d failures (%d undefined 16/32-bit controls skipped)' % (checks, failures, skipped))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
