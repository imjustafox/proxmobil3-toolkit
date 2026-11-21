# PROXmobil3 interface reference

How to drive every subsystem of the PROXmobil3 (PM3), an INIT transit validator
built on a Freescale i.MX6 module. This comes from the device's storage images, its
decompiled device tree, and testing against a live unit.

See `README.md` for access and the `pm3.py` tool, and `PROCESS.md` for how this was
reverse-engineered.

## System overview

| | |
|---|---|
| Module | TQMa6S (serial 73914987, variant TQMa6S-CE.0203) on INIT's PM3 carrier |
| SoC | i.MX6 Solo, Cortex-A9 at 792 MHz, 512 MB DDR3L |
| OS | PTXdist 2019.03.1 ("INIT SE-iLNX"), built 2020-03-31, systemd |
| Kernel | Linux 4.9.166-fsl-imx-INIT-004, armv7l |
| Boot | U-Boot in 16 MB SPI flash (mtd0), loads uImage and DTB from sda1:/boot |
| Storage | sda1 950 MB ext4 (rootfs, mounted ro), sdb1 899 MB ext4 (`/init`) |
| Stock app | `nx` at `/init/efad/pgm/NxProx`, INIT's C++ "nx" framework |

The two internal "SD cards" are INIT Ultra HS-SD1/SD2 modules behind a USB card
reader, not eMMC. U-Boot keeps `.old` copies of the kernel and DTB as a failover
(see the U-Boot env in the dumps).

## Running your own code

Ways in, cleanest first:

1. SSH: `ssh root@10.0.1.102`. Persistent once set up (see README).
2. USB `autorun.sh` through a PROXdongl3 with the EEPROM payload. It runs instead
   of nx at boot. This is the first-contact method; see `usb/autorun.sh`.
3. `/init/autorun/NN-name.sh` on sdb1. Runs each boot alongside nx, sorted by
   name. `NX_EXE=NxExe` and `INIT_ROOT=/init` are exported to it.
4. `[TestMode]` in the dongle EEPROM. `90-testmode.sh` copies the EEPROM to
   `/tmp/eeprom.dat`, and if it contains `[TestMode]`, runs those lines instead of
   nx.
5. Install bundle: a `<version>.X72` zip with an `_install.sh` at its root,
   dropped in `/init/install/archive/`, is unpacked and run at boot. Downgrades
   are skipped by comparing the name's first 4 characters against `BaseVersion` in
   `efad/pgm/arcinfo.dat`.

The PIC32 watchdog reboots the unit about 60 seconds after boot unless something
feeds it. It power-cycles and comes back (see the watchdog note under PIC32). nx
feeds it. If you stop nx, disable it (`./pm3.py watchdog 0`, or the IPP write in
`usb/autorun.sh`). Any long-running custom boot path has to handle this first.

The rootfs is mounted read-only. Use `mount -o remount,rw /` before editing system
files.

## Serial ports

The two IPP peripherals and the debug console are on i.MX UARTs. The barcode
scanner is on a USB-serial (FTDI) bridge. All run 115200 8N1.

| Linux | i.MX UART | In DTB | Function |
|---|---|---|---|
| `ttymxc0` | UART1 | disabled | unused |
| `ttymxc1` | UART2 | okay | debug console ("ARMcons" 4-pin header), `console=ttymxc1` |
| `ttymxc2` | UART3 | okay | PIC32 power/watchdog controller (IPP) |
| `ttymxc3` | UART4 | okay | cVEND FEIG NFC reader (IPP) |
| `ttymxc4` | UART5 | okay | spare RS232 with TX/RX and RTS/CTS (full flow control), ALT3 on the CSI0_DAT pads, 9600 8N1 default. No driver or peripheral is bound, nothing opens it, no traffic. A free flow-control port if you can reach its pads (not on the DB15; needs the board schematic to locate) |
| `ttyUSB0` | FTDI | none | barcode scanner (Honeywell N5680 / Code CR8200) |

## IPP protocol (PIC32 and cVEND)

Both the PIC32 and the cVEND speak INIT's framing, called IPP here. `pm3.py`
implements it.

Frame: `BC seq replyTo type lenHi lenLo crc8 [payload] [crc32]`

- `crc8` is CRC-8/Dallas-Maxim over the first six bytes.
- `crc32` is present only when `type >= 0x80`. It is CRC-32/JAMCRC (bit-inverted
  standard CRC-32), little-endian.

Replies set `replyTo` to the request's `seq` and set the high bit of `type`.

