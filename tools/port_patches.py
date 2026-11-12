"""Port a patch table (recomp/patches-<from>.txt) from one Bananza version's main to another's.

Each site is found in the new main by a window of +-4 instruction words around it, with the PC-relative immediates
masked (strict: b/bl, b.cond, cbz/cbnz, tbz/tbnz, adr/adrp, ldr literal; loose: also the add/sub-imm and ldr/str-imm12
fields). The match must be unique and the instruction word at the new site must equal the old original, except for a
`bl` original, which is re-encoded against the target the old one had (the same function: its first 8 words must be
equal). A replacement `bl` into the patch page is re-encoded against the new page (recomp/patches.py: the page is the
first 4 KiB page after main's image; `@page:xN` cannot express a call). `--sibling NEW=OLD` places a site at the
delta of an already matched site, only when the original words are equal there. Only offsets are printed; every site
that was not strict-matched goes to stderr for review. `--self-check` maps the table onto its own main (all deltas 0).

  .venv\\Scripts\\python tools\\port_patches.py --from dkb100 --to dkb458752 --sibling 5ad9f0=5ada00
"""
import argparse
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'recomp'))
from nso import Nso  # noqa: E402

BL = 0x94000000
WIN = 4


def mask(words, loose):
    w = words
    m = np.full(w.shape, 0xFFFFFFFF, dtype=np.uint32)

    def clear(cond, bits):
        m[cond] &= np.uint32(~bits & 0xFFFFFFFF)
    top6 = w >> 26
    clear((top6 == 0x05) | (top6 == 0x25), 0x03FFFFFF)
    clear((w & 0xFF000010) == 0x54000000, 0x00FFFFE0)
    clear((w & 0x7E000000) == 0x34000000, 0x00FFFFE0)
    clear((w & 0x7E000000) == 0x36000000, 0x0007FFE0)
    clear((w & 0x1F000000) == 0x10000000, 0x60FFFFE0)
    clear((w & 0x3B000000) == 0x18000000, 0x00FFFFE0)
    if loose:
        # ponytail: every add/sub-imm and ldr/str-imm12 offset; port() reports which window words differ. Masking
        # only imm12s based on a preceding adrp loses 4 of the 23 dkb458752 sites (struct offsets moved).
        clear((w & 0x1F000000) == 0x11000000, 0x003FFC00)
        clear((w & 0x3B000000) == 0x39000000, 0x003FFC00)
    return w & m


