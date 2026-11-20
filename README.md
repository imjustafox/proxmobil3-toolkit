# PROXmobil3 toolkit

Reverse-engineering notes and tools for the INIT **PROXmobil3** (PM3), a transit
validator built on a Freescale i.MX6 module (TQMa6S). These units were sold off at
transit-agency surplus auctions; this repo is for repurposing one to run your own
software — reading NFC cards and barcodes, driving the screen, buzzer, and sensors.

- **`INTERFACE.md`** — reference for every subsystem: boot, serial/IPP protocol,
  NFC reading, framebuffer, audio, sensors, networking.
- **`PROCESS.md`** — how it was reverse-engineered, and the lessons from the dead ends.
- **`docs/reversing-nx.md`** — the nx-specific RE techniques and the reader's
  streaming frame formats (`0xD1` card record, `0xBE` UID), kept so the steps don't
  have to be rediscovered.
- **`docs/wiki-cross-check.md`** — results of running the `wiki.pm3.dev` cVEND
  commands against our actual unit: confirmations, corrections, and runtime details.
- **`docs/feig-firmware.md`** — top-to-bottom static reverse-engineering of the
  reader's own `feig` application (the IPP dispatch, card schemes, SAM, HSM, ITSO,
  EMV, girogo, crypto), from the unstripped binary's symbols and disassembly.
- **`docs/system-findings.md`** — provenance (the INIT-004 BSP, toolchain,
  versions), latent onboard WiFi/BT (TI WL1837, not fitted here), kernel/platform
  capabilities, and the boot/access security posture.
- **`docs/host-system.md`** — the i.MX6 host system: boot/storage, and the
  account-based-ticketing backend (`proxy_server`/abtproxy — local HTTP API, the
  Bytemark "UVAPI" cloud flow, online/offline validation, passback, the SQLite
  queue). Secrets redacted.
- **`docs/capturing-a-unit.md`** — the full capture workflow: configuring the access
  USB, finding a unit on the network, running `dump_unit.py`, and restoring a borrowed
  unit to stock.
- **`pm3.py`** — the toolkit: IPP protocol, card reading, buzzer, PIC32 sensors,
  EEPROM access. Runs on your computer, bridges the device's serial ports over SSH.
- **`tap_demo.py`** — a working app: tap a card, its UID shows on the device screen
  with a buzzer chirp. The template for card-driven apps.
- **`sniffer/`** — an `LD_PRELOAD` shim that logs the stock app's serial traffic;
  this is what cracked the reader protocol.
- **`keyserver/`** — a small HTTP server that replaces the device's cloud backend
  locally, to drive the stock app fully offline.
- **`usb/`** — the boot script that installs SSH access via the dongle EEPROM.
- **`dump_unit.py`** — one command: a full, checksummed capture of a unit (storage +
  hardware scan + provisioning archives + cVEND reader firmware + live reader config)
  to `dumps/unit<SERIAL>/`, then restores the unit to stock. See
  **`docs/capturing-a-unit.md`**.
- **`os-build/`** — the device's kernel config, for building a custom OS image.

The storage dumps (device images, which contain the agency's production secrets)
are deliberately **not** in this repo; see the note at the bottom.

## Quick start

### 1. Get a root shell

SSH is open but root login is closed and there's no published default password.
With a PROXdongl3 that has the EEPROM payload (dated 2025-12-30 or later):

1. Format a USB stick as **MBR, one FAT32 partition, label `MP_SD`** —
   `diskutil eraseDisk FAT32 MP_SD MBRFormat /dev/diskN` on macOS. One MBR partition
   matters: the device mounts partition 1, and a default GPT layout makes that an
   empty EFI partition where the payload finds no script.
2. Copy `usb/autorun.sh` and your SSH public key as `usb/authorized_keys` onto it
   (see `usb/authorized_keys.example`).
3. Plug it into the dongle's USB-A port and power-cycle the unit.
4. Wait ~30 s, then `ssh root@<unit-ip>`. A `pm3-autorun.log` appears on the stick.

The script runs instead of nx, installs your key, and disables the watchdog. The SSH
access persists across reboots. Without the EEPROM dongle, the same script can go on
the internal SD card as `autorun/95-enable-ssh.sh`, or use the serial console on the
"ARMcons" header (115200 8N1, interrupt U-Boot). Copy files with `scp -O`.

### 2. Read NFC cards

```sh
PM3_HOST=<unit-ip> python3 tap_demo.py      # tap a card → UID on screen + chirp
```

The reader scans continuously on its own after boot. Start the app near boot and
leave it running; see the NFC section of `INTERFACE.md` for why, and for the
protocol details.

### 3. Poke the hardware

```sh
PM3_HOST=<unit-ip> ./pm3.py info            # kernel, services, ttys
./pm3.py pic-read                            # PIC32 sensors: rails, temp, counters, fw
./pm3.py pic-read 5040                        # input voltage (mV)
./pm3.py watchdog 0                           # disable the PIC32 watchdog
./pm3.py cvend-watch                          # raw card events
./pm3.py cvend-restart                         # software-restart the reader (wakes a slept one, ~6s)
./pm3.py cvend-ls /home/app0                   # list the reader's own filesystem
./pm3.py cvend-cat /etc/os-release             # read a file off the reader
./pm3.py cvend-finfo /home/app0/version        # file size + CRC32 (0x9C)
./pm3.py beep --freq 2700 --ms 120            # piezo buzzer
./pm3.py nx-stop / nx-start                   # stop/start the stock UI
```

`PM3_HOST` or `--host` picks the unit; it defaults to the example address in the code.

## Hardware at a glance

| | |
|---|---|
| Module / SoC | TQMa6S, i.MX6 Solo Cortex-A9 792 MHz, 512 MB DDR3L |
| OS / kernel | PTXdist 2019.03, Linux 4.9.166-fsl-imx (old glibc — build static) |
| Display | 5", 800×480, `/dev/fb0`, BGRX, no touchscreen |
| PIC32 power/watchdog | `/dev/ttymxc2`, 115200 8N1, IPP |
| cVEND NFC reader (FEIG) | `/dev/ttymxc3`, 115200 8N1, IPP |
| Barcode (Honeywell/Code) | `/dev/ttyUSB0`, 115200, raw text, no terminator |
| Buzzer / speaker | cVEND piezo (IPP 0x22) / TLV320 codec (ALSA card 0) |
| Stock app | `nx` at `/init/efad/pgm/`; `systemctl stop nx` |

Rear DB15: 1/2 Eth Tx±, 3/4 Eth Rx±, 5 CL15 ignition, 6/7 USB D±, 8-10 GND,
11/12 CL30 main power, 13/14 I²C, 15 3V3 out.

The PIC32 watchdog powers the unit off ~60 s after boot unless fed. nx feeds it;
if you stop nx, disable it with `./pm3.py watchdog 0`.

## References

- `wiki.pm3.dev` and `kevin.wallace.seattle.wa.us/pm3` — the public PM3 pages.
- Community projects: proxdongl3 (git.doof.net), rust-feig-app, PROXMobil3-HOP,
  haylinmoore/board (OneBusAway arrival board), proxbeacon.
- `reports/` and `research_notes/` — the FEIG/cVEND protocol research.

## A note on secrets

The device's backend config (`config.json`, `keys.json`) holds the transit agency's
OAuth credentials and card-reading keys. Those live only in the storage dumps, which
are git-ignored and not published. Using them against the agency's systems, or
against cards that aren't yours, would be unauthorized regardless of who owns the
hardware. For your own projects, replace the backend (see `keyserver/`).
