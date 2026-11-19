# PROXmobil3 interface reference

How to drive every subsystem of the PROXmobil3 (PM3), an INIT transit validator
built on a Freescale i.MX6 module. Written from the device's own storage images,
its decompiled device tree, and testing against a live unit.

See `README.md` for access and the `pm3.py` tool, and `PROCESS.md` for how this
was reverse-engineered.

## System overview

| | |
|---|---|
| Module | TQMa6S (serial 73914987, variant TQMa6S-CE.0203) on INIT's PM3 carrier |
| SoC | i.MX6 Solo, Cortex-A9 @ 792 MHz, 512 MB DDR3L |
| OS | PTXdist 2019.03.1 ("INIT SE-iLNX"), built 2020-03-31, systemd |
| Kernel | Linux 4.9.166-fsl-imx-INIT-004, armv7l |
| Boot | U-Boot in 16 MB SPI flash (mtd0) → loads uImage + DTB from sda1:/boot |
| Storage | sda1 950 MB ext4 (rootfs, mounted ro) · sdb1 899 MB ext4 (`/init`) |
| Stock app | `nx` → `/init/efad/pgm/NxProx`, INIT's C++ "nx" framework |

The two internal "SD cards" are INIT Ultra HS-SD1/SD2 modules behind a USB card
reader, not eMMC. U-Boot keeps `.old` copies of the kernel and DTB as a failover
(see the U-Boot env in the dumps).

## Running your own code

Ways in, cleanest first:

1. SSH — `ssh root@10.0.1.102`. Persistent once set up (see README).
2. USB `autorun.sh` via a PROXdongl3 with the EEPROM payload — runs instead of nx
   at boot. This is the first-contact method; see `usb/autorun.sh`.
3. `/init/autorun/NN-name.sh` on sdb1 — runs each boot alongside nx, sorted by name.
   `NX_EXE=NxExe` and `INIT_ROOT=/init` are exported to it.
4. `[TestMode]` in the dongle EEPROM — `90-testmode.sh` copies the EEPROM to
   `/tmp/eeprom.dat`, and if it contains `[TestMode]`, runs those lines instead of nx.
5. Install bundle — a `<version>….X72` zip with an `_install.sh` at its root,
   dropped in `/init/install/archive/`, is unpacked and run at boot. Downgrades are
   skipped (name's first 4 chars vs `BaseVersion` in `efad/pgm/arcinfo.dat`).

The PIC32 watchdog powers the unit off about 60 s after boot unless something feeds
it. nx feeds it; if you stop nx, disable it (`./pm3.py watchdog 0`, or the IPP write
in `usb/autorun.sh`). Any long-running custom boot path has to handle this first.

The rootfs is mounted read-only; `mount -o remount,rw /` before editing system files.

## Serial ports

The two IPP peripherals and the debug console are on i.MX UARTs; the barcode scanner
is on a USB-serial (FTDI) bridge. All 115200 8N1.

| Linux | i.MX UART | In DTB | Function |
|---|---|---|---|
| `ttymxc0` | UART1 | disabled | unused |
| `ttymxc1` | UART2 | okay | debug console ("ARMcons" 4-pin header), `console=ttymxc1` |
| `ttymxc2` | UART3 | okay | PIC32 power/watchdog controller (IPP) |
| `ttymxc3` | UART4 | okay | cVEND FEIG NFC reader (IPP) |
| `ttymxc4` | UART5 | okay | wired and enabled but idle — a free port if you can reach its pins |
| `ttyUSB0` | FTDI | — | barcode scanner (Honeywell N5680 / Code CR8200) |

## IPP protocol (PIC32 and cVEND)

Both the PIC32 and the cVEND speak INIT's framing, called IPP here. `pm3.py`
implements it.

Frame: `BC seq replyTo type lenHi lenLo crc8 [payload] [crc32]`
- `crc8` is CRC-8/Dallas-Maxim over the first six bytes.
- `crc32` is present only when `type >= 0x80`, and is CRC-32/JAMCRC (bit-inverted
  standard CRC-32), little-endian.

Replies set `replyTo` to the request's `seq` and set the high bit of `type`.

## NFC: reading card UIDs

The cVEND reader scans for ISO14443 cards continuously and indefinitely once its
own firmware has booted. It pushes a frame for each card it sees. No keys, no nx,
and no reader initialization are needed to get a card's UID.

Recipe (what `tap_demo.py` and `pm3.py cvend-watch` do):

1. Open `/dev/ttymxc3` at 115200 8N1 after the unit boots.
2. Do not send the enable/init sequence. Initializing the reader (the `0xE4`
   enables, `0xAA`, `0xE8` cert read) interrupts its autonomous scan.
3. Send a `0x04` status frame about once a second so the reader doesn't go idle.
4. Read the pushed card frames. With no card types enabled, every card arrives as
   `0xBE` (UnhandledCard) carrying the 7-byte UID. The UID starts at the first
   `0x04` byte in the payload (NXP cards begin with `0x04`).

Verified continuous: 74 reads of 5 different cards streaming from 55 s to 242 s of
uptime without a gap. Start the reader loop at boot and keep the keepalive going;
if the keepalive stops and the reader goes idle, only a power cycle wakes its scan
again (the `0x10` soft-reset wedges it).

Card event frame types the reader sends:

| Type | Meaning |
|---|---|
| `0xBE` | UnhandledCard — UID present, for card types not enabled |
| `0xD5` | card in/out for an enabled type: `[subtype][status][7-byte UID]`, subtype 0x00 enter / 0x01 leave |
| `0xB1` / `0xB9` | ISO14443A / DESFire read (UID at offset 2) |
| `0xD1` | card record (TLV with `df fe e0 NN` tags) |
| `0xED` | ASCII log line from the reader firmware |

Reading stored fare data (not just the UID) needs the card's application keys. A
transit card like ORCA returns its UID freely but its value is behind the
consortium's DESFire keys, which this unit doesn't hold; the reader logs
`transceive error on desf cmd 0x6E` and moves on.

The reader polls two independent ways: this base ISO14443A scan (`0xBE`/`0xD5`/
`0xB1`, no config needed, what we use), and a separate **EMV entry-point** poll
(`0xD0` control → `0xD1` EMVStatus) that the transit/fare path uses and that is
inert without an EMV config loaded. The `0xD0` toggle-polling command is therefore
not a way to drive standalone UID reading; see `docs/wiki-cross-check.md`.

### nx's reader handshake (reference)

Captured by LD_PRELOAD-sniffing nx's reads/writes on `/dev/ttymxc3` (see
`sniffer/`). nx sends, in order: `0x02` version, `0xE4 00 <id> 01 01` to enable each
card type (ids 4 VdvKa, 5 Mifare, 6 ISO, 7 DESFire, 8 Girogo, 9 ITSO, 10
UltralightC), `0xAA` SetTime (a timestamp, varies per session), then `0xE8
04fe0a0000`, which reads back the reader's X.509 device certificate (FEIG
Production Terminal CA, device id 17EE5468). None of this is required for raw UIDs,
and sending it stops the autonomous scan. nx does not send any periodic poll
command afterward — continuous scanning is the reader's own behavior.