## NFC: reading card UIDs

The cVEND reader scans for ISO14443 cards continuously and indefinitely once its
own firmware has booted. It pushes a frame for each card it sees. No keys, no nx,
and no reader initialization are needed to get a card's UID.

Recipe (what `tap_demo.py` does: the keyless listen):

1. Open `/dev/ttymxc3` at 115200 8N1 after the unit boots.
2. Do not send the enable/init sequence. Initializing the reader (the `0xE4`
   enables, `0xAA`, `0xE8` cert read) interrupts its autonomous scan.
3. Send a `0x04` status frame about once a second so the reader does not go idle.
4. Read the pushed card frames. With no card types enabled, every card arrives as
   `0xBE` (UnhandledCard) carrying the 7-byte UID. The UID starts at the first
   `0x04` byte in the payload (NXP cards begin with `0x04`). Gate on the frame
   `type == 0xBE`, not on "a `0x04` byte appeared." The `0xD1` status and `0xED`
   log frames also contain `0x04` bytes, and anchoring on the byte instead of the
   frame type yields phantom card reads. That bug was hit and fixed here.

Verified continuous: 74 reads of 5 different cards streaming from 55 s to 242 s of
uptime without a gap. Start the reader loop at boot and keep the keepalive going.
If the keepalive stops and the reader goes idle, wake its scan with a software
restart: `./pm3.py cvend-restart` (`0x10 02`), which brings it back in about 6
seconds without a power cycle. A bare `0x10` with no subcode wedges it, so always
send the subcode.

`pm3.py cvend-watch` is the opposite path. It runs nx's enable handshake (all card
types by default) to drive the reader's own card handlers (`0xD5`/`0xD1`), which
stops this autonomous base scan. Use it when you want the handled-card behavior,
not raw UIDs.

Card event frame types the reader sends:

| Type | Meaning |
|---|---|
| `0xBE` | UnhandledCard: UID present, for card types not enabled |
| `0xD5` | card in/out for an enabled type: `[subtype][status][7-byte UID]`, subtype 0x00 enter / 0x01 leave |
| `0xB1` / `0xB9` | ISO14443A / DESFire read (UID at offset 2) |
| `0xD1` | card record (TLV with `df fe e0 NN` tags) |
| `0xED` | ASCII log line from the reader firmware |

Reading stored fare data beyond the UID needs the card's application keys. A
transit card like ORCA returns its UID freely, but its value is behind the
consortium's DESFire keys, which this unit does not hold. The reader logs
`transceive error on desf cmd 0x6E` and moves on.

### Telling cards apart without keys

Nearly every transit card tested, including ORCA (Seattle), Compass (Vancouver),
Ventra (Chicago), Peggo (Winnipeg), and NFTA Metro (Buffalo), is an NXP DESFire
card. They present identically at the type layer (`ATQA 0x0344`, `SAK 0x20`).
Without keys there is nothing to distinguish one card, or one agency, from another
except the UID itself and its OUI-like prefix. So any "act like the ORCA reader for
ORCA cards, the Peggo reader for Peggo cards" behavior has to be driven by a UID
allow-list, not by card type.

One easy outlier: a hotel room key (for example a Marriott key) is a MIFARE
Ultralight (`ATQA 0x0044`, `SAK 0x00`). It is a different type, so it is
distinguishable without any UID list.

The reader polls two independent ways. This base ISO14443A scan (`0xBE`/`0xD5`/
`0xB1`, no config needed, what the standalone recipe uses) is separate from an EMV
entry-point poll (`0xD0` control to `0xD1` EMVStatus) used by the transit/fare
path. The EMV poll is inert without an EMV config loaded. The `0xD0` toggle-polling
command is therefore not a way to drive standalone UID reading; see
`docs/wiki-cross-check.md`.

### nx's reader handshake (reference)

Captured by LD_PRELOAD-sniffing nx's reads and writes on `/dev/ttymxc3` (see
`sniffer/`). nx sends, in order: `0x02` version; `0xE4 00 <id> 01 01` to enable
each card type (ids 4 VdvKa, 5 Mifare, 6 ISO, 7 DESFire, 8 Girogo, 9 ITSO, 10
UltralightC); `0xAA` SetTime (a timestamp, varies per session); then
`0xE8 04fe0a0000`, which reads back the reader's X.509 device certificate (FEIG
Production Terminal CA, device id 17EE5468). None of this is required for raw
UIDs, and sending it stops the autonomous scan. nx sends no periodic poll command
afterward. Continuous scanning is the reader's own behavior.

