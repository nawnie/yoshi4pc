"""CPU preflight of the actual original portable-GS probe authoring and oracle.

The source authoring helpers and canonical control packer execute without Vulkan.
Three authored modules pass the actual translator and spirv-val. Pixel coverage
is an independent mathematical check; actual replay, pixels and memory remain
the separate --probe-vkgeometry-passthrough GPU check.
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
import vk_geometry_probe_test as ordinary
from geometry_passthrough_test import Copies

ROOT = Path(__file__).resolve().parents[1]
SKIP = (0x0fffffff, 0xfffffff0, *([0xffffffff] * 6))


def cpu_source(source=None, legacy=False):
    source = source or (ROOT / 'runtime/vk_geometry_probe.c').read_text(encoding='utf-8')
    authoring = source[source.index('enum { GP_CONTROL'):source.index('#define GP_U(')]
    oracle = source[source.index('static int gp_inside('):source.index('static int gp_pixels(')]
    vertices = ''
    if not legacy:
        start = source.index('    static const float vertices[')
        end = source.index(';', start) + 1
        vertices = source[start:end]
    set_mode = 'if(mode)return 6;' if legacy else 'gp_passthrough=mode;'
    return '#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n' + \
        '#include "nvn_geometry_control.h"\n' + authoring + oracle + r'''
static int save(const char *dir,const char *prefix,unsigned stage,const char *suffix,const void *data,size_t n) {
    char path[4096];snprintf(path,sizeof path,"%s/%s-stage%u.%s",dir,prefix,stage,suffix);
    FILE *f=fopen(path,"wb");if(!f)return 0;
    int ok=fwrite(data,1,n,f)==n;return !fclose(f)&&ok;
}
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    int mode=atoi(argv[2]);
''' + set_mode + r'''
    const char *prefix=mode?"portable":"ordinary";
    uint8_t control[GP_CONTROL],code[GP_CODE];
    static const uint32_t skip[8]={0x0fffffffu,0xfffffff0u,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX};
    for(unsigned stage=0;stage<3;stage++) {
        uint32_t size=gp_program(stage,control,code);
        if(size>GP_CODE || size<GP_SKIP)return 3;
        if(mode && stage==2) {
            uint32_t actual[8];
            if(!nvn_geometry_control_pack_portable(control,sizeof control,code,size,skip) ||
               nvn_geometry_control_get(control,sizeof control,code,size,actual)!=1 ||
               memcmp(skip,actual,sizeof skip) || !save(argv[1],prefix,stage,"mask",actual,sizeof actual))return 4;
        }
        if(!save(argv[1],prefix,stage,"control",control,sizeof control) ||
           !save(argv[1],prefix,stage,"fullcode",code,size) ||
           !save(argv[1],prefix,stage,"code",code+GP_SKIP,size-GP_SKIP))return 5;
    }
''' + (vertices + r'''
    static const uint16_t indices[3]={0,1,2};
    if(!save(argv[1],prefix,0,"vertices",vertices,sizeof vertices) ||
       !save(argv[1],prefix,0,"indices",indices,sizeof indices))return 7;
''' if not legacy else '') + r'''
    for(unsigned y=0;y<GP_HEIGHT;y++)for(unsigned x=0;x<GP_WIDTH;x++)
        printf("%u %u %d %d\n",x,y,gp_inside(x,y,0),gp_inside(x,y,1));
    return 0;
}
'''


def jobs(out):
    result = []
    for stage, name in ((0, 'vs_portable'), (1, 'ps_portable'), (2, 'gs_portable')):
        job = dict(key=name, stage=('vs', 'ps', 'gs')[stage],
                   code=str((out / f'portable-stage{stage}.code').resolve()), debug=False, c1='')
        if stage == 0:
            job['attr'] = {'0': 'float', '1': 'float'}
        if stage == 2:
            words = struct.unpack('<8I', (out / 'portable-stage2.mask').read_bytes())
            job.update(geometry_version=2, gs_input='triangles', gs_passthrough_skip=words, sbuf_align=256)
        result.append(job)
    return result


class PortablePreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        args.out.mkdir(parents=True, exist_ok=False)
        cls.source = (ROOT / 'runtime/vk_geometry_probe.c').read_text(encoding='utf-8')
        baseline = subprocess.check_output(['git', 'show', '3b09d06fc00443b124edff570ea74393e4d6d7cc:runtime/vk_geometry_probe.c'],
                                           cwd=ROOT, text=True)
        for name, source in (('author', cpu_source()), ('baseline', cpu_source(baseline, legacy=True))):
            path, exe = args.out / (name + '.c'), args.out / (name + '.exe')
            path.write_text(source, encoding='utf-8')
            run = subprocess.run([args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                  '-I', str(ROOT / 'runtime'), str(path), '-o', str(exe)], capture_output=True, text=True, timeout=60)
            (args.out / (name + '-compile.log')).write_text(run.stdout + run.stderr, encoding='utf-8')
            if run.returncode:
                raise AssertionError(run.stdout + run.stderr)
            folder = args.out / name
            folder.mkdir()
            modes = ('0', '1') if name == 'author' else ('0',)
            for mode in modes:
                run = subprocess.run([str(exe.resolve()), str(folder.resolve()), mode], capture_output=True, text=True, timeout=15)
                (folder / ('oracle-' + mode + '.txt')).write_text(run.stdout, encoding='utf-8')
                if run.returncode:
                    raise AssertionError(f'{name} mode{mode}: exit{run.returncode}: {run.stdout}{run.stderr}')
        cls.folder = args.out / 'author'

    def test_mode_zero_matches_unchanged_probe_authoring(self):
        for stage in range(3):
            for suffix in ('code', 'fullcode', 'control'):
                name = f'ordinary-stage{stage}.{suffix}'
                self.assertEqual((self.folder / name).read_bytes(), (args.out / 'baseline' / name).read_bytes())
        for stage in (0, 1):
            for suffix in ('code', 'control'):
                self.assertEqual((self.folder / f'portable-stage{stage}.{suffix}').read_bytes(),
                                 (self.folder / f'ordinary-stage{stage}.{suffix}').read_bytes())

    def test_actual_passthrough_program_and_canonical_metadata(self):
        code = (self.folder / 'portable-stage2.code').read_bytes()
        full = (self.folder / 'portable-stage2.fullcode').read_bytes()
        control = (self.folder / 'portable-stage2.control').read_bytes()
        self.assertEqual(full[0x30:], code)
        self.assertEqual(len(control), 0x880)
        self.assertEqual(struct.unpack_from('<2I', control, 0x700), (len(full), len(full)))
        self.assertEqual(struct.unpack_from('<I', control, 0x714)[0], 2)
        word0, _, word2, word3, word4 = struct.unpack_from('<5I', code)
        self.assertEqual((word0 & 31, word0 >> 5 & 31, word0 >> 10 & 15, word0 >> 24 & 1), (1, 3, 4, 1))
        self.assertEqual((word2 >> 24, word3 >> 24 & 15, word4 & 0xfff), (1, 7, 1))
        self.assertEqual(struct.unpack('<8I', (self.folder / 'portable-stage2.mask').read_bytes()), SKIP)
        self.assertEqual(control[0x800:0x808], b'TKGSMETA')
        self.assertEqual(struct.unpack_from('<8I', control, 0x818), SKIP)
        words = struct.unpack('<' + 'Q' * ((len(code) - 80) // 8), code[80:])
        self.assertTrue(all(w == original.SCHED for w in words[::4]))
        ops = [w for i, w in enumerate(words) if i % 4]
        self.assertIn(original.EXIT, ops)
        self.assertFalse(any(w >> 52 == 0xeff for w in ops), 'authored AST is forbidden')
        self.assertFalse(any(w >> 51 == original.out_vertex() >> 51 for w in ops), 'authored OUT is forbidden')
        stores = [i for i, w in enumerate(ops) if w >> 51 == 0xeed8000000000000 >> 51]
        self.assertEqual([(ops[i] >> 20) & 0xffffff for i in stores], [0, 4, 8, 12, 16])
        self.assertEqual([(ops[i - 1] >> 20) & 0xffffffff for i in stores], [3, 1, 0, 0, 0])
        self.assertTrue(all(ops[i] & 255 == 8 and (ops[i] >> 8) & 255 == 10 and
                            (ops[i] >> 48) & 7 == 4 and ops[i] & (1 << 45) for i in stores))

    def test_actual_vertices_indices_and_independent_pixel_oracle(self):
        raw = (self.folder / 'portable-stage0.vertices').read_bytes()
        self.assertEqual(len(raw), 7 * 32)
        vertices = list(struct.iter_unpack('<8f', raw))
        positions = [(-.75, -.75, 0, 1), (.75, -.75, 0, 1), (0, .75, 0, 1)]
        self.assertEqual([v[:4] for v in vertices[:3]], positions)
        self.assertEqual([v[:4] for v in vertices[3:6]], positions)
        self.assertTrue(all(v[4:] == (0, 1, 0, 1) for v in vertices[:3]))
        self.assertTrue(all(v[4:] == (1, 0, 0, 1) for v in vertices[3:]))
        self.assertEqual(vertices[6][:4], (0, 0, 0, 1))
        self.assertEqual(struct.unpack('<3H', (self.folder / 'portable-stage0.indices').read_bytes()), (0, 1, 2))
        lines = (self.folder / 'oracle-1.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 1024)
        triangle = ((4, 4), (28, 4), (16, 28))
        def cross(a, b, p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        covered = 0
        for line in lines:
            x, y, normal, flipped = map(int, line.split())
            for flip, actual in ((False, normal), (True, flipped)):
                point = (x + .5, (31 - y if flip else y) + .5)
                sides = [cross(triangle[i], triangle[(i + 1) % 3], point) for i in range(3)]
                self.assertNotIn(0, sides)
                self.assertEqual(actual, int(all(s > 0 for s in sides)))
            covered += normal
        self.assertEqual(covered, 288)

    def test_actual_translation_resources_and_copy_emission(self):
        requests = jobs(self.folder)
        run = subprocess.run([str(args.xlate.resolve()), '--serve'],
            input=''.join(json.dumps({'job': job, 'out': str(self.folder.resolve())}) + '\n' for job in requests),
            capture_output=True, text=True, timeout=60)
        (self.folder / 'translation.log').write_text(run.stdout + run.stderr, encoding='utf-8')
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout.splitlines(), ['ok ' + j['key'] for j in requests])
        reports = {}
        for job in requests:
            name = job['key']
            path = self.folder / (name + '.spv')
            result = subprocess.run([str(args.spirv_val), '--target-env', 'vulkan1.3', str(path)],
                                    capture_output=True, text=True, timeout=15)
            (self.folder / (name + '-val.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            reports[name] = json.loads((self.folder / (name + '.res.json')).read_text(encoding='utf-8'))
        report = reports['gs_portable']
        self.assertEqual(report['geometry_version'], 2)
        self.assertEqual(report['gs_passthrough_skip'], list(SKIP))
        self.assertEqual(report['geometry'], dict(input_vertices=3, output_topology='triangle_strip', invocations=1,
            max_output_vertices=3, passthrough=False, source_passthrough=True))
        self.assertEqual(len(report['sbufs']), 1)
        resource = report['sbufs'][0]
        self.assertEqual((resource['cb_slot'], resource['cb_offset'], resource['flags']), (3, 0, 1))
        data = (self.folder / 'gs_portable.spv').read_bytes()
        ops = list(original.instructions(data))
        bindings = {o[0]: o[2] for op, o in ops if op == 71 and o[1] == 33}
        buffers = {var for var, binding in bindings.items() if binding == resource['binding']}
        chains = {o[1]: o[2] for op, o in ops if op == 65}
        writes = [i for i, (op, o) in enumerate(ops) if op == 62 and chains.get(o[0]) in buffers]
        self.assertEqual(len(writes), 5)
        constants = {o[1]: o[2] for op, o in ops if op == 43 and len(o) == 3}
        self.assertEqual([constants[ops[i][1][1]] for i in writes], [3, 1, 0, 0, 0])
        self.assertLess(writes[-1], next(i for i, (op, _) in enumerate(ops) if op == 218))
        self.assertEqual(sum(op == 218 for op, _ in ops), 3)
        self.assertEqual(sum(op == 219 for op, _ in ops), 1)
        module = Copies(data)
        modes = [o[1:] for op, o in ops if op == 16]
        for expected in ((22,), (29,), (0, 1), (26, 3)):
            self.assertIn(expected, modes)
        # The independent scalar-copy oracle executes only the emitted I/O suffix.
        # Storage writes above are checked structurally, not claimed as CPU/GPU execution.
        last = max(i for i, (op, o) in enumerate(module.body) if op == 62 and chains.get(o[0]) in buffers)
        module.body = module.body[last + 1:]
        positions = [tuple(0x3f000001 + v * 16 + c for c in range(4)) for v in range(3)]
        colors = [tuple(0x3f800001 + v * 16 + c for c in range(4)) for v in range(3)]
        emitted, cuts, reads = module.run_copies(positions, {0: colors})
        self.assertEqual(emitted, [(positions[v], {0: colors[v]}) for v in range(3)])
        self.assertEqual(cuts, [3])
        self.assertEqual(len(reads), 24)
        vs_user, vs_builtin = ordinary.io_contract((self.folder / 'vs_portable.spv').read_bytes())
        gs_user, gs_builtin = ordinary.io_contract(data)
        fs_user, _ = ordinary.io_contract((self.folder / 'ps_portable.spv').read_bytes())
        self.assertEqual(vs_user[3, 0], gs_user[1, 0])
        self.assertEqual(gs_user[3, 0], fs_user[1, 0])
        self.assertEqual(gs_builtin[3, 0], (32, 4))
        self.assertEqual(vs_builtin[3, 0], (32, 4))
        (args.out / 'preparation.json').write_text(json.dumps(dict(gpu_executed=False,
            source_sha256=hashlib.sha256((ROOT / 'runtime/vk_geometry_probe.c').read_bytes()).hexdigest(),
            header_sha256=hashlib.sha256((ROOT / 'runtime/nvn_geometry_control.h').read_bytes()).hexdigest(),
            translator_sha256=hashlib.sha256(args.xlate.read_bytes()).hexdigest(), reports=reports,
            limitations='CPU authoring/canonical metadata/SPIR-V/static store preservation/copy suffix/oracle only; no replay, device or memory execution.'), indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', required=True)
    parser.add_argument('--xlate', required=True, type=Path)
    parser.add_argument('--spirv-val', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__] + remaining)
