# Capturing a unit

End-to-end guide for pulling a complete image of a PROXmobil3 — storage, hardware
inventory, provisioning dataset, and the cVEND reader firmware — and (for a borrowed
unit) restoring it to stock afterward. The whole run is one command: `dump_unit.py`.

The output goes to `~/Documents/pm3-dumps/unit<SERIAL>/` by default — outside this
repo, since it contains the operator's production data (override with `--out` or
`$PM3_DUMPS`; see the secrets note in the README).

---

## 1. Prerequisites: the access USB

Root SSH isn't open by default. Access comes from the device's own maintenance path
(`90-testmode.sh`, see `host-system.md` §4): at boot it reads a `[TestMode]` payload
from a **PROXdongl3 EEPROM**, stops nx, disables the watchdog, and runs that payload
— which mounts a USB/SD stick labeled **`MP_SD`** and executes `autorun.sh` from it.
So two things must be in place:

**a) A PROXdongl3 with the `[TestMode]` EEPROM payload.** The payload, read from the
dongle's EEPROM, just mounts the `MP_SD` stick and runs its `autorun.sh`:

```sh
[TestMode]
dev=/dev/disk/by-label/MP_SD ; mp=/init/efad/mp_sd
mount -o noatime $dev $mp
[ -e $mp/autorun.sh ] && { systemctl stop init-abtproxy; sh $mp/autorun.sh; } \
                      || systemctl --no-block start nx
```

Without the EEPROM dongle the payload never runs; the same `autorun.sh` can instead
be dropped on the internal SD as `/init/autorun/95-enable-ssh.sh`, or you can use the
U-Boot serial console (ARMcons header, 115200 8N1).

**b) A USB stick / SD card holding our bootstrap.** The easy way (macOS or Linux):

```sh
./make_dongle.py            # pick the USB and your key(s) from a menu
```

`make_dongle.py` formats the stick correctly (MBR, one FAT32 partition labeled
`MP_SD`) and copies `autorun.sh`, your chosen SSH key(s) as `authorized_keys`, and the
`.pm3-nodump` marker. It only ever offers external/removable disks and asks you to
confirm before erasing. Keys can be a local `.pub`, an `https://` URL, a GitHub
username, or one picked from your `~/.ssh`.

By hand instead:

```sh
# macOS — one MBR FAT32 partition labeled MP_SD (a default GPT layout puts an
# empty EFI partition where the payload looks for the script, so MBR matters):
diskutil eraseDisk FAT32 MP_SD MBRFormat /dev/diskN

cp usb/autorun.sh            /Volumes/MP_SD/autorun.sh
cp ~/.ssh/id_ed25519.pub     /Volumes/MP_SD/authorized_keys   # your public key
```

`usb/autorun.sh` (in this repo) does three things on the unit, all reversible, and
logs to `pm3-autorun.log` on the stick:
1. disables the PIC32 watchdog (so the unit stays up with no nx feeding it),
2. **enables root SSH persistently** — remounts `/` rw, backs up the stock
   `/etc/ssh/sshd_config` to `sshd_config.stock`, writes a minimal config, installs
   your key to `/root/.ssh/authorized_keys`, `systemctl enable sshd.socket`, remounts
   `/` ro,
