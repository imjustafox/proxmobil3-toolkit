# How this was reverse-engineered

The methodology and the path taken to go from a surplus transit validator on the
LAN to a documented, programmable device with a working standalone card reader.
Written partly so the techniques are reusable on the next unknown device, and
partly because the dead ends taught more than the wins.

## Starting point

An INIT PROXmobil3, bought from a transit-agency surplus auction, sitting on the
LAN at a known IP. Two public references existed (`wiki.pm3.dev` and a personal
project page), covering the hardware and some of the protocols but not how to
read cards without the stock firmware. The goal was to understand the device well
enough to run our own software on it.

## Methodology

A few techniques carried most of the work:

- **Read the public material first, then the device's own software.** The wiki gave
  the frame format and pin maps; the real answers were in the binaries and config on
  the device's storage.
- **Image the storage, then work from the copy.** Everything about how the device
  boots and behaves is in the two internal SD cards and the SPI flash. Dumping them
  (over SSH, with checksums) meant the rest of the analysis could happen offline
  against files, not a live unit.
- **Decompile the device tree.** `init-proxmobil3.dtb` → `.dts` mapped every
  peripheral, which UART is which, and what's enabled. That turned "three serial
  ports" into "PIC32, cVEND, and one spare."
- **`strings` and symbol tables on the binaries.** The stock app `NxProx` is
  stripped, but its strings exposed command names, config keys, error messages, and
  source-file paths. `proxy_server` was unstripped, which gave the backend's exact
  behavior.
- **Sniff the real firmware instead of guessing the protocol.** The single most
  useful move: an `LD_PRELOAD` shim (`sniffer/cvsniff.c`) that logs every
  `read()`/`write()` the stock app makes on the reader's serial port. It captured
  the exact byte sequences the firmware sends, which no amount of guessing had
  produced.
- **Build tiny ARM helpers that load on the old glibc.** The shim and the
  key-server are both small C programs cross-compiled to use only base glibc
  symbols, so they run on the 2019 userland without fuss.
- **Test against the live hardware, and watch what actually happens.** Many
  conclusions only held up or fell apart when a card was physically tapped and the
  frames (or the screen, or a beep) were observed.

## The path

**Access.** SSH was open but root login was closed and no default password is
published. The way in is the PROXdongl3's EEPROM payload: a `[TestMode]` block that
runs an `autorun.sh` from a FAT USB stick instead of the stock UI. The script
installs an SSH key and disables the watchdog. Two false starts here were worth
remembering: the stick must be labelled `MP_SD`, and it must be a single MBR
partition — macOS's default GPT layout puts an empty EFI partition first, which the
device mounts and finds no script on.

**Recon and imaging.** With a shell, dumped both internal SDs and the SPI flash over
SSH with matching checksums, then mounted the images read-only in a container to
browse the real filesystem. Decompiled the device tree, pulled `dmesg`, the U-Boot
env, and the EEPROM contents. This produced the hardware map and the boot flow.

**Driving the subsystems.** Built `pm3.py` around the IPP framing (verified by
reproducing the wiki's known watchdog-off frame byte for byte) and worked through
the peripherals: PIC32 keys and sensors, the framebuffer (confirmed by drawing to
it and reading it back), the TLV320 speaker, the barcode scanner (read a test QR),
and the cVEND buzzer (full tone control — it played Song of Storms). Established
there is no touchscreen, and that the reader LED is firmware-controlled.

**The NFC problem.** Reading a card's UID turned out to be the hard part, and the
long middle of the project. The reader would detect a card sometimes and not others,
and the behavior seemed to depend on reboots, timing, and reader state in ways that
kept shifting. The debugging was not clean — several watchdog power-offs (from
stopping nx without disabling the watchdog fast enough), a reader wedged by a soft
reset, and a lot of hardware thrashing.

The `LD_PRELOAD` sniffer broke it open: it captured nx's exact reader init (the
`0xE4` enables, the `0xAA` SetTime, the `0xE8` certificate read) and corrected the
wiki's guesses. But replaying that init only read cards intermittently, because the
init itself is not what makes the reader scan.

