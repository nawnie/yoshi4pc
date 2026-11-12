// CPU fixture: production request serialization and translation-failure cleanup are inserted below.
// Cache/service/platform adapters use original synthetic bytes. No GPU or game is loaded.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <sys/stat.h>
#include "gfx.h"
#include "nvn_geometry_control.h"
#ifdef _WIN32
#include <windows.h>
#else
#include <errno.h>
#include <unistd.h>
#endif
#define PATH_CAP 1024
#define CONTROL_SIZE 0x880
#define NVN2_C0_LAYOUT 0x860
#define CODE_SKIP 0x30
#define LINE_MAX_LEN 4096
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
enum {PLAT_FS_OK,PLAT_FS_NOT_FOUND,PLAT_FS_EXISTS,PLAT_FS_NOT_EMPTY,PLAT_FS_BUSY,PLAT_FS_ERROR};
@TYPES@
@SHADER@
static GfxShader result;
static char cache_dir[PATH_CAP];
static int cache_lock,host_f64=0;
static uint32_t host_sbuf=16,host_sg[3]={32,64,32},host_gather=8;
#ifdef FIXTURE_GEOMETRY_CONTRACT
static uint32_t host_gs_sg;   // this failure-capture fixture requests FS/CS only
#endif
static volatile int64_t n_hits,n_xlated;
static int service_mode,submitted,atomic_calls,writer,require_c0_expected,disk_load_calls;
static char sent[32768];
static void check(int good,const char* message) {if(!good){fprintf(stderr,"FAIL: %s\n",message);exit(20);}}
void rt_log(const char* format,...) {(void)format;}
static int file_exists(const char* path) {FILE* f=fopen(path,"rb");if(!f)return 0;fclose(f);return 1;}
static int write_file(const char* path,const void* data,size_t n) {
    FILE* f=fopen(path,"wb");if(!f)return 0;
    int ok=fwrite(data,1,n,f)==n;return fclose(f)==0 && ok;
}
int plat_file_write_atomic(const char* path,const void* data,size_t n) {
    if (!atomic_calls++ && getenv("FIXTURE_CAPTURE_GATE")) {
        puts("capture write ready");fflush(stdout);check(getchar()=='x',"parent released the capture writer");
    }
    const char* fail_at=getenv("FIXTURE_CAPTURE_WRITE_FAIL_AT");
    if(fail_at && atomic_calls==atoi(fail_at))return 0;
    return write_file(path,data,n);
}
uint32_t plat_process_id(void) {
    const char* fixed=getenv("FIXTURE_CAPTURE_PID");if(fixed)return (uint32_t)strtoul(fixed,NULL,10);
#ifdef _WIN32
    return GetCurrentProcessId();
#else
    return (uint32_t)getpid();
#endif
}
int plat_fs_mkdir(const char* path) {
#ifdef _WIN32
    return CreateDirectoryA(path,NULL)?PLAT_FS_OK:GetLastError()==ERROR_ALREADY_EXISTS?PLAT_FS_EXISTS:PLAT_FS_ERROR;
#else
    return mkdir(path,0700)==0?PLAT_FS_OK:errno==EEXIST?PLAT_FS_EXISTS:PLAT_FS_ERROR;
#endif
}
static int plat_file_delete(const char* path) {return remove(path)==0;}
static int plat_file_replace_cache(const char* from,const char* to) {return rename(from,to)==0;}static void mkdir_p(const char* path) {(void)path;} // Python creates these owned directories first.
static int64_t plat_inc64(volatile int64_t* p) {return ++*p;}
static void plat_mutex_lock(int* p) {(void)p;}
static void plat_mutex_unlock(int* p) {(void)p;}
static GfxShader* mem_find(const uint8_t* key) {(void)key;return NULL;}
static GfxShader* disk_load(const uint8_t* key,const uint8_t* iid,int require_c0) {
    (void)key;(void)iid;
    check(require_c0==require_c0_expected,"cache lookup preserves the request's c0 requirement");
    disk_load_calls++;
    return submitted && service_mode==1?&result:NULL;
}
#ifdef FIXTURE_GEOMETRY_CONTRACT
// The capture test supplies a bounded cache/service result, not a second implementation of cache validation.
// Full cache/geometry validation is covered by the separate production-TU cache test.
static GfxShader* request_disk_load(const Req* req,const uint8_t* key,const uint8_t* iid) {
    check(req->stage==GFX_STAGE_FS || req->stage==GFX_STAGE_CS,"capture fixture requests a legacy stage");
    return disk_load(key,iid,req->require_c0);
}
#endif
static GfxShader* mem_insert(GfxShader* s) {return s;}
static int use_find(const uint8_t* hash,UseMask* mask) {(void)hash;(void)mask;return 0;}
static UseMask use_of(GfxShader* s) {(void)s;check(0,"final key has no rename");return (UseMask){0};}
static void use_store(const uint8_t* hash,const UseMask* mask) {(void)hash;(void)mask;check(0,"no use-store branch");}
static void use_put(const uint8_t* hash,int known,const UseMask* mask) {(void)hash;(void)known;(void)mask;check(0,"no use-put branch");}
static void build_key(const uint8_t* hash,const GfxShaderAnswers* a,const UseMask* mask,uint8_t* key,uint8_t* iid) {
    (void)hash;(void)a;(void)mask;(void)key;(void)iid;check(0,"final key already known");
}
static void in_store(const uint8_t* iid,int stage,const uint8_t* control,const uint8_t* code,const Req* req,const GfxShaderAnswers* a) {
    (void)iid;(void)stage;(void)control;(void)code;(void)req;(void)a;check(service_mode==1,"only success stores normal inputs");
}
static const GfxShader* fail(const char* why,const char* key) {(void)key;check(why&&*why,"original failure remains reported");return NULL;}
static int svc_request(const char* request,char* reply,size_t cap) {
    check(strlen(request)<sizeof sent,"request fits fixture");strcpy(sent,request);submitted=1;
    if(writer)snprintf(reply,cap,"fail synthetic writer %d",writer);
    else snprintf(reply,cap,"%s synthetic",service_mode==1?"ok":"fail");return service_mode!=2;
}
@FUNCTIONS@
int main(int argc,char** argv) {
    check(argc==4 || argc==5,"cache, mode and stage arguments");check(strlen(argv[1])<sizeof cache_dir,"owned cache path");
    strcpy(cache_dir,argv[1]);service_mode=atoi(argv[2]);int stage=atoi(argv[3]);
    writer=argc==5?atoi(argv[4]):0;
    uint8_t code[CODE_SKIP+4]={0},control[CONTROL_SIZE]={0},c1[]={0xab,0xcd,0xef};
    const uint8_t bad[]={(uint8_t)(writer?writer:1),2,3,4};size_t skip=stage==GFX_STAGE_CS?0:CODE_SKIP;memcpy(code+skip,bad,sizeof bad);
    require_c0_expected=stage==GFX_STAGE_CS;
    Req req={.stage_name=stage==GFX_STAGE_CS?"cs":"ps",.length=(uint32_t)(skip+sizeof bad),.c1_len=sizeof c1,.c1=c1,
             .final=1,.require_c0=require_c0_expected};
#ifdef FIXTURE_GEOMETRY_CONTRACT
    req.stage=stage;
#endif
    result.stage=stage;
    memset(req.key,0xab,sizeof req.key);GfxShaderAnswers answers={0};answers.tex_type[3]=4;answers.attr_type[2]=2;
    if(writer)host_gather=(uint32_t)writer;
    answers.img_type[1]=4;answers.img_format[1]=1;answers.frag_out_type[0]=1;answers.shared_bytes=128;
    answers.local[0]=4;answers.local[1]=2;answers.local[2]=1;control[0x718]=1;
    memcpy(control+NVN2_C0_LAYOUT,"DKC1\1\2\3\4",8);
    const uint8_t roots[NVN2_ROOT_TABLES]={1,0,7,4,64,2,0,9};
    memcpy(control+NVN2_C0_LAYOUT+12,roots,sizeof roots);
    const GfxShader* s=translate_one(&req,stage,control,code,&answers);
    check((s!=NULL)==(service_mode==1),"capture does not alter translation result");
    check(disk_load_calls==(service_mode==1?2:1),"cache miss and successful output both check the c0 requirement");
    char path[PATH_CAP+80];snprintf(path,sizeof path,"%s/sent.json",cache_dir);check(write_file(path,sent,strlen(sent)),"sent request record");
    char hex[65];key_hex(req.key,hex);snprintf(path,sizeof path,"%s/%s.code",cache_dir,hex);
    check(!file_exists(path),"temporary cache code is always removed");
    printf("atomic capture writes=%d\n",atomic_calls);return 0;
}
