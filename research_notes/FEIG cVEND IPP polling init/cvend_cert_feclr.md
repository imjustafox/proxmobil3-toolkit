# cVEND certificate startup and the feclr / RFIDReaderMultiApp API

Most of this topic sits behind FEIG's customer/NDA developer portal. The `feclr` C
API, the `RFIDReaderMultiApp` firmware component, and the cVEND startup certificate
handshake have no public documentation, headers, or source code. Negative search
results are reported below because they are informative. Where something is
inferred from FEIG naming, datasheets, ISO/IEC 14443, or host-log strings, it is
marked as inference.

## What the startup certificate handshake is

The certificate handshake is not publicly documented. The best reading is that it
is the cVEND's secure-platform attestation and provisioned-credential check. Before
the reader firmware allows card operations it validates on-board device
certificates (X.509-style credentials injected at FEIG's PCI P2PE-certified Key
Injection Facility), and only then transitions to INITIALIZED. The "valid until
<date>" in the host log is the certificate expiry being read back by the host. It
is a FEIG-proprietary mechanism, not a published SAM/TLS spec.

What the public record supports:

- cVEND is built on a "Secure ARM Cortex-A7 CPU" with "real-time memory encryption,
  cryptography, a hardware acceleration unit, a true random number generator, and
  tamper-proof hardware," and the platform is "designed for local or remote
  application and key loading"
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- cVEND runs a "cVEND specific secure Linux operating system with an SDK and
  multi-application architecture"
  ([FEIG cVEND plug flex product page](https://www.feig.de/en/products/payment/product/cvend-plug-flex/)).
- FEIG operates a PCI P2PE-certified Key Injection Facility and offers remote
  key-loading as a service, including "secure initial key loading and key updates
  into terminals that are already in field operation"
  ([FEIG PayServ.SolutionSuite RKI](https://www.feig.de/en/payserv-solutionsuite-rki/)).
  The terminal communicates with the RKI infrastructure "via a secure connection."
- The security architecture cites "crypto plug-ins for symmetric and asymmetric
  encryption, key derivation and remote key loading." Asymmetric crypto is the
  primitive under certificate and public-key handshakes
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- The terminals are PCI PTS 5.1 certified (cVEND plug/box/PIN, valid until April
  2026). Newer compact II and PIN II are PCI PTS 6.x SRED
  ([FEIG PCI 5.1 press release](https://www.feig.de/en/news/press-news/detail/view/pci-51-certified-cvend-terminal-family-provides-future-proof-payment-applications/);
  [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- The device has SAM sockets in ID-000 format: one in compact II, two in PIN II,
  and four in plug flex
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf);
  [FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)).
- No FEIG page or datasheet found here describes the handshake mechanics, a
  secure-session protocol, or the CONNECTED/INITIALIZED state machine. Multiple
  targeted searches returned marketing and certification pages only.

Inference: the log sequence CONNECTED (serial link up), then "Feig reader version
... id: 0x... slot: 0" (firmware identity plus SAM slot index 0), then "device
certificates valid until <date>" (host queries the provisioned certificate and
reads its `notAfter`), then INITIALIZED (reader accepts card/RF commands) is a
gated boot. Card reading is blocked until the device proves it holds valid,
non-expired provisioned credentials. That fits a PCI-PTS/P2PE device that must
attest its key and certificate state before operation.

"slot: 0" most plausibly refers to SAM socket index 0, matching the documented
ID-000 sockets. The handshake is almost certainly device and platform attestation,
proving the terminal is genuine and properly key-injected. That is distinct from,
and a prerequisite to, later per-application SAM authentication used to read fare
data. The device-certificate check is about the reader being trusted, not about any
particular card.

It is not a generic TLS session to a server at this stage. That TLS secure
connection is the separate RKI/remote-key-loading channel
([RKI page](https://www.feig.de/en/payserv-solutionsuite-rki/)). The startup check
is a local validation of on-device credentials over the host serial/USB link.

What remains unknown: the actual protocol, message format, cert chain, and what
signs the device certificate. Whether it is X.509, a FEIG-proprietary structure,
mutual or one-way, and whether the host must present its own certificate could not
be confirmed. The expiry semantics (does the reader refuse to initialize, or only
warn) are not public. It is also unknown whether INITIALIZED requires the SAMs to
be present or authenticated, or whether a bare device with no application SAM still
reaches INITIALIZED.

## The feclr library

`feclr` is, by strong inference from FEIG's SDK naming convention, the proprietary
"FEIG ContactLess Reader" C library that fronts the cVEND/transit reader firmware.
No public documentation, header, package, or source exists. Exhaustive code search
(GitHub, grep.app, web) found zero references to any `feclr_*` symbol. Function
behavior can only be inferred from the names.

Related public findings:

- GitHub code search for `feclr` returns only unrelated matches: Ingres'
  `FEclr_exit()`, an HC32L110 UART `FECLR` register bit, PDP-10 assembler `FECLR:`
  labels, and base64 noise. No FEIG RFID library appears (`gh search code
  "feclr"`, 2026-11-19). `RFIDReaderMultiApp` returned zero results.
- Web search for `feclr_poll feclr_start_protocol feclr_get_card` and `"feclr"
  feig library header` found nothing matching. Results were ISO/IEC 14443 standards
  pages and the C `feclearexcept` floating-point function.
- FEIG's public SDK family uses a consistent `fe`-prefixed C library naming
  convention. The documented OBID ID ISC.SDK ships C/C++/.NET/Java libraries with a
  Reader Control API, Reader Configuration API, TagHandler API, and Logging API
  ([FEIG IDENTIFICATION SDK](https://www.feig.de/en/service/software-development-kit/);
  [FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)).
- FEIG's public serial-protocol library for OBID readers is `feisc` (FEIG ISC,
  serial communication layer), and the comms/port layer is `fecom` (functions like
  `FECOM_OpenPort`, `FECOM_Transceive`). These are the publicly visible analogues
  of the naming pattern
  ([feisc_8h source, ROS docs mirror](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h_source.html)).
- The cVEND SDK is not publicly downloadable. Datasheets list SDK, development
  devices, and tools "on request"
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).

Inference: `feclr` means FEIG ContactLess Reader, the cVEND/transit counterpart to
the public `feisc`/`fecom`/`fetcl` OBID libraries. The prefix `fe` plus `clr`
(ContactLess Reader) fits FEIG's established pattern.

Likely call flow, inferred from the verbs and generic RF reader APIs:

- `feclr_open`: open the host transport handle to the reader.
- `feclr_connect`: establish the logical session with the reader firmware. This is
  probably where the device-certificate handshake runs; CONNECTED to INITIALIZED
  likely straddles `feclr_open`/`feclr_connect`.
- `feclr_start_protocol` / `feclr_enable`: select or enable an RF protocol (for
  example ISO14443 Type A/B), energize the field, and enable card detection.
- `feclr_poll`: run the RF inventory/anticollision cycle to detect a card.
- `feclr_get_card`: retrieve the detected card descriptor, which at ISO14443-3
  level includes the UID, ATQA, and SAK.
- `feclr_transceive`: send a raw APDU or command to the selected card and read the
  response. This is for ISO14443-4 and application-level exchanges, meaning keyed
  fare operations.

The pair that starts polling and returns a UID is most plausibly `feclr_poll` (or
`feclr_enable` plus `feclr_poll`) followed by `feclr_get_card`.
`feclr_transceive` is for post-selection APDU traffic, not for obtaining the UID.

Exact signatures, return codes, argument structures, and true semantics are
unverifiable without the NDA SDK header. It is also unconfirmed whether `feclr` is
one library or a layer name inside a larger cVEND SDK, and what its version and ABI
are.

## RFIDReaderMultiApp

`RFIDReaderMultiApp` is almost certainly the host/firmware component implementing
FEIG's "Multi-Application" reader concept: one reader servicing multiple card
applications (open-loop EMV plus closed-loop transit such as Calypso, MIFARE,
VDV-KA, and ITSO) in parallel through multiple SAMs. The marketing concept is
public. The component, its source, and its command set are not. The string
`RFIDReaderMultiApp` has no public footprint at all.

Supporting public material:

- `RFIDReaderMultiApp` yields zero hits in GitHub code search and web search
  (2026-11-19). It appears only in the host logs quoted in this work.
- FEIG markets a "Multi-Application technique" that supports closed-loop and
  open-loop payment at the same time and is pitched as speeding up mass-transit
  transactions
  ([FEIG multi-application press release](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/);
  [FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)).
- Multi-application is realized with multiple SAM slots. The ID CPR74 has sockets
  for four SAMs and is certifiable for VDV-KA and ITSO, supporting MIFARE
  Classic/Ultralight/DESFire/PLUS. The ID CPR60 offers up to four ISO 7816 smart
  card connectors for public transport applications such as VDV-KA
  ([FEIG ID CPR74 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Identification_Modules_ID_CPR74.pdf);
  [FEIG ID CPR60 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Identification_Modules_ID_CPR60.pdf)).
- FEIG OBID classic-pro readers support ISO/IEC 14443 and Calypso through
  integrated SAM sockets
  ([OBID classic-pro Calypso support](https://ixtenso.com/technology/obid-classic-pro-readers-do-now-support-calypso-standard-for-eticketing.html)).
- FEIG offers a "Transparent Channel Application" that a system integrator can
  implement directly, independently of FEIG and the payment application. That is a
  raw card access path separate from the fare/payment app
  ([FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)).
- The PROXmobil3 validator runs on FEIG reader hardware and firmware. An ITSO
  certificate lists "PROXmobil3 RSP Rail Validator, version 20.36 (Feig 04.19),"
  and the PROXmobil3 card reader lists ISO 14443a/b, optionally ISO 15693, EMV,
  ITSO, Calypso, VDV-KA, MIFARE, and NFC
  ([ITSO certificate c00202](https://itso.org.uk/certificate/10292.1/c00202-init-proxmobil3-rsp-rail-validator);
  [PROXmobile3 spec PDF](https://www.initse.com/fileadmin/user_upload/Content/PDFs/PROXmobile3_us-1-page.pdf)).

Inference: `RFIDReaderMultiApp.cpp` is the host-side class that drives the reader's
multi-application mode. It registers and enables a set of card applications, one
per supported scheme/SAM, runs the inventory, and dispatches a detected card to the
matching application handler. The `.cpp` and the surrounding `feclr_*` calls
indicate it is the C++ consumer of the `feclr` C library.

Its enable/disable and inventory commands are most likely thin wrappers over the
`feclr` calls (enable protocol or application profiles, then
`feclr_poll`/`feclr_get_card`), rather than a separately documented wire protocol.

No public source gives the actual command set, message encoding, or
application-enable API. Whether it is FEIG-authored or INIT-authored (consuming
FEIG's `feclr`) is unconfirmed. The "Feig 04.19" firmware tag shows FEIG firmware
underneath, but the `.cpp` could be INIT's integration layer.

## Raw ISO14443-3 UID without keys

At the ISO/IEC 14443 standard level, yes. The UID is obtained during
anticollision/SELECT with no keys. Authentication only begins after selection. Once
the cVEND reaches INITIALIZED, obtaining a raw UID needs no application or fare
keys. The gate on a cVEND is the device-certificate/secure-platform init. The
reader must be a genuine, properly key-injected device and must reach INITIALIZED
before it will energize the field at all.

Standard-level findings:

- ISO/IEC 14443-3 Type A sequence: REQA, ATQA, UID size from ATQA bits,
  ANTICOLLISION loop collects the full UID, SELECT returns SAK. "The UID is read
  without authentication; publicly visible," and authentication (for example
  MIFARE Classic key login) comes later, after selection
  ([ISO/IEC 14443-3:2018 TOC](https://committee.iso.org/standard/73598.html);
  [NFC standards guide](https://gaelle-candel.neocities.org/ai-books/rfid-nfc-guide/02-nfc-standards.html)).
- ATQA bits b7/b8 encode UID size: single 4-byte, double 7-byte, or triple 10-byte,
  with cascade levels CL1 to CL3
  ([US patent 9,851,703](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9851703);
  [IEC 14443-3 ed4.0 preview](https://www.vde-verlag.de/iec-normen/preview-pdf/info_isoiec14443-3{ed4.0}en.pdf)).
- Anticollision/inventory is explicitly the "multiple card reads at the same time"
  step and is independent of key material
  ([SecureIDNews: anticollision](https://www.secureidnews.com/?p=24499)).
- A caveat on using UID as an identifier: some chips use a random UID that changes
  every tap (MIFARE random ID; EMV cards expose a random PUPI/UID), so a pre-auth
  UID is not always stable or useful
  ([NFC standards guide](https://gaelle-candel.neocities.org/ai-books/rfid-nfc-guide/02-nfc-standards.html)).
- The PROXmobil3 reader supports ISO 14443 A/B at the RF layer, so raw Type A/B
  anticollision is physically available
  ([PROXmobile3 spec PDF](https://www.initse.com/fileadmin/user_upload/Content/PDFs/PROXmobile3_us-1-page.pdf);
  [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- FEIG's Transparent Channel Application exists to let an integrator talk to cards
  directly, independently of FEIG and the payment application. That supports
  raw/UID-level access as an intended, key-free capability
  ([FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)).

Inference: the minimal UID sequence on a cVEND, assuming the device has passed its
cert handshake and is INITIALIZED, is `feclr_open`, `feclr_connect` (session plus
device-cert gate), `feclr_start_protocol`/`feclr_enable` (ISO14443-A/B, RF on),
`feclr_poll` (REQA/WUPA plus anticollision/SELECT), and `feclr_get_card` (UID plus
ATQA/SAK). No SAM and no application or fare keys are needed for this. Keys are
only required once you `feclr_transceive` application APDUs (MIFARE auth,
DESFire/Calypso secure messaging) to read fare data.

The practical blocker for a third party is therefore the device-certificate and
secure-platform init, not the card keys. A non-genuine or unprovisioned reader will
not reach INITIALIZED and will never energize the field. On a legitimately
INITIALIZED cVEND, UID polling is pre-auth and key-free.

EMV open-loop cards present a random UID/PUPI at 14443-3, so a UID read from a bank
card tap is deliberately non-correlatable. Transit and closed-loop cards
(MIFARE/DESFire/Calypso) typically present a stable UID at 14443-3 but gate their
fare data behind keys.

Unknown: whether the cVEND firmware exposes a raw UID-only or transparent
inventory mode to the host without a SAM or application profile loaded, or whether
its secure firmware forces every card interaction through an application context
even for UID. The standard permits key-free UID. Whether FEIG's hardened payment
firmware policy allows a host to request UID-only is undocumented publicly. The
exact `feclr`/`RFIDReaderMultiApp` calls that return the UID, and whether a SAM must
be seated for the field to enable, are also not public.

## Source quality

Every FEIG-specific mechanism above (the cert handshake, `feclr`,
`RFIDReaderMultiApp`) is proprietary/NDA. No header, SDK download, forum post,
package (Debian/Yocto/meta-feig), or GitHub repo was found despite direct code
search. Treat structural and behavioral claims about these as inference, grounded
in FEIG's public naming conventions (`feisc`/`fecom`), public datasheets, and the
host-log strings supplied in this work.

The only hard, primary-sourced answer is the standards-level point: ISO/IEC 14443-3
UID/anticollision is key-free and pre-authentication. The cVEND-specific gate is the
device-cert/secure init, not fare keys.
