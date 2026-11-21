/*
 * cvendpull: read the cVEND reader's live files over IPP and save them.
 *
 * Runs on the PM3 itself, with no Python. The helper configures the tty to
 * 115200 8N1 raw. Usage:
 *
 *     cvendpull <output-directory>
 *
 * Build with dockcross/linux-armv7, matching the i.MX6DL (Cortex-A9):
 *
 *     armv7-unknown-linux-gnueabi-gcc -static -nostdlib -Os \
 *       -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -fno-builtin \
 *       -fno-stack-protector -fno-unwind-tables -fno-asynchronous-unwind-tables \
 *       -fno-pic -no-pie -Wl,-e,_start -Wl,--build-id=none \
 *       -o cvendpull cvendpull.c
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#define NULL ((void *)0)
#define TTY "/dev/ttymxc3"
#ifndef VERSION_RETRIES
#define VERSION_RETRIES 45
#endif

#define SYS_exit      1
#define SYS_read      3
#define SYS_write     4
#define SYS_open      5
#define SYS_close     6
#define SYS_mkdir    39
#define SYS_ioctl    54
#define SYS_fcntl    55
#define SYS_nanosleep 162

#define O_WRONLY 1
#define O_RDWR   2
#define O_CREAT  0100
#define O_TRUNC  01000
#define O_NOCTTY 0400
#define O_NONBLOCK 04000
#define F_SETFL 4
#define TCSETS 0x5402

struct timespec {
    long sec;
    long nsec;
};

struct termios {
    u32 iflag;
    u32 oflag;
    u32 cflag;
    u32 lflag;
    u8 line;
    u8 cc[19];
};

struct frame {
    u8 reply_to;
    u8 type;
    int len;
    u8 data[65536];
};

static u8 reqbuf[65536];
static u8 seqno;

static long sys_call(long n, long a, long b, long c, long d, long e, long f)
{
    register long r7 __asm__("r7") = n;
    register long r0 __asm__("r0") = a;
    register long r1 __asm__("r1") = b;
    register long r2 __asm__("r2") = c;
    register long r3 __asm__("r3") = d;
    register long r4 __asm__("r4") = e;
    register long r5 __asm__("r5") = f;
    __asm__ volatile("svc 0"
                     : "+r"(r0)
                     : "r"(r7), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5)
                     : "memory");
    return r0;
}

static int sys_write(int fd, const void *p, int n) { return (int)sys_call(SYS_write, fd, (long)p, n, 0, 0, 0); }
static int sys_read(int fd, void *p, int n) { return (int)sys_call(SYS_read, fd, (long)p, n, 0, 0, 0); }
static int sys_open(const char *p, int flags, int mode) { return (int)sys_call(SYS_open, (long)p, flags, mode, 0, 0, 0); }
static int sys_close(int fd) { return (int)sys_call(SYS_close, fd, 0, 0, 0, 0, 0); }
static int sys_mkdir(const char *p, int mode) { return (int)sys_call(SYS_mkdir, (long)p, mode, 0, 0, 0, 0); }

static void sleep_ms(int ms)
{
    struct timespec ts;
    ts.sec = ms / 1000;
    ts.nsec = (long)(ms % 1000) * 1000000L;
    sys_call(SYS_nanosleep, (long)&ts, 0, 0, 0, 0, 0);
}

static int slen(const char *s)
{
    int n = 0;
    while (s[n]) n++;
    return n;
}

static void *memcpy(void *d, const void *s, u32 n)
{
    u8 *dd = (u8 *)d;
    const u8 *ss = (const u8 *)s;
    while (n--) *dd++ = *ss++;
    return d;
}

static void *memmove(void *d, const void *s, u32 n)
{
    u8 *dd = (u8 *)d;
    const u8 *ss = (const u8 *)s;
    if (dd < ss) {
        while (n--) *dd++ = *ss++;
    } else {
        dd += n;
        ss += n;
        while (n--) *--dd = *--ss;
    }
    return d;
}

static void *memset(void *d, int c, u32 n)
{
    u8 *dd = (u8 *)d;
    while (n--) *dd++ = (u8)c;
    return d;
}

static int write_all(int fd, const void *p, int n)
{
    const u8 *b = (const u8 *)p;
    while (n > 0) {
        int r = sys_write(fd, b, n);
        if (r <= 0) return -1;
        b += r;
        n -= r;
    }
    return 0;
}

static void msg(const char *s)
{
    write_all(2, s, slen(s));
}

static int path_join(char *out, int cap, const char *dir, const char *name)
{
    int n = 0;
    while (dir[n] && n < cap - 1) { out[n] = dir[n]; n++; }
    if (n > 0 && out[n - 1] != '/' && n < cap - 1) out[n++] = '/';
    while (*name && n < cap - 1) out[n++] = *name++;
    out[n] = 0;
    return n;
}

static u8 crc8(const u8 *p, int n)
{
    u8 crc = 0;
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; i++)
            crc = (crc & 1) ? (u8)((crc >> 1) ^ 0x8c) : (u8)(crc >> 1);
    }
    return crc;
}

static u32 crc32_jam(const u8 *p, int n)
{
    u32 crc = 0xffffffffu;
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; i++)
            crc = (crc & 1) ? ((crc >> 1) ^ 0xedb88320u) : (crc >> 1);
    }
    return ~crc;
}

static int set_tty(int fd)
{
    struct termios t;
    memset(&t, 0, sizeof(t));
    t.cflag = 0x1002u | 0x800u | 0x80u | 0x30u; /* B115200 | CLOCAL | CREAD | CS8 */
    t.cc[5] = 5; /* VTIME, 0.5 s */
    t.cc[6] = 0; /* VMIN */
    if (sys_call(SYS_ioctl, fd, TCSETS, (long)&t, 0, 0, 0) < 0) return -1;
    sys_call(SYS_fcntl, fd, F_SETFL, 0, 0, 0, 0);
    return 0;
}

