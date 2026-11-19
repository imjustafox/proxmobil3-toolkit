# FEIG cVEND secure-session / device-certificate startup handshake and the "feclr" / RFIDReaderMultiApp API

> Scope note: This topic sits almost entirely behind FEIG's customer/NDA developer portal. The `feclr`
> C API, the `RFIDReaderMultiApp` firmware component, and the cVEND startup certificate handshake are
> **proprietary and have no public documentation, headers, or source code**. Confirmed negative results
> (searches that found nothing) are reported as findings below because they are themselves informative.
> Where I mark something as an **Inference**, it is reasoning from FEIG's naming conventions, public
> datasheets, the generic ISO/IEC 14443 standard, and the host-log strings quoted in the assignment — not
> from a primary FEIG source.

## Key Question 1 — What is the cVEND startup certificate handshake (CONNECTED -> "device certificates valid until <date>" -> INITIALIZED)? Is it SAM / mutual-auth / TLS-like, and is it documented?

### Takeaway
The certificate handshake is **not publicly documented anywhere**. It is best understood as the cVEND's
**secure-platform attestation / provisioned-credential check**: before the reader firmware will allow card
operations it validates on-board **device certificates** (X.509-style credentials injected at FEIG's
PCI P2PE-certified Key Injection Facility), and only then transitions to INITIALIZED. The "valid until
<date>" in the host log is the certificate expiry being read back by the host. It is a FEIG-proprietary
mechanism, not a published SAM/TLS spec.