## Reader internals: the FEIG cVEND OS

The NFC reader is a **FEIG ELECTRONIC cVEND** (a flush-mount contactless payment
module for transit validators), not just a UART peripheral — it runs its own
embedded Linux. `/etc/issue` says `FEIG ELECTRONIC GmbH - cVEND Development Kit`;
`/etc/os-release` is **Buildroot 2014.05**; the app is `/home/app0/feig` (an ARM
ELF run in a restart loop by `/home/app0/run`), firmware **02.35**. The `0x02`
Version reply carries three fields: device id `17ee5468`, model/build string
`cS01.05.45-49.00-2-2`, firmware `02.35`, cwd `/home/app0`.

Two protocols coexist. The host link we speak (`0xBC` "IPP") is INIT's own
closed payment-host protocol; FEIG's *public* OBID/ID-ISC reader protocol instead
uses a `0x02` start byte, so IPP only borrows its shape. The air-interface
payloads inside IPP are standard, though: DESFire and Ultralight-C opcodes match
the public NXP sets, and `emvco_ep_configure`/`_preprocess` are EMVCo Book B
Entry-Point calls. See `reports/FEIG cVEND reader research.md` for the full public
documentation map.

### Reading the reader's filesystem (file operations)

The reader exposes read/write file ops over IPP. Two are wrapped in `pm3.py`
(read-only; the write ops `0x96` PutFile / `0x9A` DeleteFile are left alone):

```sh
./pm3.py cvend-ls /home/app0          # 0xA4 FileList -> name + mtime per entry
./pm3.py cvend-cat /etc/fetpfrc        # 0x98 GetFile  -> file contents
./pm3.py cvend-cat /home/app0/config --hex --count 0x4000
```

- **`0x98` GetFile** = `[u16 pathlen][path][u32 offset][u16 count]` → `0x99
  [u32 len][data]` (one frame, so `count` ≲ 60 KB; use `offset` to page).
- **`0xA4` FileList** = `[u16 pathlen][path]` → `0xA5 [u32 len][name\0mtime\0…]`.
- `0x9C` FileInfo's payload format is not yet known (no reply to the obvious guesses).

Worth reading: `/etc/fetpfrc` (JSON payment config — EMVCo permitted SAM slots,
crypto/token plugins), `/home/startup_config.conf` (`STARTUP_APP="/home/app0"`),
`/home/app0/run` (the app launcher), `/home/app0/emv/transact-counter.dat`. The
apps `app0`–`app7` and `feig_app_loader` implement a fallback/update scheme. The
~64 KB binary `/home/app0/config` is the FEIG reader config blob (likely holds
the RF/power timers below) but did not yield to simple offset reads — an open
lead.

