"""CPU preflight of the actual original same-submission GS ordering helper.

NVN types/enums and the production helper execute unchanged. NVN recording,
completion, GPU readback, prefix setup and pixels use bounded stateful spies.
These checks establish the helper's guard/order contract, not GPU visibility.
The omitted-barrier control executes only this CPU model, never Vulkan.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from nvn2_compute_c0_test import function

ROOT = Path(__file__).resolve().parents[1]


def source(omit_barrier=False):
    production = (ROOT / "runtime/vk_geometry_probe.c").read_text()
    constants = production[production.index("enum { GP_CONTROL"):]
    constants = constants[:constants.index("};") + 2]
    require = production[production.index("#define GP_REQUIRE("):]
    require = require[:require.index("\n\n")]
    helper = function(production, "static int gp_ordered(")
    if omit_barrier:
        start = helper.index("    GP_CALL(nvnCommandBufferBarrier,")
        end = helper.index(";", start) + 1
        helper = helper[:start] + "    /* CPU-only omitted barrier. */" + helper[end:]
    before = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nvn.h"
@CONSTANTS@
static NVNcommandBuffer gp_command;
static NVNmemoryPool gp_memory_pool;
static NVNprogram gp_plain_program;
static unsigned gp_checks,gp_failures,checks,failures;
static int gp_passthrough;
#define CHECK(c,m) do { checks++; if(!(c)){failures++;fprintf(stderr,"FAIL: %s\n",m);} } while(0)
#define GP_U(p) ((uint64_t)(uintptr_t)(p))
@REQUIRE@
enum { GOOD, RESET_SUBMIT_FAIL, RESET_READ_FAIL, RESET_CANARY_FAIL, RESET_COUNT_FAIL,
       RESET_INSTANCE_FAIL, SECOND_SUBMIT_FAIL, PIXELS_FAIL, ORIENTATION_FAIL,
       FINAL_READ_FAIL, FINAL_CANARY_FAIL, FINAL_RECORD_FAIL };
static unsigned mode,nvn_calls,submits,reads,pixels,prefixes,directs,indirects,barriers;
static unsigned completed,recording,copy_recorded,producer_recorded,consumer_recorded,barrier_recorded;
static unsigned program_bound,vertex_bound,green_visible,pixel_orientation;
static uint8_t *owned_memory;
static void *owned_control;
static uint8_t gpu_guard[256],pending_guard[256];
static char events[96];static unsigned event_count;
static void event(char c){if(event_count>=sizeof events-1)abort();events[event_count++]=c;events[event_count]=0;}
static int words_equal(const uint8_t *bytes,const uint32_t expected[5]) {
    for(unsigned i=0;i<5;i++){uint32_t n;memcpy(&n,bytes+i*4,4);if(n!=expected[i])return 0;}return 1;
}
static const uint32_t reset_words[5]={0,1,0,0,0},produced_words[5]={3,1,0,0,0};
static uint64_t call(const char *name,const uint64_t args[8]) {
    nvn_calls++;
    if(!strcmp(name,"nvnMemoryPoolFlushMappedRange")) {
        event('F');CHECK(!recording && !submits,"reset source flush precedes recording");
        CHECK(args[0]==GP_U(&gp_memory_pool) && args[1]==GP_RESET && args[2]==20,"flush covers only owned reset source");
        CHECK(words_equal(owned_memory+GP_RESET,reset_words),"reset source is exact safe zero-count record");
        CHECK(GP_RESET>=GP_GUARD+sizeof gpu_guard || GP_RESET+20<=GP_GUARD,"reset source is outside protected argument guard");
    } else if(!strcmp(name,"nvnCommandBufferAddControlMemory")) {
        event('A');CHECK(!recording && !submits,"reset command control is added before recording");
        CHECK(args[0]==GP_U(&gp_command) && args[1]==GP_U(owned_control) && args[2]==GP_COMMAND_CONTROL,"reset control allocation and extent are owned");
    } else if(!strcmp(name,"nvnCommandBufferBeginRecording")) {
        event('B');CHECK(!recording && !submits && args[0]==GP_U(&gp_command),"reset recording begins once");recording=1;
    } else if(!strcmp(name,"nvnCommandBufferCopyBufferToBuffer")) {
        event('C');CHECK(recording && !submits && !copy_recorded,"reset copy is the first submission's operation");
        CHECK(args[0]==GP_U(&gp_command) && args[1]==GP_U(owned_memory+GP_RESET) &&
              args[2]==GP_U(owned_memory+GP_RECORD) && args[3]==20 && !args[4],"reset copy has exact owned source, destination, length and flags");
        memcpy(pending_guard,gpu_guard,sizeof gpu_guard);memcpy(pending_guard+128,owned_memory+GP_RESET,20);copy_recorded=1;
    } else if(!strcmp(name,"nvnCommandBufferDrawArrays")) {
        event('D');CHECK(recording && completed==1 && prefixes==1 && reads==1,"GS producer follows completed verified reset");
        CHECK(args[0]==GP_U(&gp_command) && args[1]==NVN_DRAW_PRIMITIVE_TRIANGLES && !args[2] && args[3]==3,
              "producer draws exactly three authored triangle vertices");
        memcpy(pending_guard,gpu_guard,sizeof gpu_guard);memcpy(pending_guard+128,produced_words,20);
        producer_recorded=1;directs++;
    } else if(!strcmp(name,"nvnCommandBufferBarrier")) {
        event('O');CHECK(recording && producer_recorded && !consumer_recorded && submits==1,"barrier is between producer and consumer without submission");
        CHECK(args[0]==GP_U(&gp_command) && args[1]==(NVN_BARRIER_ORDER_PRIMITIVES_BIT|NVN_BARRIER_ORDER_INDIRECT_DATA_BIT),
              "barrier requests exact primitive and indirect-data ordering");
        memcpy(gpu_guard,pending_guard,sizeof gpu_guard);barrier_recorded=1;barriers++;
    } else if(!strcmp(name,"nvnCommandBufferBindProgram")) {
        event('K');CHECK(recording && producer_recorded && !consumer_recorded,"plain program replaces producer stages before consumer");
        CHECK(args[0]==GP_U(&gp_command) && args[1]==GP_U(&gp_plain_program) &&
              args[2]==(NVN_SHADER_STAGE_VERTEX_BIT|NVN_SHADER_STAGE_FRAGMENT_BIT),"consumer selects only the plain VS/FS program");
        program_bound=1;
    } else if(!strcmp(name,"nvnCommandBufferBindVertexBuffer")) {
        event('V');CHECK(recording && producer_recorded && program_bound && !consumer_recorded,"green vertex source binds before consumer");
        CHECK(args[0]==GP_U(&gp_command) && !args[1] && args[2]==GP_U(owned_memory+GP_VERTEX) && args[3]==96,
              "consumer uses exactly the three owned green vertices");vertex_bound=1;
    } else if(!strcmp(name,"nvnCommandBufferDrawElementsIndirect")) {
        event('I');CHECK(recording && producer_recorded && program_bound && vertex_bound && completed==1 && reads==1 && pixels==0,
              "indirect consumes in the producer submission with no intervening completion, readback or pixels");
        CHECK(args[0]==GP_U(&gp_command) && args[1]==NVN_DRAW_PRIMITIVE_TRIANGLES && args[2]==NVN_INDEX_TYPE_UNSIGNED_SHORT &&
              args[3]==GP_U(owned_memory+GP_INDEX) && args[4]==GP_U(owned_memory+GP_RECORD),"indirect source and index type are exact owned bounds");
        uint16_t indices[3];memcpy(indices,owned_memory+GP_INDEX,sizeof indices);
        CHECK(indices[0]==0 && indices[1]==1 && indices[2]==2,"all consumed indices address the three owned vertices");
        // This CPU oracle intentionally exposes a zero-count record without the
        // required dependency; it makes no hardware scheduling claim.
        green_visible=words_equal(gpu_guard+128,produced_words);consumer_recorded=1;indirects++;
    } else {CHECK(0,"unexpected NVN helper dependency");}
    return 1;
}
#define GP_CALL(n,...) call(#n,(const uint64_t[8]){__VA_ARGS__})
static void gp_prefix(uint8_t *memory,void *control,int indirect) {
    event('P');CHECK(memory==owned_memory && control==owned_control && !indirect,"producer prefix selects the original full program");
    CHECK(completed==1 && submits==1 && reads==1 && !recording,"prefix begins the single ordered producer/consumer submission after reset readback");
    recording=1;prefixes++;
}
static int gp_submit(void) {
    event('S');submits++;
    CHECK(recording,"submission completes an open command recording");recording=0;
    if(submits==1) {
        CHECK(copy_recorded && !producer_recorded && !consumer_recorded,"first submission contains reset copy only");
        if(mode==RESET_SUBMIT_FAIL)return 0;
        memcpy(gpu_guard,pending_guard,sizeof gpu_guard);
    } else {
        CHECK(submits==2 && producer_recorded && consumer_recorded,"exactly one later submission contains both producer and consumer");
        if(mode==SECOND_SUBMIT_FAIL)return 0;
        memcpy(gpu_guard,pending_guard,sizeof gpu_guard);
    }
    completed++;return 1;
}
static int gp_read_gpu(uint64_t address,void *out,uint64_t size) {
    event('R');reads++;
    CHECK(!recording && address==GP_U(owned_memory+GP_GUARD) && size==sizeof gpu_guard,"readback covers only the entire owned guard after completion");
    CHECK((reads==1 && completed==1 && !producer_recorded) || (reads==2 && completed==2 && consumer_recorded),
          "readback occurs only after reset or the completed ordered submission");
    if((reads==1 && mode==RESET_READ_FAIL) || (reads==2 && mode==FINAL_READ_FAIL))return 0;
    memcpy(out,gpu_guard,sizeof gpu_guard);uint8_t *bytes=out;
    if((reads==1 && mode==RESET_CANARY_FAIL) || (reads==2 && mode==FINAL_CANARY_FAIL))bytes[255]^=1;
    if(reads==1 && mode==RESET_COUNT_FAIL)bytes[128]=1;
    if(reads==1 && mode==RESET_INSTANCE_FAIL)bytes[132]=2;
    if(reads==2 && mode==FINAL_RECORD_FAIL)bytes[128]=0;
    return 1;
}
static int gp_pixels(uint32_t *out,uint32_t color,int *orientation) {
    event('X');pixels++;
    CHECK(!recording && completed==2 && indirects==1 && reads==1,"pixels are read after the sole ordered submission completes");
    CHECK(color==0xff00ff00u,"success oracle requests the green indirect triangle");
    memset(out,0,GP_WIDTH*GP_HEIGHT*sizeof *out);
    *orientation=(int)(mode==ORIENTATION_FAIL?!pixel_orientation:pixel_orientation);
    if(mode==PIXELS_FAIL || !green_visible){*orientation=-1;return 0;}
    return 1;
}
'''.replace("@CONSTANTS@", constants).replace("@REQUIRE@", require)
    after = r'''
static void setup(unsigned test_mode,uint8_t verified[256]) {
    mode=test_mode;nvn_calls=submits=reads=pixels=prefixes=directs=indirects=barriers=completed=recording=0;
    copy_recorded=producer_recorded=consumer_recorded=barrier_recorded=program_bound=vertex_bound=green_visible=0;
    gp_checks=gp_failures=event_count=pixel_orientation=0;events[0]=0;gp_passthrough=1;
    memset(owned_memory,0x3c,GP_POOL);memset(gpu_guard,0xa5,sizeof gpu_guard);memcpy(gpu_guard+128,produced_words,20);
    memcpy(verified,gpu_guard,256);memcpy(owned_memory+GP_GUARD,gpu_guard,256);
    const uint16_t indices[3]={0,1,2};memcpy(owned_memory+GP_INDEX,indices,sizeof indices);
    static const float green[3][8]={{-.75f,-.75f,0,1,0,1,0,1},{.75f,-.75f,0,1,0,1,0,1},{0,.75f,0,1,0,1,0,1}};
    memcpy(owned_memory+GP_VERTEX,green,sizeof green);
}
int main(void) {
    owned_memory=malloc(GP_POOL);owned_control=malloc(GP_COMMAND_CONTROL);if(!owned_memory || !owned_control)return 2;
    uint8_t verified[256];setup(GOOD,verified);
    CHECK(gp_ordered(owned_memory,owned_control,GP_U(owned_memory+GP_RECORD),verified,0),"positive actual helper passes unchanged success oracle");
    CHECK(gp_checks && !gp_failures && submits==2 && completed==2 && reads==2 && prefixes==1 && directs==1 && indirects==1 && barriers==1 && pixels==1,
          "positive path has exactly one reset and one producer/consumer submission");
    CHECK(!strcmp(events,"FABCSRPDOKVISXR"),"positive helper calls follow exact reset/preflight/ordered-draw/postcheck sequence");
    CHECK(words_equal(owned_memory+GP_RESET,reset_words),"reset source remains exactly bounded after helper completion");
    CHECK(!memcmp(owned_memory+GP_GUARD,verified,256),"host guard bytes are not rewritten to fabricate GPU output");
    setup(GOOD,verified);pixel_orientation=1;
    CHECK(gp_ordered(owned_memory,owned_control,GP_U(owned_memory+GP_RECORD),verified,1),"positive flipped orientation uses the unchanged success oracle");
    for(unsigned bad=0;bad<7;bad++) {
        setup(GOOD,verified);if(bad==5)gp_passthrough=0;
        CHECK(!gp_ordered(bad==0?NULL:owned_memory,bad==1?NULL:owned_control,
              GP_U(owned_memory+GP_RECORD)+(bad==2?4:0),bad==6?NULL:verified,bad==3?-1:bad==4?2:0),
              "invalid owned-input/address/orientation/passthrough/prior-proof guard rejects");
        CHECK(!nvn_calls && !submits && !reads && !prefixes && !indirects,"invalid owned-input guard rejects before any NVN operation");
    }
    for(unsigned bad=0;bad<7;bad++) {
        setup(GOOD,verified);if(bad<2)verified[bad?255:0]^=1;else verified[128+(bad-2)*4]^=1;
        CHECK(!gp_ordered(owned_memory,owned_control,GP_U(owned_memory+GP_RECORD),verified,0),"bad prior canary/record preflight rejects");
        CHECK(!nvn_calls && !submits && !reads && !prefixes && !indirects,"invalid prior readback never records NVN commands");
    }
    for(unsigned fault=RESET_SUBMIT_FAIL;fault<=FINAL_RECORD_FAIL;fault++) {
        setup(fault,verified);
        CHECK(!gp_ordered(owned_memory,owned_control,GP_U(owned_memory+GP_RECORD),verified,0),"completion/readback/pixel fault rejects helper success");
        if(fault<=RESET_INSTANCE_FAIL)CHECK(!prefixes && !producer_recorded && !indirects && !pixels,
            "failed reset verification never reaches producer or indirect consumer");
        else CHECK(submits==2 && prefixes==1 && indirects==1,"post-production fault preserves single ordered submission structure");
    }
    printf("geometry ordering helper: %u checks, %u failures\n",checks,failures);
    free(owned_control);free(owned_memory);return failures!=0;
}
'''
    return before + helper + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC") or shutil.which("clang"))
    parser.add_argument("--out", type=Path, default=ROOT / "build/checks/geometry-ordering-probe")
    parser.add_argument("--controls", action="store_true", help="run CPU-only missing-barrier counterexample")
    args = parser.parse_args()
    if not args.cc:
        parser.error("pass --cc")
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for omit in ((False, True) if args.controls else (False,)):
        name = "no-barrier" if omit else "fixed"
        c = args.out / (name + ".c")
        c.write_text(source(omit))
        for opt in ("-O0", "-O2"):
            exe = args.out / (name + opt + (".exe" if os.name == "nt" else ""))
            command = [args.cc, opt, "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "runtime"), str(c), "-o", str(exe)]
            run = subprocess.run(command, capture_output=True, text=True)
            (args.out / (name + opt + "-compile.log")).write_text(run.stdout + run.stderr)
            if run.returncode:
                print(run.stdout + run.stderr)
                return run.returncode
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            (args.out / (name + opt + "-run.log")).write_text(run.stdout + run.stderr)
            expected = run.returncode == (1 if omit else 0)
            if omit:
                expected &= "positive actual helper passes unchanged success oracle" in run.stderr
            results.append(dict(name=name, opt=opt, command=command, exit_code=run.returncode, expected=expected,
                                stdout=run.stdout, stderr=run.stderr))
            print(name, opt, run.stdout.strip().splitlines()[-1])
            if not expected:
                print(run.stdout + run.stderr)
                return 1
    runtime = ROOT / "runtime/vk_geometry_probe.c"
    report = dict(results=results, runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
                  helper_sha256=hashlib.sha256(function(runtime.read_text(), "static int gp_ordered(").encode()).hexdigest(),
                  limitations=["CPU-only actual helper; all NVN recording, completion, GPU backing/readback and pixel work are stateful providers.",
                               "The missing-barrier provider exposes stale zero-count args intentionally; this is not a hardware scheduling result.",
                               "No loader, GPU, native lowering or game inputs are executed."])
    (args.out / "results.json").write_text(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
