# Keeping a cVEND reader awake and scanning

The FEIG cVEND reader inside an INIT PROXmobil3 falls into a 3-second heartbeat
when it goes idle. That matches FEIG's documented RF-field auto-timeout, plus a
sub-1 mA hardware standby state that the datasheet says is left only by digital
input or timer. The status frames you send may not reach it. FEIG's ID ISC reader
manuals describe an automatic "RF-Field minimum/maximum on-time" plus a "Power
on-time" in configuration block CFG21, after which "the complete Reader will turn
off automatically"
([FEIG ID ISC.PRH200 manual, p.22](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)).
There is no host sleep or wake opcode in the documented FEIG command set, so the
fix is to keep the idle timer from expiring.

Two parts have to be kept distinct: a keepalive that keeps the reader awake, and a
graded reset ladder that escalates from a benign probe to a power cycle. Every
documented timer, mode, and reset opcode above belongs to FEIG's public OBID/ID ISC
protocol (STX `0x02` framing). The cVEND speaks a separate, closed `0xBC` IPP
protocol. The OBID mechanisms tell you what FEIG hardware does, not the exact IPP
bytes to send.

Two conclusions here were improved by live-hardware work. First, a software
recovery exists: `0x10` subcode `02` (restart application) wakes a slept or wedged
reader to a fresh `0x0F` Startup in about 6 seconds with the serial link preserved
(`./pm3.py cvend-restart`). A bare `0x10` with no subcode is what wedges it. Second,
for plain UID capture the re-arm part is moot. The keepalive still matters, but the
reader scans ISO14443 autonomously after boot with no enable or arm at all (`0xBE`
frames), so there is nothing to re-arm. The public-documentation map below still
stands. The current operational account is `INTERFACE.md` (NFC and Sleep sections).

## Why the reader goes quiet

The symptom is a reader that drops to a bare periodic heartbeat, stops scanning,
and ignores status frames until it is power-cycled. Two documented FEIG mechanisms
stack up. First, FEIG ID ISC readers auto-switch the antenna RF field off after a
configured idle on-time. The "RF-Field minimum on-time" and "maximum on-time"
parameters in CFG21 cut antenna power once no transponder has been seen. After a
further "Power on-time" expires, "the complete Reader will turn off automatically"
([FEIG ID ISC.PRH200 manual p.22](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)).

