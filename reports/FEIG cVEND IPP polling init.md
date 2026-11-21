# A cVEND reader handshake captured from nx

This report started as an attempt to find the sequence that "arms" a cVEND reader.
The live-hardware work changed that conclusion. The reader scans ISO14443 cards on
its own once its firmware boots. It needs no enable, no `0xAA`, and no certificate
read to produce UIDs. Raw cards arrive as `0xBE` UnhandledCard frames.

What follows is still useful as a record of what the stock `nx` app does on the
serial link, and why the sequence looked like arming at first. The authoritative
current account is `INTERFACE.md` (NFC and Sleep sections) and `PROCESS.md`.

In short: nx sends a version read, enables card types, sends SetTime, and
reads the device certificate. That switches the reader from its own autonomous base
scan to nx's handled-card mode, where enabled types report `0xD5` card in/out with
a UID. That is a feature, not a prerequisite for UIDs. `0xAA 6afec201` is SetTime,
confirmed by the firmware handler `IppHandlerSetTime`, not an arm command. And the
old reset problem is solved: `0x10` subcode `02` restarts the application cleanly
to a fresh `0x0F` Startup in about 6 seconds with the serial link preserved. A bare
`0x10` is what wedges it.

## Frame format

Everything rides on one frame format, confirmed by the community wiki and by the
firmware sniff: `BC seq replyTo type lenHi lenLo crc8 [payload] [crc32]`.

Byte 0 is always the magic `0xBC`. Byte 1 is a sequence counter that increments
from 1 and skips 0 on rollover. Byte 2 is `replyTo`, the sequence number being
answered, or `0x00` for unsolicited reader events. Byte 3 is the message type.
Bytes 4 and 5 are the big-endian payload length. Byte 6 is a CRC-8 (Dallas/Maxim)
over the preceding six header bytes. The payload follows. Only for message types
at or above `0x80` does a trailing 4-byte CRC follow the payload
([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)). The link is `/dev/ttymxc3`
(also aliased `/dev/ttyS3`), 115200 8N1.

## What nx sends

Captured by LD_PRELOAD-sniffing the stock `nx` firmware's serial writes:

1. `0x02` Version request. The host reads device ID, firmware, and working
   directory. The reader answers with `0x03` VersionReply. This matches the public
   message table ([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)).
2. `0xE4` Enable card function, one frame per card type. Payload is
   `00 <id> 01 01`, and the reader acknowledges each with a `0xE5`
   ProxCardFunctionReply carrying status `0000`. The function IDs are `4` VdvKa,
   `5` MifareClassic, `6` ISO, `7` DESFire, `8` Girogo, `9` ITSO, `10`
   UltralightC. The wiki documents this opcode and ID table but shows the stock PM3
   firmware enabling only DESFire (`00 07 01 01`) at startup. The sniff shows the
   real firmware enabling the full set it cares about, one `0xE4` per type.
3. `0xAA` payload `6afec201`, with the reader replying `0xAB 0000`. Earlier work
   read this as a commit/arm command. It is SetTime, and the payload is a
   timestamp. The `IppHandlerSetTime` registration in the reader firmware confirms
   it. The exchange is incidental to scanning. The wiki's message table already
   called `0xAA`/`0xAB` SetTime/SetTimeReply; that naming was right.
4. `0xE8` payload `04fe0a0000`, with the reader returning `0xE9` carrying its
   X.509 device certificate. This is the host-side "device certificates valid
   until..." read that precedes nx's CONNECTED to INITIALIZED transition. It is a
   read for host validation, not a challenge-response. The host fetches the cert
   and inspects its expiry, and the reader does not demand anything of the host in
   return. The wiki lists `0xE8` SecurityServices with cert subcommands
   (ImportX509Cert, GenerateKSKPair, and so on) but publishes no flow. The sniff
   supplies the actual payload and its role.

Timing matters for the enables. The reader only begins polling after it completes
its own power-on boot, which it announces with a `0x0F` Startup frame up to about
a minute after power-up. The wiki notes the same frame arrives "approx 1 minute
after power on" ([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)). Enables sent
before the `0x0F` are silently dropped with no acknowledgement. So the host logic
for nx-style handling is: open the UART, wait for the unsolicited `0x0F`, then run
the sequence. This gating applies to the enable path. It does not apply to raw UID
capture, which works from the reader's autonomous scan.

