"""Direct mouse input and Bananza camera regressions, without game files or a GPU.

Usage: python tests/dkb_camera_test.py --cc /path/to/clang
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

src = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--cc', default=os.environ.get('CC') or shutil.which('clang'))
args = ap.parse_args()
if not args.cc:
    ap.error('pass --cc with the project Clang executable')
out = src/'build/tests/dkb-camera'
out.mkdir(parents=True, exist_ok=True)
# Compile the actual sampling functions with a fake window backend and real cfg.c. This keeps
# the test independent of SDL, a foreground window and game files while exercising live settings.
source = (src/'runtime/input.c').read_text()
functions = source[source.index('static float mouse_sens ='):source.index('static float stick_dead =')]
functions += source[source.index('int input_mouse_direct('):source.index('int input_cursor_allowed(')]
code = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "cfg.h"
#include "platform/platform.h"
const int rt_game_version = 0; // Bananza; cfg_meta_at filters game-specific settings
static PlatMutex lock=PLAT_MUTEX_INIT;
static int g_block,g_menu;
static struct { uint64_t frames; } gfx_counters;
static int captured=1,foreground=1;
static int32_t mx,my;
static int patch_on;
static int patch_lookups, patch_switches;
static int fallback_calls;
static uint64_t now_ns=1000000000ull;
static double fallback_dt;
uint64_t plat_now_ns(void) { return now_ns; }
void input_mouse_stick(int32_t dx,int32_t dy,double dt,float sens,int32_t out[2]) {
    fallback_dt=dt; (void)sens; fallback_calls++;out[0]=dx;out[1]=dy;
}
int rt_patch_set(const char *name) { assert(!strcmp(name,"mousecamera")); patch_lookups++; return 0; }
void rt_patch_switch(int set,int on) { assert(set==0);patch_switches++;patch_on=on; }
int ikb_captured(void) {return captured;}
int ikb_foreground(void) {return foreground;}
void ikb_mouse_take(int32_t *x,int32_t *y) {*x=mx;*y=my;mx=my=0;}
void plat_mutex_lock(PlatMutex *m) {(void)m;}
void plat_mutex_unlock(PlatMutex *m) {(void)m;}
void rt_fatal(const char *f,...) {(void)f;abort();}
void rt_log(const char *f,...) {(void)f;}
uint8_t *plat_file_read(const char *p,uint64_t *s) {abort();}
int plat_file_exists(const char *p) {abort();}
int64_t plat_file_size(const char *p) {abort();}
int plat_file_write_atomic(const char *p,const void *d,size_t n) {abort();}
int plat_exe_path(char *p,size_t n) {abort();}
'''+functions+r'''
int main(void) {
    float d[2]; cfg_set("TOTK_DEVICE_PROFILE","desktop");cfg_set("TOTK_MOUSE_SENS","1");
    mx=100;assert(!input_mouse_direct(d));assert(!patch_on && mx==100); // opt-in, no fallback counts lost
    assert(patch_lookups==1 && patch_switches==1);
    for (int i=0;i<1000;i++) assert(!mouse_direct_mode());
    assert(patch_lookups==1 && patch_switches==1); // idle polling must not touch the patch switch
    cfg_set("TOTK_MOUSE_CAMERA","1");
    mx=100; input_mouse_direct(d);assert(d[0]==0); // entering manual view drops old motion
    assert(patch_on && patch_switches==2);
    for (int i=0;i<1000;i++) assert(mouse_direct_mode());
    assert(patch_lookups==1 && patch_switches==2);
    gfx_counters.frames++;mx=100;my=-50;input_mouse_direct(d);
    assert(fabsf(d[0]-6.4f)<.00001f && fabsf(d[1]+3.2f)<.00001f);
    input_mouse_direct(d);assert(d[0]==0 && d[1]==0); // consume exactly once
    int32_t stick[2];mx=100;mouse_camera(stick);
    assert(stick[0]==0 && stick[1]==0 && mx==100 && fallback_calls==0);
    input_mouse_direct(d);assert(fabsf(d[0]-6.4f)<.00001f && mx==0);
    cfg_set("TOTK_MOUSE_SENS","5");mx=100;input_mouse_direct(d);assert(fabsf(d[0]-32)<.00001f);
    cfg_set("TOTK_MOUSE_CAMERA","0");mx=100;assert(!input_mouse_direct(d));assert(!patch_on && mx==100);
    mouse_camera(stick);assert(stick[0]==0 && mx==0 && fallback_calls==0); // discard the direct-camera backlog
    gfx_counters.frames++;now_ns+=16666667;mx=100;mouse_camera(stick);
    assert(stick[0]==100 && mx==0 && fallback_calls==1 && fabs(fallback_dt-1.0/60)<1e-8);
    cfg_set("TOTK_MOUSE_CAMERA","1");input_mouse_direct(d);assert(patch_on && d[0]==0);
    assert(patch_lookups==1 && patch_switches==5); // sensitivity change, off, then on
    cfg_set("TOTK_MOUSE_SENS","0");mx=100;assert(!input_mouse_direct(d));assert(d[0]==0);
    cfg_set("TOTK_MOUSE_SENS","1");mx=2000;input_mouse_direct(d);assert(fabsf(d[0]-128)<.00001f);
    gfx_counters.frames+=10;mx=100;input_mouse_direct(d);assert(d[0]==0);
    gfx_counters.frames++;mx=100;input_mouse_direct(d);assert(fabsf(d[0]-6.4f)<.00001f);
    captured=0;mx=100;assert(!input_mouse_direct(d));assert(d[0]==0 && mx==0);captured=1;
    foreground=0;mx=100;assert(!input_mouse_direct(d));assert(d[0]==0);foreground=1;
    g_menu=1;mx=100;assert(!input_mouse_direct(d));assert(d[0]==0);g_menu=0;
    g_block=1;mx=100;assert(!input_mouse_direct(d));assert(d[0]==0);g_block=0;
    cfg_set("TOTK_INPUT","none");mx=100;assert(!input_mouse_direct(d));assert(d[0]==0);
    cfg_set("TOTK_INPUT","auto");
    // Leaving follow mode: suppress up to two frames, then discard the accumulated batch exactly once.
    input_mouse_direct(d);int calls=fallback_calls;
    for (int i=0;i<3;i++) {
        mx+=300;my-=150;mouse_camera(stick);
        assert(!stick[0] && !stick[1] && fallback_calls==calls && input_mouse_direct_recent());
        gfx_counters.frames++;now_ns+=16666667;
    }
    assert(!input_mouse_direct_recent());mouse_camera(stick);
    assert(!stick[0] && !stick[1] && !mx && !my && fallback_calls==calls);
    mx=30;my=-15;mouse_camera(stick);assert(!stick[0] && mx==30); // held zero for this frame
    gfx_counters.frames++;now_ns+=16666667;mouse_camera(stick);
    assert(stick[0]==30 && stick[1]==-15 && fallback_calls==calls+1 && fabs(fallback_dt-1.0/60)<1e-8);
    mouse_camera(stick);assert(stick[0]==30 && fallback_calls==calls+1); // hold the fresh sample
    // Capture loss drains pending counts; returning to fallback must not replay them either.
    input_mouse_direct(d);mouse_camera(stick);captured=0;mx=900;mouse_camera(stick);
    assert(!stick[0] && !mx);captured=1;mouse_camera(stick);assert(!stick[0]);
    puts("PASS: raw distance, live sensitivity 0/1/5, one-time consumption, camera transitions, focus, menu, text entry, disabled input");
}
'''
(out/'input_test.c').write_text(code)

suffix = '.exe' if os.name == 'nt' else ''
for name, sources in [
    ('input_test', [out/'input_test.c', src/'runtime/cfg.c']),
    ('camera_test', [src/'tests/dkb_camera.c']),
]:
    exe = out/(name+suffix)
    subprocess.run([args.cc, '-O2', '-fno-strict-aliasing', '-ffunction-sections', '-fdata-sections',
                    '-fuse-ld=lld', '-Wl,--gc-sections',
                    *(['-Wl,--exclude-all-symbols'] if os.name == 'nt' else []),
                    *(['-pthread'] if os.name != 'nt' else []),
                    '-I', str(src/'runtime'), *[str(p) for p in sources], '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=20)
