#include "../runtime/dkb_camera.c"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
static SRWLOCK test_lock = SRWLOCK_INIT;
void plat_mutex_lock(PlatMutex *m) { assert(m==&mouse_lock); AcquireSRWLockExclusive(&test_lock); }
void plat_mutex_unlock(PlatMutex *m) { assert(m==&mouse_lock); ReleaseSRWLockExclusive(&test_lock); }
#else
#include <pthread.h>
static pthread_mutex_t test_lock = PTHREAD_MUTEX_INITIALIZER;
void plat_mutex_lock(PlatMutex *m) { assert(m==&mouse_lock); assert(!pthread_mutex_lock(&test_lock)); }
void plat_mutex_unlock(PlatMutex *m) { assert(m==&mouse_lock); assert(!pthread_mutex_unlock(&test_lock)); }
#endif
static GuestFn callbacks[5];
static int registered, has_patch = 1;
int rt_patch_set(const char *name) { assert(!strcmp(name,"mousecamera")); return has_patch ? 0 : -1; }
void *rt_patch_page(void) { return (void *)(uintptr_t)0x7002450000ull; }
void rt_register_host(uint64_t addr, GuestFn fn) {
    assert(registered < 5 && addr == 0x7002450200ull + registered*16);
    callbacks[registered++] = fn;
}
static Cpu c;
static int sample_calls;
static float test_dx, test_dy;
static int test_enabled = 1;
static uint64_t test_frame, sampled_frame;
int input_mouse_direct_recent(void) { return test_frame-sampled_frame <= 2; }
int input_mouse_direct(float out[2]) { sample_calls++; sampled_frame=test_frame; out[0]=test_dx; out[1]=test_dy; return test_enabled; }
static _Alignas(8) uint8_t follow[0x400], vertical[0x200], service[0x100], options[0x100], timing[0x40], limits[0x40], defaults[0x40];
static void reset(void) {
    memset(&c,0,sizeof c); c.sp=0x10000; sample_calls=0;
    memset(&mouse,0,sizeof mouse); memset(follow,0,sizeof follow); memset(vertical,0,sizeof vertical);
    memset(service,0,sizeof service); memset(options,0,sizeof options);
    memset(limits,0,sizeof limits); memset(defaults,0,sizeof defaults);
    PTR(follow,0xb0)=(uintptr_t)service; PTR(follow,0x168)=(uintptr_t)vertical;
    PTR(service,0x60)=(uintptr_t)options; PTR(service,0x10)=(uintptr_t)timing;
    PTR(vertical,0xc8)=(uintptr_t)defaults; PTR(vertical,0xd0)=(uintptr_t)limits;
    FLOAT(timing,4)=1; FLOAT(vertical,0x104)=FLOAT(vertical,0x108)=10;
    test_dx=test_dy=0; test_enabled=1; test_frame=sampled_frame=100;
}
static void begin(void) { camera_hook(&c,0,(uintptr_t)follow); }
static void yaw(void) { camera_hook(&c,1,(uintptr_t)follow); }
static void pitch(void) { camera_hook(&c,2,(uintptr_t)vertical); camera_hook(&c,3,(uintptr_t)vertical); }
#ifdef _WIN32
static DWORD WINAPI finish_on_thread(void *unused) {
#else
static void *finish_on_thread(void *unused) {
#endif
    (void)unused;
    yaw();
    c.x[19]=(uintptr_t)vertical; c.v[0]=0; callbacks[4](&c);
    assert(c.v[0]==0x3f800000u);
    pitch();
    return 0;
}
static void migrate_update(void) {
#ifdef _WIN32
    HANDLE t=CreateThread(NULL,0,finish_on_thread,NULL,0,NULL); assert(t);
    assert(WaitForSingleObject(t,INFINITE)==WAIT_OBJECT_0); CloseHandle(t);
#else
    pthread_t t; assert(!pthread_create(&t,NULL,finish_on_thread,NULL)); assert(!pthread_join(t,NULL));
#endif
}
int main(void) {
    has_patch=0; dkb_camera_init(); assert(registered==0);
    has_patch=1; dkb_camera_init(); assert(registered==5);
    reset(); test_dx=8; test_dy=-4;
    c.x[0]=(uintptr_t)follow; c.x[19]=(uintptr_t)follow;
    Cpu before=c; callbacks[0](&c); callbacks[1](&c); assert(!memcmp(&c,&before,sizeof c));
    c.x[19]=(uintptr_t)vertical; before=c; callbacks[2](&c); callbacks[3](&c);
    assert(!memcmp(&c,&before,sizeof c)); assert(FLOAT(follow,0x204)==-8 && FLOAT(vertical,0x104)==6);
    reset(); test_dx=test_dy=8; begin(); test_frame++; yaw(); pitch();
    assert(FLOAT(follow,0x204)==-8 && FLOAT(vertical,0x104)==18); // a present cannot discard motion
    reset(); test_dy=8; begin(); camera_hook(&c,PITCH_END,(uintptr_t)vertical);
    assert(FLOAT(vertical,0x104)==10); // no matching pitch begin

    reset(); FLOAT(follow,0x204)=2; FLOAT(follow,0x208)=4; begin(); yaw(); pitch();
    assert(FLOAT(follow,0x204)==2 && FLOAT(follow,0x208)==4); // idle mouse preserves controller/auto camera
    assert(FLOAT(vertical,0x104)==10);
    reset(); test_dx=8; test_dy=-4; FLOAT(follow,0x208)=7; begin(); yaw(); pitch();
    assert(FLOAT(follow,0x204)==-8 && FLOAT(follow,0x208)==0);
    assert(FLOAT(vertical,0x104)==6 && FLOAT(vertical,0x108)==6);
    pitch(); assert(FLOAT(vertical,0x104)==6); // a second call cannot reuse the same mouse distance
    reset(); test_dx=8; test_dy=-4; BYTE(options,8)=BYTE(options,9)=1; begin(); yaw(); pitch();
    assert(FLOAT(follow,0x204)==8 && FLOAT(vertical,0x104)==14);
    reset(); test_dy=1000; begin(); pitch(); assert(FLOAT(vertical,0x104)==85);
    reset(); test_dy=-1000; begin(); pitch(); assert(FLOAT(vertical,0x104)==-70);
    reset(); BYTE(limits,0)=1; FLOAT(limits,4)=-20; FLOAT(limits,8)=30;
    test_dy=1000; begin(); pitch(); assert(FLOAT(vertical,0x104)==30);
    reset(); BYTE(defaults,0x10)=1; FLOAT(defaults,4)=-15; FLOAT(defaults,8)=25;
    test_dy=-1000; begin(); pitch(); assert(FLOAT(vertical,0x104)==-15);
    reset(); test_dx=test_dy=12; test_enabled=0; begin(); yaw(); pitch();
    assert(FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==10);
    reset(); test_dx=test_dy=12; FLOAT(timing,4)=0; begin(); yaw(); pitch();
    assert(FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==10); // paused game
    // Native transition checks receive activity only from a current, enabled vertical mouse sample.
    reset(); test_dy=0.01f; begin(); c.x[19]=(uintptr_t)vertical; c.v[0]=0;
    before=c; callbacks[4](&c); before.v[0]=0x3f800000u; assert(!memcmp(&c,&before,sizeof c));
    test_frame++; c.v[0]=0; callbacks[4](&c); assert(c.v[0]==0x3f800000u);
    pitch(); c.v[0]=0; callbacks[4](&c); assert(c.v[0]==0); // consumed pitch cannot wake another update
    reset(); begin(); c.x[19]=(uintptr_t)vertical; callbacks[4](&c); assert(c.v[0]==0); // idle input must not wake pitch
    reset(); test_dy=1; test_enabled=0; begin(); c.x[19]=(uintptr_t)vertical; callbacks[4](&c); assert(c.v[0]==0);
    reset(); test_dy=1; begin(); c.x[19]=(uintptr_t)vertical;
    test_frame+=2; callbacks[4](&c); assert(c.v[0]==0x3f800000u);
    test_frame++; c.v[0]=0; callbacks[4](&c); assert(c.v[0]==0); // no new BEGIN: expire activity

    // Both native manual-camera guards must leave mouse counts and pitch activity alone.
    for (int flags=1;flags<4;flags++) {
        reset(); test_dx=8; test_dy=4; begin(); // first arm a valid sample
        int calls=sample_calls;
        BYTE(options,0xb)=(flags&1) ? 0x80 : 0;
        BYTE(follow,0x2d4)=(flags&2) ? 1 : 0;
        begin(); yaw(); pitch(); c.x[19]=(uintptr_t)vertical; callbacks[4](&c);
        assert(sample_calls==calls && FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==10 && c.v[0]==0);
        BYTE(options,0xb)=BYTE(follow,0x2d4)=0;
        begin(); yaw(); pitch();
        assert(sample_calls==calls+1 && FLOAT(follow,0x204)==-8 && FLOAT(vertical,0x104)==14);
    }

    // Every pointer read by the adapter can be absent; reject before consuming mouse motion.
    for (int missing=0;missing<7;missing++) {
        reset(); test_dx=test_dy=8;
        if (missing==0) PTR(follow,0xb0)=0;
        if (missing==1) PTR(service,0x10)=0;
        if (missing==2) PTR(service,0x60)=0;
        if (missing==3) PTR(follow,0x168)=0;
        if (missing==4) PTR(vertical,0xd0)=0;
        if (missing==5) PTR(vertical,0xc8)=0;
        camera_hook(&c,YAW_BEGIN,missing==6 ? 0 : (uintptr_t)follow); yaw(); pitch();
        assert(sample_calls==0 && FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==10);
    }
    for (int offset=0xc8;offset<=0xd0;offset+=8) {
        reset(); test_dy=8; begin(); camera_hook(&c,PITCH_BEGIN,(uintptr_t)vertical);
        PTR(vertical,offset)=0; camera_hook(&c,PITCH_END,(uintptr_t)vertical);
        assert(FLOAT(vertical,0x104)==10); // a pointer can also disappear after BEGIN
    }
    reset(); test_dx=8; test_dy=-4; begin(); migrate_update();
    assert(FLOAT(follow,0x204)==-8 && FLOAT(vertical,0x104)==6);

    reset(); test_dx=test_dy=8; begin(); Cpu other=c;
    camera_hook(&other,YAW_END,(uintptr_t)follow);
    camera_hook(&other,PITCH_BEGIN,(uintptr_t)vertical); camera_hook(&other,PITCH_END,(uintptr_t)vertical);
    other.x[19]=(uintptr_t)vertical; callbacks[4](&other); assert(other.v[0]==0);
    assert(FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==10);
    c.sp-=0x100; yaw(); assert(FLOAT(follow,0x204)==0); c.sp+=0x100;
    camera_hook(&c,YAW_END,(uintptr_t)options); camera_hook(&c,PITCH_BEGIN,(uintptr_t)options);
    camera_hook(&c,PITCH_END,(uintptr_t)vertical); assert(FLOAT(vertical,0x104)==10);
    camera_hook(&c,PITCH_BEGIN,(uintptr_t)vertical); c.sp-=0x100;
    camera_hook(&c,PITCH_END,(uintptr_t)vertical); assert(FLOAT(vertical,0x104)==10); c.sp+=0x100;
    test_frame+=3; camera_hook(&c,PITCH_END,(uintptr_t)vertical); yaw();
    assert(FLOAT(follow,0x204)==-8 && FLOAT(vertical,0x104)==18);
    FLOAT(follow,0x204)=0; yaw(); pitch();
    assert(FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==18); // both axes are single-use

    reset(); test_dy=8; begin(); camera_hook(&c,PITCH_BEGIN,(uintptr_t)vertical);
    begin(); camera_hook(&c,PITCH_END,(uintptr_t)vertical);
    assert(FLOAT(vertical,0x104)==10); // a new update invalidates an unfinished pitch pair
    camera_hook(&other,YAW_BEGIN,(uintptr_t)follow); yaw(); pitch();
    assert(FLOAT(follow,0x204)==0 && FLOAT(vertical,0x104)==10); // superseded owner
    puts("PASS: yaw/pitch, controller, inversion, limits, single consumption, pause, null pointers, present during update, CPU ownership, host-thread migration");
}
