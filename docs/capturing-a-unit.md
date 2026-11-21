# Capturing a unit

End-to-end guide for pulling a complete image of a PROXmobil3: storage, hardware
inventory, provisioning dataset, and the cVEND reader firmware. For a borrowed
unit, it also puts the unit back to stock. The whole run is one command,
`dump_unit.py`.

Output goes to `~/Documents/pm3-dumps/unit<SERIAL>/` by default, outside this repo,
because it contains the operator's production data. Override with `--out` or
`$PM3_DUMPS`. See the secrets note in the README.

---

## 1. Prerequisites: the access USB

Root SSH is not open by default. Access comes from the device's own maintenance
path (`90-testmode.sh`, see `host-system.md` section 4). At boot it reads a
`[TestMode]` payload from a PROXdongl3 EEPROM, stops nx, disables the watchdog, and
runs that payload. The payload mounts a USB/SD stick labeled `MP_SD` and executes
`autorun.sh` from it. Two things must be in place.

### a) A PROXdongl3 with the `[TestMode]` EEPROM payload

The payload, read from the dongle's EEPROM, just mounts the `MP_SD` stick and runs
its `autorun.sh`:

```sh
[TestMode]
dev=/dev/disk/by-label/MP_SD ; mp=/init/efad/mp_sd
mount -o noatime $dev $mp
[ -e $mp/autorun.sh ] && { systemctl stop init-abtproxy; sh $mp/autorun.sh; } \
                      || systemctl --no-block start nx
```

Without the EEPROM dongle the payload never runs. The same `autorun.sh` can go on
the internal SD as `/init/autorun/95-enable-ssh.sh`, or you can use the U-Boot
serial console (ARMcons header, 115200 8N1).

### b) A USB stick or SD card with the bootstrap

On macOS or Linux:

```sh
./make_dongle.py            # pick the USB and your key(s) from a menu
```

`make_dongle.py` formats the stick (MBR, one FAT32 partition labeled `MP_SD`) and
copies `autorun.sh`, your chosen SSH key(s) as `authorized_keys`, and the
`.pm3-nodump` marker. It only offers external/removable disks and asks you to
confirm before erasing. Keys can be a local `.pub`, an `https://` URL, a GitHub
username, or one picked from your `~/.ssh`.

By hand:

```sh
# macOS: one MBR FAT32 partition labeled MP_SD. A default GPT layout puts an
# empty EFI partition where the payload looks for the script, so MBR matters.
diskutil eraseDisk FAT32 MP_SD MBRFormat /dev/diskN

cp usb/autorun.sh            /Volumes/MP_SD/autorun.sh
cp ~/.ssh/id_ed25519.pub     /Volumes/MP_SD/authorized_keys   # your public key
```

`usb/autorun.sh` does three things on the unit, all reversible, and logs to
`pm3-autorun.log` on the stick:

1. Disables the PIC32 watchdog, so the unit stays up with no nx feeding it.
2. Enables root SSH persistently. It remounts `/` read-write, backs up the stock
   `/etc/ssh/sshd_config` to `sshd_config.stock`, writes a minimal config, installs
   your key to `/root/.ssh/authorized_keys`, enables `sshd.socket`, and remounts
   `/` read-only.
3. Does not start nx, leaving the reader's fresh-boot auto-scan free for the tools.

It also drops a `.pm3-nodump` marker so `dump_unit.py` never captures the dongle.

There is a second variant, `usb/autorun-autodump.sh`, that does all of the above
and captures the unit's internal disks to `pm3-dump/` on the stick on first boot
(`dd | gzip` per disk, with sha256sums in `pm3-dump/device.sha256`; later boots
skip it). Install it with `make_dongle.py --autodump`, or copy it to the stick as
`autorun.sh`. It is a hands-off fallback capture. `dump_unit.py` is still the
fuller, checksummed pull, including reader firmware, live config, and cleanup.

Bring the unit up: insert the dongle and the `MP_SD` stick, power on, and wait 30
to 60 seconds. The unit gets a DHCP lease. Find it in the next section, then
`ssh root@<ip>` should work.

---

## 2. Find the unit on the network

The TQMa6S module's MAC OUI is `00:d0:93` (TQ-Systems). On the unit's subnet:

```sh
for i in $(seq 1 254); do ping -c1 -t1 192.168.1.$i >/dev/null 2>&1 & done; wait
arp -an | grep -i '0:d0:93'          # the PM3(s); note the IP
```

---

## 3. Capture and restore: `dump_unit.py`

One command does the full capture and then restores the unit to stock:

