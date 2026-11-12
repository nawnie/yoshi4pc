"""CPU checks of the actual opt-in geometry-context logger and its passive query guards.

Actual VkExec/program/payload headers and the NVN2 classifier are used. Stage and
origin lookup, passive inspection and logging are bounded spies over original
metadata-only fixtures. No shader body, Vulkan library or GPU is executed.
Each child process starts with fresh logger environment/cache/cap state.
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


def source():
    draw = (ROOT / "runtime/vk_exec_draw.c").read_text()
    shader = (ROOT / "runtime/gfx_shader.c").read_text()
    before = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "vk_exec.h"
#define NVN_STAGE_VS 0
#define NVN_STAGE_FS 1
#define NVN_STAGE_GS 2
static unsigned checks,failures,classifications,stage_lookups,origin_lookups,passive_queries;
static unsigned contexts,buffer_logs,other_logs,inspect_fail;
#define CHECK(c,m) do {checks++;if(!(c)){failures++;fprintf(stderr,"FAIL: %s\n",m);}}while(0)
static uint8_t controls[3][0x880],code_tokens[3],compact[8];
static uint8_t buffer0[64],buffer1[128],buffer2[256];
static const uint64_t origins[3]={UINT64_C(0x0123456789abcdef),UINT64_C(0xfedcba9876543210),UINT64_C(0xa5a55a5a12345678)};
static const int stages[3]={NVN_STAGE_VS,NVN_STAGE_GS,NVN_STAGE_FS};
static char last_context[4096];
void rt_log(const char *format,...) {
    char line[4096];va_list args;va_start(args,format);
    int n=vsnprintf(line,sizeof line,format,args);va_end(args);
    CHECK(n>=0 && (size_t)n<sizeof line,"original metadata log fits the bounded capture");
    if(n<0 || (size_t)n>=sizeof line)return;
    if(!strncmp(line,"geometry_context: record=",25)) {
        contexts++;memcpy(last_context,line,(size_t)n+1);
    } else if(!strncmp(line,"geometry_buffer_context:",24))buffer_logs++;
    else other_logs++;
}
#define gfx_shader_is_nvn2 original_is_nvn2
'''
    classifier = function(shader, "int gfx_shader_is_nvn2(")
    providers = r'''
#undef gfx_shader_is_nvn2
int gfx_shader_is_nvn2(const uint8_t *control) {
    classifications++;
    CHECK(control==compact || control==controls[0] || control==controls[1] || control==controls[2],
          "classifier sees only owned control metadata");
    return original_is_nvn2(control);
}
// Stage discovery is an explicit provider. The actual logger must reject raw
// compact controls before this legacy-shaped metadata lookup is called.
static int find_stage(const prog_t *program,int stage,const uint8_t **control,const uint8_t **code,uint32_t *length) {
    stage_lookups++;
    CHECK(program && program->nstage<=6,"legacy stage provider requires a bounded program");
    if(!program || program->nstage>6)return 0;
    for(uint32_t i=0;i<program->nstage;i++) {
        const uint8_t *ctl=program->sd[i].control;
        CHECK(ctl!=compact,"compact control never reaches legacy stage provider");
        if(!ctl || ctl==compact)continue;
        uint32_t stored;memcpy(&stored,ctl+0x714,4);
        if(stored==(uint32_t)stage) {
            *control=ctl;*code=(const uint8_t *)(uintptr_t)program->sd[i].data;*length=0;return 1;
        }
    }
    return 0;
}
uint64_t nvn2_origin(const uint8_t *code) {
    origin_lookups++;
    for(unsigned i=0;i<3;i++)if(code==code_tokens+i)return origins[stages[i]];
    CHECK(0,"origin lookup never reads shader bytes or an unknown pointer");return 0;
}
int vk_mem_inspect(uint64_t address,uint64_t size,VkMemInspect *out) {
    passive_queries++;memset(out,0,sizeof *out);
    CHECK((address==(uintptr_t)buffer0 && size==sizeof buffer0) ||
          (address==(uintptr_t)buffer1 && size==sizeof buffer1) ||
          (address==(uintptr_t)buffer2 && size==sizeof buffer2),
          "passive query uses only a recorded GS range, never indirect arguments");
    if(inspect_fail)return 0;
    *out=(VkMemInspect){.offset=0,.avail=size,.pool_kind=VK_MEM_INSPECT_POOL_IMPORT,
                        .cls=VK_MCLS_HOST_CACHED,.buffer_present=1};return 1;
}
'''
    actual = "\n".join(function(draw, name) for name in (
        "static void geometry_context_buffer_log(", "static void geometry_context_log("))
    after = r'''
static void initialize(VkExec *ex,prog_t *program) {
    memset(ex,0,sizeof *ex);memset(program,0,sizeof *program);
    memset(controls,0,sizeof controls);memset(compact,0,sizeof compact);
    program->nstage=3;program->serial=17;ex->prog=program;ex->prog_stages=31;
    for(unsigned i=0;i<3;i++) {
        uint32_t stage=(uint32_t)stages[i];memcpy(controls[i]+0x714,&stage,4);
        program->sd[i]=(NVNshaderData){(NVNbufferAddress)(uintptr_t)(code_tokens+i),controls[i]};
    }
    ex->ssbo[NVN_STAGE_GS][0]=(p_bind_buf){.addr=(uintptr_t)buffer0,.size=sizeof buffer0};
    ex->ssbo[NVN_STAGE_GS][1]=(p_bind_buf){.addr=(uintptr_t)buffer1,.size=sizeof buffer1};
    ex->ubo[NVN_STAGE_GS][0]=(p_bind_buf){.addr=(uintptr_t)buffer2,.size=sizeof buffer2};
    ex->fence=23;
}
static void untouched(const VkExec *ex,const VkExec *saved,const prog_t *program,const prog_t *saved_program) {
    CHECK(!memcmp(ex,saved,sizeof *ex),"logger leaves replay POD state unchanged");
    CHECK(!memcmp(program,saved_program,sizeof *program),"logger leaves the program object unchanged");
}
static void zero_queries(void) {
    CHECK(!classifications && !stage_lookups && !origin_lookups && !passive_queries,"guard path performs no classification, stage, origin or passive queries");
    CHECK(!contexts && !buffer_logs,"guard path emits no context or buffer record");
}
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    const char *mode=argv[1];VkExec ex;prog_t program;initialize(&ex,&program);
    const VkExec saved=ex;const prog_t saved_program=program;
    p_draw direct={.prim=NVN_DRAW_PRIMITIVE_TRIANGLES,.first=3,.count=27,.base_instance=2,.instances=1};
    if(!strcmp(mode,"off")) {
        geometry_context_log(&ex,OP_DRAW,&direct);zero_queries();CHECK(!other_logs,"disabled logger emits nothing");
    } else if(!strcmp(mode,"wrong-op")) {
        geometry_context_log(&ex,OP_DISPATCH,&direct);zero_queries();CHECK(!other_logs,"wrong opcode returns before environment diagnostics");
    } else if(!strcmp(mode,"null-ex")) {
        geometry_context_log(NULL,OP_DRAW,&direct);zero_queries();
    } else if(!strcmp(mode,"null-payload")) {
        geometry_context_log(&ex,OP_DRAW,NULL);zero_queries();
    } else if(!strcmp(mode,"invalid-filter")) {
        geometry_context_log(&ex,OP_DRAW,&direct);zero_queries();CHECK(other_logs==1,"invalid filter is diagnosed once and disabled");
    } else if(!strcmp(mode,"nonmatch")) {
        geometry_context_log(&ex,OP_DRAW,&direct);
        CHECK(classifications==3 && stage_lookups==3 && origin_lookups==3,"nonmatching filter only performs bounded stage metadata lookup");
        CHECK(!passive_queries && !contexts && !buffer_logs,"nonmatching origin performs zero passive queries");
    } else if(!strcmp(mode,"zero-filter-no-program")) {
        ex.prog=NULL;geometry_context_log(&ex,OP_DRAW,&direct);zero_queries();
        ex=saved;
    } else if(!strcmp(mode,"overstage") || !strcmp(mode,"compact")) {
        if(!strcmp(mode,"overstage"))program.nstage=7;
        else {
            uint32_t magic=0x98761234,version=0xc9;memcpy(compact,&magic,4);memcpy(compact+4,&version,4);
            program.sd[0].control=compact;
        }
        geometry_context_log(&ex,OP_DRAW,&direct);
        CHECK(!stage_lookups && !origin_lookups,"overlong or compact program never enters legacy lookup");
        CHECK(classifications==(!strcmp(mode,"compact")?1u:0u),"compact guard performs only the bounded eight-byte classifier read");
        CHECK(contexts==1 && buffer_logs==3 && passive_queries==3,"unfiltered malformed program still describes recorded ranges passively");
        CHECK(strstr(last_context,"stage_metadata=unavailable")!=NULL,"malformed program metadata remains explicitly unavailable");
        program=saved_program;
    } else if(!strcmp(mode,"cap")) {
        prog_t other_program=program;other_program.serial=19;
        const prog_t other_saved=other_program;
        VkExec second=ex;second.prog=&other_program;const VkExec second_saved=second;
        for(unsigned i=0;i<25;i++)geometry_context_log(i&1?&second:&ex,OP_DRAW,&direct);
        CHECK(contexts==12 && buffer_logs==36 && passive_queries==36,"process-wide twelve-record cap permits at most thirty-six passive queries");
        CHECK(classifications==36 && stage_lookups==36 && origin_lookups==36,"cap stops all metadata lookup on subsequent draws");
        CHECK(!memcmp(&second,&second_saved,sizeof second),"shared process cap never modifies a second replay object");
        CHECK(!memcmp(&other_program,&other_saved,sizeof other_program),"process cap is shared across distinct program objects");
    } else if(!strcmp(mode,"empty-ranges")) {
        p_bind_buf empty={.addr=0,.size=64},zero={.addr=(uintptr_t)buffer0,.size=0};
        geometry_context_buffer_log(1,"empty",&empty);geometry_context_buffer_log(2,"zero",&zero);
        CHECK(!passive_queries && buffer_logs==2,"empty recorded ranges log without querying a backing");
        CHECK(!classifications && !stage_lookups && !origin_lookups,"buffer-only logger has no program dependency");
    } else {
        if(!strcmp(mode,"inspect-failure"))inspect_fail=1;
        if(!strcmp(mode,"indexed")) {
            p_draw_idx indexed={.prim=NVN_DRAW_PRIMITIVE_TRIANGLES,.itype=NVN_INDEX_TYPE_UNSIGNED_SHORT,
                .count=27,.base_vertex=4,.base_instance=2,.instances=1,.ibuf=(uintptr_t)buffer0};
            geometry_context_log(&ex,OP_DRAW_IDX,&indexed);
        } else if(!strcmp(mode,"indirect")) {
            // Original opaque GPU-address PODs are deliberately not CPU-dereferenceable.
            p_draw_idx_ind indirect={.prim=NVN_DRAW_PRIMITIVE_TRIANGLES,.itype=NVN_INDEX_TYPE_UNSIGNED_SHORT,
                .ibuf=UINT64_C(0x100000000000),.ind=UINT64_C(0x200000000000)};
            geometry_context_log(&ex,OP_DRAW_IDX_IND,&indirect);
            CHECK(strstr(last_context,"count=unknown instances=unknown")!=NULL,"indirect argument counts remain unknown");
        } else geometry_context_log(&ex,OP_DRAW,&direct);
        CHECK(contexts==1 && buffer_logs==3 && passive_queries==3,"enabled matching draw issues exactly three passive range queries");
        CHECK(classifications==3 && stage_lookups==3 && origin_lookups==3,"matching stage filter uses bounded metadata discovery");
        CHECK(!other_logs,"valid filter emits no diagnostics");
    }
    untouched(&ex,&saved,&program,&saved_program);
    printf("geometry context %s: %u checks, %u failures\n",mode,checks,failures);
    return failures!=0;
}
'''
    return before + classifier + providers + actual + after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default=os.environ.get("CC") or shutil.which("clang"))
    parser.add_argument("--deps", type=Path, required=True, help="runtime dependencies with Vulkan and VMA headers")
    args = parser.parse_args()
    if not args.cc:
        parser.error("pass --cc")
    out = ROOT / "build/test/geometry-context-log"
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / "geometry_context.c"
    fixture.write_text(source())
    cases = [("default-off", "off", None, None)]
    cases += [("toggle-" + name, "off", value, None) for name, value in (
        ("empty", ""), ("zero", "0"), ("true", "true"), ("two", "2"), ("space", "1 "))]
    cases += [(name, name, "1", None) for name in (
        "null-ex", "null-payload", "overstage", "compact", "cap", "empty-ranges", "indexed", "indirect", "inspect-failure")]
    cases += [("wrong-op", "wrong-op", "1", "not-hex")]
    cases += [("invalid-filter-" + name, "invalid-filter", "1", value) for name, value in (
        ("empty", ""), ("prefix", "0x"), ("nonhex", "not-hex"), ("space", " 1"),
        ("negative", "-1"), ("overlong", "10000000000000000"))]
    cases += [("match-" + name, "direct", "1", value) for name, value in (
        ("vs", "0123456789abcdef"), ("gs", "0xa5a55a5a12345678"), ("fs", "0XFEDCBA9876543210"))]
    cases += [("nonmatch", "nonmatch", "1", "ffffffffffffffff"),
              ("zero-filter-no-program", "zero-filter-no-program", "1", "0")]
    results = []
    for opt in ("-O0", "-O2"):
        exe = out / ("geometry_context" + opt + (".exe" if os.name == "nt" else ""))
        command = [args.cc, opt, "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "runtime"),
                   "-I", str(args.deps / "include"), "-I", str(args.deps / "include/vma"), str(fixture), "-o", str(exe)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=60)
        (out / (opt + "-compile.log")).write_text(run.stdout + run.stderr)
        if run.returncode:
            print(run.stdout + run.stderr)
            return run.returncode
        for label, mode, toggle, origin in cases:
            env = {k: v for k, v in os.environ.items() if k not in ("DKB_GEOMETRY_CONTEXT", "DKB_GEOMETRY_CONTEXT_ORIGIN")}
            if toggle is not None:
                env["DKB_GEOMETRY_CONTEXT"] = toggle
            if origin is not None:
                env["DKB_GEOMETRY_CONTEXT_ORIGIN"] = origin
            run = subprocess.run([str(exe), mode], env=env, capture_output=True, text=True, timeout=10)
            (out / (opt + "-" + label + ".log")).write_text(run.stdout + run.stderr)
            results.append(dict(opt=opt, case=label, exit_code=run.returncode, output=run.stdout + run.stderr))
            if run.returncode:
                print(label, opt, run.stdout + run.stderr)
                return run.returncode
        print(f"geometry context {opt}: {len(cases)} child cases pass")
    (out / "results.json").write_text(json.dumps(dict(results=results, runtime_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("runtime/vk_exec_draw.c", "runtime/gfx_shader.c", "runtime/vk.h", "runtime/vk_exec.h", "runtime/nvn_obj.h")}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
