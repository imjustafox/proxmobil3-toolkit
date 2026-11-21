# PROXmobil3 toolkit

Notes and tools for the INIT PROXmobil3 (PM3), a transit validator built on a
Freescale i.MX6 module (TQMa6S). These units were sold at transit-agency surplus
auctions. This repo is about repurposing one to run your own software: reading NFC
cards and barcodes, driving the screen, buzzer, and sensors.

- `INTERFACE.md`: reference for every subsystem: boot, serial/IPP protocol, NFC
  reading, framebuffer, audio, sensors, networking.
- `PROCESS.md`: how the device was reverse-engineered, including the dead ends.
- `docs/reversing-nx.md`: nx-specific RE techniques and the reader's streaming
  frame formats (`0xD1` card record, `0xBE` UID).
- `docs/wiki-cross-check.md`: results from running the `wiki.pm3.dev` cVEND
  commands against this unit.
- `docs/feig-firmware.md`: static reverse-engineering of the reader's `feig`
  application, covering IPP dispatch, card schemes, SAM, HSM, ITSO, EMV, girogo,
  and crypto.
- `docs/system-findings.md`: build provenance (INIT-004 BSP, toolchain, versions),
  latent onboard WiFi/BT (TI WL1837, not fitted), kernel/platform capabilities,
  and boot/access security.
- `docs/host-system.md`: the i.MX6 host, including the account-based-ticketing
  backend (`proxy_server`/abtproxy, local HTTP API, Bytemark "UVAPI" cloud flow,
  online/offline validation, passback, SQLite queue). Secrets redacted.
- `docs/capturing-a-unit.md`: capture workflow: prepare the access USB, find a
  unit on the network, run `dump_unit.py`, restore a borrowed unit to stock.
- `pm3.py`: toolkit for IPP, card reading, buzzer, PIC32 sensors, and EEPROM
  access. Runs on your computer and bridges the device's serial ports over SSH.
- `tap_demo.py`: working app: tap a card, its UID appears on the device screen
  with a buzzer chirp. Template for card-driven apps.
- `sniffer/`: an `LD_PRELOAD` shim that logs the stock app's serial traffic.
  This is how the reader protocol was captured.
- `keyserver/`: a small HTTP server that replaces the device's cloud backend
  locally, so the stock app can run offline.
- `usb/`: boot script that installs SSH access through the dongle EEPROM.
- `make_dongle.py`: prepares the access USB on macOS or Linux. Formats the stick
  (MBR/FAT32/`MP_SD`) and copies `autorun.sh`, your SSH key(s), and the
  `.pm3-nodump` marker. Keys can come from a local `.pub`, an https URL, a GitHub
  username, or `~/.ssh`.
- `dump_unit.py`: one command for a full, checksummed capture of a unit (storage,
  hardware scan, provisioning archives, cVEND reader firmware, live reader config)
  to `~/Documents/pm3-dumps/unit<SERIAL>/`, then restores the unit to stock. See
  `docs/capturing-a-unit.md`.
- `os-build/`: the device's kernel config, for building a custom OS image.

