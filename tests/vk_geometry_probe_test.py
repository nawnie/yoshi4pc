"""Prepare the actual original GS replay probe programs without loading Vulkan.

Compiles only the in-source authoring helpers and pixel oracle, translates their
three Maxwell stages, validates the SPIR-V, and checks interfaces/store metadata.
The runtime --probe-vkgeometry result remains a separate real GPU check.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import unittest

import geometry_shader_fixture as original

ROOT = Path(__file__).resolve().parents[1]


def cpu_source():
    source = (ROOT / 'runtime/vk_geometry_probe.c').read_text()
    authoring = source[source.index('enum { GP_CONTROL'):source.index('#define GP_U(')]
    oracle = source[source.index('static int gp_inside('):source.index('static int gp_pixels(')]
    return '#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n' + authoring + oracle + r'''
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    uint8_t ctl[GP_CONTROL], code[GP_CODE];
    for (unsigned stage=0;stage<3;stage++) {
        char path[4096];
        uint32_t size=gp_program(stage,ctl,code);
        if (size>GP_CODE || size<GP_SKIP) return 3;
        snprintf(path,sizeof path,"%s/stage%u.control",argv[1],stage);
        FILE *f=fopen(path,"wb"); if(!f)return 4;
        int ok=fwrite(ctl,1,sizeof ctl,f)==sizeof ctl; if(fclose(f)||!ok)return 5;
        snprintf(path,sizeof path,"%s/stage%u.code",argv[1],stage);
        f=fopen(path,"wb"); if(!f)return 6;
        ok=fwrite(code+GP_SKIP,1,size-GP_SKIP,f)==size-GP_SKIP; if(fclose(f)||!ok)return 7;
    }
    for(unsigned y=0;y<GP_HEIGHT;y++)for(unsigned x=0;x<GP_WIDTH;x++)
        printf("%u %u %d %d\n",x,y,gp_inside(x,y,0),gp_inside(x,y,1));
    return 0;
}
'''


def io_contract(data):
    types, pointers, variables, locations, builtins, arrays, structs, members = {}, {}, {}, {}, {}, {}, {}, {}
    for op, o in original.instructions(data):
        if op in (21, 22):
            types[o[0]] = (o[1], 1)
        elif op == 23:
            types[o[0]] = (types[o[1]][0], o[2])
        elif op == 28:
            arrays[o[0]] = o[1]
        elif op == 30:
            structs[o[0]] = o[1:]
        elif op == 32:
            pointers[o[0]] = o[2]
        elif op == 59:
            variables[o[1]] = (o[2], o[0])
        elif op == 71 and o[1] == 30:
            locations[o[0]] = o[2]
        elif op == 71 and o[1] == 11:
            builtins[o[0]] = o[2]
        elif op == 72 and o[2] == 11:
            members[o[0], o[1]] = o[3]
    def element(t):
        while t in arrays:
            t = arrays[t]
        return t
    def numeric(t):
        return types.get(element(t))
    user = {(variables[var][0], location): numeric(pointers[variables[var][1]])
            for var, location in locations.items() if var in variables}
    builtin = {(variables[var][0], builtin): numeric(pointers[variables[var][1]])
               for var, builtin in builtins.items() if var in variables}
    for storage, pointer in variables.values():
        struct = element(pointers[pointer])
        for member, t in enumerate(structs.get(struct, ())):
            if (struct, member) in members:
                builtin[storage, members[struct, member]] = numeric(t)
    return user, builtin


class ProbePreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        args.out.mkdir(parents=True, exist_ok=True)
        cls.cfile = args.out / 'author.c'
        cls.cfile.write_text(cpu_source())
        cls.exe = args.out / ('author.exe' if os.name == 'nt' else 'author')
        command = [args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', str(cls.cfile), '-o', str(cls.exe)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=60)
        (args.out / 'compile.log').write_text(run.stdout + run.stderr)
        if run.returncode:
            raise AssertionError(run.stdout + run.stderr)
        run = subprocess.run([str(cls.exe.resolve()), str(args.out.resolve())], capture_output=True, text=True, timeout=15)
        (args.out / 'pixel-oracle.txt').write_text(run.stdout)
        if run.returncode:
            raise AssertionError(run.stdout + run.stderr)
        cls.pixel_lines = run.stdout.splitlines()

    def test_actual_maxwell_programs(self):
        for stage, sph in ((0, 1), (1, 5), (2, 4)):
            with self.subTest(stage=stage):
                control = (args.out / f'stage{stage}.control').read_bytes()
                code = (args.out / f'stage{stage}.code').read_bytes()
                self.assertEqual((len(control), len(code) % 8), (0x880, 0))
                self.assertEqual(struct.unpack_from('<3I', control, 0x700)[:2], (len(code) + 0x30,) * 2)
                self.assertEqual(struct.unpack_from('<I', control, 0x714)[0], stage)
                self.assertEqual((struct.unpack_from('<I', code)[0] >> 10) & 15, sph)
                words = struct.unpack('<' + 'Q' * ((len(code) - 80) // 8), code[80:])
                self.assertTrue(all(w == original.SCHED for w in words[::4]))
                ops = [w for i, w in enumerate(words) if i % 4]
                self.assertIn(original.EXIT, ops)
                if stage == 2:
                    stores = [w for w in ops if w >> 51 == 0xeed8000000000000 >> 51]
                    self.assertEqual(len(stores), 5)
                    self.assertEqual([(w >> 20) & 0xffffff for w in stores], [0, 4, 8, 12, 16])
                    self.assertEqual([(ops[i - 1] >> 20) & 0xffffffff for i, w in enumerate(ops) if w in stores],
                                     [3, 1, 0, 0, 0])
                    self.assertTrue(all(ops[i - 1] & 255 == 8 and w & 255 == 8 and (w >> 8) & 255 == 10
                                        for i, w in enumerate(ops) if w in stores))
                    self.assertTrue(all((w >> 48) & 7 == 4 and w & (1 << 45) for w in stores))
                    self.assertEqual([(w & 255, (w >> 34) & 31, (w >> 20) & 0x3fff)
                        for w in ops if w >> 51 == 0x4c98000000000000 >> 51], [(10, 3, 0), (11, 3, 1)])
                    emits = [w for w in ops if w >> 51 == 0xf6e0000000000000 >> 51]
                    self.assertEqual([(w >> 39) & 3 for w in emits], [1, 1, 3])

    def test_actual_pixel_oracle(self):
        self.assertEqual(len(self.pixel_lines), 32 * 32)
        triangle = ((4, 4), (28, 4), (16, 28))
        def cross(a, b, p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        covered = 0
        for line in self.pixel_lines:
            x, y, normal, flipped = map(int, line.split())
            for flip, actual in ((False, normal), (True, flipped)):
                point = (x + 0.5, (31 - y if flip else y) + 0.5)
                sides = [cross(triangle[i], triangle[(i + 1) % 3], point) for i in range(3)]
                self.assertNotIn(0, sides, 'oracle must avoid implementation-dependent edge ties')
                self.assertEqual(actual, int(all(side > 0 for side in sides)))
            covered += normal
        self.assertEqual(covered, 288)

    def test_actual_translator_and_interfaces(self):
        jobs = []
        for stage, name in ((0, 'vs'), (1, 'ps'), (2, 'gs')):
            job = dict(key=name, stage=name, code=str((args.out / f'stage{stage}.code').resolve()), debug=False, c1='')
            if name == 'vs':
                job['attr'] = {'0': 'float', '1': 'float'}
            if name == 'gs':
                job.update(geometry_version=1, gs_input='points')
            jobs.append(job)
        run = subprocess.run([str(args.xlate.resolve()), '--serve'],
            input=''.join(json.dumps(dict(job=j, out=str(args.out.resolve()))) + '\n' for j in jobs),
            text=True, capture_output=True, timeout=60)
        (args.out / 'translator.log').write_text(run.stdout + run.stderr)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.splitlines(), ['ok vs', 'ok ps', 'ok gs'], run.stdout + run.stderr)
        reports, interfaces = [], {}
        for job in jobs:
            key = job['key']
            spv = args.out / (key + '.spv')
            reflection = json.loads((args.out / (key + '.res.json')).read_text())
            self.assertEqual(reflection['stage'], key)
            run = subprocess.run([str(args.spirv_val.resolve()), '--target-env', 'vulkan1.3', str(spv.resolve())],
                text=True, capture_output=True, timeout=15)
            (args.out / (key + '.validation.log')).write_text(run.stdout + run.stderr)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            interfaces[key] = io_contract(spv.read_bytes())
            if key == 'gs':
                self.assertEqual(reflection['geometry'], dict(input_vertices=1, output_topology='triangle_strip',
                    invocations=1, max_output_vertices=3, passthrough=False))
                self.assertEqual(reflection['gs_input'], 'points')
                self.assertEqual(len(reflection['sbufs']), 1)
                resource = reflection['sbufs'][0]
                self.assertEqual((resource['cb_slot'], resource['cb_offset'], resource['flags']), (3, 0, 1))
                operations = list(original.instructions(spv.read_bytes()))
                self.assertEqual(sum(op == 218 for op, _ in operations), 3)
                self.assertEqual(sum(op == 219 for op, _ in operations), 1)
                decorations = {o[0]: o[2] for op, o in operations if op == 71 and o[1] == 33}
                storage = {var for var, binding in decorations.items() if binding == resource['binding']}
                pointers = {o[1]: o[2] for op, o in operations if op == 65}
                self.assertEqual(sum(op == 62 and pointers.get(o[0]) in storage for op, o in operations), 5)
            reports.append(dict(stage=key, reflection=reflection, spirv_sha256=hashlib.sha256(spv.read_bytes()).hexdigest(),
                                validation='PASS'))
        vs, gs, fs = interfaces['vs'][0], interfaces['gs'][0], interfaces['ps'][0]
        self.assertEqual(vs[(1, 0)], (32, 4))
        self.assertEqual(vs[(1, 1)], (32, 4))
        self.assertEqual(vs[(3, 0)], gs[(1, 0)])
        self.assertEqual(gs[(3, 0)], fs[(1, 0)])
        self.assertEqual(gs[(3, 0)], (32, 4))
        self.assertEqual(interfaces['vs'][1][(3, 0)], (32, 4))  # Position
        self.assertEqual(interfaces['vs'][1][(3, 1)], (32, 1))  # PointSize, valid disabled points draw
        self.assertEqual(interfaces['gs'][1][(3, 0)], (32, 4))
        (args.out / 'preparation.json').write_text(json.dumps(dict(
            source_sha256=hashlib.sha256((ROOT / 'runtime/vk_geometry_probe.c').read_bytes()).hexdigest(),
            translator_sha256=hashlib.sha256(args.xlate.read_bytes()).hexdigest(), reports=reports,
            gpu_executed=False, limits='Offline original authoring/interface proof only; actual NVN replay/pixels/indirect consumption pending.'), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default=os.environ.get('CC', 'clang'))
    parser.add_argument('--xlate', required=True, type=Path)
    parser.add_argument('--spirv-val', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__] + remaining)
