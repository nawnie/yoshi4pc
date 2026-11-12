"""Original actual-header EXIT capture regression; no game, Vulkan or GPU.

Use --source-root for an independent baseline checkout. Both ProgramCaptureState
and LowerToMaxwell are real production headers; no instruction decoder is mocked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default=os.environ.get('CXX') or shutil.which('clang++'))
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--opt', choices=('0', '2'), default='2')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.cxx:
        parser.error('pass --cxx with the project Clang++ executable')
    args.out.mkdir(parents=True, exist_ok=True)
    include = args.source_root.resolve() / 'runtime/third_party/eglantine'
    fixture = ROOT / 'tests/native_exit_capture.cpp'
    exe = args.out / ('native-exit-capture.exe' if os.name == 'nt' else 'native-exit-capture')
    command = [args.cxx, '-std=c++20', f'-O{args.opt}', '-Wall', '-Wextra', '-Werror',
               '-I', str(include), str(fixture), '-o', str(exe)]
    if os.name == 'nt':
        command += ['-static-libstdc++', '-static-libgcc']
    compile = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (args.out / 'compile.log').write_text(compile.stdout + compile.stderr)
    if compile.returncode:
        print(compile.stdout + compile.stderr, end='')
        return compile.returncode
    run = subprocess.run([str(exe.resolve())], capture_output=True, text=True, timeout=15)
    (args.out / 'result.log').write_text(run.stdout + run.stderr)
    files = [fixture, include / 'shader_recompiler/frontend/ampere/program_capture.h',
             include / 'shader_recompiler/frontend/ampere/lower_to_maxwell.h']
    (args.out / 'result.json').write_text(json.dumps(dict(command=command, optimization=args.opt,
        source_root=str(args.source_root.resolve()), exit_code=run.returncode, output=run.stdout + run.stderr,
        source_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}), indent=2) + '\n')
    print(run.stdout + run.stderr, end='')
    return run.returncode


if __name__ == '__main__':
    raise SystemExit(main())
