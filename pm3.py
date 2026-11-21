#!/usr/bin/env python3
"""Host-side tool for a PROXmobil3 (PM3).

Talks INIT's "IPP" framing to the PIC32 power/watchdog controller
(/dev/ttymxc2) and the FEIG cVEND NFC reader (/dev/ttymxc3) by bridging the
serial port over SSH, so nothing needs installing on the device.

Protocol notes come from https://wiki.pm3.dev/pic32 and /cvend.

Frame:  BC seq replyTo msgType lenHi lenLo hdrCRC8 data... [crc32 LE]
        hdrCRC8 = CRC-8/MAXIM over the first 6 bytes
        crc32 (CRC-32/JAMCRC, bit-inverted, little-endian) only when msgType >= 0x80
"""
import argparse
import binascii
import os
import struct
import subprocess
import sys
import threading
import time
import queue

HOST = os.environ.get("PM3_HOST", "10.0.1.102")
PIC32_TTY = "/dev/ttymxc2"
CVEND_TTY = "/dev/ttymxc3"


def crc8_maxim(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def crc32_jam(data: bytes) -> int:
    # cVEND uses CRC-32/JAMCRC (bit-inverted standard CRC-32), little-endian.
    return (~binascii.crc32(data)) & 0xFFFFFFFF


def encode(msg_type: int, data: bytes = b"", seq: int = 1, reply_to: int = 0) -> bytes:
    hdr = bytes([0xBC, seq & 0xFF, reply_to & 0xFF, msg_type & 0xFF]) + struct.pack(">H", len(data))
    out = hdr + bytes([crc8_maxim(hdr)]) + data
    if msg_type >= 0x80:
        out += struct.pack("<I", crc32_jam(data))
    return out


class Decoder:
    """Incremental frame parser; resyncs on 0xBC with a valid header CRC."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, chunk: bytes):
        self.buf += chunk
        frames = []
        while True:
            i = self.buf.find(0xBC)
            if i < 0:
                self.buf.clear()
                break
            del self.buf[:i]
            if len(self.buf) < 7:
                break
            if crc8_maxim(self.buf[:6]) != self.buf[6]:
                del self.buf[0]
                continue
            seq, reply_to, mtype = self.buf[1], self.buf[2], self.buf[3]
            n = struct.unpack(">H", self.buf[4:6])[0]
            total = 7 + n + (4 if mtype >= 0x80 else 0)
            if len(self.buf) < total:
                break
            data = bytes(self.buf[7:7 + n])
            ok = True
            if mtype >= 0x80:
                got = struct.unpack("<I", self.buf[7 + n:total])[0]
                # Accept either JAMCRC (cVEND) or standard CRC-32 (PIC32 doc).
                ok = got in (crc32_jam(data), binascii.crc32(data) & 0xFFFFFFFF)
            frames.append({"seq": seq, "replyTo": reply_to, "type": mtype, "data": data, "crc_ok": ok})
            del self.buf[:total]
        return frames


class SshSerial:
    """Bidirectional raw pipe to a device tty over ssh.

    Holding the tty while nx is running will fight with nx; stop it first
    (`pm3.py nx-stop`).
    """

    def __init__(self, tty: str, host: str = None):
        host = host if host is not None else HOST   # read HOST at call time so --host works
        cmd = (f"stty -F {tty} 115200 cs8 -cstopb -parenb raw -echo -ixon && "
               f"(cat {tty} & CATPID=$!; cat > {tty}; kill $CATPID)")
        self.p = subprocess.Popen(["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                                   "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                                   f"root@{host}", cmd],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.q = queue.Queue()
        self.dec = Decoder()
        threading.Thread(target=self._reader, daemon=True).start()
        self.seq = 0

    def _reader(self):
        while True:
            chunk = os.read(self.p.stdout.fileno(), 4096)
            if not chunk:
                self.q.put(None)
                return
            for f in self.dec.feed(chunk):
                self.q.put(f)

    def send(self, msg_type: int, data: bytes = b"", reply_to: int = 0) -> int:
        self.seq = (self.seq % 255) + 1
        self.p.stdin.write(encode(msg_type, data, self.seq, reply_to))
        self.p.stdin.flush()
        return self.seq

    def recv(self, timeout=2.0):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def request(self, msg_type: int, data: bytes = b"", timeout=2.0):
        seq = self.send(msg_type, data)
        deadline = time.time() + timeout
        while time.time() < deadline:
            f = self.recv(deadline - time.time())
            if f and f["replyTo"] == seq:
                return f
        return None

    def close(self):
        try:
            self.p.stdin.close()
        finally:
            self.p.terminate()


def fmt(f):
    return f"seq={f['seq']:02x} replyTo={f['replyTo']:02x} type={f['type']:02x} data={f['data'].hex()}" + \
        ("" if f["crc_ok"] else " CRC-BAD")


def ssh(cmd: str):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                           "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
                           f"root@{HOST}", cmd]).returncode


# --- PIC32 -----------------------------------------------------------------

PIC_KEYS = {
    0x0100: ("u8", "internal power button"), 0x03FB: ("u8", "ignition"),
    0x07E0: ("u8", "audio PA enable (1=on, 0=off)"),
    0x4000: ("u16", "watchdog residual s"), 0x4003: ("u16", "watchdog timeout s"),
    0x4004: ("u16", "boot watchdog timeout s"), 0x500B: ("u16", "ambient light"),
    0x5040: ("u16", "input voltage mV"),
    0x5041: ("u16", "rail ~3V3 mV"), 0x5042: ("u16", "rail ~24V mV"),
    0x5043: ("u16", "rail ~24V mV"), 0x5044: ("u16", "rail ~23V mV"),
    0x504f: ("u16", "rail 3V3 mV"), 0x5050: ("u16", "rail 5V mV"),
    0xc0c0: ("str", "timer stats"),
    0x8100: ("u32", "PwrOnTime"), 0x8102: ("u32", "PwrOnCnt"), 0x8103: ("u32", "StartCnt"),
    0x810A: ("u32", "ShutdownCnt"), 0x8110: ("u32", "WdCnt"),
    0xC000: ("str", "pic32 version"), 0xC001: ("str", "bootloader version"),
}


def decode_value(kind, raw: bytes):
    # ValueReadReply = key16 echo + value (big-endian). Strings carry a u16
    # length then NUL-separated fields. Verified on hardware.
    val = raw[2:]
    if kind == "str":
        return " | ".join(p.decode(errors="replace").strip() for p in val[2:].split(b"\0") if p)
    return int.from_bytes(val, "big")


def cmd_pic_read(args):
    s = SshSerial(PIC32_TTY)
    keys = [int(k, 16) for k in args.keys] or list(PIC_KEYS)
    for k in keys:
        r = s.request(0x02, struct.pack(">H", k))
        kind, name = PIC_KEYS.get(k, ("u16", "?"))
        if r is None:
            print(f"{k:04x} {name:28s} (no reply)")
        else:
            print(f"{k:04x} {name:28s} raw={r['data'].hex():20s} ~ {decode_value(kind, r['data'])}")
    s.close()


def cmd_watchdog(args):
    s = SshSerial(PIC32_TTY)
    r = s.request(0x04, struct.pack(">HH", 0x4003, args.seconds))
    print(fmt(r) if r else "no reply (the write may still have landed)")
    s.close()


def cmd_pic_raw(args):
    s = SshSerial(PIC32_TTY)
    r = s.request(int(args.type, 16), bytes.fromhex(args.data))
    print(fmt(r) if r else "no reply")
    s.close()


# --- cVEND -----------------------------------------------------------------

CARD_FUNCS = {"vdvka": 4, "mifare": 5, "iso": 6, "desfire": 7,
              "girogo": 8, "itso": 9, "ultralightc": 10}


def cmd_cvend_version(args):
    s = SshSerial(CVEND_TTY)
    r = s.request(0x02)
    print(fmt(r) if r else "no reply")
    if r:
        print(r["data"].decode(errors="replace"))
    s.close()


def cmd_beep(args):
    s = SshSerial(CVEND_TTY)
    # Buzzer: >HH = (frequency Hz, duration ms), big-endian. Verified on hardware;
    # ~2700 Hz is loudest (piezo resonance), volume is not adjustable.
    s.send(0x22, struct.pack(">HH", args.freq, args.ms))
    time.sleep(args.ms / 1000 + 0.2)
    s.close()


def _find_uid(d: bytes):
    """Find a 7-byte ISO14443A UID in a payload by its NXP prefix (0x04).

    Only matches NXP UIDs (MIFARE/DESFire/Ultralight); a 7-byte UID from
    another manufacturer, or a 4-byte UID, won't be found this way."""
    for i in range(len(d) - 6):
        if d[i] == 0x04:
            return ":".join(f"{b:02X}" for b in d[i:i + 7])
    return None


def decode_event(f):
    """Human-readable gloss for reader->host frames seen in practice."""
    t, d = f["type"], f["data"]
    if t == 0xED:  # log message: [level byte][ascii]
        return "LOG: " + d[1:].decode(errors="replace").strip()
    if t == 0xD5 and f["replyTo"] == 0:  # unsolicited card event
        # [subtype][status][7-byte UID]. subtype 0x00 = entered, 0x01 = left.
        if d[:1] == b"\x00":
            return "CARD IN  uid=" + ":".join(f"{b:02X}" for b in d[2:9])
        if d[:1] == b"\x01":
            return "CARD OUT"
    if t == 0xBE:  # UnhandledCard: UID present even for non-enabled card types
        uid = _find_uid(d)
        return "UNHANDLED card uid=" + uid if uid else "UNHANDLED card " + d.hex()
    if t in (0xB1, 0xB9):  # 14443A / DESFire card read (UID at offset 2)
        uid = _find_uid(d)
        return ("14443A" if t == 0xB1 else "DESFire") + " card uid=" + (uid or d.hex())
    if t in (0xB3, 0xBB):
        return ("14443A" if t == 0xB3 else "DESFire") + " card removed"
    if t == 0xD1:  # structured card record (TLV with 'dffee0NN' tags)
        tags = {}
        i = 0
        while i + 3 < len(d):
            if d[i:i+3] == b"\xdf\xfe\xe0":
                tag = d[i+3]; ln = d[i+4]; val = d[i+5:i+5+ln]
                tags[f"{tag:02x}"] = val.hex(); i += 5 + ln
            else:
                i += 1
        return "CARD RECORD " + " ".join(f"{k}={v}" for k, v in tags.items())
    return None


def cvend_enable(s, names, retries=8):
    """Replicate nx's real reader-enable handshake (reverse-engineered by
    LD_PRELOAD-sniffing nx) and retry until the reader actually acks an enable.

    The reader only accepts enables in the right state; the leading 0xEA primes
    it, but it can take several attempts (it ignores commands while busy/asleep).
    Returns True once an 0xE4 is acked (0xE5 … 0000)."""
    ids = [CARD_FUNCS[n] for n in names]
    for attempt in range(1, retries + 1):
        s.request(0xEA, bytes.fromhex("0100"), timeout=1.2)  # prime/wake
        s.request(0x02, timeout=1.2)                         # version
        for cid in ids:
            s.request(0xE4, bytes([0x00, cid, 0x01, 0x01]), timeout=1.2)
        s.request(0xAA, bytes.fromhex("6afec201"), timeout=1.2)   # 0xAA = SetTime (timestamp)
        # This replicates nx's handshake so the reader reports ENABLED types as
        # handled 0xD5 enter/leave events. It is NOT needed for raw UIDs: the
        # reader scans autonomously after boot and this init actually stops that
        # scan (see INTERFACE.md and tap_demo.py for the no-init 0xBE recipe).
        # The cert read (0xE9, ~1KB) completing is nx's CONNECTED->INITIALIZED mark.
        r = s.request(0xE8, bytes.fromhex("04fe0a0000"), timeout=2.0)
        if r and r["type"] == 0xE9 and len(r["data"]) > 100:
            print(f"reader INITIALIZED (cert read ok, attempt {attempt})")
            return True
        print(f"arm attempt {attempt}: no cert yet, retrying ...")
        for _ in range(3):
            s.send(0x04); time.sleep(0.3)   # nudge awake between tries
    print("reader never returned cert (continuing; polling may be off)")
    return False


def cvend_wait_startup(s, timeout=75):
    """Wait for the reader's 0x0F Startup frame (its power-on completion)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        f = s.recv(2.0)
        if f and f["type"] == 0x0F:
            return True
    return False


def cmd_cvend_watch(args):
    """Enable card functions and print every frame the reader sends."""
    s = SshSerial(CVEND_TTY)
    if args.reset or args.wait_startup:
        print("restarting reader (0x10 02) and waiting for 0x0F startup ...")
        s.send(0x10, b"\x02")  # subcode 2 = restart app -> 0x0F Startup (bare 0x10 wedges it)
        print("startup seen" if cvend_wait_startup(s) else "no startup (continuing)")
    cvend_enable(s, args.enable)
    print("--- tap a card ---")
    last_status = 0
    try:
        while True:
            if time.time() - last_status > 5:  # keep the reader awake
                s.send(0x04)
                last_status = time.time()
            f = s.recv(1.0)
            if f is None:
                if s.p.poll() is not None:
                    break
                continue
            if f["type"] in (0x05, 0x07) and not args.verbose:
                continue
            g = decode_event(f)
            print(fmt(f) + (f"\n    -> {g}" if g else ""))
    except KeyboardInterrupt:
        pass
    s.close()


# --- cVEND file operations -------------------------------------------------
# The reader runs its own embedded Linux (FEIG cVEND, Buildroot 2014.05). These
# two IPP commands read its filesystem; layouts reverse-engineered by sniffing
# nx and verified on hardware. Read-only -- the write ops (0x96 PutFile, 0x9A
# DeleteFile) are deliberately not wrapped here.

def cvend_filelist(s, path):
    """0xA4 FileList -> 0xA5. Returns [(name, mtime_iso), ...] or None."""
    pl = path.encode()
    r = s.request(0xA4, struct.pack(">H", len(pl)) + pl, timeout=3.0)
    if not r:
        return None
    body = r["data"][4:]  # skip u32 reply length
    toks = [t.decode(errors="replace") for t in body.split(b"\0") if t]
    return list(zip(toks[0::2], toks[1::2]))   # name, timestamp pairs


def cvend_getfile(s, path, offset=0, count=0xF000):
    """0x98 GetFile -> 0x99. payload=[u16 pathlen][path][u32 offset][u16 count];
    reply=[u32 len][data]. One frame (count <= ~60KB). Returns bytes or None."""
    pl = path.encode()
    r = s.request(0x98, struct.pack(">H", len(pl)) + pl + struct.pack(">IH", offset, count),
                  timeout=5.0)
    if not r:
        return None
    d = r["data"]
    n = struct.unpack(">I", d[:4])[0] if len(d) >= 4 else 0
    return d[4:4 + n]


def cvend_fileinfo(s, path, off=0, length=0):
    """0x9C FileInfo -> 0x9D. payload=[u16 pathlen][path][u32 off][u32 length];
    reply (10 bytes) = [status:u16][size:u32 BE][crc32:u32 BE] (CRC is a FEIG
    variant, not standard/JAM CRC-32). off/length bound the CRC range; 0,0 =
    whole file. Returns (status, size, crc32) or None."""
    pl = path.encode()
    r = s.request(0x9C, struct.pack(">H", len(pl)) + pl + struct.pack(">II", off, length),
                  timeout=2.5)
    if not r or len(r["data"]) < 10:
        return None
    status = struct.unpack(">H", r["data"][0:2])[0]
    size, crc = struct.unpack(">II", r["data"][2:10])
    return status, size, crc


def cmd_cvend_finfo(args):
    s = SshSerial(CVEND_TTY)
    info = cvend_fileinfo(s, args.path)
    if info is None:
        print("(no reply / short reply)")
    else:
        st, size, crc = info
        print(f"status={st:#04x}  size={size}  crc32={crc:#010x}")
    s.close()


def cmd_cvend_ls(args):
    s = SshSerial(CVEND_TTY)
    rows = cvend_filelist(s, args.path)
    if rows is None:
        print("(no reply -- not a directory, a plain file, or reader busy)")
    else:
        for name, mtime in rows:
            print(f"{mtime}  {name}")
    s.close()


def cmd_cvend_cat(args):
    # Read the whole file: 0x98 returns one frame per call (up to --count bytes),
    # so loop from the offset until a short frame marks the end.
    s = SshSerial(CVEND_TTY)
    out = bytearray()
    offset = args.offset
    data = cvend_getfile(s, args.path, offset, args.count)
    if data is None:
        s.close()
        print("(no reply)")
        return
    while data:
        out += data
        offset += len(data)
        if len(data) < args.count:
            break
        data = cvend_getfile(s, args.path, offset, args.count)
        if data is None:
            print(f"(partial: no reply after {len(out)} bytes at offset {offset})", file=sys.stderr)
            break
    s.close()
    if args.hex:
        print(bytes(out).hex())
    else:
        sys.stdout.buffer.write(bytes(out))


def cmd_cvend_restart(args):
    """Clean software restart of the reader app via 0x10 subcode 2.

    Recovers a reader that has gone to sleep (scanning stopped) WITHOUT a physical
    power cycle: ~6 s later the reader emits 0x0F Startup and is back in its fresh
    post-boot scanning state. Bare 0x10 (no subcode) instead wedges it -- always
    send the subcode."""
    s = SshSerial(CVEND_TTY)
    print("restarting reader app (0x10 02) ...")
    s.send(0x10, b"\x02")                 # subcode 2 = restart application
    ok = cvend_wait_startup(s, timeout=20)
    print("0x0F Startup seen -- reader restarted, scanning fresh"
          if ok else "no 0x0F within 20s (rare; if unresponsive, power-cycle)")
    s.close()


# --- audio (ALSA speaker) --------------------------------------------------
# The grille speakers are on the TLV320AIC32x4 Line-Out, ALSA card 0 "PM3 Audio",
# but the Line-Out feeds an EXTERNAL power amp ("PAmobil2") that is OFF at power-on
# and switched on over the PIC32: ValueWrite key 0x07E0, 1 = on, 0 = off -- one master
# gate for both channels, readable, latched until the PIC32 resets at power-off. With
# the amp off the codec/mixer/clocks are all fine and the speaker is still SILENT,
# which is why playback historically "needed nx": nx switches the amp on once at
# startup (its NxPaCtrl / NxPaMobil2PicDev). `play` and `amp on` set 0x07E0=1 here, so
# no nx is needed. Two ALSA details still matter: keep the stock routing (alsactl
# restore) with `LO Driver Gain` 6 (0 dB baseline), and play a FILE, not a pipe (stdin
# into aplay is silent on this device). The piezo buzzer (beep) is separate hardware
# and always works. See INTERFACE.md for the full story.

PA_ENABLE_KEY = 0x07E0   # PIC32 audio power-amp master enable: 1 = on, 0 = off


def _pic_set_amp(enable: bool):
    """Switch the external audio power amp on/off via PIC32 ValueWrite 0x07E0."""
    s = SshSerial(PIC32_TTY)
    s.request(0x04, struct.pack(">H", PA_ENABLE_KEY) + bytes([1 if enable else 0]))
    s.close()


def cmd_amp(args):
    s = SshSerial(PIC32_TTY)
    if args.state == "status":
        r = s.request(0x02, struct.pack(">H", PA_ENABLE_KEY))
        if r is None:
            print("no reply")
        else:
            on = int.from_bytes(r["data"][2:], "big")
            print(f"amp {'on' if on else 'off'} (0x07e0={on})")
    else:
        s.request(0x04, struct.pack(">H", PA_ENABLE_KEY) + bytes([1 if args.state == "on" else 0]))
        print(f"amp {args.state}")
    s.close()


def cmd_play(args):
    if not os.path.isfile(args.file):
        print(f"no such file: {args.file}", file=sys.stderr)
        sys.exit(1)
    if not args.no_amp:
        _pic_set_amp(True)   # external power amp on (PIC32 0x07E0 = 1); harmless if already on
    remote = "/tmp/pm3play-" + os.path.basename(args.file)
    opts = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
    if subprocess.run(["scp", "-O", *opts, args.file, f"root@{HOST}:{remote}"]).returncode:
        print("scp failed", file=sys.stderr)
        sys.exit(1)
    setup = []
    if not args.no_restore:
        setup.append("alsactl -f /etc/asound.state restore >/dev/null 2>&1")
    setup.append(f"amixer -c 0 sset 'LO Driver Gain' {args.lo_gain} >/dev/null")
    setup.append(f"amixer -c 0 sset PCM {args.pcm}% >/dev/null")
    for m in args.mixer or []:
        name, _, val = m.partition("=")
        setup.append(f"amixer -c 0 sset '{name}' '{val}' >/dev/null")
    # Show the resulting level: PCM percent is very non-linear here (0 dB is ~73%,
    # 15% is about -50 dB / inaudible), so print the actual dB before playing.
    setup.append("printf 'PCM level: '; amixer -c 0 sget PCM | grep -i 'playback.*dB' | head -1")
    # aplay's own exit status is what we return; clean up the temp file either way.
    cmd = "; ".join(setup) + f"; aplay {remote}; rc=$?; "
    if not args.keep:
        cmd += f"rm -f {remote}; "
    sys.exit(ssh(cmd + "exit $rc"))


# --- system ----------------------------------------------------------------

def cmd_nx_stop(args):
    # Order matters: stop nx, then kill the watchdog before it powers us off.
    # NxExe is in PATH (/usr/bin); disable the watchdog via IPP as a fallback so
    # this never leaves the unit counting down to poweroff.
    rc = ssh("systemctl stop nx; systemctl stop init-abtproxy; NxExe watchdog 0 2>/dev/null")
    s = SshSerial(PIC32_TTY)
    s.request(0x04, struct.pack(">HH", 0x4003, 0))  # ValueWrite watchdog timeout = 0
    s.close()
    sys.exit(rc)


def cmd_nx_start(args):
    sys.exit(ssh("systemctl start init-abtproxy; systemctl start nx"))


def cmd_info(args):
    sys.exit(ssh("uname -a; uptime; cat /etc/os-release 2>/dev/null; free; df -h; "
                 "systemctl is-active nx init-abtproxy; ls /dev/ttymxc* /dev/ttyUSB* /dev/fb* 2>/dev/null"))


def main():
    global HOST
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=HOST, help="unit IP or hostname (default: $PM3_HOST or %(default)s)")
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("info", help="print kernel, uptime, memory, services, and ttys").set_defaults(fn=cmd_info)
    sp.add_parser("nx-stop", help="stop stock UI + disable watchdog").set_defaults(fn=cmd_nx_stop)
    sp.add_parser("nx-start", help="start the stock UI (nx) and abtproxy again").set_defaults(fn=cmd_nx_start)

    p = sp.add_parser("pic-read", help="read PIC32 keys (hex); default: all known keys")
    p.add_argument("keys", nargs="*", help="16-bit keys in hex, e.g. 5040 c000 (see PIC_KEYS)")
    p.set_defaults(fn=cmd_pic_read)
    p = sp.add_parser("watchdog", help="set PIC32 watchdog timeout (0 = off)")
    p.add_argument("seconds", type=int, help="timeout in seconds; 0 disables the watchdog")
    p.set_defaults(fn=cmd_watchdog)
    p = sp.add_parser("pic-raw", help="send a raw IPP frame to the PIC32")
    p.add_argument("type", help="message type byte in hex, e.g. 02")
    p.add_argument("data", nargs="?", default="", help="payload as hex, e.g. 5040 (default: none)")
    p.set_defaults(fn=cmd_pic_raw)
    p = sp.add_parser("amp", help="switch the external audio power amp (PIC32 0x07E0) on/off, or read its state")
    p.add_argument("state", choices=["on", "off", "status"], help="on, off, or status")
    p.set_defaults(fn=cmd_amp)

    sp.add_parser("cvend-version", help="print the cVEND reader firmware version").set_defaults(fn=cmd_cvend_version)
    p = sp.add_parser("beep", help="sound the cVEND piezo buzzer")
    p.add_argument("--freq", type=int, default=2000, help="frequency in Hz (default 2000; ~2700 is loudest)")
    p.add_argument("--ms", type=int, default=200, help="duration in milliseconds (default 200)")
    p.set_defaults(fn=cmd_beep)
    p = sp.add_parser("play", help="play a WAV through the Line-Out speaker (enables the PIC32 power amp first; no nx needed)")
    p.add_argument("file", help="local .wav file (copied to the unit, then aplay'd)")
    p.add_argument("--no-amp", action="store_true",
                   help="don't touch the PIC32 amp enable (0x07E0) before playing")
    p.add_argument("--pcm", type=int, default=65,
                   help="PCM volume percent (default 65; non-linear: ~73%% = 0 dB, 15%% is near silent)")
    p.add_argument("--lo-gain", type=int, default=6,
                   help="LO Driver Gain 0-35 (default 6 = 0 dB baseline; raise PCM for volume)")
    p.add_argument("--no-restore", action="store_true",
                   help="skip 'alsactl restore' of the stock output routing")
    p.add_argument("--keep", action="store_true", help="leave the uploaded file on the unit")
    p.add_argument("--mixer", action="append", metavar="NAME=VAL",
                   help="extra amixer control, e.g. --mixer 'HP Driver Gain=6' (repeatable)")
    p.set_defaults(fn=cmd_play)
    p = sp.add_parser("cvend-watch", help="enable card types and dump reader events")
    p.add_argument("--enable", nargs="*", default=list(CARD_FUNCS), choices=list(CARD_FUNCS))
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--wait-startup", action="store_true",
                   help="wait for the reader's 0x0F boot frame before enabling (use right after power-on)")
    p.add_argument("--reset", action="store_true",
                   help="restart the reader (0x10 02) and wait for its 0x0F startup, then enable (reliable cold arm)")
    p.set_defaults(fn=cmd_cvend_watch)

    sp.add_parser("cvend-restart", help="clean software restart of the reader app (0x10 02); wakes a slept reader").set_defaults(fn=cmd_cvend_restart)
    p = sp.add_parser("cvend-ls", help="list a directory on the reader's own filesystem (0xA4)")
    p.add_argument("path")
    p.set_defaults(fn=cmd_cvend_ls)
    p = sp.add_parser("cvend-cat", help="read a file from the reader's own filesystem (0x98)")
    p.add_argument("path", help="absolute path on the reader, e.g. /home/app0/config")
    p.add_argument("--offset", type=int, default=0, help="start reading at this byte offset (default 0)")
    p.add_argument("--count", type=lambda x: int(x, 0), default=0xF000,
                   help="bytes per frame; the file is read in chunks of this size (default 0xF000)")
    p.add_argument("--hex", action="store_true", help="print hex instead of raw bytes")
    p.set_defaults(fn=cmd_cvend_cat)
    p = sp.add_parser("cvend-finfo", help="file size + CRC32 from the reader's filesystem (0x9C)")
    p.add_argument("path")
    p.set_defaults(fn=cmd_cvend_finfo)

    args = ap.parse_args()
    HOST = args.host
    args.fn(args)


if __name__ == "__main__":
    main()
