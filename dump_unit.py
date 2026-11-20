#!/usr/bin/env python3
"""dump_unit.py -- full capture + stock-restore for an INIT PROXmobil3 unit.

Does, over SSH (root access is provided by the mp_sd [TestMode] dongle's autorun),
everything we do by hand to a borrowed unit, writing to dumps/unit<SERIAL>/:

  1. identify     - TQMa6S module EEPROM serial  -> dumps/unit<SERIAL>/
  2. hardware     - hwscan.txt, dmesg.txt
  3. storage      - mtdblock0.img.gz, sda.img.gz, sdb.img.gz  (streamed dd|gzip, sha256)
  4. provisioning - host-archive/  (the .p72/.g72/.C72 dataset from /init/efad/data/archive)
  5. reader fw    - reader-firmware/  (cVEND kernel+rootfs+app, unpacked from V0200.C72)
  6. reader live  - reader-live/  (config/version/EMV counter/Girogo, via pm3.py over the serial)
  7. SUMMARY.md   - manifest with serial, hardware, checksums
  8. cleanup      - restore stock sshd_config (from the autorun's own .stock backup),
                    remove our key + the sshd.socket enable, remount rootfs ro
                    (skip with --no-cleanup)

Usage:
    python3 dump_unit.py --host 192.168.1.98
    python3 dump_unit.py --host 10.0.1.102 --no-cleanup          # keep our access
    python3 dump_unit.py --host 192.168.1.98 --no-reader --no-dump   # scans only

The dumps hold operator production data; the dumps/ tree is git-ignored. After a run
with cleanup, we are locked out (stock restored) -- pull the dongle before returning
the unit.  Reader file-ops reuse pm3.py (same directory).
"""
import argparse
import gzip
import hashlib
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PM3 = os.path.join(HERE, "pm3.py")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=12"]


def log(msg):
    print(f"[dump_unit] {msg}", flush=True)


def sh(host, cmd, timeout=90):
    """Run a shell command on the unit over ssh; return stdout (text)."""
    r = subprocess.run(SSH + [f"root@{host}", cmd], capture_output=True, text=True, timeout=timeout)
    return r.stdout