### Sleep behavior and keeping it awake

The reader **auto-powers its RF field down after an idle timeout** and can drop to
a `<1 mA` hardware standby that FEIG's datasheet says is left only "by digital
input or timer" — there is **no host wake opcode**. Symptom: scanning stops, only
the `0x07` Heartbeat (every **3.0 s**) continues, and a `0x04` Status does *not*
reliably wake it. This is documented FEIG behavior, not a bug. Practical rules:

- Keep a keepalive going and start the reader loop near boot; don't let it idle.
- Our reset path is weak: `0x10` soft-resets wedge it, and re-arming a slept
  reader is not reproducible. The one deterministic recovery is a **power cycle**,
  then wait for the `0x0F` Startup frame (~60 s) before the enable/arm handshake.
- Avoid probing it with unknown commands when idle — that is what has twice
  tipped it into the sleep-lock. See `reports/FEIG cVEND reader research.md` for
  the full prevention/recovery ladder and the (documented-for-OBID, unconfirmed-
  for-cVEND) RF on-time config angle.

## Display, touch, LEDs

Framebuffer `/dev/fb0`, 800×480, 32 bpp (BGRX), "DISP3 BG", i.MX `mxc_sdc_fb`
parallel RGB LCD. `/dev/fb1` is an overlay; `video16`/`video17` are V4L2 outputs.
Write BGRX directly, or use an fbdev library.

Grab the screen with `ssh root@… 'cat /dev/fb0' > fb.raw`, then read it as 800×480,
stride 3200, byte order B,G,R,X.

There is no touchscreen. `/dev/input` and `/proc/bus/input/devices` are empty, no
touch driver loads, no touch controller answers on any I²C bus, and the DTB has no
touch node. The `QWS_MOUSE_PROTO=tslib:event0` in nx.service is INIT's generic
template with nothing behind it. User input is NFC taps, barcode scans, and the
single power button (PIC32 key 0x0100).

The center NFC-logo LED is firmware-driven (it blinks with the reader's RF
activity) and is not host-controllable. The `0x20` LED-bitmap message produced no
change in any format tried. nx's own `led`/`ledseq`/`ledtest` shell commands exist
but sit behind its remote shell on `localhost:26`, which needs a maintenance
password that isn't on the device. Use the buzzer and the screen for feedback.

`/sys/class/leds` exposes only the SD-activity LEDs (`mmc0::`, `mmc1::`).

Backlight has no `/sys/class/backlight` entry and the LCD DTB node has no
`pwm-backlight`, so there's no software brightness control; backlight follows LCD
power. To blank the screen, blank fb0.

## Audio and buzzer

cVEND buzzer (piezo): IPP `0x22`, payload `>HH` = (frequency Hz, duration ms).
Frequency sets pitch; ~2.7 kHz is loudest (piezo resonance); a 10 ms pulse is
inaudible, ~120 ms is a clean beep. Volume isn't adjustable — shorten the pulse or
move off resonance to make it quieter. `./pm3.py beep --freq 2700 --ms 120`.
`tap_demo.py` includes a note on driving melodies.

Speaker: TI TLV320AIC32x4 codec on I²C bus 0 @ 0x18 via SSI, as ALSA card 0
"PM3 Audio". `aplay file.wav` plays through the speaker; there's a capture path too
(Mic PGA / ADC). Mixer controls include `PCM`, `HP Driver Gain`, `LO Driver Gain`.
The piezo buzzer is separate hardware — the ALSA mixer does not affect it.

## Barcode scanner

`/dev/ttyUSB0` (FTDI), 115200 8N1 raw. Present a 1D/2D/QR code and the decoded text
appears on the port with no terminator or delimiter, so split scans by an idle gap
(flush after ~50 ms of silence). Reliable and re-scannable.

```
stty -F /dev/ttyUSB0 115200 cs8 -cstopb -parenb -ixon raw -echo
```
To quiet the aimer on a Code CR8200: `echo -e "CDOPPMD0\r\n" > /dev/ttyUSB0`.

## PIC32 controller and sensors

The PIC32 is a power and health supervisor, not just a watchdog. Read its keys with
`./pm3.py pic-read <key…>`.

- Voltage rails (`50xx` block, mV): `5040` = 25.0 V input, `5041` ≈ 3.17 V,
  `5042`/`5043` ≈ 24.9 V, `5044` ≈ 23.0 V, `504f` ≈ 3.27 V (3V3), `5050` ≈ 5.06 V (5V).
- `500b` ambient light, `03fb` ignition, `0100` power button, `8104` ignition-start
  count, `c000`/`c001` firmware/bootloader versions, `c0c0` timer-health string.