One correction to the public record: the wiki frames "the two 0xBC messages" (body
`0x60` for DESFire GetVersion, and body `5A2BC3F9` for DESFire SelectApplication)
as what the host sends "after initialization"
([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)). Those are application-level
DESFire reads against a present card, not the init/enable handshake. They
presuppose an already-armed reader and a tapped DESFire card, and they are
irrelevant to obtaining a raw UID.

## cVEND inherits the OBID RF engine but hides its payment skin

FEIG runs two parallel protocol worlds. The OBID / ID ISC RFID readers speak a
fully public "FEIG Reader Protocol" in which a single control byte names each
command: `0x52` Baud Rate Detection, `0x63` CPU Reset, `0x65` Get Software Info,
`0x69` RF Reset, `0x80`-`0x83` the configuration block, and `0x0B 0x01` (or the
older per-standard `0xB0 0x01`) Inventory, which runs ISO anticollision and
returns the transponder UID
([Amarok79/InlayTester.Drivers.FeigReader](https://github.com/Amarok79/InlayTester.Drivers.FeigReader);
[FEIG i-scan ID ISC.PR101 user manual](https://manualmachine.com/feigelectronic/obidiscanidiscmr101/23026941-user-manual)).
The public serial library is `feisc` (`FEISC_RF_RESET = 0x69`, `FEISC_ISO_COMMAND
= 0xB0`), with FEDM as the C++ layer above it
([feisc.h, ROS rfid_drivers doxygen](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h.html)).

The cVEND payment terminals are a separate secure line. FEIG's cVEND user manual
says the reader "offers an easy to use secure protocol" and "can be used in
payment mode as well as in transparent card reader mode," with support gated
behind `cvend-support@feig.de`
([Feig cVEND User Manual](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual)).
Every cVEND datasheet says "Development devices, tools and SDK available on
request"
([cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf);
[cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)).
The INIT PROXmobil3 validator is built on this hardware. An ITSO certificate lists
"PROXmobil3 RSP Rail Validator, version 20.36 (Feig 04.19)"
([ITSO certificate c00202](https://itso.org.uk/certificate/10292.1/c00202-init-proxmobil3-rsp-rail-validator)).

That is why IPP `0xBC` does not look like the OBID `0x0B 0x01` inventory call.
cVEND wraps the same RF front end in a proprietary secure application protocol.
Instead of the host issuing an inventory command and parsing a tag table, the host
enables card types and the reader pushes card events asynchronously (`0xD5`,
`0xB1`, `0xBE`). The `feclr`-style "FEIG Contactless Reader" library that the
PROXmobil3's `RFIDReaderMultiApp.cpp` component consumes is the cVEND counterpart
to the public `feisc`, and it is NDA-only. Exhaustive code search found zero public
references to any `feclr_*` symbol or to `RFIDReaderMultiApp` (GitHub code search,
2026-11-19, no public URL).

The secrecy is a payment-certification posture. cVEND terminals are PCI PTS
certified, run a "cVEND specific secure Linux operating system," and are
provisioned at FEIG's PCI P2PE-certified Key Injection Facility
([cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf);
[FEIG PayServ RKI](https://www.feig.de/en/payserv-solutionsuite-rki/)). The
protocol is withheld to protect the payment kernel, not the UID path.

One protocol detail the community could not crack is now confirmed: the trailing
4-byte CRC on type-`0x80`-and-above frames is CRC-32/JAMCRC, the standard CRC-32
bit-inverted, little-endian. The wiki author wrote that this CRC "doesn't match any
polynomial they recognize" ([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)).
The sniff identifies it, so a builder can generate valid `0xE4`/`0xAA`/`0xE8`
frames (all below `0x80`, so header CRC-8 only) and validate or synthesize the
`0x80`-and-above application frames.

## The certificate step reads an identity, it does not negotiate one

The `0xE8 04fe0a0000` to `0xE9` exchange returns the reader's actual X.509 device
certificate: issued by the FEIG Production Terminal CA, device ID 17EE5468, valid
2020-05-04 to 2030-05-02. This is the concrete object behind the nx log line
"device certificates valid until <date>" between CONNECTED and INITIALIZED. It is a
one-way read for host-side validation, not a mutual auth or TLS-like handshake,
and not a gate the host must satisfy with its own credential. The host asks the
reader for its certificate, reads the `notAfter` field, and proceeds.

This resolves a question the web research could only hypothesize. FEIG's platform
carries "manufacturer-issued X.509 device certificates used for key encryption and
device authentication"
([SFEY TPS Device API, Key Management](https://sfeydocs.sfey.com/docs/doc-api-spec/API%20v3.0/TPS%20Device%20API/Terminal%20Registration/03%20Key%20Management%20Automatic)),
and the cert-expiry-then-INITIALIZED boot pattern looked like it could be a
cryptographic attestation. It is not, at least not on the serial link and not as a
prerequisite for reading UIDs. The expensive, PCI-driven cryptography (remote key
injection, EMV secure messaging) lives elsewhere. The RKI channel is a separate
secure connection to FEIG's infrastructure
([FEIG PayServ RKI](https://www.feig.de/en/payserv-solutionsuite-rki/)), and
fare-data decryption needs the application SAM keys. The startup cert read is cheap
and informational. A builder who wants only UIDs can skip step 4 entirely.

## No keys are needed

The standards layer predicts this, and the empirical result confirms it. In
ISO/IEC 14443-3, the UID is collected during the REQA/anticollision/SELECT sequence
before any authentication. MIFARE, DESFire, and Calypso key login only happens
after selection ([ISO/IEC 14443-3:2018 TOC](https://committee.iso.org/standard/73598.html)).
Once a cVEND is scanning, emitting a UID requires no application, fare, or SAM
keys.

The proof: with no nx running, and without sending the init sequence, a real
card's UID `04:50:67:0A:81:22:90` was read from a `0xBE` UnhandledCard frame. The
`0xBE` frame is what the reader emits for a card whose type was not enabled. It
still reports the UID; the wiki describes `0xBE` UnhandledCard as carrying "UID +
historical bytes" for a "card type not enabled"
([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)). For enabled types, the reader
instead pushes a `0xD5` frame: byte 0 is `0x00` (card entered) or `0x01` (card
left), byte 1 is `0x00`, and bytes 2 to 8 are the 7-byte UID. Either path yields a
raw UID with zero key material.

Every prior card-touching project worked around the init problem rather than
solving it. `checkraisefold/rust-feig-app` is a passive parser that opens the port
and prints frames but never writes a byte
([rust-feig-app main.rs](https://raw.githubusercontent.com/checkraisefold/rust-feig-app/main/src/main.rs)).
`Jarynnnn/PROXMobil3-HOP` boots the stock nx for about 20 seconds to let it
initialize the NFC hardware and create the serial links, then kills nx and
passively sniffs taps
([PROXMobil3-HOP autorun.sh](https://raw.githubusercontent.com/Jarynnnn/PROXMobil3-HOP/main/autorun.sh)).
The community noted that no published, reproducible "open the port cold, send
these exact bytes, get a UID without nx" recipe existed
([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)). It exists now, and it is
shorter than expected: do not initialize anything.

Minimal builder recipe for a standalone UID reader: open `/dev/ttymxc3` at 115200
8N1 after the unit boots. Do not send enables or init. Send `0x04` Status about
once a second as a keepalive. Consume unsolicited `0xBE` frames for cards of
disabled types; the UID starts at the first `0x04` byte in the payload. If you
enable card types, consume `0xD5` (7-byte UID at offset 2) instead. Build every
frame with the CRC-8 Dallas/Maxim header checksum. For any type-`0x80`-and-above
frame you receive or send, validate or append the CRC-32/JAMCRC trailer.

## Open problems

Two operational problems remain. First, re-arming an already-running reader with
the nx sequence is not reliable. The sequence assumes a fresh cold boot that
produces the `0x0F` Startup frame. Sending enables before that is silently
dropped, and re-arming polling on a reader that is already up does not
reproducibly work. The wiki observed the same sleep behavior and suggested
periodic `0x04` Status keepalives. That helps the base scan but does not rebuild
the nx handled state.

Second, host-driven reads through `0xD4` are blocked by the reader's own handler
behavior, as described in `docs/wiki-cross-check.md`. Use the internal handlers
instead: enable the type, let the reader transceive, and read the events.

The practical consequence for a standalone reader is simpler than the old
power-cycle-to-arm advice. For raw UIDs, start the listen loop near boot and keep
the `0x04` keepalive going. If the reader goes idle, `0x10 02` restarts it. For
nx-style handled reads, wait for `0x0F` and then run the enable sequence.

Worth doing next: sweep the remaining `0x10` Reset subcodes (avoid `4`, poweroff),
characterize the exact idle-sleep timeout, and transcribe the linked
`cvend-bootup.sal` logic-analyzer capture
([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)) against the now-known frame
grammar. That would show whether the stock firmware does anything between `0x0F`
and `0x02` that the sniff did not surface.

## Sources

- INIT PROXmobil3 to cVEND "IPP" `0xBC` serial protocol, frame format, message-type
  table, `0xE4` enable flow, `0xD5`/`0xB1`/`0xBE` card events, `0x0F` Startup,
  `0x10` Reset subcodes, CRC description, sample flow:
  [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)
- PM3 community projects, NX stock firmware, passive-only repos:
  [wiki.pm3.dev/projects](https://wiki.pm3.dev/projects);
  [wiki.pm3.dev/nx](https://wiki.pm3.dev/nx);
  [checkraisefold/rust-feig-app main.rs](https://raw.githubusercontent.com/checkraisefold/rust-feig-app/main/src/main.rs);
  [Jarynnnn/PROXMobil3-HOP autorun.sh](https://raw.githubusercontent.com/Jarynnnn/PROXMobil3-HOP/main/autorun.sh);
  [kevin.wallace.seattle.wa.us/pm3](https://kevin.wallace.seattle.wa.us/pm3/)
- FEIG OBID / ID ISC public reader protocol, command bytes, `feisc`/FEDM libraries:
  [Amarok79/InlayTester.Drivers.FeigReader](https://github.com/Amarok79/InlayTester.Drivers.FeigReader);
  [FEIG i-scan ID ISC.PR101 user manual](https://manualmachine.com/feigelectronic/obidiscanidiscmr101/23026941-user-manual);
  [feisc.h, ROS rfid_drivers doxygen](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h.html);
  [FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)
- cVEND secure-payment line, transparent mode, X.509 device certs, PCI/P2PE key
  injection:
  [Feig cVEND User Manual](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual);
  [cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf);
  [cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf);
  [FEIG PayServ.SolutionSuite RKI](https://www.feig.de/en/payserv-solutionsuite-rki/);
  [SFEY TPS Device API, Key Management](https://sfeydocs.sfey.com/docs/doc-api-spec/API%20v3.0/TPS%20Device%20API/Terminal%20Registration/03%20Key%20Management%20Automatic)
- ISO14443-3 key-free UID and anticollision:
  [ISO/IEC 14443-3:2018 TOC](https://committee.iso.org/standard/73598.html)
- PROXmobil3 as FEIG 04.19 firmware:
  [ITSO certificate c00202, PROXmobil3 RSP Rail Validator](https://itso.org.uk/certificate/10292.1/c00202-init-proxmobil3-rsp-rail-validator)
- Empirical core from this session: LD_PRELOAD sniff of stock nx firmware serial
  writes; `0xAA 6afec201` to `0xAB 0000` SetTime; `0xE8 04fe0a0000` to `0xE9`
  device-cert read (FEIG Production Terminal CA, device ID 17EE5468, valid
  2020-05-04 to 2030-05-02); CRC-32/JAMCRC trailer identification; `0x0F`-gated
  enable timing; and standalone UID `04:50:67:0A:81:22:90` recovered from a `0xBE`
  frame with no nx running. Not published anywhere; supersedes and confirms the
  web research above.