class Img:
    def __init__(self, path):
        self.nso = Nso(str(path))
        self.lo, n = self.nso.text
        self.words = np.frombuffer(bytes(self.nso.image[self.lo:self.lo + n]), '<u4')
        self.size = self.nso.size
        self.page = (self.size + 0xFFF) & ~0xFFF   # offset from main's base (recomp/patches.py load)
        self._masked = {}

    def word(self, off):
        return int(self.words[(off - self.lo) // 4])

    def masked(self, loose):
        if loose not in self._masked:
            self._masked[loose] = mask(self.words, loose)
        return self._masked[loose]

    def find(self, off, new, loose):
        i = (off - self.lo) // 4
        assert WIN <= i < len(self.words) - WIN, f'{off:x}: window outside .text'
        want = self.masked(loose)[i - WIN:i + WIN + 1]
        m = new.masked(loose)
        n = len(m)
        ok = np.ones(n - 2 * WIN, dtype=bool)
        for k in range(2 * WIN + 1):
            ok &= m[k:n - 2 * WIN + k] == want[k]
        return [new.lo + 4 * (int(j) + WIN) for j in np.nonzero(ok)[0]]


def bl_target(w, off):
    return off + ((((w & 0x3FFFFFF) ^ 0x2000000) - 0x2000000) << 2)


def bl_word(off, target):
    d = (target - off) >> 2
    assert -(1 << 25) <= d < (1 << 25) and (target - off) % 4 == 0
    return BL | d & 0x3FFFFFF


def parse(path):
    """[(line, kind, fields)] kind: 'set' | 'site' | 'text'."""
    out = []
    for raw in Path(path).read_text().splitlines():
        body, _, tail = raw.partition('#')
        f = body.split()
        out.append((raw, f[0] if f and f[0] in ('set', 'site') else 'text', f, tail.strip()))
    return out


def port(old, new, lines, sibling, drop, log):
    """New text lines, plus {old offset: new offset}."""
    moved, done = {}, []
    sites = [(int(f[3], 16), f) for _, k, f, _ in lines if k == 'site' and f[1] not in drop]
    for sib_new, sib_old in sibling.items():
        assert sib_new in dict(sites) and sib_old in dict(sites), f'--sibling: {sib_new:x}={sib_old:x} are not both sites'
    for off, f in sites:
        if off in sibling:
            continue
        hits, how = old.find(off, new, False), 'strict'
        if not hits:
            hits, how = old.find(off, new, True), 'loose'
        if len(hits) != 1:
            log.append(f'{off:x}: {len(hits)} {how} matches, unresolved')
            continue
        moved[off] = (hits[0], how)
        if how != 'strict':
            k = [d for d in range(-WIN, WIN + 1) if old.word(off + 4 * d) != new.word(hits[0] + 4 * d)
                 and old.masked(False)[(off - old.lo) // 4 + d] != new.masked(False)[(hits[0] - new.lo) // 4 + d]]
            log.append(f'{off:x} -> {hits[0]:x}: loose window match, imm12 words differ at {k}')
    for off, f in sites:
        if off in sibling:
            sib = sibling[off]
            if sib not in moved:
                log.append(f'{off:x}: sibling {sib:x} not matched')
                continue
            to = off + moved[sib][0] - sib
            moved[off] = (to, 'sibling')
            log.append(f'{off:x} -> {to:x}: by the delta of {sib:x}')
    return moved


def translate(old, new, off, f, to, log):
    """Replacement words for a site at the new offset; None when it needs a human."""
    orig = int(f[4], 16)
    have = new.word(to)
    repl = []
    if have != orig and orig & 0x9F000000 == 0x90000000 and have & 0x9F000000 == 0x90000000:
        # adrp: the window match fixes the register; the page it names is the new image's own
        nxt = 'equal' if new.word(to + 4) == old.word(off + 4) else 'DIFFERS'
        log.append(f'{off:x} -> {to:x}: adrp original takes the new word (next word {nxt}); '
                   'check the symbol it addresses')
    elif have != orig:
        if orig >> 26 != 0x25 or have >> 26 != 0x25:
            log.append(f'{off:x} -> {to:x}: original word differs and is not a bl, dropped')
            return None
        ot, nt = bl_target(orig, off), bl_target(have, to)
        same = all(old.word(ot + 4 * k) == new.word(nt + 4 * k) for k in range(8))
        log.append(f'{off:x} -> {to:x}: bl original re-targeted ({nt - ot:+#x}, '
                   f'first 8 words {"equal" if same else "DIFFER"})')
        if not same:
            return None
    for w in f[5:]:
        if w.startswith('@page'):
            repl.append(w)
            continue
        v = int(w, 16)
        if v == orig:
            v = have
        elif v >> 26 != 0x25 and mask(np.array([v], np.uint32), False)[0] != v:
            log.append(f'{off:x} -> {to:x}: replacement {v:08x} is PC-relative and not the original, dropped')
            return None
        elif v >> 26 == 0x25:
            pt = bl_target(v, off)
            if not old.page <= pt < old.page + 0x1000:
                log.append(f'{off:x} -> {to:x}: bl replacement outside the page, dropped')
                return None
            v = bl_word(to, new.page + pt - old.page)
        repl.append(f'{v:08x}')
    return repl


def run(args):
    old, new = Img(args.old_main), Img(args.new_main)
    lines = parse(args.table_from)
    drop = set(args.drop)
    sibling = dict(s.split('=') for s in args.sibling)
    sibling = {int(a, 16): int(b, 16) for a, b in sibling.items()}
    log = []
    moved = port(old, new, lines, sibling, drop, log)
    out = []
    # drop a blank-line separated paragraph whose set / site lines all belong to a dropped set
    paras, cur = [], []
    for ln in lines:
        cur.append(ln)
        if not ln[0].strip():
            paras.append(cur)
            cur = []
    paras.append(cur)
    stats = {}
    for p in paras:
        keys = [f[1] for _, k, f, _ in p if k in ('set', 'site')]
        if keys and all(k in drop for k in keys):
            log.append(f'dropped set {keys[0]} and its comments')
            continue
        for raw, kind, f, tail in p:
            if kind == 'site':
                off = int(f[3], 16)
                if off not in moved:
                    log.append(f'{off:x}: not ported')
                    continue
                to, how = moved[off]
                repl = translate(old, new, off, f, to, log)
                if repl is None:
                    continue
                stats[f[1]] = stats.get(f[1], 0) + 1
                note = f'  # {tail}' if tail else ''
                if off != to:
                    note += f'  [1.0.0 {off:x}]' if tail else f'  # 1.0.0 {off:x}'
                out.append(f'site {f[1]} main {to:x} {f"{new.word(to):08x}"} '
                           + ' '.join(repl) + note)
            elif not raw.startswith('# Code patches for'):
                out.append(raw.replace(f'main+0x{old.page:x}', f'main+0x{new.page:x}'))
    return out, log, moved, stats, old, new


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='src', default='dkb100')
    ap.add_argument('--to', dest='dst', default='dkb458752')
    ap.add_argument('--from-main', type=Path)
    ap.add_argument('--to-main', type=Path)
    ap.add_argument('--table', type=Path, help='table to port (default recomp/patches-<from>.txt)')
    ap.add_argument('--out', type=Path, help='output (default recomp/patches-<to>.txt)')
    ap.add_argument('--drop', action='append', help='set to leave out (default hidproxy)')
    ap.add_argument('--sibling', action='append', default=[], metavar='NEW=OLD',
                    help='place site NEW at the delta of site OLD (hex offsets, 1.0.0 side)')
    ap.add_argument('--self-check', action='store_true')
    a = ap.parse_args()
    a.drop = a.drop or ['hidproxy']
    ex = ROOT / 'build/extracted'
    a.old_main = a.from_main or ex / a.src / 'exefs/main'
    a.new_main = a.old_main if a.self_check else (a.to_main or ex / a.dst / 'exefs/main')
    a.table_from = a.table or ROOT / f'recomp/patches-{a.src}.txt'
    if a.self_check:
        a.sibling = []
    out, log, moved, stats, old, new = run(a)
    for m in log:
        print(m, file=sys.stderr)
    if a.self_check:
        bad = [f'{o:x}->{t:x}' for o, (t, _) in moved.items() if o != t]
        assert not bad, f'nonzero deltas: {bad}'
        want = sum(1 for _, k, f, _ in parse(a.table_from) if k == 'site' and f[1] not in a.drop)
        assert len(moved) == want and sum(stats.values()) == want, f'{len(moved)}/{sum(stats.values())} of {want} sites'
        print(f'self-check ok: {len(moved)} sites, all deltas 0', file=sys.stderr)
        return
    want = sum(1 for _, k, f, _ in parse(a.table_from) if k == 'site' and f[1] not in a.drop)
    if sum(stats.values()) != want:
        sys.exit(f'only {sum(stats.values())} of {want} sites ported (see above); table not written')
    print(f'ported per set: {stats}; page main+{new.page:#x}', file=sys.stderr)
    dst = a.out or ROOT / f'recomp/patches-{a.dst}.txt'
    head = [f'# Code patches for Donkey Kong Bananza {a.dst[3:]} main (recomp/patches.py), ported from {a.src} by',
            f'# tools/port_patches.py. Each original word is checked against main. Offsets inside comments, and',
            f'# "[1.0.0 xxx]" tags, are {a.src} addresses. hidproxy is gone: the controller constructor calls',
            f'# InitializeNpad directly (main+0x758650, a {a.dst[3:]} address) and the host overrides that.', '']
    dst.write_text('\n'.join(head + out) + '\n', newline='\n')


if __name__ == '__main__':
    main()