```sh
python3 dump_unit.py --host 192.168.1.98
```

The steps run in order, writing to `~/Documents/pm3-dumps/unit<SERIAL>/`:

| # | Step | Output |
|---|------|--------|
| 1 | Identify (module EEPROM serial at i2c `2-0050`) | folder name |
| 2 | Hardware scan | `hwscan.txt` (uname, DT model, cpuinfo, i2c devices and bus scan, EEPROM, USB, GPIO, services, U-Boot env), `dmesg.txt` |
| 3 | Storage dump: every whole disk, smallest first (streamed `dd \| gzip`, sha256 each), skipping the boot dongle and any disk too big for free space | `<disk>.img.gz`, for example `mtdblock0.img.gz` (SPI/U-Boot), `sda.img.gz` (rootfs), `sdb.img.gz` (`/init`) |
| 4 | Provisioning archives | `host-archive/` (`.t71/.z71/.Z72/.P72/.p72/.g72/.C72`) |
| 5 | cVEND reader firmware (unpacked from `V0200.C72`) | `reader-firmware/` (kernel.gz, rootfs.gz, U-Boot env, app; `app0-extracted/feig` is the unstripped 1.6 MB binary) |
| 6 | Live reader config (through `pm3.py` over serial) | `reader-live/` (config, version, EMV `transact-counter.dat`, Girogo persdata and listings) |
| 7 | Manifest | `SUMMARY.md` (serial, hardware, every disk seen with per-disk status and sha256) |
| 8 | Cleanup: restore stock config, remove traces | prints a verify line |

The boot dongle is skipped automatically. `autorun.sh` leaves a `.pm3-nodump`
marker on the stick, and the capture skips any disk whose mounted filesystem
carries it.

Flags:

- `--no-cleanup`: leave SSH access in place for a unit you keep or keep working on.
- `--no-reader`: skip the live reader serial pull (step 6).
- `--no-dump`: scans and archives only, no big block images (step 3).
- `--out <dir>`: output root. Defaults to `$PM3_DUMPS` or `~/Documents/pm3-dumps`.

If you press Ctrl-C during a capture, `dump_unit.py` restores the unit to stock
before exiting, the same cleanup as step 8, unless `--no-cleanup` is set. Partial
`.img.gz` files and a newly created `host-archive/` are removed. The cleanup step
ignores further Ctrl-C presses so it can finish. With `--no-cleanup`, an interrupt
leaves SSH access in place and says so.

The reader file ops reuse `pm3.py` from the same directory. The ssh calls skip
host-key checks, so a unit that changed IP needs no `known_hosts` cleanup.

### The on-stick auto-dump

If you built the dongle with the auto-dump autorun (`make_dongle.py --autodump`,
or `usb/autorun-autodump.sh` copied on by hand), its first boot captures the
unit's internal disks and metadata to `pm3-dump/` on the stick, with sha256sums in
`pm3-dump/device.sha256`. It also writes `hwscan.txt`, `dmesg.txt`, and a
`reader-live/` pull of the cVEND reader (version, directory listings, config,
EMV counter, and Girogo persdata). Later boots skip it. That is a hands-off
fallback and a record of every unit the dongle has booted. `dump_unit.py` is still
the fuller capture: it also pulls the reader firmware archive, writes a manifest,
and cleans up. The plain `autorun.sh` does not dump anything.

---

## 4. Returning a borrowed unit

If the unit has to go back, step 8's cleanup is what leaves it stock. It restores
`/etc/ssh/sshd_config` from the autorun's own `.stock` backup, removes
`/root/.ssh/authorized_keys`, disables `sshd.socket`, and remounts `/` read-only.
After that you are locked out, which is the confirmation it worked. Everything else
we touch is runtime-only and reverts on the next boot. The watchdog re-arms, the
reader `0x10 02` restart is gone, and nx was never started.

Then physically pull the `MP_SD` stick and the dongle. They hold your key and the
auto-dumps, and the dongle is what triggers `[TestMode]`. With both removed, the
next boot is a normal stock nx boot, and nothing of yours remains on the unit's
storage.

To verify a run manually:

```sh
ssh root@<ip> true    # after cleanup this should fail: Permission denied
```

---

## 5. Secrets

The dumps contain the operator's production data: backend credentials, card keys,
and provisioning. They default to `~/Documents/pm3-dumps`, outside this repo, and
must stay local. Do not commit or publish image dumps or extracted secrets.
`dumps/` is also git-ignored, so an in-tree `--out ./dumps` is still safe. See the
README's secrets note.
