/* LD_PRELOAD shim: log all read()/write() on /dev/ttymxc3 (cVEND) and
 * /dev/ttymxc2 (PIC32). Uses raw syscalls so it depends only on glibc's
 * stable `syscall` symbol -> loads on the device's old glibc. */
#define _GNU_SOURCE
#include <sys/syscall.h>
#include <unistd.h>
#include <stddef.h>

static int logfd = -2;

static long sc_write(int fd, const void *b, unsigned long n){ return syscall(SYS_write, fd, b, n); }
static long sc_read(int fd, void *b, unsigned long n){ return syscall(SYS_read, fd, b, n); }
static long sc_open(const char *p, int fl, int mo){ return syscall(SYS_open, p, fl, mo); }
static long sc_readlink(const char *p, char *b, unsigned long n){ return syscall(SYS_readlink, p, b, n); }

static unsigned long slen(const char *s){ unsigned long i=0; while(s[i]) i++; return i; }
static int contains(const char *h, const char *n){
    for(unsigned long i=0; h[i]; i++){ unsigned long j=0; while(n[j] && h[i+j]==n[j]) j++; if(!n[j]) return 1; } return 0;
}
static void itoa_fd(int fd, char *out){ /* small int -> decimal */
    char t[8]; int i=0; if(fd==0){out[0]='0';out[1]=0;return;} while(fd>0){t[i++]='0'+fd%10;fd/=10;}
    int k=0; while(i>0) out[k++]=t[--i]; out[k]=0;
}
static const char HEX[]="0123456789abcdef";

/* which fds are the two serial ports we care about; cache by probing */
static int interesting(int fd){
    char path[32]="/proc/self/fd/"; char num[8]; itoa_fd(fd,num);
    unsigned long p=slen(path); for(unsigned long i=0;num[i];i++) path[p++]=num[i]; path[p]=0;
    char tgt[128]; long n=sc_readlink(path,tgt,sizeof(tgt)-1); if(n<=0) return 0; tgt[n]=0;
    if(contains(tgt,"ttymxc3")) return 3;
    if(contains(tgt,"ttymxc2")) return 2;
    return 0;
}
static void ensure_log(){
    if(logfd!=-2) return;
    logfd = (int)sc_open("/init/cvsniff.log", 01|0100|02000 /*WRONLY|CREAT|APPEND*/, 0644);
}
static void logline(int which, char dir, const unsigned char *buf, long n){
    ensure_log(); if(logfd<0) return;
    char out[8192]; int o=0;
    out[o++]= which==3?'3':'2'; out[o++]=dir; out[o++]=' ';
    for(long i=0;i<n && o<8180;i++){ out[o++]=HEX[buf[i]>>4]; out[o++]=HEX[buf[i]&15]; }
    out[o++]='\n';
    sc_write(logfd, out, o);
}

ssize_t write(int fd, const void *buf, size_t n){
    long r = sc_write(fd, buf, n);
    int w = interesting(fd); if(w && r>0) logline(w,'>',(const unsigned char*)buf, r);
    return r;
}
ssize_t read(int fd, void *buf, size_t n){
    long r = sc_read(fd, buf, n);
    int w = interesting(fd); if(w && r>0) logline(w,'<',(const unsigned char*)buf, r);
    return r;
}