Storage dumps (device images containing the agency's production secrets) land
outside this repo by default, in `~/Documents/pm3-dumps`. See the note at the
bottom.

## Quick start

### 1. Get a root shell

SSH is open, but root login is closed and there is no published default password.
With a PROXdongl3 that has the EEPROM payload (dated 2025-12-30 or later):

1. Prepare an access USB. On macOS or Linux:
   ```sh
   ./make_dongle.py      # pick the USB and your SSH key(s); it formats and copies everything
   ```
   It formats the stick as MBR with one FAT32 partition labeled `MP_SD`, then
   copies `autorun.sh`, your key(s) as `authorized_keys`, and the `.pm3-nodump`
   marker. macOS needs only the built-in `diskutil`. Linux needs `parted`,
   `mkfs.vfat` from `dosfstools`, `lsblk`/`partprobe`/`udevadm` from util-linux,
   and `sudo`.

   To do it by hand: format the stick the same way (`diskutil eraseDisk FAT32
   MP_SD MBRFormat /dev/diskN` on macOS). The one MBR partition matters because
   the device mounts partition 1. A default GPT layout makes that an empty EFI
   partition, where the payload finds no script. Then copy `usb/autorun.sh` and
   your public key as `usb/authorized_keys` (see `usb/authorized_keys.example`).
2. Plug it into the dongle's USB-A port and power-cycle the unit.
3. Wait about 30 seconds, then `ssh root@<unit-ip>`. A `pm3-autorun.log` appears
   on the stick.

The script runs instead of nx, installs your key, and disables the watchdog. SSH
access persists across reboots. Without the EEPROM dongle, the same script can go
on the internal SD card as `autorun/95-enable-ssh.sh`, or you can use the serial
console on the "ARMcons" header (115200 8N1, interrupt U-Boot). Copy files with
`scp -O`.

### 2. Read NFC cards

```sh
PM3_HOST=<unit-ip> python3 tap_demo.py      # tap a card: UID on screen + chirp
```

The reader scans continuously on its own after boot. Start the app near boot and
leave it running. See the NFC section of `INTERFACE.md` for why and for the
protocol details.

### 3. Poke the hardware

```sh
PM3_HOST=<unit-ip> ./pm3.py info            # kernel, services, ttys
./pm3.py blank-screen                        # clear the framebuffer to black
./pm3.py pic-read                            # PIC32 sensors: rails, temp, counters, fw
./pm3.py pic-read 5040                        # input voltage (mV)
./pm3.py watchdog 0                           # disable the PIC32 watchdog
./pm3.py cvend-watch                          # enable card handlers, dump reader events
./pm3.py cvend-restart                        # software-restart the reader (wakes a slept one, ~6s)
./pm3.py cvend-ls /home/app0                  # list the reader's own filesystem
./pm3.py cvend-cat /etc/os-release            # read a file off the reader
./pm3.py cvend-finfo /home/app0/version       # file size + CRC32 (0x9C)
./pm3.py beep --freq 2700 --ms 120            # piezo buzzer
./pm3.py amp on                               # enable the external audio power amp (PIC32 0x07E0)
./pm3.py play tone.wav                        # play a WAV out the speaker (enables the amp first; no nx)
./pm3.py nx-stop / nx-start                   # stop/start the stock UI
```

`PM3_HOST` or `--host` picks the unit. It defaults to the example address in the
code.

## Hardware at a glance

| | |
|---|---|
| Module / SoC | TQMa6S, i.MX6 Solo Cortex-A9 792 MHz, 512 MB DDR3L |
| OS / kernel | PTXdist 2019.03, Linux 4.9.166-fsl-imx (old glibc, build static) |
| Display | 5", 800x480, `/dev/fb0`, BGRX, no touchscreen |
| PIC32 power/watchdog | `/dev/ttymxc2`, 115200 8N1, IPP |
| cVEND NFC reader (FEIG) | `/dev/ttymxc3`, 115200 8N1, IPP |
| Barcode (Honeywell/Code) | `/dev/ttyUSB0`, 115200, raw text, no terminator |
| Buzzer / speaker | cVEND piezo (IPP 0x22) / TLV320 codec (ALSA card 0) |
| Stock app | `nx` at `/init/efad/pgm/`; `systemctl stop nx` |

Rear DB15: 1/2 Eth Tx+/-, 3/4 Eth Rx+/-, 5 CL15 ignition, 6/7 USB D+, 8-10 GND,
11/12 CL30 main power, 13/14 I2C, 15 3V3 out.

The PIC32 watchdog reboots the unit about 60 seconds after boot unless it is fed.
It power-cycles and comes back; it does not stay off. nx feeds it. If you stop nx,
disable it with `./pm3.py watchdog 0`. See `INTERFACE.md` section PIC32 for the
reboot-versus-power-off detail.

## References

- `wiki.pm3.dev` and `kevin.wallace.seattle.wa.us/pm3`: the public PM3 pages.
- Community projects: proxdongl3 (git.doof.net), rust-feig-app, PROXMobil3-HOP,
  haylinmoore/board (OneBusAway arrival board), proxbeacon.
- `reports/` and `research_notes/`: FEIG/cVEND protocol research.

## A note on secrets

The device's backend config (`config.json`, `keys.json`) holds the transit
agency's OAuth credentials and card-reading keys. Those live only in the storage
dumps, which default to `~/Documents/pm3-dumps` outside this repo and are not
published. `dumps/` is also git-ignored, so capturing in-tree with `--out ./dumps`
is safe too. Using the credentials against the agency's systems, or the keys
against cards that are not yours, would be unauthorized regardless of who owns the
hardware. For your own projects, replace the backend (see `keyserver/`).