static int read_byte(int fd, u8 *b)
{
    return sys_read(fd, b, 1) == 1;
}

static int read_exact(int fd, u8 *p, int n)
{
    while (n > 0) {
        if (!read_byte(fd, p)) return 0;
        p++;
        n--;
    }
    return 1;
}

static u8 send_frame(int fd, u8 type, const u8 *data, int n)
{
    u8 hdr[7];
    seqno++;
    if (seqno == 0) seqno = 1;
    hdr[0] = 0xbc;
    hdr[1] = seqno;
    hdr[2] = 0;
    hdr[3] = type;
    hdr[4] = (u8)(n >> 8);
    hdr[5] = (u8)n;
    hdr[6] = crc8(hdr, 6);
    write_all(fd, hdr, 7);
    if (n > 0) write_all(fd, data, n);
    if (type >= 0x80) {
        u32 crc = crc32_jam(data, n);
        u8 tail[4];
        tail[0] = (u8)crc;
        tail[1] = (u8)(crc >> 8);
        tail[2] = (u8)(crc >> 16);
        tail[3] = (u8)(crc >> 24);
        write_all(fd, tail, 4);
    }
    return seqno;
}

static int read_frame(int fd, struct frame *f)
{
    u8 hdr[7];
    int have = 0;
    int found = 0;
    for (int guard = 0; guard < 4096; guard++) {
        u8 b;
        if (!read_byte(fd, &b)) return 0;
        if (have == 0 && b != 0xbc) continue;
        hdr[have++] = b;
        if (have < 7) continue;
        if (crc8(hdr, 6) == hdr[6]) { found = 1; break; }
        memmove(hdr, hdr + 1, 6);
        have = 6;
    }
    if (!found) return 0;
    int len = ((int)hdr[4] << 8) | hdr[5];
    if (len > (int)sizeof(f->data)) return 0;
    if (!read_exact(fd, f->data, len)) return 0;
    if (hdr[3] >= 0x80) {
        u8 tail[4];
        if (!read_exact(fd, tail, 4)) return 0;
        u32 got = (u32)tail[0] | ((u32)tail[1] << 8) |
                  ((u32)tail[2] << 16) | ((u32)tail[3] << 24);
        if (got != crc32_jam(f->data, len)) return 0;
    }
    f->reply_to = hdr[2];
    f->type = hdr[3];
    f->len = len;
    return 1;
}

static int request(int fd, u8 type, u8 expect, const u8 *data, int n)
{
    u8 seq = send_frame(fd, type, data, n);
    for (int i = 0; i < 12; i++) {
        struct frame f;
        if (!read_frame(fd, &f)) return -1;
        if (f.reply_to == seq && f.type == expect) {
            memcpy(reqbuf, f.data, f.len);
            return f.len;
        }
    }
    return -1;
}

static void be16(u8 *p, int v)
{
    p[0] = (u8)(v >> 8);
    p[1] = (u8)v;
}

static void be32(u8 *p, u32 v)
{
    p[0] = (u8)(v >> 24);
    p[1] = (u8)(v >> 16);
    p[2] = (u8)(v >> 8);
    p[3] = (u8)v;
}

static u32 rd32(const u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}

static int save_blob(const char *dir, const char *name, const u8 *data, int len)
{
    char path[512];
    path_join(path, sizeof(path), dir, name);
    int fd = sys_open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    int rc = write_all(fd, data, len);
    sys_close(fd);
    return rc;
}