### Cited Findings
- cVEND is built on a **"Secure ARM Cortex-A7 CPU"** with "real-time memory encryption, cryptography, a hardware acceleration unit, a true random number generator, and tamper-proof hardware," and the platform is "designed for local or remote application and key loading" — [FEIG cVEND compact II – Platform for App Development datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)
- cVEND runs a **"cVEND specific secure Linux operating system with an SDK and multi-application architecture"** — [FEIG cVEND plug flex product page](https://www.feig.de/en/products/payment/product/cvend-plug-flex/)
- FEIG operates a **PCI P2PE-certified Key Injection Facility** and offers "a PCI P2PE compliant solution for Remote Key-Loading as a service … secure initial key loading and key updates into terminals that are already in field operation" — [FEIG PayServ.SolutionSuite RKI](https://www.feig.de/en/payserv-solutionsuite-rki/)
- Remote key loading: "The terminal then communicates with the FEIG Remote Key Injection infrastructure **via a secure connection**," using PCI P2PE-certified processes for key exchange — [FEIG PayServ.SolutionSuite RKI](https://www.feig.de/en/payserv-solutionsuite-rki/)
- Security architecture cites **"crypto plug-ins for symmetric and asymmetric encryption, key derivation and remote key loading"** (asymmetric crypto = the primitive underlying certificate/public-key handshakes) — [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)
- The terminals are **PCI PTS 5.1 certified** (cVEND plug/box/PIN, valid until April 2026) and newer compact II / PIN II are **PCI PTS 6.x SRED** — [FEIG PCI 5.1 certification press release](https://www.feig.de/en/news/press-news/detail/view/pci-51-certified-cvend-terminal-family-provides-future-proof-payment-applications/); [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)
- The device contains one or more **SAM sockets (ID000 format)**: compact II has "1 x SAM Socket ID000 format," PIN II has "2 x SAM Socket," and plug flex provides "4 SAM sockets (ID000 format)" — [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf); [FEIG cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf)
- No FEIG page or datasheet I could reach describes the handshake/certificate mechanics, a secure-session protocol, or the CONNECTED/INITIALIZED state machine. Multiple targeted searches ("cVEND device certificates secure session handshake," "SAM secure access module … architecture") returned only marketing/certification pages — [FEIG PCI 5.1 press release](https://www.feig.de/en/news/press-news/detail/view/pci-51-certified-cvend-terminal-family-provides-future-proof-payment-applications/)

### Inferences
- The log sequence `CONNECTED` (serial/USB link up) -> read "Feig reader version … id: 0x… slot: 0" (firmware identity + SAM slot index 0) -> `device certificates valid until <date>` (host queries the terminal's provisioned certificate and reads its notAfter expiry) -> `INITIALIZED` (reader now accepts card/RF commands) is a **gated boot**: card reading is blocked until the device proves it holds valid, non-expired provisioned credentials. This is consistent with a PCI-PTS/P2PE device that must attest its key/cert state before operation.
- "slot: 0" in the version line most plausibly refers to the **SAM socket index 0**, matching the documented ID000 SAM sockets — i.e., the host is enumerating the reader + its SAM population at init.
- The handshake is almost certainly **device/platform attestation (prove the terminal is genuine and properly key-injected)**, which is distinct from — and a prerequisite to — later **per-application SAM authentication** used to read fare data. The device-certificate check is about the *reader being trusted*, not about any particular card.
- It is **not** a generic TLS session to a server at this stage (that TLS secure connection is the separate RKI/remote-key-loading channel, [RKI page](https://www.feig.de/en/payserv-solutionsuite-rki/)); the startup check is a **local** validation of on-device credentials performed over the host serial/USB link.

### Gaps
- No primary source describes the actual protocol, message format, cert chain, or what signs the device certificate. Whether it is X.509, a FEIG-proprietary structure, mutual vs one-way, and whether host software must present its own certificate, could not be confirmed. The expiry date semantics (what happens on expiry — refuse to initialize, or warn) are not documented publicly.
- Could not determine whether INITIALIZED requires the SAM(s) to be present/authenticated, or whether a bare device with no application SAM still reaches INITIALIZED.

## Key Question 2 — What is the FEIG "feclr" library (feclr_open/connect/transceive/start_protocol/enable/poll/get_card)? Which calls start RF polling and return a UID? Are docs/headers public?

### Takeaway
`feclr` is (by overwhelming inference from FEIG's SDK naming convention) **FEIG's proprietary "ContactLess
Reader" C library** that fronts the cVEND/transit reader firmware. **No public documentation, header, package,
or source exists** — exhaustive code search (GitHub, grep.app, web) found zero references to any `feclr_*`
symbol. Function behavior can only be inferred from the names.

### Cited Findings
- **GitHub code search for `feclr` returns only unrelated matches** — Ingres' `FEclr_exit()`, an HC32L110 UART `FECLR` register bit, PDP-10 assembler `FECLR:` labels, and base64 noise. **No FEIG RFID library** appears (`gh search code "feclr"`, 2026-11-19). `RFIDReaderMultiApp` returned **zero** results. — GitHub code search (no public URL; query `feclr` / `RFIDReaderMultiApp` via `gh search code`)
- Web search for `feclr_poll feclr_start_protocol feclr_get_card` and `"feclr" feig library header` found **nothing** matching; results were ISO/IEC 14443 standards pages and the C `feclearexcept` floating-point function — [ISO/IEC 14443-3 TOC](https://committee.iso.org/standard/73598.html); [feclearexcept man page](https://tribblix.org/man/man3m/feclearexcept.html)
- FEIG's public SDK family uses a consistent **`fe`-prefixed C library naming** convention. The documented OBID "ID ISC.SDK" ships C/C++/.NET/Java libraries with a **Reader Control API, Reader Configuration API, TagHandler API, and Logging API** — [FEIG IDENTIFICATION SDK](https://www.feig.de/en/service/software-development-kit/); [FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)
- FEIG's public serial-protocol library for OBID readers is **`feisc`** (FEIG ISC — serial communication layer), and the comms/port layer is **`fecom`** (functions like `FECOM_OpenPort`, `FECOM_Transceive`); these are the publicly-visible analogues of the naming pattern — [feisc_8h source (ROS docs mirror)](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h_source.html)
- The cVEND SDK itself is **not publicly downloadable**: datasheets list "SDK, Development Devices, Tools … on request" and "Development Devices, Tools and SDK on request" — [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)

### Inferences
- **`feclr` = FEIG ContactLess Reader library**, the cVEND/transit counterpart to the public `feisc`/`fecom`/`fetcl` OBID libraries. The prefix `fe` + `clr` (ContactLess Reader) fits FEIG's established pattern exactly.
- Likely call-flow mapping (inferred from the verbs, generic to RF reader APIs):
  - `feclr_open` — open the host transport (serial/USB) handle to the reader.
  - `feclr_connect` — establish the logical session with the reader firmware (this is probably where the **device-certificate handshake** of Q1 runs; CONNECTED -> INITIALIZED likely straddles `feclr_open`/`feclr_connect`).
  - `feclr_start_protocol` / `feclr_enable` — select/enable an RF protocol (e.g., ISO14443 Type A/B) and energize the field / enable card detection.
  - `feclr_poll` — run the RF **inventory/anticollision** cycle to detect a card in field.
  - `feclr_get_card` — retrieve the detected card descriptor, which at ISO14443-3 level includes the **UID (and ATQA/SAK)**.
  - `feclr_transceive` — send a raw APDU/command to the selected card and read the response (used for ISO14443-4 / application-level exchanges, i.e., the keyed fare operations).
- The pair that **"starts polling and returns a UID"** is most plausibly `feclr_poll` (or `feclr_enable` + `feclr_poll`) followed by `feclr_get_card`. `feclr_transceive` is for post-selection APDU traffic, not for obtaining the UID.

### Gaps
- Exact signatures, return codes, required argument structures, and the true semantics of each `feclr_*` call are unverifiable without the NDA SDK header. The mapping above is informed inference, not documentation.
- Could not confirm whether `feclr` is a single library or a layer name within a larger cVEND SDK, nor its version/ABI.

## Key Question 3 — What is "RFIDReaderMultiApp" (string in cVEND firmware logs, e.g. RFIDReaderMultiApp.cpp)? Is it FEIG multi-application firmware, and what commands enable card applications / start an inventory?

### Takeaway
`RFIDReaderMultiApp` is almost certainly the **host/firmware software component implementing FEIG's
"Multi-Application" reader concept** — one reader servicing multiple card applications (open-loop EMV +
closed-loop transit: Calypso, MIFARE, VDV-KA, ITSO) in parallel via multiple SAMs. The marketing concept is
public; the **component, its source, and its command set are not** — `RFIDReaderMultiApp` has no public
footprint at all.

### Cited Findings
- `RFIDReaderMultiApp` yields **zero** hits in GitHub code search and web search (2026-11-19) — the string appears only in the host logs quoted in this assignment; no public document names it. (GitHub `gh search code "RFIDReaderMultiApp"` -> empty)
- FEIG markets a **"Multi-Application technique"** that "support[s] closed-loop and open-loop payment methods at the same time" and is pitched as speeding up mass-transit transactions — [FEIG multi-application press release](https://www.feig.de/en/news/press-news/detail/view/feigs-multi-application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/); [FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)
- Multi-application is realized with **multiple SAM slots**: e.g. ID CPR74 "has sockets for 4 Security Access Modules (SAM)" and is "certifiable for … VDV-KA and ITSO," supporting MIFARE Classic/Ultralight/DESFire/PLUS; ID CPR60 offers "up to 4 smart card connectors according to ISO 7816 … suitable for ticket applications in public transport (VDV-KA)" — [FEIG ID CPR74 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Identification_Modules_ID_CPR74.pdf); [FEIG ID CPR60 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Identification_Modules_ID_CPR60.pdf)
- FEIG OBID classic-pro readers "support … ISO/IEC 14443, the current Calypso standard, [and older Calypso]" via integrated SAM sockets (CPR40.30 / CPR44.0x) — [OBID classic-pro Calypso support (ixtenso)](https://ixtenso.com/technology/obid-classic-pro-readers-do-now-support-calypso-standard-for-eticketing.html)
- FEIG offers a **"Transparent Channel Application,"** which a "system integrator can implement directly … independently of FEIG and the payment application" (i.e., raw card access path separate from the fare/payment app) — [FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)
- The PROXmobil3 validator (the INIT device in question) runs on FEIG reader hardware/firmware: an ITSO certificate lists "PROXmobil3 RSP Rail Validator, version 20.36 (**Feig 04.19**)" and the PROXmobil3 card reader lists "standards: ISO 14443a/b, optionally ISO 15693, EMV, ITSO, Calypso, VDV-KA, MIFARE, NFC" — [ITSO certificate c00202 PROXmobil3](https://itso.org.uk/certificate/10292.1/c00202-init-proxmobil3-rsp-rail-validator); [PROXmobile3 spec PDF](https://www.initse.com/fileadmin/user_upload/Content/PDFs/PROXmobile3_us-1-page.pdf)

### Inferences
- `RFIDReaderMultiApp.cpp` is the host-side (likely INIT PROXmobil3 driver, or FEIG-provided) class that drives the reader's **multi-application** mode: it registers/enables a set of card applications (one per supported scheme/SAM), runs the inventory, then dispatches a detected card to the matching application handler. The ".cpp" and the surrounding `feclr_*` calls indicate it is the C++ consumer of the `feclr` C library.
- Its "commands to enable/disable card applications and start an inventory" are most likely thin wrappers over the `feclr` calls (enable protocol/application profiles, then `feclr_poll`/`feclr_get_card`), rather than a separately-documented wire protocol.

### Gaps
- No public source gives the actual command set, message encoding, or application-enable API of `RFIDReaderMultiApp`. Whether it is FEIG-authored or INIT-authored (consuming FEIG's `feclr`) is unconfirmed — the "Feig 04.19" firmware tag shows FEIG firmware underneath, but the `.cpp` could be INIT's integration layer.

## Key Question 4 — Can a host get a raw ISO14443-3 UID from a cVEND with no application/fare keys (pre-auth), and what minimal sequence achieves it?

### Takeaway
**At the ISO/IEC 14443 standard level, yes: the UID is obtained during anticollision/SELECT with no keys
whatsoever** — authentication only begins *after* selection. So once the cVEND reaches INITIALIZED, obtaining
a raw UID needs **no application/fare keys**. The real gate on a cVEND is **not** the card keys but the
**device-certificate/secure-platform init (Q1)**: the reader must be a genuine, properly key-injected device
and reach INITIALIZED before it will energize the field at all. Within those bounds, UID/anticollision is a
pre-authentication operation.

### Cited Findings
- ISO/IEC 14443-3 Type A sequence: **REQA -> ATQA -> (UID-size from ATQA bits) -> ANTICOLLISION loop collects full UID -> SELECT returns SAK**; "the UID is read **without authentication**; publicly visible," and "authentication (e.g. MIFARE Classic key login) comes later, after selection" — [ISO/IEC 14443-3:2018 TOC (ISO)](https://committee.iso.org/standard/73598.html); [NFC standards guide](https://gaelle-candel.neocities.org/ai-books/rfid-nfc-guide/02-nfc-standards.html)
- ATQA bits b7/b8 encode UID size (single 4-byte / double 7-byte / triple 10-byte, with cascade levels CL1..CL3) — [US patent 9,851,703 (UID cascade size)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9851703); [IEC 14443-3 ed4.0 preview](https://www.vde-verlag.de/iec-normen/preview-pdf/info_isoiec14443-3{ed4.0}en.pdf)
- Anticollision/inventory is explicitly the "multiple card reads at the same time" step and is independent of any key material — [SecureIDNews: anticollision](https://www.secureidnews.com/?p=24499)
- Caveat on using UID as an identifier: "some chips use a **random UID** that changes every tap" (MIFARE random ID / EMV cards expose a random PUPI/UID), so a pre-auth UID is not always a stable/useful identifier — [NFC standards guide](https://gaelle-candel.neocities.org/ai-books/rfid-nfc-guide/02-nfc-standards.html)
- cVEND/PROXmobil3 reader supports ISO 14443 A/B at the RF layer, so raw Type A/B anticollision is physically available on the hardware — [PROXmobile3 spec PDF](https://www.initse.com/fileadmin/user_upload/Content/PDFs/PROXmobile3_us-1-page.pdf); [FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)
- FEIG's "Transparent Channel Application" exists precisely to let an integrator talk to cards directly "independently of FEIG and the payment application" — supporting that raw/UID-level card access is an intended, key-free capability path — [FEIG public transport ticketing](https://www.feig.de/en/industries/public-transport-ticketing/)

### Inferences
- **Minimal UID sequence on a cVEND (inferred), assuming the device has already passed its cert handshake and is INITIALIZED:** `feclr_open` -> `feclr_connect` (session + device-cert gate) -> `feclr_start_protocol`/`feclr_enable` (ISO14443-A/B, RF on) -> `feclr_poll` (REQA/WUPA + anticollision/SELECT) -> `feclr_get_card` (returns UID + ATQA/SAK). **No SAM and no application/fare keys are needed for this** — keys are only required once you `feclr_transceive` application APDUs (MIFARE auth, DESFire/Calypso secure messaging) to read fare data.
- The practical blocker for an attacker/third party is therefore **Q1's device-certificate/secure-platform init, not the card keys**: a non-genuine or un-provisioned reader will not reach INITIALIZED and will never energize the field. On a legitimately INITIALIZED cVEND, UID polling is pre-auth and key-free.
- EMV open-loop cards present a **random UID/PUPI** at 14443-3, so a UID read off a bank card tap is deliberately non-correlatable; transit/closed-loop cards (MIFARE/DESFire/Calypso) typically present a stable UID at 14443-3 but gate their *fare data* behind keys.

### Gaps
- Could not confirm from any primary FEIG source whether the cVEND firmware *exposes* a raw UID-only / "transparent"/inventory mode to the host **without** a SAM/application profile loaded, or whether its secure firmware forces every card interaction through an application context even for UID. The standard permits key-free UID; whether FEIG's hardened payment firmware *policy* allows a host to request UID-only is undocumented publicly.
- The exact `feclr`/`RFIDReaderMultiApp` call(s) that return the UID, and whether a SAM must be seated for the field to enable, are not publicly documented.

## Cross-cutting note on source quality
- Every FEIG-specific mechanism in Q1–Q3 (the cert handshake, `feclr`, `RFIDReaderMultiApp`) is **proprietary/NDA** — no header, SDK download, forum post, package (Debian/Yocto/meta-feig), or GitHub repo was found despite direct code search. Treat all structural/behavioral claims about these three as **inference**, grounded in (a) FEIG's public naming conventions (`feisc`/`fecom`), (b) public datasheets, and (c) the host-log strings supplied in the assignment.
- The only **hard, primary-sourced** answer is Q4's standards-level point: ISO/IEC 14443-3 UID/anticollision is key-free and pre-authentication. The cVEND-specific gate is the device-cert/secure init, not fare keys.
