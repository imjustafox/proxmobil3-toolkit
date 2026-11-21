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
- `docs/unit-comparison.md`: differences between the three captured units.
  The images themselves are kept offline.
- `pm3.py`: toolkit for IPP, card reading, buzzer, PIC32 sensors, and EEPROM
  access. Runs on your computer and bridges the device's serial ports over SSH.
- `tap_demo.py`: working app: tap a card, its UID appears on the device screen
  with a buzzer chirp. Template for card-driven apps.
- `sniffer/`: an `LD_PRELOAD` shim that logs the stock app's serial traffic.
  This is how the reader protocol was captured.
- `keyserver/`: a small HTTP server that replaces the device's cloud backend
  locally, so the stock app can run offline.
- `usb/`: boot script that installs SSH access through the dongle EEPROM. The
  auto-dump variant also captures a hardware scan and the live reader config.
- `make_dongle.py`: prepares the access USB on macOS or Linux. Formats the stick
  (MBR/FAT32/`MP_SD`) and copies `autorun.sh`, your SSH key(s), the
  `.pm3-nodump` marker, and the reader-pull helper used by the auto-dump variant.
  Keys can come from a local `.pub`, an https URL, a GitHub username, or `~/.ssh`.
- `dump_unit.py`: one command for a full, checksummed capture of a unit (storage,
  hardware scan, provisioning archives, cVEND reader firmware, live reader config)
  to `~/Documents/pm3-dumps/unit<SERIAL>/`, then restores the unit to stock. See
  `docs/capturing-a-unit.md`.
- `os-build/`: the device's kernel config, for building a custom OS image.

Storage dumps (device images) land outside this repo by default, in
`~/Documents/pm3-dumps`.

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
| Module / SoC | TQMa6S, i.MX6DL (DualLite) Cortex-A9 792 MHz, 512 MB DDR3L; UP kernel |
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

## pm3.py command reference

The general form is:

```sh
./pm3.py --host <unit-ip> <command> [args]
```

`--host` must come before the command. If omitted, `PM3_HOST` is used, then the
default address in the script.

### System

- `info` prints the kernel, uptime, memory, filesystems, active services, and the
  serial and framebuffer devices.
- `blank-screen` stops the fbcon cursor from blinking and writes zeros to
  `/dev/fb0`. The screen stays black until something redraws it. `nx-start`
  redraws the stock UI.
- `nx-stop` asks nx to disable the PIC32 watchdog, then stops nx and abtproxy. It
  writes the watchdog value over IPP afterward as a fallback.
- `nx-start` starts abtproxy and then the stock nx UI. Expect the validator screen
  and possibly a startup beep.

### PIC32

- `pic-read [key ...]` reads PIC32 values. With no keys it prints every known key.
  Keys are hex, for example `5040` for input voltage in mV, `504f` for the 3V3
  rail, `c000` for the PIC32 firmware string, and `07e0` for the audio amp state.
- `watchdog <seconds>` sets the PIC32 watchdog timeout. `0` disables it. When the
  timeout expires the unit reboots; it does not stay off.
- `pic-raw <type> [hex-data]` sends a raw IPP frame to the PIC32. Read the
  external EEPROM with `pic-raw 0a 10000000000080`, or the internal EEPROM with
  `pic-raw 0a 18000000000080`.
- `amp on|off|status` switches the external audio power amp through PIC32 key
  `0x07E0`, or reads its current state. The amp is latched until the next
  power-off.

### cVEND reader

- `cvend-version` prints the reader's version frame and decoded identity string.
- `cvend-watch` runs nx's enable handshake and prints reader events. By default it
  enables every card type, which stops the autonomous base scan. Options:
  `--enable <type ...>` limits the card types (`vdvka`, `mifare`, `iso`,
  `desfire`, `girogo`, `itso`, `ultralightc`), `--wait-startup` waits for the
  reader's `0x0F` boot frame first, `--reset` sends `0x10 02` and waits for a
  fresh startup, and `-v` shows status and heartbeat frames. Ctrl-C exits
  cleanly.
- `cvend-restart` sends `0x10 02` (restart application) and waits up to 20 seconds
  for the `0x0F` startup frame. If no startup arrives, the reader may need a
  power cycle.
- `cvend-ls <path>` lists a directory on the reader's own filesystem with the
  `0xA4` FileList command.
- `cvend-cat <path>` reads a file from the reader's filesystem with `0x98`
  GetFile. Use `--offset` to start partway in, `--count` for bytes per frame
  (default `0xF000`), and `--hex` to print hex instead of raw bytes.
- `cvend-finfo <path>` requests file status, size, and CRC32 with `0x9C`
  FileInfo. Some paths return no reply.
- `beep --freq <Hz> --ms <ms>` sounds the cVEND piezo buzzer. About 2700 Hz is
  loudest. Volume is not adjustable.

### Audio

- `play <file.wav>` copies a WAV to the unit, enables the PIC32 audio amp, restores
  the stock ALSA routing, and plays the file with `aplay`. It works without nx.
  Options: `--no-amp` leaves `0x07E0` alone, `--no-restore` skips `alsactl
  restore`, `--pcm <percent>` sets playback volume (default 65), `--lo-gain
  <0-35>` sets the Line-Out baseline (default 6, which is 0 dB), `--mixer
  NAME=VAL` adds an `amixer` control, and `--keep` leaves the uploaded file on the
  unit.

## References

- `wiki.pm3.dev` and `kevin.wallace.seattle.wa.us/pm3`: the public PM3 pages.
- Community projects: proxdongl3 (git.doof.net), rust-feig-app, PROXMobil3-HOP,
  haylinmoore/board (OneBusAway arrival board), proxbeacon.
- `reports/` and `research_notes/`: FEIG/cVEND protocol research.