static int list_dir(int fd, const char *dir, const char *path, const char *name)
{
    u8 req[300];
    int plen = slen(path);
    be16(req, plen);
    memcpy(req + 2, path, plen);
    int n = request(fd, 0xa4, 0xa5, req, 2 + plen);
    if (n < 4) return -1;

    char outpath[512];
    path_join(outpath, sizeof(outpath), dir, name);
    int ofd = sys_open(outpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (ofd < 0) return -1;

    const u8 *p = reqbuf + 4;
    int left = n - 4;
    int i = 0;
    while (i < left) {
        const char *fname = (const char *)(p + i);
        int fl = 0;
        while (i + fl < left && p[i + fl]) fl++;
        i += fl + 1;
        if (i >= left) break;
        const char *mtime = (const char *)(p + i);
        int ml = 0;
        while (i + ml < left && p[i + ml]) ml++;
        i += ml + 1;
        if (fl == 0) continue;
        write_all(ofd, mtime, ml);
        write_all(ofd, "  ", 2);
        write_all(ofd, fname, fl);
        write_all(ofd, "\n", 1);
    }
    sys_close(ofd);
    return 0;
}

static int get_file(int fd, const char *dir, const char *path, const char *name)
{
    char outpath[512];
    path_join(outpath, sizeof(outpath), dir, name);
    int ofd = sys_open(outpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (ofd < 0) return -1;

    int plen = slen(path);
    u32 offset = 0;
    const int chunk = 0xf000;
    int rc = -1;
    for (int guard = 0; guard < 512; guard++) {
        u8 req[300];
        be16(req, plen);
        memcpy(req + 2, path, plen);
        be32(req + 2 + plen, offset);
        be16(req + 2 + plen + 4, chunk);
        int n = request(fd, 0x98, 0x99, req, 2 + plen + 6);
        if (n < 4) break;
        u32 got = rd32(reqbuf);
        if ((int)got > n - 4) break;
        if (write_all(ofd, reqbuf + 4, (int)got) < 0) break;
        offset += got;
        if ((int)got < chunk) { rc = 0; break; }
    }
    sys_close(ofd);
    return rc;
}

__attribute__((used)) int c_start(int argc, char **argv)
{
    if (argc < 2) {
        msg("usage: cvendpull <output-directory>\n");
        return 2;
    }
    const char *dir = argv[1];
    sys_mkdir(dir, 0755);

    int fd = sys_open(TTY, O_RDWR | O_NOCTTY | O_NONBLOCK, 0);
    if (fd < 0) {
        msg("cvendpull: cannot open " TTY "\n");
        return 1;
    }
    if (set_tty(fd) < 0) {
        msg("cvendpull: tty setup failed\n");
        sys_close(fd);
        return 1;
    }

    msg("cvendpull: waiting for reader\n");
    int n = -1;
    for (int i = 0; i < VERSION_RETRIES; i++) {
        send_frame(fd, 0x04, NULL, 0);
        n = request(fd, 0x02, 0x03, NULL, 0);
        if (n >= 0) break;
        sleep_ms(2000);
    }
    if (n < 0) {
        msg("cvendpull: reader did not answer\n");
        sys_close(fd);
        return 1;
    }
    if (save_blob(dir, "version-ipp.bin", reqbuf, n) < 0)
        msg("cvendpull: writing version failed\n");
    msg("cvendpull: reader version captured\n");

    if (list_dir(fd, dir, "/home/app0", "ls.txt") < 0)
        msg("cvendpull: list /home/app0 failed\n");
    if (list_dir(fd, dir, "/home/app0/emv", "ls-emv.txt") < 0)
        msg("cvendpull: list /home/app0/emv failed\n");
    if (list_dir(fd, dir, "/home/app0/ggo", "ls-ggo.txt") < 0)
        msg("cvendpull: list /home/app0/ggo failed\n");
    if (list_dir(fd, dir, "/home/app0/ggo/cfg", "ls-ggo-cfg.txt") < 0)
        msg("cvendpull: list /home/app0/ggo/cfg failed\n");
    if (list_dir(fd, dir, "/home/app0/ggo/int", "ls-ggo-int.txt") < 0)
        msg("cvendpull: list /home/app0/ggo/int failed\n");

    if (get_file(fd, dir, "/home/app0/config", "config.bin") < 0)
        msg("cvendpull: read config failed\n");
    if (get_file(fd, dir, "/home/app0/version", "version.bin") < 0)
        msg("cvendpull: read version failed\n");
    if (get_file(fd, dir, "/home/app0/emv/transact-counter.dat", "emv-transact-counter.dat") < 0)
        msg("cvendpull: read transact-counter failed\n");
    if (get_file(fd, dir, "/home/app0/ggo/cfg/persdata.bin", "ggo-persdata.bin") < 0)
        msg("cvendpull: read persdata failed\n");

    sys_close(fd);
    msg("cvendpull: done\n");
    return 0;
}

__attribute__((naked, noreturn)) void _start(void)
{
    __asm__ volatile(
        "mov r3, sp\n"
        "ldr r0, [r3]\n"
        "add r1, r3, #4\n"
        "bl c_start\n"
        "mov r7, #1\n"
        "svc 0\n");
}
