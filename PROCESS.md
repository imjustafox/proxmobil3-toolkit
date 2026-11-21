# How this was reverse-engineered

This is the path from a surplus transit validator on the LAN to a documented,
programmable device with a working standalone card reader. Some of it is here so
the techniques can be reused on the next unknown device. Some of it is here
because the dead ends taught more than the wins.

## Starting point

An INIT PROXmobil3, bought from a transit-agency surplus auction, sitting on the
LAN at a known IP. Two public references existed (`wiki.pm3.dev` and a personal
project page). They covered the hardware and some protocols, but not how to read
cards without the stock firmware. The goal was to understand the device well
enough to run our own software on it.

## Methodology

A few techniques carried most of the work:

- Read the public material first, then the device's own software. The wiki gave
  the frame format and pin maps. The real answers were in the binaries and config
  on the device's storage.
- Image the storage, then work from the copy. Everything about how the device
  boots and behaves is in the two internal SD cards and the SPI flash. Dumping
  them over SSH, with checksums, meant the rest of the analysis could happen
  offline against files instead of a live unit.
- Decompile the device tree. `init-proxmobil3.dtb` to `.dts` mapped every
  peripheral, which UART was which, and what was enabled. That turned "three
  serial ports" into "PIC32, cVEND, and one spare."
- Run `strings` and read symbol tables. The stock app `NxProx` is stripped, but
  its strings exposed command names, config keys, error messages, and source-file
  paths. `proxy_server` was unstripped, which gave the backend's exact behavior.
- Sniff the real firmware instead of guessing the protocol. An `LD_PRELOAD` shim
  (`sniffer/cvsniff.c`) logged every `read()` and `write()` the stock app made on
  the reader's serial port. It captured the exact byte sequences the firmware
  sends, which no amount of guessing had produced.
- Build small ARM helpers that load on the old glibc. The shim and the key server
  are both small C programs cross-compiled against base glibc symbols, so they run
  on the 2019 userland without fuss.
- Test against the live hardware and watch what actually happens. Many
  conclusions only held up, or fell apart, when a card was physically tapped and
  the frames, the screen, or a beep were observed.

## The path

### Access

SSH was open, but root login was closed and no default password is published. The
way in is the PROXdongl3's EEPROM payload: a `[TestMode]` block that runs an
`autorun.sh` from a FAT USB stick instead of the stock UI. The script installs an
SSH key and disables the watchdog.

Two false starts were worth remembering. The stick must be labeled `MP_SD`, and
it must be a single MBR partition. macOS's default GPT layout puts an empty EFI
partition first, which the device mounts and finds no script on.

### Recon and imaging

With a shell, we dumped both internal SDs and the SPI flash over SSH with matching
checksums, then mounted the images read-only in a container to browse the real
filesystem. We decompiled the device tree, pulled `dmesg`, the U-Boot env, and the
EEPROM contents. This produced the hardware map and the boot flow.

### Driving the subsystems

We built `pm3.py` around the IPP framing, verified by reproducing the wiki's known
watchdog-off frame byte for byte, and worked through the peripherals: PIC32 keys
and sensors, the framebuffer (confirmed by drawing to it and reading it back), the
TLV320 speaker, the barcode scanner (read a test QR), and the cVEND buzzer (full
tone control; it played Song of Storms). We established that there is no
touchscreen and that the reader LED is firmware-controlled.

### The NFC problem

Reading a card's UID was the hard part and the long middle of the project. The
reader would detect a card sometimes and not others. The behavior seemed to depend
on reboots, timing, and reader state in ways that kept shifting. The debugging was
not clean: several watchdog power-offs from stopping nx without disabling the
watchdog fast enough, a reader wedged by a soft reset, and a lot of hardware
thrashing.

The `LD_PRELOAD` sniffer explained it. It captured nx's exact reader init: the
`0xE4` enables, the `0xAA` SetTime, and the `0xE8` certificate read. It also
corrected the wiki's guesses. But replaying that init only read cards
intermittently, because the init itself is not what makes the reader scan.