Second, there is no escape hatch in software. A scan of the ID ISC.LR1002 command
list (`0x52`, `0x63`, `0x64`, `0x66`, `0x69`, `0x6A`, `0x6E`, `0x72`, `0x74`,
`0x80`-`0x83`, and so on) contains no sleep, standby, power-down, or wake opcode
([FEIG ID ISC.LR1002 System Manual](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
Entering sleep is a timer firing. Exiting it is configuration-driven or
stimulus-driven, not a command.

The cVEND hardware adds a real low-power layer that the OBID readers lack. FEIG's
cVEND datasheet rates the module at under 1 mA in standby, with wake-up by digital
input or timer
([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
That explains why status frames do not revive it. If the reader has dropped into
hardware standby, the intended exits are a hardware digital-input assertion or a
timer, and an in-band serial frame may never reach the sleeping RF/CPU path.

This also reframes the 3-second heartbeat. In FEIG's Notification operating mode
the reader pushes buffered data and emits keepalive messages that are never
acknowledged
([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
The cVEND's `0x07` heartbeat is consistent with that pattern.

## Prevention: a keepalive shorter than the idle window

The strategy is to keep the reader stimulated so the CFG21 idle timer never
elapses. On documented OBID hardware, drive the reader in Host Mode and issue a
lightweight command on a cadence shorter than the RF-field minimum on-time:
Inventory `[0x01]`, Get Reader Info `[0x66]`, or Reader Diagnostic `[0x6E]`. Treat
a missed response as "wedged"
([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).

On the cVEND's closed IPP link the analog is to send `0x04` Status frames on a
fixed cadence. The wiki suggests `0x04` Status "to keep the reader awake"
([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)). Because status alone has been
insufficient in practice, earlier work also re-issued the nx enable sequence. That
part did not reproduce reliably. Re-arming a running reader with `0xE4` and
`0xAA` worked only sometimes. Cold-starting the reader was deterministic;
re-arming one that had already slept was not. The `0x10 02` restart is the
reliable software recovery now.

A documented lever exists, but we cannot confirm it is reachable over IPP. If the
cVEND exposes CFG21's RF-field on-time timers through its file and config
operations (the wiki lists `0x96`-`0xA5` PutFile/GetFile/FileInfo file ops),
lengthening or disabling the RF-field maximum on-time and Power on-time would
remove the trigger entirely. That is documented FEIG behavior for OBID and pure
inference for the cVEND. It is worth probing through the file-op interface.

## Recovery: a graded ladder

When the reader is already wedged, escalate in order and stop at the first rung
that recovers scanning. The documented OBID ladder and the reverse-engineered
cVEND equivalents line up rung for rung, but diverge in reliability.

| Rung | OBID / ID ISC action | cVEND IPP equivalent (our RE) | Confidence |
|---|---|---|---|
| 1. Probe, do not assume dead | `[0x66]` Get Reader Info / `[0x6E]` Reader Diagnostic (temperature, control, impedance, power flags) ([LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)) | `0x02` Version / `0x04` Status. If a reply or `0x07` heartbeat arrives, the UART is alive and the fault is RF or mode | High (both documented) |
| 2. Re-arm RF without rebooting | `[0x6A]` RF Output ON (effect depends on the active mode), then `[0x69]` RF Reset ([LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)) | Re-send `0xE4` enables plus `0xAA` SetTime | Low on cVEND; re-arm of a slept reader is not reproducible |
| 3. Soft reset, keep serial link | `[0x63]` RF-Controller Reset: RF field off after CPU reset, communication interface not reset ([LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)) | `0x10` Reset, subcode `2` restart app / `3` reboot ([wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend)) | High for `0x10 02`: fresh `0x0F` in about 6 s, serial preserved. Bare `0x10` wedges |
| 4. Full reboot, drops serial | `[0x64]` System Reset MODE 0x00: resets main controller, RF field off and comm interface reset ([LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)) | `0x10` subcode `3` reboot / `4` poweroff | Untested. Avoid `4` |
| 5. Hardware power cycle | external | Cut and restore power (CL30 continuous, then momentary CL15), then wait for the `0x0F` Startup frame (up to about 60 s) before re-running the enable sequence | High, but no longer the only option |

Two documented gotchas sit alongside this ladder. Baud Rate Detection `[0x52]`
works only with the reader's real COM-ADR, never the broadcast `0xFF`
([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
A wrong-address probe makes a healthy reader look unresponsive, so rule that out
before escalating. FEIG's documented timing is built around frame timeouts (a
roughly 20 ms transparent-command no-transponder timeout, plus TR-RESPONSE-TIME),
not hangs
([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
A malformed IPP frame should therefore time out rather than wedge the link, but
that is unconfirmed for the cVEND and should be tested, not assumed.

The practical conclusion from the reverse-engineering: for nx-style handled reads,
wait for the `0x0F` Startup frame before sending enables, because earlier enables
are silently dropped. For raw UID capture, skip the handshake entirely and keep
the base scan alive. If it sleeps, use `0x10 02`.

## The contactless duty cycle: LPCD can look like sleep

One more mechanism can produce a "will not see the card" symptom that looks like
sleep but is not. EMVCo-style contactless front ends increasingly use Low Power
Card Detection (LPCD). Instead of continuous full-power polling, the reader emits
very short LPCD pulses, and only a field perturbation from an approaching card
triggers a full poll
([Renesas PTX205R LPCD application note](https://www.renesas.com/en/document/apn/ptx205r-low-power-card-detection-lpcd-application-note?r=25612866)).
Vendor guidance recommends a programmable delay between polling attempts, using a
representative 400 ms inter-poll delay, while warning that overly aggressive
empty-field thresholds reduce detection sensitivity and that EMV contactless spec
changes increased the required power
([Analog Devices: Low Power Polling with Secure NFC Microcontrollers](https://www.analog.com/en/resources/design-notes/low-power-polling-with-maxim-secure-nfc-microcontrollers.html)).

If the cVEND is in an LPCD-style idle rather than true standby, a card that is too
far away or moving too fast can go unseen, making the reader appear asleep when it
is polling at low sensitivity. That is a different failure from the CFG21
power-down, and lengthening the active poll window or raising sensitivity would
address it. This is directional context from vendor app notes, not the EMVCo
specification itself, and it is not confirmed for the cVEND front end.

## The hardware: a first-generation cVEND plug flex in DK configuration

The unit is, with high confidence, a first-generation FEIG cVEND plug in the
flex/DK (open-application-development) configuration. `/etc/issue` says "cVEND
Development Kit," the device identifies as a "cVEND Application," and the
flex/"DK" software configuration all point there. INIT is the integrator who wrote
the application layer on FEIG's secure Linux
([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).

The cVEND plug is FEIG's flush-mount module built for transit validators and fare
gates, launched October 2015. It first deployed as about 1,100 terminals on a
Portland-Vancouver bus line, which is the reference architecture the PROXmobil3
instantiates ([FEIG "10 years of cVEND"](https://www.feig.de/en/news-en/10-years-of-cvend/)).
Buildroot 2014.05 places the unit in Generation I, not the later PCI PTS 6.x plug
II. Gen I shipped 128 MB RAM and 256 MB flash; Gen II has 512 MB and 1 GB, so the
memory size is a quick generation check
([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).

Electrically it is a roughly 79 x 70 x 31 mm, 5.0-5.5 V DC module on a secure
ARM9/Cortex-A-class CPU with memory encryption, crypto acceleration, a TRNG, and
tamper protection. It carries four ID-000 SAM sockets through the SAM extension
board, six LEDs, a buzzer, and both a V.24 RS232 port and an RS232-LVTTL low-voltage
UART. The latter is the likely home of the debug/IPP link
([FEIG cVEND plug flex product page](https://www.feig.de/en/payment-terminals/cvend-plug-flex/)).
The contactless interface covers ISO/IEC 14443 Type A/B, ISO/IEC 15693, NFC card
emulation, and MIFARE, with FCC filings confirming 13.56 MHz operation on an
integrated antenna ([FCC ID PJMCVEND](https://fcc.report/FCC-ID/PJMCVEND/2598130.pdf)).

Two things remain undocumented: the exact RF transceiver IC and the serial
pinout. Both are in the NDA integration manual or the FCC internal photos, neither
of which was accessible here.

## The IPP/BC protocol: a closed payment skin over a public OBID RF engine

FEIG runs two parallel protocol worlds. The public OBID/ID ISC "advanced protocol"
frames every command as `STX(0x02) | length(2, big-endian) | COM-ADR | control-byte
| [mode] | data | CRC16`, scaling to 65535-byte frames
([FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual);
corroborated by the [OBID classic-pro manual](https://manualslib.com/manual/1633605/Feig-Electronic-Obid-Classic-Pro-Series.html)).

The cVEND's `0xBC` IPP framing is categorically different. It starts with `0xBC`,
not `0x02`, and no public FEIG source documents a `0xBC` magic byte
([GitHub amarok79/InlayTester.Drivers.FeigReader](https://github.com/amarok79/InlayTester.Drivers.FeigReader)).
IPP is a separate proprietary payment-host protocol that shares the OBID protocol's
shape: start byte, length prefix, command/address, CRC trailer.

The two coexist by layering. The RF front end is driven internally through the NDA
`feclr` ("FEIG ContactLess Reader") library, the cVEND counterpart to the public
`feisc`, consumed by the firmware's `RFIDReaderMultiApp.cpp`. The external link to
the PROXmobil3 uses IPP. Exhaustive code search finds zero public references to any
`feclr_*` symbol, so this library is closed. The SDK is distributed only
through `cvend-support@feig.de`
([FEIG cVEND user manual](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual)).

Where public documentation does confirm the reverse-engineering is the card-command
layer carried inside IPP payloads. The DESFire native opcodes match the public
DESFire command set exactly: `0x5A` SelectApplication, `0x0A`/`0x1A`/`0xAA`
Authenticate, `0x60` GetVersion, `0xBD`/`0x3D` Read/Write, and the `0xAF`
additional-frame continuation
([python-desfire supported commands](https://python-desfire.readthedocs.io/en/latest/supported-commands/)).
Ultralight-C opcodes (`0x30` READ, `0xA2` WRITE, `0x1A` AUTH) match NXP's public
sets, and `emvco_ep_configure`/`_preprocess` are EMVCo Book B Entry-Point calls.
The envelope is closed. The payloads inside it are standard.

## The transit stack: a handler table where DESFire carries every closed-loop scheme

The firmware's enabled "ProxCard" handlers are VdvKa(4), MifareClassic(5), Iso(6),
Desfire(7), Girogo(8), Itso(9), and UltralightC(10). They are the concrete
realization of FEIG's marketed "eight independent application directories" that
process open-loop payment "in parallel with closed-loop ticketing... with the same
priority"
([FEIG press: multi-application technique](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/);
[FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)).

The index numbers look like entries in a fixed handler-type enum, with slots 0 to 3
(none/raw/EMV/FeliCa) not enabled on this unit. Iso(6) is most plausibly a generic
ISO 14443-4 / 7816 APDU base used by the higher schemes.

The important point for understanding the handlers is that DESFire is the physical
carrier for the logical transit applications, so several handlers overlap at the
chip level. ITSO's Shell is mapped onto DESFire files in the current Part 10
revision, which added placeholders for DESFire and Calypso and marked MIFARE
Classic 1K obsolete
([ITSO technical specification](https://www.itso.org.uk/itso-specification/itso-technical-specification)).
Germany's VDV-KA eTicket stores its entitlement (the Berechtigung/EFS in TLV
format, with an application logbook and MAC-protected control records) on
microprocessor cards that are now commonly DESFire
([VDV control-verification doc, 2017](https://media.frag-den-staat.de/files/foi/565526/20171122KontrollnachweiseEFS_geschwaerzt.pdf);
[Intelligent Transport](https://www.intelligenttransport.com/transport-articles/10003/eticket-germany/)).

That is why Itso(9), VdvKa(4), and Desfire(7) are not redundant. DESFire is the
platform, the scheme handlers are the logical applications layered on it, and each
needs its scheme keys held in one of the four SAMs. Girogo(8) is a legacy artifact.
The German contactless prepaid purse was wound down between 2020 and 2025
([Sparkasse GeldKarte FAQ](https://www.sparkasse.de/unsere-loesungen/privatkunden/karten/geldkarte.html);
[Wikipedia: GeldKarte](https://en.wikipedia.org/wiki/GeldKarte)), so that handler is
almost certainly dormant in current deployments.

The EMV side explains a behavior that mirrors the sleep problem. The Entry Point
cannot poll until it is configured. Each supported brand must be provisioned as a
"reader combination" (AID, Kernel ID, transaction limits) per Book A Tables 5-2
and 5-3. With no valid combination set, the Entry Point has nothing to match a card
against and will not start
([US Patent 11138583](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11138583);
[US Patent 11107055](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11107055)).
For open-loop transit the amount at tap is typically zero, with fare computed later
by the back office in an account-based-ticketing flow. So `emvco_ep_preprocess` is
configured for a zero-amount/deferred-authorization path rather than a retail sale;
the validator captures a token and the cloud does the fare math
([Masabi: account-based ticketing](https://blog.masabi.com/blog/everything-you-need-to-know-about-account-based-ticketing)).

Across all of this, raw UID capture needs none of it. ISO/IEC 14443-3 collects the
UID during anticollision/SELECT before any authentication. That is why the
standalone recovery of UID `04:50:67:0A:81:22:90` from a `0xBE` UnhandledCard frame
required no SAM, no fare keys, and no application context.

## Public knowledge versus our reverse-engineering

This is where each finding stands: publicly confirmed, ours alone, or dark on both
sides.

| Finding | Status | Basis |
|---|---|---|
| Ultralight-C opcodes (READ `0x30`, WRITE `0xA2`, AUTH `0x1A`/`0xAF`) in `ProxCardUltralightC` | Public docs confirm our RE | [NXP MF0ICU2](https://www.nxp.com/docs/en/data-sheet/MF0ICU2.pdf), [nfc-tools](https://nfc-tools.github.io/resources/rfid-tags/mifare-ultralight-c) |
| DESFire opcodes (`0x5A`, `0x0A`/`0x1A`/`0xAA`, `0x60`, `0xBD`/`0x3D`, `0xAF`) in IPP payloads | Public docs confirm our RE | [python-desfire](https://python-desfire.readthedocs.io/en/latest/supported-commands/), [NXP AN12752](https://www.nxp.jp/docs/en/application-note/AN12752.pdf) |
| EMVCo Entry-Point gating (`emvco_ep_configure`/`_preprocess` will not poll without a reader-combination config) | Public docs confirm our RE | [US 11138583](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11138583), [EMVCo Kernel ID](https://www.emvco.com/processes-category/kernel-id/) |
| Multi-application handler model (ProxCard enum = FEIG "parallel application directories"; DESFire carries ITSO/VDV-KA) | Public docs confirm our RE (concept level) | [FEIG multi-application press](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/), [ITSO spec](https://www.itso.org.uk/itso-specification/itso-technical-specification) |
| RF idle auto-timeout as the sleep cause (CFG21 RF-field/Power on-time; no sleep/wake opcode) | Public docs explain the symptom (OBID, inferred onto cVEND) | [ID ISC.PRH200 p.22](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22), [ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html) |
| `0xBC`/IPP frame format (BC magic, seq/replyTo/type/len, CRC-8 header) | Our RE, beyond public docs (FEIG docs show only STX `0x02`) | our work plus [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend) |
| `0xAA 6afec201` SetTime plus `0x0F`-gated enable timing | Our RE only; no public source | LD_PRELOAD sniff of stock nx |
| CRC-32/JAMCRC trailer on type-`0x80`-and-above frames | Our RE only (wiki author called it unrecognizable) | our work |
| GetFile/FileList/FileInfo file-op protocol (`0x96`-`0xA5`) and `0xD1` EMVStatus TLV | Our RE / wiki beyond public docs | [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend) |
| Continuous-scan / standalone-UID recipe (no init, consume `0xBE`) | Our RE only; no public reproducible recipe | our work |
| cVEND soft-reset subcode (the `0x10` subcode that cleanly reboots to `0x0F`) | Our RE, resolved | `0x10 02` (restart app): fresh `0x0F` in about 6 s, serial link preserved (`INTERFACE.md`, Sleep) |
| "cS01.05.45-49.00-2-2" string fields | Neither side has it | no public decode |
| `0x9C` FileInfo payload format and exact cVEND SAM/transparent opcodes | Neither side has it | NDA / unconfirmed |

## Conclusion

The most useful shift from this research is diagnostic. The sleep lock is expected behavior from a FEIG RF idle
timer and a sub-1 mA hardware standby, not something a magic wake frame can fix. The wake paths FEIG documents are a
shorter-than-idle keepalive, a configuration change to the RF on-time timers, a
hardware digital-input/timer assertion, or a power cycle. On the cVEND, `0x10 02`
adds a software restart that works. The boundary is that every
documented timer and reset opcode belongs to FEIG's public OBID protocol, so they
describe what the silicon does, not the exact IPP bytes to send. The
highest-leverage next experiments are to probe whether the cVEND's file-op
interface (`0x96`-`0xA5`) exposes CFG21-style RF on-time parameters, and to test
the remaining `0x10` subcodes.

The public record also brackets the reverse-engineering well. Everything inside the
air interface and the payment standards is corroborated by NXP, EMVCo, and ITSO
documentation, which means the interpretation of IPP payloads rests on solid
ground. Everything about the IPP envelope itself (the `0xBC` framing, the `0xAA`
SetTime behavior, the JAMCRC trailer, the file-op protocol, the cold-boot scan
recipe) is ours alone, filling a gap FEIG keeps closed behind
`cvend-support@feig.de` to protect the payment kernel, not the UID path. The
remaining unknowns (the `0x10` reboot subcode, the "cS..." string, the `0x9C`
FileInfo format, the secure SAM/transparent opcodes) are bounded on both sides and
are the right targets for the next sniff or a formal NDA request to FEIG.
