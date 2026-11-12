"""Differential check of ARM64 vector UDOT lifting against Unicorn."""
import ctypes
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get('UNICORN_PATH'):
    sys.path.insert(0, os.environ['UNICORN_PATH'])
sys.path.insert(0, str(ROOT / 'recomp'))

from unicorn import UC_ARCH_ARM64, UC_MODE_ARM, Uc
from unicorn.arm64_const import UC_ARM64_REG_Q0, UC_CPU_ARM64_MAX
from lifter import Lifter


class Cpu(ctypes.Structure):
    _fields_ = [('v', ctypes.c_uint64 * 64)]


def main():
    cases = [(0x6e819402, 2, 0, 1), (0x2e8b9505, 5, 8, 11), (0x6e819400, 0, 0, 1), (0x6e819421, 1, 1, 1)]
    src = '#include <stdint.h>\ntypedef __uint128_t u128; typedef struct {u128 v[32];} Cpu;\n'
    for i, (word, _, _, _) in enumerate(cases):
        src += f'__declspec(dllexport) void run{i}(Cpu *c) ' + Lifter(0, 'c').lift(word, 0).code + '\n'

    cc = os.environ.get('CC', r'C:\msys64\ucrt64\bin\clang.exe' if os.name == 'nt' else 'clang')
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        c_path = tmp / 'udot_test.c'
        dll_path = tmp / ('udot_test.dll' if os.name == 'nt' else 'udot_test.so')
        c_path.write_text(src, encoding='utf-8')
        subprocess.run([cc, '-shared', '-O2', str(c_path), '-o', str(dll_path)], check=True)
        dll = ctypes.CDLL(str(dll_path))
        rng = random.Random(12345)
        for ix, (word, d, n, m) in enumerate(cases):
            fn = getattr(dll, f'run{ix}')
            fn.argtypes = [ctypes.POINTER(Cpu)]
            for _ in range(100):
                vals = [rng.getrandbits(128) for _ in range(32)]
                cpu = Cpu()
                for i, v in enumerate(vals):
                    cpu.v[2 * i] = v & ((1 << 64) - 1)
                    cpu.v[2 * i + 1] = v >> 64
                fn(ctypes.byref(cpu))
                actual = cpu.v[2 * d] | (cpu.v[2 * d + 1] << 64)
                u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
                u.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
                u.mem_map(0x1000, 0x1000)
                u.mem_write(0x1000, word.to_bytes(4, 'little'))
                for i in {d, n, m}:
                    u.reg_write(UC_ARM64_REG_Q0 + i, vals[i])
                u.emu_start(0x1000, 0x1004)
                expected = u.reg_read(UC_ARM64_REG_Q0 + d)
                assert actual == expected, (hex(word), hex(actual), hex(expected))
    print('PASS: 400 UDOT comparisons against Unicorn, Q=0/1 and overlapping registers')


if __name__ == '__main__':
    main()
