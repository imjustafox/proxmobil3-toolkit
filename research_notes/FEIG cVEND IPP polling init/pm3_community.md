# PM3 to FEIG cVEND "IPP" serial protocol: community reverse-engineering

This covers what the hobbyist and RE community has published about the INIT
PROXmobil3 (PM3) to FEIG cVEND serial protocol ("IPP", `0xBC` frames), with an
emphasis on reader init, handshake, and getting the reader to scan cards and emit
UID events. The primary source is `wiki.pm3.dev/cvend`. Exact bytes and message
types are quoted with URLs.

## What wiki.pm3.dev documents

`wiki.pm3.dev/cvend` is the most detailed public source. It fully documents the
`0xBC` frame format and a large message-type table, and it describes an
enable-card flow: the host sends `0xE4` ProxCardFunction `00 07 01 01` to enable
DESFire at startup. It does not mention a certificate handshake, an INITIALIZED
state, or any requirement to initialize before card reading. The only documented
prerequisite to card reading is enabling the card type with `0xE4`.

The "two 0xBC messages" are explicitly the only two message types the host sends
after initialization: DESFire GetVersion (`0x60`) and SelectApplication
(`5A2BC3F9`). These are application-level reads, not a generic init or handshake.

Serial link and frame format, from the wiki:

- Link: `/dev/ttymxc3`, 115200 8N1 on the PM3's Linux.
- Byte 0 is always `0xBC` (frame magic).
- Byte 1 is `seq`, incrementing from 1 and skipping 0 on rollover.
- Byte 2 is `replyTo`, the `seq` being answered, or 0 for unsolicited.
- Byte 3 is `msgType`.
- Bytes 4 and 5 are `msgLen`, the payload length, big-endian; sample `00 68`.
- Byte 6 is `hdrCRC`, CRC-8 Dallas/Maxim over the previous 6 bytes.
- The payload (`msgData`) follows.
- For `msgType >= 0x80` only, a trailing 4-byte `msgCRC` follows. The wiki
  describes it as little-endian bit-inverted CRC-32/JAMCRC over the payload; the
  author says it does not match a recognized polynomial. The length field excludes
  these bytes.

Message-type table, with direction as host-to-reader or reader-to-host, names as
the wiki gives them:

- `0x02` to `0x03`: Version / VersionReply (length-prefixed strings: device ID,
  firmware, cwd)
- `0x04` to `0x05`: Status / StatusReply (suggested to keep the reader awake)
- `0x07`: Heartbeat (periodic)
- `0x0F`: Startup, "sent by reader after startup, approx 1 minute after power on,
  e.g. `\x00`"
- `0x10` to `0x11`: Reset / ResetReply (first byte: 2 restart app, 3 reboot,
  4 poweroff, 33-36 reset SAM 1-4)
- `0x20`: LEDs (u32 bitmap; for example `00 00 00 40`, `00 00 00 80`)
- `0x22`: Buzzer (u16 frequency, u16 duration; for example `06 00 01 00`)
- `0x32`: CardRelease
- `0x46`: AbortCardHandling
- `0x96`-`0xA5`: file ops (PutFile/GetFile/DeleteFile/FileInfo/FileList plus
  replies)
- `0xAA` to `0xAB`: SetTime / SetTimeReply
- `0xAC`-`0xAF`: ITSO (ITSOData/ITSOCtrl plus replies)
- `0xB1`: ISORead ("card UID at offset 2")
- `0xB3`: ISOCardReleased
- `0xB4` to `0xB5`: APDUProx / APDUProxReply
- `0xB6` to `0xB7`: SAMCtrl / SAMCtrlReply
- `0xB9`: DESFireRead (DESFire card presented)
- `0xBA`: unknown
- `0xBB`: DESFireCardRemoved
- `0xBC` to `0xBD`: DESFireCommand / DESFireCommandReply
- `0xBE`: UnhandledCard ("card type not enabled", with UID and historical bytes)
- `0xCE`: unknown
- `0xD0` to `0xD1`: EMV / EMVStatus
- `0xD4` to `0xD5`: UltralightCommand / UltralightReply
- `0xE4` to `0xE5`: ProxCardFunction / ProxCardFunctionReply
- `0xE6`: unknown
- `0xE8` to `0xE9`: SecurityServices / SecurityServicesReply
- `0xEA`: unknown
- `0xED`: Log (level byte 1 INFO, 2 WARN, 3 ERROR, then a null-terminated message)

`0xE4` ProxCardFunction (enable card type):

- Payload is a 2-byte function ID, then `0x01`, then `0x00` (disable) or `0x01`
  (enable).
- Function IDs: 4 VdvKa, 5 MifareClassic, 6 Iso, 7 DESFire, 8 Girogo, 9 ITSO,
  10 UltralightC.