- `0x4003` watchdog timeout (seconds; 0 disables).

Watchdog control: `./pm3.py watchdog 0`. Never send PIC32 IPP `0x0c` or `0x0e` with
an empty payload — they power the unit off instantly.

EEPROMs are read through the PIC32 with IPP `0x0a`:
- `./pm3.py pic-raw 0a 10000000000080` → external EEPROM (the dongle or mounting
  plate). On our dongle this holds the `[TestMode]` autorun payload.
- `./pm3.py pic-raw 0a 18000000000080` → internal EEPROM (the device identity):
  `[GeraeteParam]` with `UTCOffset=-360` (CST), `CardReaderSerNum=761310000101`,
  `VariantCode=025`, `SerienNr=9443`.

I²C sensors on bus 2: PFUZE100 PMIC @ 0x08, LM75 temperature @ 0x48
(`cat /sys/class/hwmon/hwmon0/temp1_input` → milli-°C; the driver owns the bus, so
use hwmon, not `i2cget`), TQMa6 module EEPROM @ 0x50, board-data EEPROM @ 0x57.

The clock is correct (CST, from the internal EEPROM's `UTCOffset=-360`). cVEND log
timestamps are in UTC, which is the only reason they can look six hours off.
`/dev/rtc0` is present; there's no `hwclock` binary.

## The stock app (nx)

`/init/efad/pgm/` holds `NxProx` (the UI) and `NxExe` (a multi-tool with
`eepromdump`, `watchdog <n>`, `memoryUsage`), plus INI/XML config. Notable config:
`env.ini` (`VertriebsWeg=72`, `Waehrung=USD`, `BetriebsKennung=ABM1`), `gui.xml`
(the whole UI), `opscript.nxs` (the behavior script). The German strings are INIT's
base codebase; this is a generic INIT ticketing stack skinned for CapMetro.

nx boots to an OUT-OF-SERVICE screen because it has no vehicle address. It looks
for one in a `vehicle.dat` in the parameter archive (absent here) or in the
external mounting-plate EEPROM matching `Fahrzeugadresse=<nonzero>` (ours holds
`[TestMode]` instead). nx also stays out of service until it fetches card keys from
`abtproxy` (see below). nx runs a remote shell on `localhost:26` while up.

### Driving nx in service on your own key-server

nx's card pipeline is gated on fetching keys from `http://127.0.0.1:80/v1/device/keys`.
That endpoint is `abtproxy`/`proxy_server`, which won't open port 80 until it gets
an OAuth token from Bytemark's servers. Offline, it never serves.

`keyserver/keyserve.c` is a small HTTP server that serves the cached
`/init/abtproxy/*.json` on port 80, replacing abtproxy. With it running, nx fetches
its keys and labels locally and goes in service (the live SCAN/TAP screen). Starting
it before nx (so nx gets keys during the reader's post-boot scan window) makes nx
read and process taps normally. This is only needed for nx's handled, fare-aware
reads; raw UIDs don't need it.

## The ABT backend (`/init/abtproxy/`)

`abtproxy` v1.3.6 is the on-device client for CapMetro's account-based-ticketing
cloud (Bytemark). `proxy_server` is the ARM binary (unstripped); `abtproxy` is a
restart wrapper around it. It holds:

- `config.json` — OAuth client id/secret, access token, device id, backend URLs.
- `keys.json` — card read keys. `labels.json` — fare product definitions.
- `denylist.json` — blocked-card hotlist. `proxyDB.db` — SQLite transactions.

These are CapMetro production secrets. They stay in the (git-ignored) storage dumps
and must not be published. Using the OAuth credentials against CapMetro's servers,
or the card keys against cards that aren't yours, would be unauthorized regardless
of who owns the hardware. For your own projects, replace the backend or point it at
your own.

## Networking

`eth0` (FEC, 100 Mbit), DHCP via systemd-networkd, plus IPv6 SLAAC. U-Boot has a
static TFTP fallback (`ipaddr=10.0.42.2 / serverip=10.0.42.1`). With nx and abtproxy
stopped, the only listening sockets are SSH (`:22`) and systemd-resolved.

## Building software for it

ARM hard-float, old glibc. Cross-compile a static binary:
```
cross build --release --target armv7-unknown-linux-gnueabihf   # Rust
# or arm-linux-gnueabihf-gcc for C (see sniffer/ and keyserver/ for working examples)
```
`sniffer/cvsniff.c` and `keyserver/keyserve.c` build against the device's old glibc
by using only base symbols; both load with no issues.

Kernel config is saved at `os-build/kernel-config-4.9.166` for anyone rebuilding
the kernel or an OS image. U-Boot boots whatever uImage + DTB + rootfs are on the
SD card, so a custom OS can be installed there without touching the SPI flash.
