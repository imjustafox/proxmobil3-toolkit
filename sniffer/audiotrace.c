/* LD_PRELOAD shim: trace a process's device access, to find what the stock app
 * `nx` does to the audio hardware that a plain `aplay` does not. Logs every
 * open()/openat() path+flags, and every ioctl() on an "interesting" fd (one that
 * resolves to /dev/snd*, /dev/i2c*, /dev/mem, a gpio or clk node, or any /sys
 * path). The decisive signal is any device touched beyond /dev/snd*.
 *
 * Same approach as cvsniff.c: the "real" calls are raw `syscall()`s, so this
 * depends only on glibc's stable `syscall` + `getenv` symbols and loads on the
 * device's 2019 userland. Process-agnostic: the SAME .so works for `nx` and for
 * `aplay`; each log line is prefixed with [pid:comm] so the two runs are
 * distinguishable even in one shared log.
 *
 * Build (on a host with the cross toolchain, as used for cvsniff.so):
 *     arm-linux-gnueabihf-gcc -shared -fPIC -O2 -o audiotrace.so audiotrace.c
 *
 * Use:
 *   cold aplay run:  LD_PRELOAD=/init/audiotrace.so AUDIOTRACE_LOG=/init/at_aplay.log \
 *                    aplay /tmp/tone.wav
 *   nx run:          add to nx.service (ExecStart=/init/efad/pgm/NxProx,
 *                    WorkingDirectory=/init/efad/pgm) via a drop-in:
 *                      [Service]
 *                      Environment=LD_PRELOAD=/init/audiotrace.so
 *                      Environment=AUDIOTRACE_LOG=/init/at_nx.log
 *                    then `systemctl daemon-reload; systemctl restart nx`, tap once.
 *   diff at_nx.log vs at_aplay.log -> the extra device/ioctl is the gate.
 *
 * Default log path is /init/audiotrace.log; override with $AUDIOTRACE_LOG.
 */
#define _GNU_SOURCE
#include <sys/syscall.h>
#include <unistd.h>
#include <stddef.h>
#include <stdarg.h>
#include <stdlib.h>
#include <fcntl.h>

static long sc_write(int fd, const void *b, unsigned long n){ return syscall(SYS_write, fd, b, n); }
static long sc_read(int fd, void *b, unsigned long n){ return syscall(SYS_read, fd, b, n); }
static long sc_open(const char *p, int fl, int mo){ return syscall(SYS_open, p, fl, mo); }
static long sc_readlink(const char *p, char *b, unsigned long n){ return syscall(SYS_readlink, p, b, n); }
static int  sc_getpid(void){ return (int)syscall(SYS_getpid); }

static int logfd = -2;
static char pfx[48];          /* "[pid:comm] " built once */
static int  pfxlen = 0;

static int contains(const char *h, const char *n){
    for(unsigned long i=0; h[i]; i++){ unsigned long j=0; while(n[j] && h[i+j]==n[j]) j++; if(!n[j]) return 1; }
    return 0;
}
static const char HEX[]="0123456789abcdef";

/* append helpers into a caller buffer at offset *o (bounded by cap) */
static void a_str(char *b,int *o,int cap,const char *s){ for(int i=0;s[i]&&*o<cap;i++) b[(*o)++]=s[i]; }
static void a_dec(char *b,int *o,int cap,long v){
    char t[24]; int i=0; if(v<0){ if(*o<cap)b[(*o)++]='-'; v=-v; }
    if(v==0){ if(*o<cap)b[(*o)++]='0'; return; }
    while(v>0){ t[i++]='0'+(int)(v%10); v/=10; }
    while(i>0 && *o<cap) b[(*o)++]=t[--i];
}
static void a_hex(char *b,int *o,int cap,unsigned long v){
    a_str(b,o,cap,"0x");
    int started=0;
    for(int s=28;s>=0;s-=4){ int nib=(int)((v>>s)&0xf); if(nib||started||s==0){ if(*o<cap) b[(*o)++]=HEX[nib]; started=1; } }
}