- The PM3 host sends `00 07 01 01` at startup "to enable DESFire reading at
  startup."
- The `0xE5` reply payload is 4 bytes: `00`, function number, `00`, `00`.

`0xD5` UltralightReply, card in/out plus UID:

- `replyTo` is 0 for unsolicited events.
- Byte 0 is `0x00` for card entered, `0x01` for card left.
- Byte 1 is `0x00`.
- Bytes 2 to 8 are the 7-byte UID (for example `04 21 B9 01 10 04 03` for an
  NTAG 215).
- The table names `0x05`/`0xD5` "UltralightReply"; the prose attaches the
  card-entered/left and UID semantics to it.

The two `0xBC` messages, which the source task called "init messages," are quoted
verbatim: "Host only sends two types of messages after initialization - both of
type 0xBC. One is length 1 and the body is always 0x60 (+ negated CRC 2A714F60),
the other is of length 4 and the body is always 5A2BC3F9 (+ negated-CRC
11A8A56A)." Full frames are `BC2200BC000158602A714F60` (body `0x60` is DESFire
GetVersion, hdrCRC `58`, trailing CRC `2A714F60`) and
`BC2300BC0004AA5A2BC3F911A8A56A` (body `5A2BC3F9` is DESFire SelectApplication for
app `5A2BC3F9`, hdrCRC `AA`, trailing CRC `11A8A56A`). The page notes that the
DESFire application ID varies by issuer.

Sample reader flow, verbatim steps:

1. "Host enables desired card type with ProxCardFunction."
2. "Reader acknowledges with ProxCardFunctionReply."
3. "Reader waits for card, seems like it eventually goes to sleep without any
   stimuli. Might have to keep it awake by sending packets occasionally (e.g.
   Status)."

Then, for DESFire: the reader sends `0xB9` DESFireRead. If the type is disabled it
sends `0xBE`. The host sends DESFire commands as `0xBC`, and the reader replies
`0xBD`.

On the certificate handshake and INITIALIZED state: the wiki describes no
certificate handshake, no INITIALIZED state, and no requirement to initialize
before card reading. `0xE8` SecurityServices lists key/cert subcommands
(ImportX509Cert, GenerateKSKPair, and so on) but gives no flow. A boot-up
logic-analyzer capture `cvend-bootup.sal` is linked, but the boot sequence is not
transcribed into text.

Inference: the wiki frames the two `0xBC` messages as DESFire application reads
(GetVersion and SelectApplication of the ORCA/issuer app), not as a reader init or
handshake. The "init messages" in the task are really the steady-state card-read
commands the stock firmware emits once a DESFire card is present. They presuppose
that the reader is already enabled and a card is detected. Per the wiki's own flow,
the only documented step needed to make the reader scan and report a card (and emit
a UID through `0xD5`/`0xB1`/`0xBE`) is sending `0xE4` ProxCardFunction to enable a
card type. Keeping it awake may require periodic `0x04` Status. The wiki gives no
evidence that a certificate handshake gates basic UID reporting.

Gaps: the wiki does not transcribe the `cvend-bootup.sal` capture, so the exact
byte-by-byte power-on handshake (Version exchange, any security or `0xE8` traffic
before enable) is not published in text. The `0x60`/`5A2BC3F9` msgCRC algorithm is
also not fully pinned down; the author says the CRC-32 variant does not match a
recognized polynomial. Independently generating valid `0xBC` trailing CRCs may not
be reproducible from the page alone.

## Community repos and pages

Two repos touch the cVEND bus. `checkraisefold/rust-feig-app` is a passive parser
and sniffer that only reads, never writes. `Jarynnnn/PROXMobil3-HOP` is an
idle-screen emulator that relies on nx to initialize the hardware and passively
sniffs taps. No published repo sends its own init or enable-polling bytes to the
cVEND and gets a UID standalone. The other repos (proxmobil-stuff, board,
proxbeacon) are unrelated to the serial protocol.

### checkraisefold/rust-feig-app

- Listed on the wiki projects page as the project doing "PM3 to cVEND protocol
  analysis" ([wiki.pm3.dev/projects](https://wiki.pm3.dev/projects)).
