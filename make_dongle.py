#!/usr/bin/env python3
"""make_dongle.py: prepare a PROXmobil3 access dongle (USB) on macOS or Linux.

Formats a USB stick the way the unit's boot expects (MBR, one FAT32 partition
labelled MP_SD) and copies the access payload onto it:

  - autorun.sh      the boot script: enables root SSH, disables the watchdog, leaves
                    nx stopped. Plain (usb/autorun.sh) by default, or the auto-dump
                    variant with --autodump (usb/autorun-autodump.sh), which also
                    captures the unit to pm3-dump/ on the stick on first boot
  - authorized_keys the SSH public key(s) you choose
  - .pm3-nodump     marker so dump_unit.py never captures this dongle

Plug the result into the dongle's USB-A port and power-cycle the unit (see README).

Keys can come from a local .pub file, an https:// URL, a GitHub username
(github.com/<user>.keys), or one or more keys from ~/.ssh/*.pub.

Usage:
    ./make_dongle.py                                  # interactive: pick disk + keys
    ./make_dongle.py --device disk4 --key ~/.ssh/id_ed25519.pub
    ./make_dongle.py --github octocat --dry-run
    ./make_dongle.py --device sdb --autodump --key-url https://example.com/me.pub --yes

Formatting erases the whole disk. The tool only offers external/removable disks,
never the system disk, and asks you to type the device name before it erases.

Requirements: Python 3. macOS uses the built-in `diskutil`. Linux uses `lsblk`,
`parted`, `mkfs.vfat` (dosfstools), `partprobe`/`udevadm` (util-linux), and `sudo`.
"""
import argparse
import contextlib
import glob
import json
import os
import platform
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
USB_DIR = os.path.join(HERE, "usb")
AUTORUN_PLAIN = os.path.join(USB_DIR, "autorun.sh")           # SSH + watchdog off, no dump
AUTORUN_DUMP = os.path.join(USB_DIR, "autorun-autodump.sh")   # the above + one-time auto-dump

KEY_TYPES = {
    "ssh-ed25519", "ssh-rsa", "ssh-dss",
    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
    "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com",
}


def die(msg):
    print(f"make_dongle: {msg}", file=sys.stderr)
    sys.exit(1)


@contextlib.contextmanager
def _ignore_sigint():
    """Let a destructive format or cleanup step finish despite Ctrl-C."""
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old)


def run(cmd):
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def run_ok(cmd, tries=1, delay=2.0):
    """Run best-effort; retry on failure. Returns True if it eventually succeeds."""
    print("  $ " + " ".join(cmd))
    for i in range(tries):
        if subprocess.run(cmd).returncode == 0:
            return True
        if i + 1 < tries:
            time.sleep(delay)
    return False


# --- SSH keys ---------------------------------------------------------------

def valid_key(line):
    p = line.split()
    return (len(p) >= 2 and p[0] in KEY_TYPES
            and re.fullmatch(r"[A-Za-z0-9+/]+={0,3}", p[1]) is not None and len(p[1]) > 20)