def reachable(host):
    return subprocess.run(SSH + [f"root@{host}", "true"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# ---- 1. identify -----------------------------------------------------------

def identify(host):
    """Return (serial, part, mac) from the TQMa6S module EEPROM + eth0."""
    strs = [l.strip() for l in sh(host,
            "strings /sys/bus/i2c/devices/2-0050/eeprom 2>/dev/null").splitlines() if l.strip()]
    serial = strs[0] if strs else ""
    part = next((l for l in strs if l.startswith("TQMa")), "")
    mac = sh(host, "cat /sys/class/net/eth0/address 2>/dev/null").strip()
    if not serial:
        serial = mac.replace(":", "") or "unknown"
    return serial, part, mac


# ---- 2. hardware scan ------------------------------------------------------

HWSCAN = r'''
echo "### uname"; uname -a
echo "### cmdline"; cat /proc/cmdline
echo "### dt-model"; cat /proc/device-tree/model; echo; tr "\0" " " < /proc/device-tree/compatible; echo
echo "### cpuinfo"; cat /proc/cpuinfo
echo "### partitions"; cat /proc/partitions
echo "### mtd"; cat /proc/mtd
echo "### blkid"; blkid 2>/dev/null
echo "### mount"; mount
echo "### df"; df -h 2>/dev/null
echo "### net"; ip addr 2>/dev/null | grep -E "inet |ether"
echo "### i2c-devices"; for d in /sys/bus/i2c/devices/*/name; do echo "$d: $(cat $d)"; done 2>/dev/null
echo "### i2c-scan"; for b in 0 1 2; do echo "-- bus $b --"; i2cdetect -y -r $b 2>/dev/null; done
echo "### module-eeprom"; xxd /sys/bus/i2c/devices/2-0050/eeprom 2>/dev/null | head -8
echo "### lm75-temp"; cat /sys/class/hwmon/hwmon*/temp1_input 2>/dev/null
echo "### usb"; cat /sys/kernel/debug/usb/devices 2>/dev/null
echo "### serial-ports"; ls -la /dev/ttymxc* /dev/ttyUSB* 2>/dev/null
echo "### gpio"; cat /sys/kernel/debug/gpio 2>/dev/null
echo "### lsmod"; lsmod
echo "### enabled-services"; systemctl list-unit-files --state=enabled 2>/dev/null
echo "### os-release"; cat /etc/os-release 2>/dev/null
echo "### uboot-env"; fw_printenv 2>/dev/null || echo "(no fw_printenv; env is in mtdblock0.img.gz)"
'''


def hardware_scan(host, outdir):
    log("hardware scan (hwscan.txt, dmesg.txt)")
    with open(os.path.join(outdir, "hwscan.txt"), "w") as f:
        f.write(sh(host, HWSCAN, timeout=120))
    with open(os.path.join(outdir, "dmesg.txt"), "w") as f:
        f.write(sh(host, "dmesg", timeout=60))


# ---- 3. storage dump -------------------------------------------------------

def dump_block(host, dev, outpath):
    """Stream `dd if=/dev/<dev>` over ssh -> gzip locally, returning (sha256, bytes)."""
    log(f"dumping /dev/{dev} -> {os.path.basename(outpath)} (streaming dd|gzip)")
    p = subprocess.Popen(SSH + [f"root@{host}", f"dd if=/dev/{dev} bs=1M 2>/dev/null"],
                         stdout=subprocess.PIPE)
    h = hashlib.sha256()
    total = 0
    with gzip.open(outpath, "wb", compresslevel=3) as gz:
        while True:
            chunk = p.stdout.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            gz.write(chunk)
            total += len(chunk)
    p.wait()
    log(f"  {dev}: {total:,} bytes  sha256={h.hexdigest()}")
    return h.hexdigest(), total


# ---- 4. provisioning archives ---------------------------------------------

def copy_archives(host, outdir):
    dst = os.path.join(outdir, "host-archive")
    os.makedirs(dst, exist_ok=True)
    log("copying /init/efad/data/archive -> host-archive/")
    p1 = subprocess.Popen(SSH + [f"root@{host}", "tar -C /init/efad/data/archive -cf - . 2>/dev/null"],
                          stdout=subprocess.PIPE)
    p2 = subprocess.Popen(["tar", "-xf", "-", "-C", dst], stdin=p1.stdout)
    p1.stdout.close()
    p2.wait()
    p1.wait()
    return sorted(os.listdir(dst))


# ---- 5. reader firmware (from the host archive) ----------------------------

def unpack_reader_fw(outdir):
    rf = os.path.join(outdir, "reader-firmware")
    c72 = os.path.join(outdir, "host-archive", "V0200.C72")
    if not os.path.isfile(c72):
        log("no V0200.C72 in host-archive -- skipping reader firmware")
        return None
    os.makedirs(rf, exist_ok=True)
    log("unpacking cVEND reader firmware from V0200.C72")
    subprocess.run(["unzip", "-o", "-q", c72, "-d", rf], check=False)
    app = os.path.join(rf, "feig", "app0", "update.tar.gz")
    if os.path.isfile(app):
        ex = os.path.join(rf, "app0-extracted")
        os.makedirs(ex, exist_ok=True)
        subprocess.run(["tar", "-xzf", app, "-C", ex], check=False)
    av = os.path.join(rf, "feig", "app0", "version")
    return open(av).read().strip() if os.path.isfile(av) else None


# ---- 6. live reader config (over the serial, via pm3.py) -------------------

READER_LISTS = ["/home/app0", "/home/app0/emv", "/home/app0/ggo",
                "/home/app0/ggo/cfg", "/home/app0/ggo/int"]
READER_FILES = [("/home/app0/config", "config.bin"),
                ("/home/app0/version", "version.bin"),
                ("/home/app0/emv/transact-counter.dat", "emv-transact-counter.dat"),
                ("/home/app0/ggo/cfg/persdata.bin", "ggo-persdata.bin")]


def reader_live(host, outdir):
    rl = os.path.join(outdir, "reader-live")
    os.makedirs(rl, exist_ok=True)
    env = {**os.environ, "PM3_HOST": host}
    log("live reader pull (restart + version + config over the serial)")

    def pm3_text(args, timeout=45):
        return subprocess.run([sys.executable, PM3, *args], env=env,
                              capture_output=True, text=True, timeout=timeout).stdout

    def pm3_bytes(args, timeout=45):
        return subprocess.run([sys.executable, PM3, *args], env=env,
                              capture_output=True, timeout=timeout).stdout

    pm3_text(["cvend-restart"])              # wake a slept/idle reader
    open(os.path.join(rl, "version.txt"), "w").write(pm3_text(["cvend-version"]))
    for path in READER_LISTS:
        name = "ls" + path.replace("/home/app0", "").replace("/", "-") + ".txt"
        open(os.path.join(rl, name), "w").write(pm3_text(["cvend-ls", path]))
    for path, name in READER_FILES:
        data = pm3_bytes(["cvend-cat", path])
        if data:
            open(os.path.join(rl, name), "wb").write(data)


# ---- 7. manifest -----------------------------------------------------------

def write_summary(outdir, serial, part, mac, host, sums, archives, reader_ver):
    dt = ""
    hp = os.path.join(outdir, "hwscan.txt")
    if os.path.isfile(hp):
        lines = open(hp, errors="replace").read().splitlines()
        for i, l in enumerate(lines):
            if l.startswith("### dt-model") and i + 1 < len(lines):
                dt = lines[i + 1].strip()
                break
    with open(os.path.join(outdir, "SUMMARY.md"), "w") as f:
        f.write(f"# PM3 unit dump — {host}\n\n")
        f.write(f"- Module: **{part or '?'}**, serial **{serial}**, MAC {mac}\n")
        f.write(f"- Device-tree model: {dt}\n")
        f.write(f"- Captured: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Storage dumps (gzipped; sha256 of decompressed image)\n")
        for name, sha in sums.items():
            f.write(f"- {name}  sha256={sha}\n")
        f.write("\n## Also captured\n")
        f.write("- hwscan.txt, dmesg.txt\n")
        f.write(f"- host-archive/ — provisioning dataset: {' '.join(archives)}\n")
        f.write(f"- reader-firmware/ — cVEND firmware (kernel/rootfs/app), version {reader_ver}\n")
        f.write("- reader-live/ — live reader config pulled over the serial\n\n")
        f.write("Operator production data — keep local, do not commit/publish.\n")


# ---- 8. cleanup ------------------------------------------------------------

CLEANUP = r'''
mount -o remount,rw /
[ -f /etc/ssh/sshd_config.stock ] && cp /etc/ssh/sshd_config.stock /etc/ssh/sshd_config && rm -f /etc/ssh/sshd_config.stock && echo "sshd_config restored to stock"
rm -f /root/.ssh/authorized_keys; rmdir /root/.ssh 2>/dev/null && echo "/root/.ssh removed" || echo "/root/.ssh kept (not empty)"
systemctl disable sshd.socket 2>&1 | grep -i removed || echo "sshd.socket disable done"
sync; mount -o remount,ro / 2>&1 && echo "rootfs read-only again"
echo "VERIFY: stock_backup=$([ -f /etc/ssh/sshd_config.stock ] && echo PRESENT-BAD || echo gone) key=$([ -e /root/.ssh/authorized_keys ] && echo PRESENT-BAD || echo gone) enable_symlink=$([ -L /etc/systemd/system/sockets.target.wants/sshd.socket ] && echo PRESENT-BAD || echo gone) rootfs=$(mount | grep 'on / ' | grep -oE '\(ro|\(rw')"
'''


def cleanup(host):
    log("cleanup: restore stock config, remove our traces")
    # runs fully server-side; our ssh session survives until the command returns,
    # then we are locked out (which confirms the key/config were removed).
    print(sh(host, CLEANUP, timeout=60))


# ---- orchestration ---------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Full capture + stock-restore of a PROXmobil3 unit.")
    ap.add_argument("--host", required=True, help="unit IP (reachable via the [TestMode] dongle's ssh)")
    ap.add_argument("--out", default=os.path.join(HERE, "dumps"), help="output root (default: ./dumps)")
    ap.add_argument("--no-dump", action="store_true", help="skip the big block dumps (scans only)")
    ap.add_argument("--no-reader", action="store_true", help="skip the live reader serial pull")
    ap.add_argument("--no-cleanup", action="store_true", help="leave our ssh access in place")
    a = ap.parse_args()
    host = a.host

    if not reachable(host):
        log(f"cannot ssh root@{host} — is the unit booted with the [TestMode] dongle inserted?")
        sys.exit(1)

    serial, part, mac = identify(host)
    outdir = os.path.join(a.out, f"unit{serial}")
    os.makedirs(outdir, exist_ok=True)
    log(f"unit serial={serial} part={part} mac={mac}")
    log(f"output -> {outdir}")

    hardware_scan(host, outdir)

    sums = {}
    if not a.no_dump:
        for dev, name in [("mtdblock0", "mtdblock0.img.gz"), ("sda", "sda.img.gz"), ("sdb", "sdb.img.gz")]:
            sha, _ = dump_block(host, dev, os.path.join(outdir, name))
            sums[name] = sha
    else:
        log("--no-dump: skipping block dumps")

    archives = copy_archives(host, outdir)
    reader_ver = unpack_reader_fw(outdir)

    if not a.no_reader:
        try:
            reader_live(host, outdir)
        except Exception as e:
            log(f"reader-live skipped ({e})")

    write_summary(outdir, serial, part, mac, host, sums, archives, reader_ver)
    log(f"capture complete -> {outdir}")

    if a.no_cleanup:
        log("--no-cleanup: our SSH access is still on the unit.")
    else:
        cleanup(host)
        log("cleanup done — we are now locked out (stock restored).")
        log("Pull the mp_sd dongle before returning the unit; the next boot is then stock nx.")


if __name__ == "__main__":
    main()