## Reader internals: the FEIG cVEND OS

The NFC reader is a FEIG ELECTRONIC cVEND, a flush-mount contactless payment
module for transit validators with its own embedded Linux. `/etc/issue` says `FEIG ELECTRONIC GmbH - cVEND Development Kit`.
`/etc/os-release` is Buildroot 2014.05. The app is `/home/app0/feig`, an ARM ELF
run in a restart loop by `/home/app0/run`, firmware 02.35. The `0x02` Version reply
carries three fields: device id `17ee5468`, model/build string
`cS01.05.45-49.00-2-2`, firmware `02.35`, cwd `/home/app0`.

Two protocols coexist. The host link we speak (`0xBC` "IPP") is INIT's own closed
payment-host protocol. FEIG's public OBID/ID-ISC reader protocol instead uses a
`0x02` start byte, so IPP only borrows its shape. The air-interface payloads inside
IPP are standard, though. DESFire and Ultralight-C opcodes match the public NXP
sets, and `emvco_ep_configure`/`_preprocess` are EMVCo Book B Entry-Point calls.
See `reports/FEIG cVEND reader research.md` for the public documentation map.

### Reading the reader's filesystem

The reader exposes read/write file ops over IPP. Two are wrapped in `pm3.py`
(read-only; the write ops `0x96` PutFile and `0x9A` DeleteFile are left alone):

```sh
./pm3.py cvend-ls /home/app0          # 0xA4 FileList: name + mtime per entry
./pm3.py cvend-cat /etc/fetpfrc        # 0x98 GetFile: file contents
./pm3.py cvend-cat /home/app0/config --hex --count 0x4000
```

- `0x98` GetFile is `[u16 pathlen][path][u32 offset][u16 count]` and replies `0x99
  [u32 len][data]`. It is one frame, so `count` should stay under about 60 KB. Use
  `offset` to page.
- `0xA4` FileList is `[u16 pathlen][path]` and replies `0xA5 [u32 len][name\0mtime\0...]`.
- `0x9C` FileInfo's payload format is not yet known. There is no reply to the
  obvious guesses.

Worth reading: `/etc/fetpfrc` (JSON payment config: EMVCo permitted SAM slots,
crypto/token plugins), `/home/startup_config.conf` (`STARTUP_APP="/home/app0"`),
`/home/app0/run` (the app launcher), and `/home/app0/emv/transact-counter.dat`.
The apps `app0` to `app7` and `feig_app_loader` implement a fallback/update
scheme. The roughly 64 KB binary `/home/app0/config` is the FEIG reader config blob
and likely holds the RF/power timers below, but it did not yield to simple offset
reads. That is still an open lead.

### Sleep behavior and keeping it awake

The reader powers its RF field down after an idle timeout and can drop to a sub-1
mA hardware standby. FEIG's datasheet says the standby state is left only by
digital input or timer, and there is no host wake opcode. Symptom: scanning stops,
only the `0x07` Heartbeat (every 3.0 s) continues, and a `0x04` Status does not
reliably wake it. This is documented FEIG behavior, not a bug. Practical rules:

- Keep a keepalive going and start the reader loop near boot. Do not let it idle.
- Software recovery exists: `./pm3.py cvend-restart` sends `0x10 02` (restart
  application). The reader emits `0x11` ResetReply, aborts, re-inits, and emits
  `0x0F` Startup in about 6 seconds with the serial link preserved and scanning
  fresh. No power cycle. Use this to wake a slept reader and to get a fresh
  handled-scanning state on demand. Only a bare `0x10`, or an unknown command sent
  while idle, wedges it (that has twice forced a physical power cycle). The
  subcode matters. A power cycle remains the fallback if a wedge happens.
- See `reports/FEIG cVEND reader research.md` for the prevention/recovery ladder
  and the RF on-time config angle. That angle is documented for OBID and
  unconfirmed for cVEND.

## Display, touch, LEDs

Framebuffer `/dev/fb0`, 800x480, 32 bpp (BGRX), "DISP3 BG", i.MX `mxc_sdc_fb`
parallel RGB LCD. `/dev/fb1` is an overlay. `video16`/`video17` are V4L2 outputs.
Write BGRX directly, or use an fbdev library.

Grab the screen with `ssh root@... 'cat /dev/fb0' > fb.raw`, then read it as
800x480, stride 3200, byte order B,G,R,X.