3. does **not** start nx (leaves the reader's fresh-boot auto-scan free for our tools).

It also drops a `.pm3-nodump` marker so `dump_unit.py` never captures the dongle.

There is a second variant, `usb/autorun-autodump.sh`, that does all of the above **and**
captures the unit's internal disks to `pm3-dump/` on the stick on the first boot
(`dd | gzip` per disk, with sha256sums in `pm3-dump/device.sha256`; later boots skip
it). Install it with `make_dongle.py --autodump`, or copy it to the stick as
`autorun.sh` by hand. It's a hands-off fallback capture — `dump_unit.py` is still the
fuller, checksummed pull (reader firmware + live config + cleanup).

**Bring the unit up:** insert the dongle + the `MP_SD` stick, power on, wait ~30–60 s.
The unit gets a DHCP lease; find it (next section) and `ssh root@<ip>` should work.

---

## 2. Find the unit on the network

The TQMa6S module's MAC OUI is `00:d0:93` (TQ-Systems). On the unit's subnet:

```sh
for i in $(seq 1 254); do ping -c1 -t1 192.168.1.$i >/dev/null 2>&1 & done; wait
arp -an | grep -i '0:d0:93'          # the PM3(s); note the IP
```

---

## 3. Capture + restore: `dump_unit.py`

One command does the full capture and then restores the unit to stock:

```sh
python3 dump_unit.py --host 192.168.1.98
```

Steps, in order, writing to `~/Documents/pm3-dumps/unit<SERIAL>/`:

| # | Step | Output |
|---|------|--------|
| 1 | Identify (module EEPROM serial at i2c `2-0050`) | folder name |
| 2 | Hardware scan | `hwscan.txt` (uname, DT model, cpuinfo, i2c devices + bus scan, EEPROM, USB, GPIO, services, U-Boot env), `dmesg.txt` |
| 3 | Storage dump — every whole disk, smallest-first (streamed `dd \| gzip`, sha256 each), skipping the boot dongle and any disk too big for free space | `<disk>.img.gz`, e.g. `mtdblock0.img.gz` (SPI/U-Boot), `sda.img.gz` (rootfs), `sdb.img.gz` (`/init`) |
| 4 | Provisioning archives | `host-archive/` (`.t71/.z71/.Z72/.P72/.p72/.g72/.C72`) |
| 5 | cVEND reader firmware (unpacked from `V0200.C72`) | `reader-firmware/` (kernel.gz, rootfs.gz, u-boot env, app; `app0-extracted/feig` — the unstripped 1.6 MB binary) |
| 6 | Live reader config (via `pm3.py` over the serial) | `reader-live/` (config, version, EMV `transact-counter.dat`, Girogo persdata + listings) |
| 7 | Manifest | `SUMMARY.md` (serial, hardware, every disk seen with per-disk status + sha256) |
| 8 | **Cleanup** — restore stock config, remove our traces | (prints a verify line) |

The boot dongle is skipped automatically: `autorun.sh` leaves a `.pm3-nodump` marker
on the stick, and the capture skips any disk whose mounted filesystem carries it.

Flags:

- `--no-cleanup` — leave our SSH access in place (for a unit you keep / keep working on).
- `--no-reader` — skip the live reader serial pull (step 6).
- `--no-dump` — scans + archives only, skip the big block images (step 3).
- `--out <dir>` — output root (default `$PM3_DUMPS` or `~/Documents/pm3-dumps`).

The reader file-ops reuse `pm3.py` (same directory); the ssh calls skip host-key
checks, so a unit that changed IP doesn't need any `known_hosts` cleanup.

### The on-stick auto-dump

If you built the dongle with the auto-dump autorun (`make_dongle.py --autodump`, or
`usb/autorun-autodump.sh` copied on by hand), its first boot captures the unit's
internal disks + metadata to `pm3-dump/` on the stick, with sha256sums in
`pm3-dump/device.sha256`; later boots skip it. That's a hands-off fallback and a
record of every unit the dongle has booted. `dump_unit.py` is still the fuller,
checksummed capture — it also pulls the reader firmware and live config, and cleans
up. The plain `autorun.sh` does **not** dump anything.

---

## 4. Returning a borrowed unit

If the unit has to go back, step 8's cleanup is what leaves it stock. It restores
`/etc/ssh/sshd_config` from the autorun's own `.stock` backup, removes
`/root/.ssh/authorized_keys`, `systemctl disable sshd.socket`, and remounts `/` ro —
after which **you are locked out**, which is the confirmation it worked. Everything
else we touch is runtime-only and reverts on the next boot (the watchdog re-arms, the
reader `0x10 02` restart is gone, nx was never started).

Then **physically pull the `MP_SD` stick and the dongle** — they hold your key and the
auto-dumps, and the dongle is what triggers `[TestMode]`. With both removed, the next
boot is a normal, stock nx boot and nothing of yours remains on the unit's storage.

To verify a run manually:

```sh
ssh root@<ip> true    # after cleanup this should fail: Permission denied
```

---

## 5. Secrets

The dumps contain the operator's production data (backend credentials, card keys,
provisioning). They default to `~/Documents/pm3-dumps` — outside this repo — and must
stay local: do not commit or publish image dumps or extracted secrets. (`dumps/` is
also git-ignored, so an in-tree `--out ./dumps` is still safe.) See the README's
secrets note.