**The key-server detour.** The reader scans continuously once nx is "in service,"
and nx is gated on fetching card keys from a local endpoint served by `abtproxy`,
which refuses to run offline because it can't reach Bytemark for an OAuth token.
Reversed that endpoint's response shape and built `keyserver/keyserve.c` to serve
the cached keys locally. It worked — nx went in service on our own server, no cloud.
But getting continuous reads out of it still depended on fragile boot timing, and
the whole nx path dragged the loud validator beep along with it.

**The actual answer.** Stepping back from nx entirely: the reader scans on its own,
continuously, right after its firmware boots — no keys, no init, no nx. The two
mistakes that had hidden this all along were re-initializing the reader (which stops
its autonomous scan) and letting it go idle (without a steady keepalive it sleeps).
A final test proved it: connect to the reader port at boot, send a status frame
once a second, just listen, and it streams a UID frame for every card, indefinitely
— 74 reads of 5 different cards over four minutes, no gap. That became the recipe in
`tap_demo.py`.

## Lessons

- **Disable the watchdog the instant you stop the firmware that was feeding it.** Do
  it in the same breath, not a step later. Most of the power-offs came from a gap
  between stopping nx and sending `watchdog 0`.
- **Sniff before you guess.** Days of protocol guessing were beaten by one
  `LD_PRELOAD` capture of what the firmware actually sends.
- **The simplest explanation was right, and we reached it last.** The reader just
  scans and pushes; everything clever we tried (re-init, arming, key-server) was
  working against that, not with it.
- **When every register you can read is identical but the behaviour differs, the
  variable is on a bus you aren't watching — that's a direction, not a dead end.** The
  speaker played nothing with nx stopped, so the first guess was "needs nx's init." Two
  stacked silent-failure traps were real but not the whole story: piping into `aplay`
  (stdin) is silent on this device where a *file* plays, and the routing needs `alsactl
  -f /etc/asound.state restore`. Fixing those got sound after nx had run, so we called
  it nx-free — premature: from a *genuinely* cold boot (nx never started) it was still
  silent. Chasing it, we eliminated everything readable from the SoC — codec registers
  (pages 0–1, incl. the DAC clock-source), the DAPM graph, GPIO, the whole clock tree
  (PLL, SSI1, the 24 MHz codec MCLK), AUDMUX, and SSI1 — all byte-identical between
  cold-silent and warm-audible, backed by an `LD_PRELOAD` trace of nx's ALSA calls vs a
  cold `aplay` (same `dmix`→`hw:0`, no mixer write, no `i²c`/`mem`/`gpio`), plus cold
  `aplay -D hw:0`, a stream-primed retry, and a 30 s sustained stream — all silent. That
  *total identity* was the clue we nearly walked past: if nothing you can read differs,
  the cause is on something you're not reading. The answer was in nx's own binary
  strings the whole time — `ActivateExternalSpeaker`, `NxPaCtrl` ("PA Amplifier Control
  Mode"), `NxPaMobil2PicDev` — an external power amp switched on over the **PIC32**
  (`ttymxc2`), downstream of the codec and off-SoC: the one bus none of the audio-side
  probes watched. Sniffing nx's first-init PIC32 traffic (the same `cvsniff` shim that
  cracked the reader — it already logs `ttymxc2`) caught a one-time `ValueWrite
  0x07E0=1` buried in the watchdog/sensor chatter; toggling it on the live unit gave a
  clean beep→silent→beep, and a verified-cold boot with just that write — no nx — plays.
  The fix is one frame (`pm3.py amp on`, and `play` sets `0x07E0=1` itself). Lessons:
  (1) distinguish "needs the firmware running now" from "needs a one-time setup step the
  firmware does," and re-test from a clean boot before calling a subsystem
  firmware-independent; (2) "every register I can read matches" points *at* the state
  you aren't instrumenting — widen the net (here, from the SoC audio buses to the PIC32
  serial) instead of digging deeper into the ones you already trust; (3) read the
  firmware's own strings early — the mechanism was named in plain text long before we
  found it the hard way.
- **Watch the real hardware.** The screen going from OUT OF SERVICE to SCAN/TAP, a
  beep on a tap, an LED blink — those physical signals repeatedly settled questions
  that the logs alone left ambiguous.
- **Keep the firmware's secrets out of the repo.** The backend config holds the
  agency's real credentials and card keys; they live only in the local storage dumps,
  which are git-ignored.