- Public Rust repo, three commits on `main`, no README. `src/` has `main.rs` and
  `ipp.rs`
  ([github.com/checkraisefold/rust-feig-app](https://github.com/checkraisefold/rust-feig-app),
  [api.github.com contents/src](https://api.github.com/repos/checkraisefold/rust-feig-app/contents/src)).
- `main.rs` opens `serialport::new("/dev/ttyS3", 115_200)` with
  `.timeout(Duration::MAX)`, allocates a receive buffer of
  `vec![0u8; 65536 + 4 + 8]`, loops on `port.read`, parses each frame as
  `IppMessage` (binrw), and prints it. It never writes any bytes to the port: no
  init, no ProxCardFunction, no frame building, no UID extraction
  ([raw main.rs](https://raw.githubusercontent.com/checkraisefold/rust-feig-app/main/src/main.rs)).
- `ipp.rs` defines `IppMessage` with `#[brw(big, magic = 0xbcu8)]`, then fields
  `sequence_number: u8`, `unk: u8` (the replyTo position, role undocumented),
  `message_type: u8`, `data_length: u16`, `crc_header: u8`, `data: Message`, and
  `data_crc: u32`, present only when `(message_type >> 7) > 0`. The `Message` enum
  has Version=0x2, VersionReply=0x3, Status=0x4, StatusReply=0x5, Heartbeat=0x7,
  Startup=0xF, PICCRead=0xBE (comment "// >=0x80 has crc"),
  EMVTransactionSuccessUnk=0xD1, and an `Unknown` catch-all. No UID parsing, no
  enable/init constants
  ([raw ipp.rs](https://raw.githubusercontent.com/checkraisefold/rust-feig-app/main/src/ipp.rs)).

### Jarynnnn/PROXMobil3-HOP

- The README describes a standby/idle screen emulator for PROXMobil3 with HOP-style
  animations and feedback on barcode or NFC events. It "does not connect to trimet,
  hop, or any real fare systems." The repo "only exists to host the installer
  script source," with assets shipped in a GitHub release
  ([github.com/Jarynnnn/PROXMobil3-HOP](https://github.com/Jarynnnn/PROXMobil3-HOP)).
- `autorun.sh` details
  ([raw autorun.sh](https://raw.githubusercontent.com/Jarynnnn/PROXMobil3-HOP/main/autorun.sh)):
  - NFC device is `NFC_DEV="/dev/ttymxc3"` at 115200; barcode is `/dev/ttyS5`,
    symlinked to `/dev/ttyUSB0` if missing.
  - It does not write to the serial ports. It configures them with `stty` (raw,
    8N1, no flow control or echo) and reads with `dd`.
  - `nfc_watch` reads up to 256 bytes, hexdumps them, and treats the substring
    `"00d1"` as a tap (passive detection). Note that `00 d1` is a frame with
    msgType `0xD1` (EMVStatus), so it keys off the EMV-status reply, not a raw UID.
  - The only hardware-init step is `prime_nx`: `systemctl start --no-block nx`,
    wait up to 10 seconds for `NxProx` in `pidof`, sleep 20 seconds "to init devices
    (create ttyS5 link, etc)", `systemctl stop nx`, then `NxExe watchdog 0`. All
    device and reader setup happens inside nx. The script just starts nx, waits,
    and stops it.

### Other repos and pages

From [wiki.pm3.dev/projects](https://wiki.pm3.dev/projects):

- `git.uninsane.org/shelvacu/proxmobil-stuff`: "miscellaneous collection, currently
  mainly DOOM builds for static arm32" (pulls a fork of fbdoom). Not cVEND-related.
- `github.com/haylinmoore/board`: a transit arrival board using the OneBusAway
  API. App-level only.
- `github.com/mikekutzma/proxbeacon`: an MTA countdown clock. App-level only.
- `git.doof.net/proxdongl3`: a power-adapter PCB (rear D-Sub to 9-33 V passive
  PoE, USB, I2C EEPROM, power button) plus the EEPROM payload `flash.py`.
  Hardware and power only, no protocol. Also referenced from
  [kevin.wallace.seattle.wa.us/pm3](https://kevin.wallace.seattle.wa.us/pm3/).

Inference: every known card-touching project either passively sniffs the `0xBC`
bus while the stock nx firmware drives the reader (rust-feig-app, HOP's nfc_watch)
or boots nx for about 20 seconds specifically to initialize the NFC and barcode
hardware and create the serial device links, then kills nx (HOP). None performs its
own cVEND init or enable handshake.

`/dev/ttyS3` (rust-feig-app) and `/dev/ttymxc3` (HOP and the wiki) are the same
cVEND UART under different names or device links. The HOP note that nx creates the
required serial device links explains why a standalone program may not find the
port until nx has run once.

Gaps: no public repo demonstrates opening the cVEND UART cold, without nx having
initialized it, and driving it to a UID. Whether `0xE4` plus a `0x04` keepalive
alone suffices from a clean boot is untested in any published code.
`proxmobil-stuff` was not read file by file beyond the wiki's description; if any
serial code exists, it is not advertised.

## Press and community coverage

There is very little published community narrative beyond the wiki and Kevin
Wallace's project page. The wiki projects page links three Reddit posts
(r/IThinkYouShouldLeave, r/soundtransit, r/Seattle) that are transit-themed PM3
card and emulator demos, not protocol write-ups. No Hackaday or Hackster article,
public Discord or mailing-list thread, or protocol blog was found in searches.

Findings:

- The wiki projects page links the three Reddit posts as "transit-themed PM3 card
  projects." Their content is inferable only from the URLs: demos, not protocol
  docs ([wiki.pm3.dev/projects](https://wiki.pm3.dev/projects)).
- `kevin.wallace.seattle.wa.us/pm3/` is a personal RE project page. Its stated goal
  is to reverse-engineer INIT PROXmobil3 variants "to make them suitable for
  non-transit uses." A key hardware finding: "Dongles dated 2025-12-30 or later
  contain an EEPROM chip with a payload that enables code execution off of a USB
  storage device." Boot sequence: supply CL30 continuously, then momentarily
  supply CL15, or press the internal power button. It describes the FEIG cVEND plug
  NFC module as connecting "via UART" but gives no serial protocol bytes. No
  Reddit, Discord, or blog links on the page, only a KUT news article about
  CapMetro retiring the hardware and the RIPTA system design PDF
  ([kevin.wallace.seattle.wa.us/pm3](https://kevin.wallace.seattle.wa.us/pm3/)).
- Web searches for Hackaday, Hackster, Discord, Reddit, or mailing-list coverage of
  PROXmobil3/cVEND RE returned only FEIG product datasheets, INIT marketing and
  product sheets, an ITSO certificate (PROXmobil3 RSP Rail Validator v20.36, ITSO
  TS 1000 v2.1.4), the 2018 RIPTA system design document, and generic Proxmark3 or
  vending-RE articles. Nothing with protocol details.

Inference: the reverse-engineering community for this device is small and
centralized on `wiki.pm3.dev` and Kevin Wallace's page. There is no mainstream
maker-press coverage. Discussion likely happens in private or invite channels that
are not indexed by search. The wiki has an account-request email but no public
Discord link was surfaced.

Gaps: no public Discord invite, mailing list, or forum thread was located. If one
exists, it is not discoverable by web search and may be gated behind the wiki
account-request process. The three linked Reddit posts' text was not fetched; they
appear to be demo/show-and-tell, not protocol sources.

## Handshake, bypass, and standalone UID polling

No public source describes a cVEND certificate handshake, a bypass, or a confirmed
standalone raw-UID polling sequence. The wiki documents the enable-and-read flow
(`0xE4` ProxCardFunction plus card events `0xD5`/`0xB1`/`0xBE`) with no certificate
step, but no one has published working code that drives the reader to a UID without
nx having initialized it first. This is the central unanswered question in the
community material.

Findings:

- `wiki.pm3.dev/cvend` documents the full enable/read flow with no certificate
  handshake and no INITIALIZED-state requirement. The only `0xE8`
  SecurityServices entry lists cert subcommands (ImportX509Cert,
  GenerateKSKPair) with no flow
  ([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)).
- `wiki.pm3.dev/nx` describes nx as the stock UI that interacts with
  cvend/barcode/pic32/framebuffer/alsa/init-abtproxy. It can be stopped with
  `systemctl stop nx` (also run `NxExe watchdog 0` to stop the PIC32 powering off
  after 60 seconds), is configured through `/init/efad/pgm/`, and has a CLI
  (`./NxProx`). It gives no cVEND init, handshake, cert, or key details
  ([wiki.pm3.dev/nx](https://wiki.pm3.dev/nx)).
- In practice the one working deployment, the HOP emulator, sidesteps the init
  problem by booting nx for about 20 seconds to initialize the NFC hardware and
  create serial links, then killing nx and passively reading `/dev/ttymxc3`. It
  lets the stock cert-bearing firmware do whatever init is needed rather than
  reproducing it
  ([raw autorun.sh](https://raw.githubusercontent.com/Jarynnnn/PROXMobil3-HOP/main/autorun.sh)).

Inference: taken together, the published record suggests UID and card events
(`0xD5` card in/out with a 7-byte UID, `0xB1` ISORead UID, `0xBE` UnhandledCard
UID) are emitted by the reader for enabled card types without application keys.
Raw UID does not require ORCA or issuer DESFire keys; those are only needed to read
the DESFire application, the `0x60`/`5A2BC3F9` command flow. But because no one has
published a from-cold-boot standalone enable sequence, whether a cert or `0xE8`
exchange is silently required before `0xE4` takes effect remains unconfirmed.

Gaps: whether the cVEND performs a mandatory certificate or security handshake at
power-on, visible in the un-transcribed `cvend-bootup.sal` capture, before it will
honor `0xE4` or report UIDs, is not documented in text anywhere found. This is the
key open question. No published, reproducible "open the port cold, send these exact
bytes, get a UID without nx" recipe exists. Explicitly, no working standalone card
read or enable-polling sequence has been published by the community. All known
successes rely on nx to initialize the reader.
