"""Check the real feedback scan sees changing uniform-backed texture handles."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nvn2_compute_c0_test import function
ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'runtime/vk_exec_draw.c').read_text()
shim = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef struct { int slot, count, dynamic; } GfxShaderRes;
typedef struct { int id; } GfxShader;
typedef struct { uint32_t value; } SubRange;
typedef struct { const GfxShader *fb_fs; uint64_t fb_serial,tex_serial,fb_pass,pass_serial; uint32_t fb_sampled; uint64_t tex[6][128]; } VkExec;
#define GFX_RES_TEX 2
#define FM_N 8192
static struct { uint64_t context,h,tok; uint32_t gen; SubRange r; } FM[FM_N];
static uint64_t descriptor_serial=1, dynamic_handle;
static GfxShaderRes resource;
static int samples;
static void descriptor_state(VkExec *e) {(void)e;}
static int gfx_shader_resources(const GfxShader *s,int k,const GfxShaderRes **r) {(void)s;(void)k;*r=&resource;return 1;}
static int yoshi_uniform_texture(const GfxShaderRes *r) {return r->dynamic;}
static uint64_t yoshi_texture_handle(const VkExec *e,int st,const GfxShaderRes *r) {(void)e;(void)st;(void)r;return dynamic_handle;}
static int gfx_shader_stage(const GfxShader *s) {(void)s;return 1;}
static int nvn_stage_of(int st) {return st;}
static uint32_t vk_texture_slots_gen(void) {return 1;}
static int td_mode(void) {return 0;}
static int slot_still(const VkExec *e,uint32_t *g,uint64_t tok,uint64_t h,uint32_t gen) {(void)e;(void)g;(void)tok;(void)h;(void)gen;return 0;}
static void vk_texture_lock(void) {}
static void vk_texture_unlock(void) {}
static SubRange sampled_sub(const VkExec *e,uint64_t h) {(void)e;samples++;return (SubRange){(uint32_t)h};}
static uint32_t attached_as(const VkExec *e,const SubRange *r) {(void)e;return r->value;}
static uint64_t token_of(const VkExec *e,uint64_t h) {(void)e;return h;}
static void rt_fatal(const char *m,...) {(void)m;abort();}
'''
shim += '\n' + function(source, 'static uint32_t feedback_scan(') + '\n'
shim += r'''
#define CHECK(x) do {if (!(x)) {fprintf(stderr,"failed line %d: %s\n",__LINE__,#x);return 1;}} while (0)
int main(void) {
    VkExec ex={0}; GfxShader shader={0}; ex.tex_serial=1; ex.pass_serial=1;
    resource=(GfxShaderRes){.slot=-1,.count=1,.dynamic=1};
    dynamic_handle=1; CHECK(feedback_scan(&ex,&shader)==1);
    dynamic_handle=2; CHECK(feedback_scan(&ex,&shader)==2); CHECK(samples==2);
    resource.dynamic=0; resource.slot=2; ex.tex[1][2]=4;
    CHECK(feedback_scan(&ex,&shader)==4); CHECK(samples==3);
    ex.tex[1][2]=8; CHECK(feedback_scan(&ex,&shader)==4); CHECK(samples==3);
    puts("uniform texture feedback rescan checks passed");return 0;
}
'''
cc=os.environ.get('CC',r'D:\games\Recomps\DKB-Setup\llvm\bin\clang.exe')
with tempfile.TemporaryDirectory(prefix='yoshi-feedback-test-') as tmp:
    cfile,exe=Path(tmp)/'test.c',Path(tmp)/'test.exe';cfile.write_text(shim)
    subprocess.run([cc,'-std=gnu11','-Wall','-Wextra','-Werror',str(cfile),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