There is no touchscreen. `/dev/input` and `/proc/bus/input/devices` are empty, no
touch driver loads, no touch controller answers on any I2C bus, and the DTB has no
touch node. The `QWS_MOUSE_PROTO=tslib:event0` in nx.service is INIT's generic
template with nothing behind it. User input is NFC taps, barcode scans, and the
single power button (PIC32 key 0x0100).

The front LEDs are host-controllable through the cVEND `0x20` LED message: a u32
bitmap, sent as 4 bytes big-endian, with all eight LEDs in the low byte. This was
verified bit by bit against the opened reader board:

| Bit | LED |
|---|---|
| `0x01` | status row 1, green |
| `0x02` | status row 2, green |
| `0x04` | status row 3, green |
| `0x08` | status row 4, green |
| `0x10` | status row 3, amber (same LED as `0x04`; green plus amber reads amber) |
| `0x20` | status row 4, red (same LED as `0x08`; green plus red reads red) |
| `0x40` | NFC logo, right segment |
| `0x80` | NFC logo, left segment |

So it is a four-LED left-to-right status row (the two left are green-only, the two
right are bi-color green/amber and green/red) plus the two-segment logo.
`s.send(0x20, struct.pack(">I", 0x0f))` lights all four green. `0x00` clears. The
firmware also drives these during RF activity, so a host write holds only until
the firmware next updates them. Drive them from a loop if you want them steady.
The upper three bytes of the u32 are inert. Sweeping all 32 bits showed the eight
LEDs live entirely in the low byte, with no brightness/blink/PWM field above it. An
earlier "no change in any format" note was wrong; it was an artifact of reader
state, with nx holding the port.

nx's own `led`/`ledseq`/`ledtest` shell commands also exist, but they sit behind
its remote shell on `localhost:26`, which needs a maintenance password that is not
on the device. The `0x20` message is the direct path.

`/sys/class/leds` exposes only the SD-activity LEDs (`mmc0::`, `mmc1::`).

Backlight has no `/sys/class/backlight` entry, and the LCD DTB node has no
`pwm-backlight`, so there is no software brightness control. Backlight follows LCD
power. To blank the screen, blank fb0.

## Audio and buzzer

cVEND buzzer (piezo): IPP `0x22`, payload `>HH` = frequency in Hz, duration in ms.
Frequency sets pitch. About 2.7 kHz is loudest (piezo resonance). A 10 ms pulse is
inaudible, and about 120 ms is a clean beep. Volume is not adjustable; shorten the
pulse or move off resonance to make it quieter. `./pm3.py beep --freq 2700 --ms
120`. `tap_demo.py` has a note on driving melodies.

Speaker: the two grille speakers are on the Line-Out (LOL/LOR) of a TI
TLV320AIC32x4 codec (I2C bus 0 at 0x18, fed over SSI), exposed as ALSA card 0 "PM3
Audio". There is a capture path too (Mic PGA / ADC). The piezo buzzer above is
separate hardware. The ALSA mixer does not affect it, and vice versa.

The Line-Out feeds an external power amplifier ("PAmobil2") that is off at
power-on and must be switched on over the PIC32. This is the one thing that makes
the whole codec/ALSA side look dead. With the amp off, the codec, mixer, clocks,
and SSI are all fully configured and clocking real samples, and the speaker is
still silent. The amp is gated by a single PIC32 value:

- Key `0x07E0` (PIC32 `ValueWrite`, type `0x04`): `1` means amp on, `0` means amp
  off. One master gate for both channels. It reads back (`ValueRead`), so you can
  query the current state. It is a hard latch: once set it stays on until the
  PIC32 resets at the next power-off, so a borrowed unit reverts to stock on
  reboot. Nothing persistent is written.

```sh
./pm3.py amp on          # PIC32 0x07E0 = 1 (enable the power amp)
./pm3.py amp status      # read 0x07E0 (1 = on, 0 = off)
./pm3.py play tone.wav   # sets 0x07E0 = 1 itself, then plays; no nx needed
```

`./pm3.py play` asserts the amp enable before every playback, so it works from a
cold, nx-free boot. The raw equivalent is `./pm3.py pic-raw 04 07e001`. The stock
app does the same thing once at startup. This is its `NxPaCtrl` "PA Amplifier
Control Mode", driven on this unit through `NxPaMobil2PicDev`, a PIC32 command.
That is why "the speaker only worked after nx had run" for so long: nx had switched
the amp on, and it stayed latched until reboot. nx's config also has a `0x4031`
value of 15000 ms for "Hold on Active", but the enable is durable. It does not
auto-standby across that window, so a one-time `amp on` is enough. `play`
re-asserts it anyway.

