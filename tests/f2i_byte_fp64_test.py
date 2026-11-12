"""Validate original FP64 S8/U8 conversions through the shared F2I emitter.

The native byte lowerer currently admits FP32. These broader translator inputs
exercise the existing FP64 branch without changing its FP32 numerical tests.
No numeric FP64, direct-U8 NaN policy, hardware or GPU claim follows from validation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from float_minmax_test import fragment

ROOT = Path(__file__).resolve().parents[1]


def shader(signed):
    # Original dynamic c0 double in R4/R5; F2I source format3, byte destination,
    # signed bit12, truncation3, FTZ off. All four outputs carry the same result.
    load = 0xef90000000000000 | (5 << 48) | (255 << 8) | (7 << 16) | 4
    convert = 0x5cb0000000000000 | (3 << 10) | (int(signed) << 12) | (4 << 20) | (3 << 39) | (7 << 16)
    return fragment([load, *(convert | rd for rd in range(4)), 0xe30000000007000f], fp64=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--translator', type=Path, required=True)
    parser.add_argument('--spirv-val', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.relative_to((ROOT / 'build').resolve())
    out.mkdir(parents=True, exist_ok=False)
    jobs = []
    for name, signed in (('s8', True), ('u8', False)):
        code = out / (name + '.code')
        code.write_bytes(shader(signed))
        jobs.append(dict(key=name, stage='ps', code=str(code), debug=False))
    job_file = out / 'jobs.json'
    job_file.write_text(json.dumps(jobs))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', DOTNET_PROCESSOR_COUNT='2')
    run = subprocess.run([str(args.translator.resolve()), str(job_file), str(out)],
                         env=env, capture_output=True, encoding='utf-8', timeout=60)
    (out / 'translator.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    if run.returncode:
        raise AssertionError('translator failed: ' + run.stderr)
    results = []
    for job in jobs:
        path = out / (job['key'] + '.spv')
        validation = subprocess.run([str(args.spirv_val.resolve()), '--target-env', 'vulkan1.2', str(path)],
                                    env=env, capture_output=True, encoding='utf-8', timeout=30)
        (out / (job['key'] + '.validate.log')).write_text(validation.stdout + validation.stderr, encoding='utf-8')
        results.append(dict(case=job['key'], exit=validation.returncode,
                            code_sha256=hashlib.sha256(Path(job['code']).read_bytes()).hexdigest(),
                            spirv_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if validation.returncode:
            print(job['key'] + ': ' + validation.stdout + validation.stderr)
    failures = sum(row['exit'] != 0 for row in results)
    report = dict(results=results, validations=2, failures=failures, gpu_executed=False,
                  translator_sha256=hashlib.sha256(args.translator.read_bytes()).hexdigest(),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('f2i FP64 byte: 2 complete modules, %d invalid' % failures)
    return int(failures != 0)


if __name__ == '__main__':
    raise SystemExit(main())