### The key-server detour

The reader scans continuously once nx is "in service." nx is gated on fetching card
keys from a local endpoint served by `abtproxy`, which refuses to run offline
because it cannot reach Bytemark for an OAuth token. We reversed that endpoint's
response shape and built `keyserver/keyserve.c` to serve the cached keys locally.
It worked: nx went in service on our own server, no cloud. But continuous reads
still depended on fragile boot timing, and the nx path dragged the loud validator
beep along with it.

### What the reader was doing all along

Stepping back from nx entirely: the reader scans on its own, continuously, right
after its firmware boots. No keys, no init, no nx. Two mistakes had hidden this.
Re-initializing the reader stops its autonomous scan, and letting it go idle puts
it to sleep.

A final test proved it. Connect to the reader port at boot, send a status frame
once a second, and just listen. It streams a UID frame for every card,
indefinitely: 74 reads of 5 different cards over four minutes, no gap. That became
the recipe in `tap_demo.py`.

## The audio gate

For a long time the speaker only played after nx had run. Between a silent
cold-boot playback and a working post-nx playback, everything readable from the
kernel was identical: codec registers (regmap, pages 0 and 1), DAPM widgets, GPIO,
the whole audio clock tree (including the 24 MHz CKO2 that is the codec MCLK),
AUDMUX, and the SSI1 config. SSI1 transmitted valid I2S with real samples in both
cases. That total identity was the clue. If nothing readable differs, the cause is
on a bus we were not watching.

An `LD_PRELOAD` trace of nx's ALSA calls (`sniffer/audiotrace.c`) against a cold
`aplay` confirmed the userspace side: nx opens no `i2c`, `mem`, `gpio`, or `clk`
device, writes no mixer control, and uses the same `default` to dmix to `hw:0`
sink at the same format. Cold `aplay -D hw:0`, a stream-primed retry, and a 30
second sustained stream were all silent too.

The answer had been in nx's binary strings: `ActivateExternalSpeaker`,
`NxPaCtrl` ("PA Amplifier Control Mode"), and `NxPaMobil2PicDev`. An external
power amp is switched on over the PIC32 (`ttymxc2`), downstream of the codec and
off-SoC. That was the one bus none of the audio-side probes watched.

Sniffing nx's first-init PIC32 traffic with the same `cvsniff` shim, which already
logged `ttymxc2`, caught a one-time `ValueWrite 0x07E0 = 1` buried in the
watchdog and sensor chatter. Toggling it on the live unit gave a clean
beep, silent, beep. A verified cold boot with just that write, and no nx, plays.
The fix is one frame: `pm3.py amp on`, and `play` sets `0x07E0 = 1` itself.

The useful distinction is between "needs the firmware running now" and "needs a
one-time setup step the firmware performs." Test from a clean boot before calling
a subsystem firmware-independent. Also, when every register you can read matches,
the state you are not instrumenting is the place to look. Widen the net instead of
digging deeper into buses you already trust. And read the firmware's own strings
early. This mechanism had a plain-text name long before we found it the hard way.

## Lessons

- Disable the watchdog the instant you stop the firmware that was feeding it. Do
  it in the same breath, not a step later. Most of the power-offs came from the
  gap between stopping nx and sending `watchdog 0`.
- Sniff before you guess. Days of protocol guessing were beaten by one
  `LD_PRELOAD` capture of what the firmware actually sends.
- The simplest explanation was right, and we reached it last. The reader just
  scans and pushes. Everything clever we tried (re-init, arming, key server) was
  working against that.
- When every register you can read is identical but the behavior differs, the
  variable is on a bus you are not watching. That is a direction, not a dead end.
- Watch the real hardware. The screen going from OUT OF SERVICE to SCAN/TAP, a
  beep on a tap, an LED blink: those physical signals repeatedly settled questions
  the logs left ambiguous.
- Keep the firmware's secrets out of the repo. The backend config holds the
  agency's real credentials and card keys. They live only in the local storage
  dumps, which are git-ignored.