With the amp on and nx stopped, two ALSA details still have to be right, or you
get silence with no error:

1. Line-Out driver gain at its 0 dB baseline. `alsa-restore.service` already
   restores `/etc/asound.state` at boot, so the routing is set. Just confirm the
   gain:
   ```sh
   amixer -c 0 sset 'LO Driver Gain' 6     # 6 = 0 dB; this is the baseline, not the volume
   ```
2. Play from a file, not a pipe. `aplay /tmp/x.wav` plays. Piping into aplay
   (`... | aplay -q -` reading stdin) is silent on this device's aplay/ALSA. Copy
   the WAV onto the unit and play the file.

Volume is the `PCM` control, as a percentage: `amixer -c 0 sset PCM 65%`. Leave
`LO Driver Gain` at the 6/0 dB baseline and use PCM as the knob. End to end:

```sh
./pm3.py pic-raw 04 07e001                              # amp on (PIC32 0x07E0 = 1)
alsactl -f /etc/asound.state restore
amixer -c 0 sset 'LO Driver Gain' 6
amixer -c 0 sset PCM 65%
scp -O tone.wav root@<ip>:/tmp/ && ssh root@<ip> aplay /tmp/tone.wav   # file, not a pipe
```

The discovery path for this is in `PROCESS.md`. In short: every readable
audio register matched between a silent cold boot and a working post-nx run, so
the gate was not in the SoC. nx's binary strings named an external amplifier, and
a PIC32 sniff caught the one-time `0x07E0 = 1`.

## Barcode scanner

`/dev/ttyUSB0` (FTDI), 115200 8N1 raw. Present a 1D/2D/QR code and the decoded
text appears on the port with no terminator or delimiter. Split scans by an idle
gap, flushing after about 50 ms of silence. Reliable and re-scannable.

```
stty -F /dev/ttyUSB0 115200 cs8 -cstopb -parenb -ixon raw -echo
```
To quiet the aimer on a Code CR8200: `echo -e "CDOPPMD0\r\n" > /dev/ttyUSB0`.

## PIC32 controller and sensors

The PIC32 handles power and health as well as the watchdog. Read its keys with
`./pm3.py pic-read <key...>`.

- Voltage rails (`50xx` block, mV): `5040` = 25.0 V input, `5041` about 3.17 V,
  `5042`/`5043` about 24.9 V, `5044` about 23.0 V, `504f` about 3.27 V (3V3),
  `5050` about 5.06 V (5V).
- `500b` ambient light, `03fb` ignition, `0100` power button, `8104`
  ignition-start count, `c000`/`c001` firmware/bootloader versions, `c0c0`
  timer-health string.
- `0x4003` watchdog timeout in seconds (0 disables).
- `0x07e0` audio power-amp enable (`1` on, `0` off; the external speaker amp, see
  the Speaker section). `./pm3.py amp on|off|status`.

Watchdog control: `./pm3.py watchdog 0`. When the PIC32 watchdog expires it
reboots the unit with a full power-cycle that comes back on its own. It is not a
permanent power-off, so letting it expire is in effect the one software path to a
hardware reboot without the power button. That is distinct from PIC32 IPP `0x0c`
or `0x0e` with an empty payload, which power the unit off instantly and it stays
off. Never send those.

There is a second watchdog: the i.MX6 SoC's own `imx2-wdt` (about 10 s), which
systemd feeds through its `RuntimeWatchdogSec` setting. systemd keeps feeding it as
long as it runs, so stopping nx does not trip it. Only the external PIC32 watchdog
bites when nx stops, which is why `watchdog 0` is the one you need.

The PIC32 is a PIC32MX795, per nx's `spic/pic32mx795` driver. Firmware identity
(keys `c000`/`c001`): app `PROXmobil3 PIC32 / PM3-P32` rev 0.20 (Apr 2017),
bootloader `PROXmobil3-Bootloader / PM3-BL` rev 1.1 (Sep 2016), copyright INIT
GmbH. Its own program code is not reachable from here. The IPP interface exposes
only value keys, EEPROM (`0x0a`), the watchdog, and sensors. There is no
memory-read command, no PIC32 firmware image is bundled on the host (nx can flash
it through the `PM3-BL` bootloader, but there is no read-back), and recovering the
code would need physical ICSP/JTAG on the code-protected MCU. The protocol above
is the full extent of PIC32 understanding. The firmware internals are a hard
limit, not an undone task.

EEPROMs are read through the PIC32 with IPP `0x0a`:

