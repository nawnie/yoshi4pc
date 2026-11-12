"""Exercise the actual Vulkan uniform texture reads without requiring a GPU."""
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nvn2_compute_c0_test import function

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'runtime/vk_exec_draw.c').read_text()
shim = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "gfx_texture_handle.h"
typedef struct { uint64_t addr, size; } p_bind_buf;
typedef struct { uint64_t fence; p_bind_buf ubo[6][18]; } VkExec;
typedef struct { int unused; } VkMemSpan;
typedef struct { int32_t texture_cbuf_slots; uint32_t texture_handle; } GfxShaderRes;
typedef struct { const VkExec *ex; int stage; } YoshiTextureRead;
#define UPD_N 4096
static struct { uint64_t fence; uint32_t n; struct { uint64_t lo,hi; const uint8_t *data; } u[UPD_N]; } UPD;
static void rt_log(const char *format, ...) { (void)format; }
static uint64_t valid_lo, valid_hi;
static int vk_mem_resolve(uint64_t addr, uint64_t size, VkMemSpan *span) {
    (void)span; return addr >= valid_lo && addr <= valid_hi && size <= valid_hi - addr;
}
'''
for name in ('static int upd_read(', 'static int yoshi_texture_word(', 'static uint64_t yoshi_texture_handle('):
    shim += '\n' + function(source, name) + '\n'
shim += r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "failed line %d: %s\n",__LINE__,#x); return 1; } } while (0)
int main(void) {
    uint32_t memory[8] = {0x12345,0,0,0,0xaaa00000};
    uint32_t update = 0xbbb00000;
    VkExec ex = {0}; ex.fence = 7;
    ex.ubo[1][0].addr = (uint64_t)(uintptr_t)memory;
    ex.ubo[1][0].size = sizeof memory;
    valid_lo = ex.ubo[1][0].addr; valid_hi = valid_lo + sizeof memory;
    GfxShaderRes r = {0x40003,0x10010000};
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0xaaa12345);
    UPD.fence=7; UPD.n=1; UPD.u[0].lo=valid_lo+16; UPD.u[0].hi=valid_lo+20; UPD.u[0].data=(uint8_t*)&update;
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0xbbb12345);
    uint8_t partial = 0xcc;
    UPD.u[0].lo=valid_lo+19; UPD.u[0].hi=valid_lo+20; UPD.u[0].data=&partial;
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0xcca12345);
    UPD.fence=6;
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0xaaa12345);
    ex.ubo[1][0].size=16;
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0);
    ex.ubo[1][0].size=sizeof memory; valid_hi=valid_lo+16;
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0);
    r.texture_cbuf_slots=0x50003;
    CHECK(yoshi_texture_handle(&ex,1,&r) == 0);
    puts("uniform texture reads and current update checks passed"); return 0;
}
'''
cc = os.environ.get('CC', r'D:\games\Recomps\DKB-Setup\llvm\bin\clang.exe')
with tempfile.TemporaryDirectory(prefix='yoshi-texture-test-') as tmp:
    cfile, exe = Path(tmp) / 'test.c', Path(tmp) / 'test.exe'
    cfile.write_text(shim)
    subprocess.run([cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'runtime'), str(cfile), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

