"""Run the lifted UI correction on synthetic matrices, without game data or GPU.

Check the complete register state, stack restoration, untouched matrix rows and
surrounding memory, and pixel proportions at five output shapes. This exercises
the actual replacement words from the patch table through the portable lifter.
"""
import argparse
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recomp'))
from lifter import Lifter


def check_mouse_calls(table):
    """Every mousecamera BL reaches patch page +0x200..0x240 (step 0x10), and the page the table's comment assumes
    (main+0x...) is the one those BL immediates imply."""
    text = (ROOT / table).read_text()
    pages = set()
    for line in text.splitlines():
        f = line.split('#', 1)[0].split()
        if len(f) < 6 or f[:3] != ['site', 'mousecamera', 'main']:
            continue
        w = int(f[-1], 16)
        assert w >> 26 == 0x25, f'{f[3]}: last replacement word is not a BL'
        target = int(f[3], 16) + ((((w & 0x3FFFFFF) ^ 0x2000000) - 0x2000000) << 2)
        assert target & 0xFFF in range(0x200, 0x250, 0x10), f'{f[3]}: BL target {target:#x} is not a dispatch slot'
        pages.add(target & ~0xFFF)
    assert len(pages) == 1, f'mousecamera BLs name several pages: {sorted(map(hex, pages))}'
    assumed = re.findall(r'patch page is at main\+(0x[0-9a-f]+)', text)
    assert assumed and {int(a, 16) for a in assumed} == pages, f'comment assumes {assumed}, BLs imply {list(map(hex, pages))}'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cc', default='clang')
    ap.add_argument('--out', type=Path, default=ROOT / 'build/dkb-wide-projection-test')
    ap.add_argument('--table', type=Path, default=Path('recomp/patches-dkb100.txt'), help='patch table (relative to the repo root)')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lifter = Lifter(0x7000000000, simd='c')
    bodies = []
    for line in (ROOT / args.table).read_text().splitlines():
        f = line.split('#', 1)[0].split()
        if len(f) < 6 or f[:3] != ['site', 'dkbwide', 'main']:
            continue
        pc, original = int(f[3], 16), int(f[4], 16)
        if original >> 26 != 0x25:  # BL sites supply a newly computed UI matrix.
            continue
        if f[-1] != f[4]:
            raise AssertionError('UI patch must preserve its original final call')
        code = []
        for word in f[5:-1]:
            if word == '@page:x8':
                code.append('c->x[8] = (uintptr_t)page;')
            else:
                lifted = lifter.lift(int(word, 16), 0x7000000000 + pc)
                assert lifted.kind == 'op'
                code.append(lifted.code)
        bodies.append('void patch%d(Cpu *c, void *page) {\n%s\n}' % (len(bodies), '\n'.join(code)))
    assert len(bodies) == 4
    check_mouse_calls(args.table)
    source = '#include "cpu.h"\n#include <math.h>\n#include <stdio.h>\n' + '\n'.join(bodies)
    source += '\nvoid (*patches[])(Cpu*,void*) = {' + ','.join(f'patch{i}' for i in range(len(bodies))) + '};\n'
    source += r'''
int main(void) {
    unsigned errors = 0;
    const unsigned sizes[][2] = {{2880,1620},{3440,1440},{2560,1080},{3840,1600},{5120,1440},{7680,2160}};
    // Full UI canvas, observed bubble/icon/text captures, and captures that
    // match just one full-canvas dimension or only its aspect ratio.
    const float canvases[][2] = {{1920,1080},{650,200},{578.4f,120},{100,100},
                                {366,44},{1920,200},{650,1080},{960,540}};
    unsigned cases = 0;
    for (unsigned p=0;p<sizeof patches/sizeof *patches;p++)
    for (unsigned r=0;r<sizeof sizes/sizeof *sizes;r++)
    for (unsigned canvas=0;canvas<sizeof canvases/sizeof *canvases;canvas++)
    for (unsigned trial=0;trial<32;trial++) {
        _Alignas(16) unsigned char page[4096] = {0}, stack[256];
        struct { float before[4], matrix[16], after[4]; } memory, wanted;
        for (unsigned i=0;i<24;i++) ((float*)&memory)[i]=(float)((int)(trial*7+i)-80)/17;
        memory.matrix[0]=2.0f/canvases[canvas][0];
        memory.matrix[5]=2.0f/canvases[canvas][1];
        wanted=memory;
        float factor=((float)sizes[r][0]/sizes[r][1])/(16.0f/9.0f);
        memcpy(page+0x10c,&factor,4);
        if (p!=0 || canvas==0)
            for (unsigned i=0;i<4;i++) wanted.matrix[i]/=factor;
        memset(stack,0xa5,sizeof stack);
        Cpu c={0};
        for (unsigned i=0;i<32;i++) {c.x[i]=0x123456789abcdef0ull+i;c.v[i]=(__uint128_t)c.x[i]<<64|~c.x[i];}
        c.sp=(uintptr_t)(stack+sizeof stack);
        c.x[1]=(uintptr_t)memory.matrix;
        c.nzcv=0xa0000000;
        Cpu saved=c;
        patches[p](&c,page);
        errors += memcmp(c.x,saved.x,sizeof c.x)!=0;
        errors += memcmp(c.v,saved.v,sizeof c.v)!=0;
        errors += c.sp!=saved.sp || c.nzcv!=saved.nzcv;
        errors += memcmp(&memory,&wanted,sizeof memory)!=0;
        for (unsigned i=0;i<sizeof stack-(p==0 ? 80 : 48);i++) errors += stack[i]!=0xa5;
        errors += fabs((double)sizes[r][0]/(1280*factor)-(double)sizes[r][1]/720)>0.000002;
        cases++;
    }
    printf("UI projection: %u matrix/register cases, %u failures\n",cases,errors);
    return errors!=0;
}
'''
    src = args.out / 'projection.c'
    src.write_text(source)
    for opt in ('-O0', '-O2'):
        exe = args.out / ('projection' + opt[1:] + ('.exe' if sys.platform == 'win32' else ''))
        subprocess.run([args.cc, opt, '-march=x86-64-v3', '-fno-strict-aliasing',
                        '-I', str(ROOT / 'runtime'), str(src), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