- `./pm3.py pic-raw 0a 10000000000080` reads the external EEPROM (the dongle or
  mounting plate). On this dongle it holds the `[TestMode]` autorun payload.
- `./pm3.py pic-raw 0a 18000000000080` reads the internal EEPROM (device
  identity): `[GeraeteParam]` with `UTCOffset=-360` (CST),
  `CardReaderSerNum=761310000101`, `VariantCode=025`, `SerienNr=9443`.

I2C sensors on bus 2: PFUZE100 PMIC at 0x08, LM75 temperature at 0x48
(`cat /sys/class/hwmon/hwmon0/temp1_input` gives milli-degrees C; the driver owns
the bus, so use hwmon, not `i2cget`), TQMa6 module EEPROM at 0x50, board-data
EEPROM at 0x57.

The clock is correct (CST, from the internal EEPROM's `UTCOffset=-360`). cVEND log
timestamps are in UTC, which is the only reason they can look six hours off.
`/dev/rtc0` is present. There is no `hwclock` binary.

## The stock app (nx)

`/init/efad/pgm/` holds `NxProx` (the UI) and `NxExe` (a multi-tool with
`eepromdump`, `watchdog <n>`, `memoryUsage`), plus INI/XML config. Notable config:
`env.ini` (`VertriebsWeg=72`, `Waehrung=USD`, `BetriebsKennung=ABM1`), `gui.xml`
(the whole UI), `opscript.nxs` (the behavior script). The German strings are
INIT's base codebase. This is a generic INIT ticketing stack skinned for CapMetro.

nx boots to an OUT-OF-SERVICE screen because it has no vehicle address. It looks
for one in a `vehicle.dat` in the parameter archive (absent here) or in the
external mounting-plate EEPROM matching `Fahrzeugadresse=<nonzero>`; ours holds
`[TestMode]` instead. nx also stays out of service until it fetches card keys from
`abtproxy` (see below). nx runs a remote shell on `localhost:26` while up.

### Driving nx in service on your own key server

nx's card pipeline is gated on fetching keys from
`http://127.0.0.1:80/v1/device/keys`. That endpoint is `abtproxy`/`proxy_server`,
which will not open port 80 until it gets an OAuth token from Bytemark's servers.
Offline, it never serves.

`keyserver/keyserve.c` is a small HTTP server that serves the cached
`/init/abtproxy/*.json` on port 80, replacing abtproxy. With it running, nx fetches
its keys and labels locally and goes in service (the live SCAN/TAP screen).
Starting it before nx, so nx gets keys during the reader's post-boot scan window,
makes nx read and process taps normally. This is only needed for nx's handled,
fare-aware reads. Raw UIDs do not need it.

## The ABT backend (`/init/abtproxy/`)

`abtproxy` v1.3.6 is the on-device client for CapMetro's account-based-ticketing
cloud (Bytemark). `proxy_server` is the ARM binary (unstripped). `abtproxy` is a
restart wrapper around it. It holds:

- `config.json`: OAuth client id/secret, access token, device id, backend URLs.
- `keys.json`: card read keys. `labels.json`: fare product definitions.
- `denylist.json`: blocked-card hotlist. `proxyDB.db`: SQLite transactions.

These are CapMetro production secrets. They stay in the git-ignored storage dumps
and must not be published. Using the OAuth credentials against CapMetro's servers,
or the card keys against cards that are not yours, would be unauthorized
regardless of who owns the hardware. For your own projects, replace the backend or
point it at your own.

## Networking

`eth0` (FEC, 100 Mbit), DHCP through systemd-networkd, plus IPv6 SLAAC. U-Boot has
a static TFTP fallback (`ipaddr=10.0.42.2`, `serverip=10.0.42.1`). With nx and
abtproxy stopped, the only listening sockets are SSH (`:22`) and
systemd-resolved.

## Building software for it

ARM hard-float, old glibc. Cross-compile a static binary:

```
cross build --release --target armv7-unknown-linux-gnueabihf   # Rust
# or arm-linux-gnueabihf-gcc for C (see sniffer/ and keyserver/ for working examples)
```

`sniffer/cvsniff.c` and `keyserver/keyserve.c` build against the device's old
glibc by using only base symbols. Both load with no issues.

Kernel config is saved at `os-build/kernel-config-4.9.166` for anyone rebuilding
the kernel or an OS image. U-Boot boots whatever uImage, DTB, and rootfs are on the
SD card, so a custom OS can be installed there without touching the SPI flash.