static void init_once(void){
    if(logfd!=-2) return;
    /* prefix: "[pid:comm] " */
    int o=0; pfx[o++]='[';
    a_dec(pfx,&o,(int)sizeof(pfx)-2,sc_getpid());
    pfx[o++]=':';
    int cf=(int)sc_open("/proc/self/comm", O_RDONLY, 0);
    if(cf>=0){ char c[20]; long n=sc_read(cf,c,sizeof(c)-1); syscall(SYS_close,cf);
               for(long i=0;i<n && o<(int)sizeof(pfx)-3;i++){ if(c[i]=='\n'||c[i]==0) break; pfx[o++]=c[i]; } }
    pfx[o++]=']'; pfx[o++]=' '; pfxlen=o;
    const char *lp = getenv("AUDIOTRACE_LOG"); if(!lp||!lp[0]) lp="/init/audiotrace.log";
    logfd = (int)sc_open(lp, O_WRONLY|O_CREAT|O_APPEND, 0644);
}

/* resolve fd -> target path via /proc/self/fd/N; returns length or 0 */
static int fd_path(int fd, char *tgt, int tcap){
    char path[32]="/proc/self/fd/"; int p=14;
    long v=fd; char t[12]; int i=0; if(v==0)t[i++]='0'; while(v>0){t[i++]='0'+(int)(v%10);v/=10;}
    while(i>0) path[p++]=t[--i];
    path[p]=0;
    long n=sc_readlink(path,tgt,tcap-1); if(n<=0) return 0; tgt[n]=0; return (int)n;
}

static void emit(const char *b,int n){ init_once(); if(logfd<0) return; sc_write(logfd,pfx,pfxlen); sc_write(logfd,b,n); }

static void log_open(const char *fn, const char *path, int flags, long ret){
    if(path && contains(path,"audiotrace")) return;           /* don't trace our own log */
    char b[320]; int o=0;
    a_str(b,&o,sizeof(b),fn); b[o++]=' ';
    a_str(b,&o,sizeof(b), path?path:"(null)");
    a_str(b,&o,sizeof(b)," flags="); a_hex(b,&o,sizeof(b),(unsigned long)(unsigned)flags);
    a_str(b,&o,sizeof(b)," -> "); a_dec(b,&o,sizeof(b),ret);
    b[o++]='\n'; emit(b,o);
}

int open(const char *path, int flags, ...){
    int mode=0; if(flags & O_CREAT){ va_list ap; va_start(ap,flags); mode=va_arg(ap,int); va_end(ap); }
    long r = sc_open(path, flags, mode);
    log_open("open", path, flags, r);
    return (int)r;
}
int openat(int dirfd, const char *path, int flags, ...){
    int mode=0; if(flags & O_CREAT){ va_list ap; va_start(ap,flags); mode=va_arg(ap,int); va_end(ap); }
    long r = syscall(SYS_openat, dirfd, path, flags, mode);
    log_open("openat", path, flags, r);
    return (int)r;
}
int ioctl(int fd, unsigned long req, ...){
    void *arg; va_list ap; va_start(ap,req); arg=va_arg(ap,void*); va_end(ap);
    long r = syscall(SYS_ioctl, fd, req, arg);
    char tgt[160];
    if(fd_path(fd,tgt,sizeof(tgt))){
        if(contains(tgt,"snd")||contains(tgt,"i2c")||contains(tgt,"/dev/mem")||
           contains(tgt,"gpio")||contains(tgt,"clk")||contains(tgt,"/sys/")){
            char b[256]; int o=0;
            a_str(b,&o,sizeof(b),"ioctl fd="); a_dec(b,&o,sizeof(b),fd);
            a_str(b,&o,sizeof(b)," ("); a_str(b,&o,sizeof(b),tgt); a_str(b,&o,sizeof(b),") req=");
            a_hex(b,&o,sizeof(b),req);
            /* decode _IOC(type,nr): type char + nr */
            a_str(b,&o,sizeof(b)," type='"); { char tc=(char)((req>>8)&0xff); b[o++]= (tc>=32&&tc<127)?tc:'?'; }
            a_str(b,&o,sizeof(b),"' nr="); a_dec(b,&o,sizeof(b),(long)(req&0xff));
            a_str(b,&o,sizeof(b)," -> "); a_dec(b,&o,sizeof(b),r);
            b[o++]='\n'; emit(b,o);
        }
    }
    return (int)r;
}

/* large-file variants libasound/aplay may call on 32-bit */
int open64(const char *path, int flags, ...) __attribute__((alias("open")));
int openat64(int dirfd, const char *path, int flags, ...) __attribute__((alias("openat")));
