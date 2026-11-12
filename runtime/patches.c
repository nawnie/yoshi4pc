// Code patch sets (recomp/patches.py, gen.py --patches). The generator lifts both the original and the replacement
// instructions of every patched site, and rt_patch_on[set] picks one when the site runs, so a set is switched at start
// without touching code, and also while the game runs (rt_patch_switch: the frame-limit setting of the menu). The sets,
// their environment switches and defaults, and the patch page come from the generated patches.h; without it (C
// generated without --patches) there are no sets and every site runs the original.
//
// The patch page is the first 4 KiB page after main's image, inside the module window memory.c reserved: replacement
// code reaches it with one adrp, as MacNativeGames' data page after main (games/totk/runtime/game_patches.c). Its
// layout belongs to the sets that use it (frame_rate.c: +0 the 30 Hz ratio, +4 the frame step in seconds, +8 the
// step in 60 Hz ticks).
// Probe modes never call rt_patches_init: every set stays off.
#include "cfg.h"
#include "platform/platform.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"

#if __has_include("patches.h")
#include "patches.h"
#endif
#ifndef RT_PATCH_COUNT
#define RT_PATCH_COUNT 0
#endif

uint8_t rt_patch_on[RT_PATCH_COUNT > 0 ? RT_PATCH_COUNT : 1];   // read by the generated C at every patched site

#if RT_PATCH_COUNT
static const struct { const char *name, *env; int on; } sets[] = {
#define X(i, n, e, d) {#n, e, d},
    RT_PATCH_SETS(X)
#undef X
};
static void *page;
#endif

void rt_patches_init(void) {
#if RT_PATCH_COUNT
    if (!plat_mem_commit(RT_PATCH_PAGE, 0x1000))
        rt_fatal("patches: cannot commit the patch page at %#llx", RT_PATCH_PAGE);
    page = (void *)(uintptr_t)RT_PATCH_PAGE;
    char list[512];
    size_t n = 0;
    list[0] = 0;
    for (int i = 0; i < RT_PATCH_COUNT; i++) {
        const char *e = cfg_get(sets[i].env);
        // a set with a row in the settings table takes its default from there; the generated default serves the rest
        rt_patch_on[i] = (uint8_t)(cfg_meta(sets[i].env) ? cfg_bool(sets[i].env) : e && *e ? strcmp(e, "0") != 0 : sets[i].on);
        n += (size_t)snprintf(list + n, sizeof list - n, "%s%s %s", i ? ", " : "", sets[i].name,
                              rt_patch_on[i] ? "on" : "off");
        if (n >= sizeof list) n = sizeof list - 1;
    }
    rt_log("patches: %s (page %#llx)", list, RT_PATCH_PAGE);
#endif
}

int rt_patch_set(const char *name) {
#if RT_PATCH_COUNT
    for (int i = 0; i < RT_PATCH_COUNT; i++)
        if (!strcmp(sets[i].name, name)) return i;
#endif
    (void)name;
    return -1;
}

int rt_patch_enabled(int set) { return set >= 0 && set < RT_PATCH_COUNT && rt_patch_on[set]; }

void rt_patch_disable(int set) {
    if (set >= 0 && set < RT_PATCH_COUNT) rt_patch_on[set] = 0;
}

void rt_patch_switch(int set, int on) {
    if (set >= 0 && set < RT_PATCH_COUNT) __atomic_store_n(&rt_patch_on[set], (uint8_t)(on != 0), __ATOMIC_RELAXED);
}

void *rt_patch_page(void) {
#if RT_PATCH_COUNT
    return page;
#else
    return NULL;
#endif
}

// ---- guards (recomp/patches.py `guard`): checks of one register before game code follows it, cheap enough to run
// once per element of a hot loop (recomp/patches-dkb100.txt, poolguard, #126). A failed check sends the code to the
// guard's target instead. They read memory only once it is known to be readable.

// A guest data pointer: inside the guest address space, past the null page and 8-byte aligned. Catches the stale
// list entries whose "pointers" are float data or non-canonical.
static int guard_ok(uint64_t p) { return p >= 0x10000 && p < RT_ADDRESS_LIMIT && !(p & 7); }

// Every failed check is counted, and the first ones are logged with the value: a guard that fires in normal play
// rather than around an area change would show that something else is wrong.
static uint64_t g_guard_fails;
static int guard_fail(const char *kind, uint64_t v, uint64_t w) {
    uint64_t n = __atomic_add_fetch(&g_guard_fails, 1, __ATOMIC_RELAXED);
    if (n <= 32 || !(n & (n - 1)))
        rt_log("patches: guard %s failed (%llu so far): %#llx %#llx", kind, (unsigned long long)n, (unsigned long long)v,
               (unsigned long long)w);
    return 0;
}

// Range checks alone pass an aligned pointer into a page nothing maps (a crash at 410df0 after the first fix), so a
// pointer must also be readable over the bytes the code reads next. plat_mem_readable is a syscall, and the guards run
// once per list entry (thousands a frame), so each thread keeps the last few pages it found readable: the valid entries
// name a handful of layer records and cells, and only a stale pointer misses and pays the syscall.
#define GUARD_PAGES 16
static _Thread_local uint64_t g_good[GUARD_PAGES];
static _Thread_local unsigned g_good_next;
static int guard_readable(uint64_t p, uint64_t n) {
    uint64_t first = p >> 12, last = (p + n - 1) >> 12;
    for (uint64_t pg = first; pg <= last; pg++) {
        int hit = 0;
        for (int i = 0; i < GUARD_PAGES && !hit; i++) hit = g_good[i] == pg + 1;
        if (hit) continue;
        if (!plat_mem_readable(pg << 12, 1)) return 0;
        g_good[g_good_next++ % GUARD_PAGES] = pg + 1;
    }
    return 1;
}

// A pointer the code reads from next: a layer record (+0x30, +0x40, +0x44), a cell's +0x48 target, a cell's element
// array. 0x50 bytes cover the furthest field read at the guarded sites.
int rt_guard_ptr(uint64_t p) {
    if (!guard_ok(p)) return guard_fail("ptr", p, 0);
    return guard_readable(p, 0x50) ? 1 : guard_fail("ptr unmapped", p, 0);
}

// An object whose first word is a vtable in main and whose slot +0x10 points into main, as a devirtualised call
// expects before it loads that slot and compares or calls it. A zeroed object (a cell that was never constructed), a
// pointer into main's code, or an object whose vtable slot is gone fails it instead of calling through garbage.
int rt_guard_vcall(uint64_t obj) {
    if (!guard_ok(obj)) return guard_fail("vcall object", obj, 0);
    if (!guard_readable(obj, 0x50)) return guard_fail("vcall object unmapped", obj, 0);   // +0 vtable ... +0x48 (eb8 path)
    const RtLoaded *m = ldr_count() > 0 ? ldr_module(0) : NULL;
    if (!m) return 1;
    uint64_t data = m->base + m->data_off, end = m->base + m->size, text = m->base, text_end = m->base + m->text_end;
    uint64_t vt = *(const volatile uint64_t *)(uintptr_t)obj;
    if (vt < data || vt + 0x18 > end || (vt & 7)) return guard_fail("vcall vtable", obj, vt);   // in main's data
    uint64_t fn = *(const volatile uint64_t *)(uintptr_t)(vt + 0x10);
    return fn >= text && fn < text_end && !(fn & 3) ? 1 : guard_fail("vcall slot", obj, fn);   // code of main
}