def keys_from_text(text, where):
    """Pull valid public-key lines out of fetched/read text; warn on the rest."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if valid_key(line):
            found.append(line)
        else:
            print(f"  (ignored a non-key line from {where})")
    return found


def keys_from_file(path):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        die(f"no such key file: {path}")
    with open(path) as f:
        ks = keys_from_text(f.read(), path)
    if not ks:
        die(f"no valid SSH public key in {path}")
    return ks


def keys_from_url(url):
    if not url.lower().startswith("https://"):
        die(f"refusing non-https key URL: {url}")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as e:
        die(f"fetch failed ({url}): {e}")
    ks = keys_from_text(text, url)
    if not ks:
        die(f"no valid SSH public key at {url}")
    return ks


def keys_from_github(user):
    return keys_from_url(f"https://github.com/{user.strip().lstrip('@')}.keys")


def local_pubs():
    return sorted(glob.glob(os.path.expanduser("~/.ssh/*.pub")))


def key_label(line):
    p = line.split()
    return f"{p[0]} ...{p[1][-12:]}" + (f"  {p[2]}" if len(p) > 2 else "")


def collect_keys(args):
    """Flags win; otherwise ask interactively."""
    keys = []
    for path in args.key or []:
        keys += keys_from_file(path)
    for url in args.key_url or []:
        keys += keys_from_url(url)
    for user in args.github or []:
        keys += keys_from_github(user)
    if keys:
        return dedupe(keys)
    if not sys.stdin.isatty():
        die("no keys given (--key/--key-url/--github) and no terminal to ask")
    return dedupe(interactive_keys())


def dedupe(keys):
    seen, out = set(), []
    for k in keys:
        sig = " ".join(k.split()[:2])   # type+blob, ignore comment
        if sig not in seen:
            seen.add(sig)
            out.append(k)
    return out


def interactive_keys():
    pubs = local_pubs()
    chosen = []
    while True:
        print("\nSSH keys to install" + (f" (so far: {len(chosen)})" if chosen else "") + ":")
        for i, p in enumerate(pubs, 1):
            try:
                with open(p) as f:
                    lbl = key_label(f.readline().strip())
            except OSError:
                lbl = "(unreadable)"
            print(f"  {i}) {p}  [{lbl}]")
        print("  p) a local file path")
        print("  u) an https:// URL")
        print("  g) a GitHub username")
        print("  d) done" + ("" if chosen else " (need at least one key)"))
        sel = input("select (e.g. 1,3 or p/u/g/d): ").strip().lower()
        if sel == "d":
            if chosen:
                return chosen
            print("  pick at least one key first.")
            continue
        if sel == "p":
            chosen += keys_from_file(input("  path to .pub: ").strip())
        elif sel == "u":
            chosen += keys_from_url(input("  https:// URL: ").strip())
        elif sel == "g":
            chosen += keys_from_github(input("  GitHub username: ").strip())
        else:
            for tok in sel.replace(" ", "").split(","):
                if tok.isdigit() and 1 <= int(tok) <= len(pubs):
                    with open(pubs[int(tok) - 1]) as f:
                        chosen += keys_from_text(f.read(), pubs[int(tok) - 1])
                elif tok:
                    print(f"  ignoring '{tok}'")
        chosen = dedupe(chosen)


# --- disk discovery ---------------------------------------------------------

class Disk:
    def __init__(self, ident, dev, size, model):
        self.ident, self.dev, self.size, self.model = ident, dev, size, model

    def human(self):
        gb = self.size / 1e9
        return f"{self.ident:10s} {gb:6.1f} GB  {self.model}"


def external_disks():
    if IS_MAC:
        return _macos_disks()
    if IS_LINUX:
        return _linux_disks()
    die(f"unsupported OS: {platform.system()} (macOS or Linux only)")


def _macos_disks():
    out = subprocess.run(["diskutil", "list", "-plist", "external", "physical"],
                         capture_output=True).stdout
    whole = plistlib.loads(out).get("WholeDisks", []) if out else []
    disks = []
    for ident in whole:
        info = plistlib.loads(subprocess.run(["diskutil", "info", "-plist", ident],
                                             capture_output=True).stdout)
        if info.get("Internal"):
            continue
        model = info.get("MediaName") or info.get("IORegistryEntryName") or "?"
        disks.append(Disk(ident, f"/dev/{ident}", info.get("TotalSize", 0), model))
    return disks


def _linux_disks():
    out = subprocess.run(["lsblk", "-J", "-b", "-o",
                          "NAME,SIZE,TYPE,RM,HOTPLUG,MODEL,TRAN,MOUNTPOINT"],
                         capture_output=True, text=True).stdout
    disks = []
    for d in json.loads(out).get("blockdevices", []):
        if d.get("type") != "disk":
            continue
        removable = _truthy(d.get("rm")) or _truthy(d.get("hotplug")) or d.get("tran") == "usb"
        if not removable or _holds_root(d):
            continue
        disks.append(Disk(d["name"], f"/dev/{d['name']}", int(d.get("size") or 0),
                          (d.get("model") or "?").strip()))
    return disks


def _truthy(v):
    return v in (True, 1, "1")


def _holds_root(node):
    if node.get("mountpoint") == "/":
        return True
    return any(_holds_root(c) for c in node.get("children", []))


def choose_disk(args):
    disks = external_disks()
    if args.device:
        want = args.device.replace("/dev/", "")
        for d in disks:
            if d.ident == want:
                return d
        die(f"{args.device} is not an external/removable disk I can see. "
            f"Available: {', '.join(d.ident for d in disks) or '(none)'}")
    if not disks:
        die("no external/removable disk found. Plug in the USB stick and retry.")
    if not sys.stdin.isatty():
        die("multiple/0 disks and no terminal; pass --device")
    print("\nExternal disks (the system disk is never listed):")
    for i, d in enumerate(disks, 1):
        print(f"  {i}) {d.human()}")
    sel = input("which disk to ERASE and make into a dongle? ").strip()
    if not (sel.isdigit() and 1 <= int(sel) <= len(disks)):
        die("cancelled")
    return disks[int(sel) - 1]


# --- format + install -------------------------------------------------------

def confirm_erase(disk):
    print(f"\n!! This ERASES ALL DATA on {disk.ident} ({disk.size/1e9:.1f} GB, {disk.model}).")
    typed = input(f"   Type '{disk.ident}' to confirm: ").strip()
    if typed != disk.ident:
        die("confirmation did not match; nothing was changed")


def format_and_mount(disk):
    """Erase to MBR + one FAT32 'MP_SD' partition; return the mount directory
    and a cleanup callback."""
    if IS_MAC:
        run(["diskutil", "eraseDisk", "FAT32", "MP_SD", "MBRFormat", disk.ident])

        def cleanup():
            subprocess.run(["sync"])
            if not run_ok(["diskutil", "eject", disk.ident], tries=4, delay=2.0):
                print(f"  note: could not eject {disk.ident} (macOS was still indexing it). "
                      f"The payload is written and synced. Eject it in Finder, or wait a "
                      f"few seconds and unplug it.")
        return "/Volumes/MP_SD", cleanup
    # Linux
    for part in sorted(glob.glob(disk.dev + "?*")):
        subprocess.run(["sudo", "umount", part], stderr=subprocess.DEVNULL)
    run(["sudo", "parted", "-s", disk.dev, "mklabel", "msdos",
         "mkpart", "primary", "fat32", "1MiB", "100%"])
    subprocess.run(["sudo", "partprobe", disk.dev], stderr=subprocess.DEVNULL)
    subprocess.run(["sudo", "udevadm", "settle"], stderr=subprocess.DEVNULL)
    part = disk.dev + ("p1" if disk.ident[-1].isdigit() else "1")
    for _ in range(20):   # the partition node can lag behind parted; wait for it
        if os.path.exists(part):
            break
        time.sleep(0.5)
    else:
        die(f"partition {part} did not appear after partitioning {disk.dev}")
    run(["sudo", "mkfs.vfat", "-F", "32", "-n", "MP_SD", part])
    mnt = tempfile.mkdtemp(prefix="mp_sd_")
    run(["sudo", "mount", "-o", f"uid={os.getuid()},gid={os.getgid()}", part, mnt])

    def cleanup():
        subprocess.run(["sync"])
        if not run_ok(["sudo", "umount", mnt], tries=4, delay=2.0):
            subprocess.run(["sudo", "umount", "-l", mnt])
            print(f"  note: lazy-unmounted {mnt}; safe to unplug once writes flush")
        try:
            os.rmdir(mnt)
        except OSError:
            pass
    return mnt, cleanup


def choose_autorun(args):
    """Pick which boot script to install (copied onto the stick as autorun.sh)."""
    if args.autodump:
        return AUTORUN_DUMP, "auto-dump"
    if not sys.stdin.isatty():
        return AUTORUN_PLAIN, "plain"
    ans = input("\nInstall the auto-dump autorun (captures the unit to the stick on "
                "first boot)? [y/N]: ").strip().lower()
    return (AUTORUN_DUMP, "auto-dump") if ans in ("y", "yes") else (AUTORUN_PLAIN, "plain")


def install_payload(mnt, keys_text, autorun_src):
    print(f"\ninstalling payload -> {mnt}")
    shutil.copy(autorun_src, os.path.join(mnt, "autorun.sh"))
    helper = os.path.join(USB_DIR, "cvendpull")
    if os.path.isfile(helper):
        shutil.copy2(helper, os.path.join(mnt, "cvendpull"))
        os.chmod(os.path.join(mnt, "cvendpull"), 0o755)
    else:
        print("  note: usb/cvendpull missing; autodump will skip the reader-live pull")
    with open(os.path.join(mnt, "authorized_keys"), "w") as f:
        f.write(keys_text)
    open(os.path.join(mnt, ".pm3-nodump"), "w").close()
    print(f"  autorun.sh ({os.path.basename(autorun_src)}), cvendpull, authorized_keys, .pm3-nodump written")
    if IS_MAC:
        # Keep the FAT stick clean: tell Spotlight not to index it (also avoids the
        # indexer blocking the eject) and drop the ._ AppleDouble sidecar files.
        open(os.path.join(mnt, ".metadata_never_index"), "w").close()
        subprocess.run(["dot_clean", mnt], stderr=subprocess.DEVNULL)
        for junk in (".Spotlight-V100", ".fseventsd", ".Trashes"):
            shutil.rmtree(os.path.join(mnt, junk), ignore_errors=True)


def main():
    global IS_MAC, IS_LINUX
    IS_MAC = platform.system() == "Darwin"
    IS_LINUX = platform.system() == "Linux"

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="disk to use (e.g. disk4 on macOS, sdb on Linux); "
                                      "omit to pick from a list")
    ap.add_argument("--key", action="append", metavar="PATH", help="a local .pub file (repeatable)")
    ap.add_argument("--key-url", action="append", metavar="URL", help="an https:// .pub URL (repeatable)")
    ap.add_argument("--github", action="append", metavar="USER",
                    help="a GitHub username; fetches github.com/USER.keys (repeatable)")
    ap.add_argument("--autodump", action="store_true",
                    help="install the auto-dump autorun (captures the unit to the stick on first boot)")
    ap.add_argument("--yes", action="store_true", help="skip the typed erase confirmation")
    ap.add_argument("--dry-run", action="store_true", help="show the plan; don't erase or write")
    args = ap.parse_args()

    keys = collect_keys(args)
    keys_text = "\n".join(keys) + "\n"
    print(f"\n{len(keys)} key(s) to install:")
    for k in keys:
        print(f"  - {key_label(k)}")

    autorun_src, variant = choose_autorun(args)
    if not os.path.isfile(autorun_src):
        die(f"missing {autorun_src} (run this from the toolkit checkout)")

    disk = choose_disk(args)

    if args.dry_run:
        print(f"\n[dry-run] would format {disk.ident} ({disk.size/1e9:.1f} GB) as "
              f"MBR/FAT32 'MP_SD' and write autorun.sh ({variant}) + cvendpull + "
              f"authorized_keys ({len(keys)} key(s)) + .pm3-nodump. No changes made.")
        return

    if not args.yes:
        confirm_erase(disk)

    cleanup = None
    try:
        with _ignore_sigint():
            mnt, cleanup = format_and_mount(disk)
        install_payload(mnt, keys_text, autorun_src)
    finally:
        if cleanup is not None:
            with _ignore_sigint():
                cleanup()

    print(f"\nDone. {disk.ident} is ready.")
    print("Plug it into the dongle's USB-A port, power-cycle the unit, wait ~30s,")
    print("then: ssh root@<unit-ip>   (a pm3-autorun.log appears on the stick).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
