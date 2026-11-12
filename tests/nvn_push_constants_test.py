"""Compile with the project's Clang toolchain and run synthetic recorder checks, without game files.

Usage: python tests/nvn_push_constants_test.py [--cc /path/to/clang]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default=os.environ.get('CC') or shutil.which('clang'))
    args = parser.parse_args()
    if not args.cc:
        parser.error('pass --cc with the project\'s Clang executable')
    out = ROOT / 'build' / 'test' / 'nvn-push-constants'
    out.mkdir(parents=True, exist_ok=True)
    exe = out / ('nvn_push_constants.exe' if os.name == 'nt' else 'nvn_push_constants')
    subprocess.run([args.cc, '-O2', '-Wall', '-fno-strict-aliasing', '-ffunction-sections', '-fdata-sections',
                    '-I', str(ROOT / 'runtime'), str(ROOT / 'tests' / 'nvn_push_constants.c'),
                    str(ROOT / 'runtime' / 'nvn_api_cmd.c'), str(ROOT / 'runtime' / 'nvn_api_nvn2.c'),
                    '-Wl,--gc-sections', '-o', str(exe)], check=True)
    return subprocess.run([str(exe)]).returncode


if __name__ == '__main__':
    raise SystemExit(main())
