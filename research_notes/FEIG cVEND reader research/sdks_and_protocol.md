# FEIG Reader SDKs, Host-Communication Libraries, and DESFire/APDU Command Interfaces

Scope: What is publicly documented about how a host talks to FEIG readers (SDKs, libraries, the FEIG "advanced/standard" serial protocol, DESFire/Ultralight command wrapping, APDU/SAM exchange), to map against a reverse-engineered BC-framed "IPP" serial protocol in a FEIG cVEND reader (fw 02.35) inside an INIT PROXmobil3.

Note on sourcing: FEIG's authoritative reader-protocol and FEDM/FEISC manuals are not freely indexed in full; much detail below comes from (a) an open-source C# reimplementation of FEIG's protocol, (b) FEIG product datasheets, (c) a Scribd copy of a FEIG CPR70 manual surfaced via search snippets (unofficial, treat with care), and (d) NXP/public DESFire/Ultralight references. The cVEND-specific SDK (and the `feclr` API) is distributed "on request" / under NDA and is NOT publicly documented — this is a recurring gap below.

---

## Q1: FEIG SDKs/libraries and the "advanced/standard" protocol — relation to a "BC"-magic frame?

### Takeaway
FEIG's public reader family (OBID) uses a well-defined serial host protocol with two framing variants ("standard" and "advanced"), both beginning with an **STX = 0x02** start byte and ending with **CRC16**. The SDK stack is FEDM (C++ data-exchange module) layered over FEISC (protocol/command codec) over the transport libs FECOM (serial) / FEUSB / FETCL (TCP). No public FEIG source documents a **"BC" (0xBC) magic start byte** — that strongly indicates the cVEND "IPP" protocol is a different, proprietary framing, not the standard OBID advanced protocol.

### Cited Findings
- FEIG's GEN3 Software Development Kit targets C++, .NET, and JAVA with an identical API across languages — [FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)
- The OBID/FEDM C++ class library ("ID FEDM C++ Class Library", doc H10202-32e-ID-B, v4.06.06, 2014) is the "Part B.ISC" software-support document for OBID i-scan and OBID classic-pro readers; it embeds/uses the `feisc.h` FEISC command layer — [FEDM C++ manual (ST community mirror)](https://community.st.com/ysqtg83639/attachments/ysqtg83639/st25-nfc-rfid-tags-readers-forum/6729/1/C++%20FEDM%20-%20H10202-32e-ID-B.pdf); FEDM header mirror referenced in [ROS rfid_drivers FEDM_ISCReaderID_8h](https://docs.ros.org/en/hydro/api/rfid_drivers/html/FEDM__ISCReaderID_8h.html)
- A FEISC command code example from the ROS mirror: `FEISC_READER_INFO 0x66` — [ROS rfid_drivers feisc_8h](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h.html) (page itself now returns an Anubis bot-block; value surfaced via search index of that page)
- Open-source C# reimplementation (amarok79 InlayTester.Drivers.FeigReader) states it "supports all Feig RFID reader/modules that run Feig's standard or advanced protocol"; protocol is a global/per-call setting `Protocol = FeigProtocol.Advanced` or `.Standard` — [GitHub amarok79/InlayTester.Drivers.FeigReader](https://github.com/amarok79/InlayTester.Drivers.FeigReader)
- **Documented FEIG common command codes** (control byte in the command position of the frame), from the FeigReader README "Common Commands" table — [GitHub amarok79/InlayTester.Drivers.FeigReader](https://github.com/amarok79/InlayTester.Drivers.FeigReader):
  - `0x52` Baud Rate Detection (TestCommunication)
  - `0x63` CPU Reset
  - `0x65` Get Software Version
  - `0x66` Reader Info (from ROS mirror)
  - `0x69` RF Reset
  - `0x80` Read Configuration / `0x81` Write Configuration / `0x82` Save Configuration / `0x83` Set Default Configuration
  - `0x0B 0x01` Inventory (ISO Standard) — note the two-byte command (mode + sub-command)
- **Standard vs advanced frame capacity:** standard protocol is limited to 255 bytes total and "not recommended for new applications"; the advanced protocol frame can transfer up to 65535 bytes per frame; the reader answers an advanced-protocol request with an advanced-protocol frame — [FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual) (unofficial); corroborated for OBID classic-pro: reader selects advanced frame when response exceeds 255 bytes — [OBID classic-pro series manual, manualslib](https://manualslib.com/manual/1633605/Feig-Electronic-Obid-Classic-Pro-Series.html)
- **Advanced protocol frame layout (request):** `STX(0x02) | ALENGTH(2 bytes, big-endian, whole frame incl. STX+CRC) | bus address (COM-ADR) | control byte (command) | [mode] | data… | CRC16(2 bytes)`. Response: `STX(0x02) | ALENGTH(2) | COM-ADR | control byte | STATUS | data… | CRC16(2)` — [FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual) (unofficial)
- **Worked example traffic** (from the CPR70 copy): request `02 00 09 FF B0 01 00 18 43`; response `02 00 13 00 B0 00 01 03 D1 E0 04 02 00 00 01 AA 76 B1 94`. Here: `02`=STX, `00 09`/`00 13`=length covering whole frame, `FF`/`00`=bus address, `B0`=control byte (ISO14443 host command), on the request `01`=mode, response `00` after B0 = STATUS OK — [FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual) (unofficial)
- Notation convention in FEIG manuals: a hex value in brackets, e.g. `[0x52]`, denotes a control byte (command) — [FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)

### Inferences
- The FEIG standard/advanced OBID protocol uses **STX = 0x02**, not **0xBC**. The cVEND "IPP"/"BC"-magic framing is therefore almost certainly a *separate* FEIG payment-side protocol, not the OBID RFID host protocol. The two may coexist (RFID front-end spoken internally via FEISC-style 0xB0 commands; the external host link to the PROXmobil3 using the BC/IPP framing).
- `feclr_transceive` and `Ipp.cpp` in the firmware suggest the cVEND runs a Linux app stack where the application talks to the contactless front-end via the `feclr` library, while the external serial link uses the IPP/BC protocol — a layering distinct from FEDM/FEISC.
- The `0xB0` control byte with a leading "mode" byte is FEIG's generic "ISO14443 host command" dispatcher; the firmware's `feclr_transceive` is the functional analogue (send raw bytes to PICC, get response) exposed at the cVEND SDK level.

### Gaps
- No public source confirms a 0xBC start byte / "BC magic" anywhere in FEIG's documented protocol. The IPP framing appears undocumented publicly.
- The exact CRC16 polynomial/seed for the FEIG advanced protocol was not extracted from a primary source here (FEIG uses CRC16 per ISO; typical FEIG readers use CRC16 CCITT with preset 0xFFFF, poly 0x8408/0x1021 — NOT verified against a FEIG doc in this pass).
- Full FECOM/FEUSB/FETCL transport API not retrieved (download portal is gated).

---

## Q2: The "feclr" prefix — FEIG cVEND contactless library and its API

### Takeaway
"feclr" is almost certainly **FEIG ContactLess Reader** — the cVEND-side library/API for driving the contactless front-end (analogous to "transceive to card"). It is NOT publicly documented; the cVEND SDK ("cVEND.OS & SDK") is Linux-based and provided only on request / under NDA from FEIG. No public headers for `feclr_transceive` were found.

### Cited Findings
- cVEND plug flex runs a "secure Linux OS" and "comes with an SDK on request"; positioned for system integrators writing their own Level 3 payment application — [cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf); [cVEND plug flex product page](https://www.feig.de/en/products/payment/product/cvend-plug-flex/)
- cVEND compact II is described as a "flexible secure Linux platform" with a "Linux-based cVEND.OS & SDK" for developers — [cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)
- Architecture: "secure Linux operating system and an architecture of eight independent application directories" to run open-loop payment and closed-loop ticketing in parallel — [Pressebox: FEIG Multi-Application](https://www.pressebox.com/pressrelease/feig-electronic-gmbh/FEIGs-Multi-Application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/boxid/851978)
- cVEND flex I variant ships "a fully configured payment operating system — without level 2 kernel or level 3 host applications" (integrator supplies their own kernels/L3); flex II includes certified L2 kernels — [cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf); [FEIG cVEND L2](https://www.feig.de/en/cvend-l2/)
- Support contact for the cVEND SDK is `cvend-support@feig.de` (per the cVEND user manual) — [FEIG cVEND users manual (index)](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual) (body returned 403 on fetch)

### Inferences
- `feclr_*` = FEIG ContactLess Reader library; `feclr_transceive` = raw ISO14443-4 (and lower) send/receive to the PICC, the building block the EMV L2 kernel and any closed-loop (DESFire/Ultralight) app use. This mirrors the role of FEISC's `0xB0` ISO command on OBID readers but exposed as a C library on the cVEND's Linux OS rather than over the wire.
- `emvco_ep_configure` / `emvco_ep_preprocess` are EMVCo "Entry Point" (Book B) function names — the pre-processing/combination-selection stage of a contactless transaction — confirming the firmware embeds an EMVCo Entry Point + L2 kernels (consistent with cVEND L2 certification).
- `RFIDReaderMultiApp.cpp` aligns with FEIG's advertised "Multi-Application"/eight-application-directory design.

### Gaps
- No public `feclr` header, function signature, or man page was found. The API surface (`feclr_transceive`, reader open/close/field control) is NDA/SDK-gated.
- No public doc ties `Ipp.cpp` to a named FEIG protocol; "IPP" is not resolved from public FEIG materials.
- The "feig" app loader / application-directory loading mechanism is not publicly documented beyond marketing descriptions.

---

## Q3: DESFire — "m075031_desfire.pdf" and the native command set

### Takeaway
`m075031` is an NXP document-number style identifier; `m075031_desfire.pdf` is almost certainly an **NXP MIFARE DESFire functional/command specification** (NXP internal doc number format, typically NDA). The native DESFire datasheet is NDA-classified, but the command opcodes are well known from public reimplementations. Key reader-relevant opcodes below.

### Cited Findings
- NXP confirms the native DESFire datasheet is NDA-classified; developers are pointed to public ISO7816 commands — [MIFARE.net forum reply](https://www.mifare.net/support/forum/reply/27490/)
- **DESFire native command codes** (from python-desfire supported-commands and NXP AN12752) — [python-desfire supported commands](https://python-desfire.readthedocs.io/en/latest/supported-commands/):
  - Authenticate (legacy DES/3DES): `0x0A`
  - AuthenticateISO (3K3DES): `0x1A`
  - AuthenticateAES: `0xAA`
  - AuthenticateEV2First: `0x71`; AuthenticateEV2NonFirst: `0x72` — [NXP AN12752 (via search)](https://www.nxp.jp/docs/en/application-note/AN12752.pdf)
  - GetVersion: `0x60` (with `0xAF` additional-frame continuations)
  - SelectApplication: `0x5A` (3-byte AID)
  - GetApplicationIDs: `0x6A`; CreateApplication: `0xCA`; DeleteApplication: `0xDA`
  - GetFileIDs: `0x6F`; GetFileSettings: `0xF5`; CreateStdDataFile: `0xCD`; DeleteFile: `0xDF`
  - ReadData: `0xBD`; WriteData: `0x3D`
  - ChangeKey: `0xC4`; GetKeySettings: `0x45`; ChangeKeySettings: `0x54`; GetKeyVersion: `0x64`
  - GetRealUID/GetCardUID: `0x51`; ChangePICCConfiguration: `0x5C`; FormatPICC: `0xFC`
  - **Additional Frame / continuation: `0xAF`** (also the "more data" status) — [NXP AN12752 (via search)](https://www.nxp.jp/docs/en/application-note/AN12752.pdf)
- GetVersion is supported on EV1/EV2/EV3; Authenticate `0x0A` on EV1/EV2/EV3 — [NXP AN12752 (via search)](https://www.nxp.jp/docs/en/application-note/AN12752.pdf)
- A selected application stays active until an error or another AID is selected — [MIFARE.net forum reply](https://www.mifare.net/support/forum/reply/27490/)
- DESFire supports both native command framing and ISO7816-4 APDU wrapping (e.g., DESFire Light is "fully compliant with ISO/IEC 14443-4 and ISO/IEC 7816-4"); native commands can be wrapped in ISO7816 APDUs with CLA=0x90, INS=command code, P1=P2=0x00, data, Le=0x00 (the "wrapped" mode), status SW1SW2 = 91 00 (OK) / 91 AF (additional frame) — [MIFARE application programming guide for DESFire rev.e](https://scancode.ru/upload/iblock/de4/mifare_application_programming_guide_for_desfire_rev.e.pdf)

### Inferences
- `ProxCardUltralightC` + DESFire references in the firmware indicate the cVEND's closed-loop app layer implements native DESFire and Ultralight-C command flows over `feclr_transceive`, not just EMV.
- `m075031_desfire.pdf` being referenced in firmware strings means the FEIG developers worked from NXP's DESFire functional spec (NDA) to implement the command set; the number format `mNNNNNN` is characteristic of NXP document IDs.

### Gaps
- Cannot confirm the precise title/edition of `m075031_desfire.pdf` (NDA doc not public). Opcodes above are corroborated from independent public reimplementations, not that document.
- DESFire status/error code table (0x0C, 0x0E, 0x1C, 0x1E, 0x9D, 0x9E, 0xAE, 0xAF, 0xBE, 0xCA, 0xF0, etc.) not fully enumerated from a primary source in this pass.

---

## Q4: APDU proxy / transparent channel and SAM control on FEIG readers

### Takeaway
FEIG readers expose raw ISO14443-4 / ISO7816 APDU exchange to the host (a "transparent" transceive command) and provide SAM/SAV sockets controlled via dedicated host commands. Exact FEIG opcode values for the transparent/SAM commands were not confirmed from a primary FEIG source in this pass; the concept and the SAM hardware are documented. The cVEND's `feclr_transceive` is the on-device equivalent of the transparent APDU channel.

### Cited Findings
- cVEND readers offer "4 x SAM Sockets" (optionally via a SAM Extension Board) — [cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf); [cVEND Vending Extension Board datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_Vending_Extension_Board_EN.pdf)
- A FEIG CPR70 manual lists a "Supported Host Commands" section with a "Transparent" entry (snippet only; no byte detail) — [FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual) (unofficial)
- Comparative/industry context for transparent channels (not FEIG-specific): PC/SC transparent transceive uses CLA=0xFF INS=0xC2 (ENVELOPE-modeled), returning card data transparently and allowing protocol switching between ISO14443-3 and -4 — [PC/SC part 3 v2.02.00 supplement](https://kolegite.com/EE_library/standards/pcsc3_v2.02.00_sup2.pdf); Microsoft NFC storage-card APDUs use INS 0xB0 (Read Binary) and a transparent-exchange INS 0xC2 — [Microsoft storage card requirements](https://learn.microsoft.com/en-us/windows-hardware/drivers/nfc/storage-card-requirements); NXP MIFARE SAM AV3 transparent exchange uses INS 0x7E — [NXP SAM/DESFire AN (via search)](https://www.nxp.com.cn/docs/en/application-note/AN12705.pdf); Baltech provides a raw ISO14443-4 APDU exchange channel where the reader does not interpret the data — [Baltech ISO14B transparent command](https://docs.baltech.de/refman/cmds/iso14b/index.html)

### Inferences
- On OBID readers the FEIG "transparent"/APDU exchange is reached through the `0xB0` ISO14443 host command family (mode byte selects Request/Anticollision/Select/Authenticate/Read/Write/Transparent); FEDM exposes this as a `FEISC_0xB0_ISOCmd`-style call. The cVEND replaces the over-the-wire 0xB0 with the local `feclr_transceive` C call.
- `SecurityServices.cpp` in the firmware is the likely home of SAM/SAV socket control and key/crypto services, consistent with the 4× SAM sockets and the "SAV" (Secure Authentication/Access?) naming.

### Gaps
- Exact FEIG control-byte value(s) for the transparent APDU command and for SAM/SAV socket access (open slot, APDU to SAM, power/select) were not confirmed from a FEIG primary source. (On FEIG these are commonly in the 0xB0/0xB2/0xBx range but this was NOT verified against a FEIG doc here.)
- No public doc on how the cVEND maps host "IPP" commands to SAM sockets.

---

## Q5: MIFARE Ultralight / Ultralight-C command set and FEIG wrapping

### Takeaway
The Ultralight / Ultralight-C native command set the user listed is correct and public (READ 0x30, WRITE 0xA2, AUTHENTICATE 0x1A). FEIG wraps these either in its `0xB0` ISO14443-3/transparent command (OBID) or, on cVEND, via `feclr_transceive` of the raw PICC frames. `ProxCardUltralightC` in the firmware is the cVEND's Ultralight-C handler.

### Cited Findings
- MIFARE Ultralight C (NXP MF0ICU2) features 3DES authentication; the 3DES key resides in pages 0x2C–0x2F; AUTH0 config byte set via WRITE — [NXP MF0ICU2 datasheet](https://www.nxp.com/docs/en/data-sheet/MF0ICU2.pdf); [NXP community: Ultralight C password/protection](https://community.nxp.com/docs/DOC-341606)
- AUTHENTICATE command for Ultralight-C is `0x1A`, cited to datasheet §7.5.5, a two-part exchange: `0x1A` then `0xAF` follow-up for the encrypted-RndB/RndA steps — [NXP community (Ultralight C 3DES)](https://community.nxp.com/docs/DOC-341606)
- READ = `0x30` (returns 4 pages / 16 bytes from a given start page); WRITE = `0xA2` (writes one 4-byte page, ACK `0x0A`); AUTH = `0x1A` (Ultralight-C only) — [nfc-tools Ultralight C reference](https://nfc-tools.github.io/resources/rfid-tags/mifare-ultralight-c) and third-party guide (secondary; verify against NXP datasheet) — [RFID/NFC guide ch.4](https://gaelle-candel.neocities.org/ai-books/rfid-nfc-guide/04-mifare-ultralight.html)
- (Ultralight EV1 adds FAST_READ 0x3A, COMPATIBILITY_WRITE 0xA0, PWD_AUTH 0x1B, READ_CNT 0x39 — not separately re-sourced here but standard; flagged as not verified in this pass.)

### Inferences
- The firmware's `ProxCardUltralightC` implements the 0x1A/0xAF 3DES mutual-auth handshake plus 0x30/0xA2 page I/O over `feclr_transceive`. In a captured IPP/BC stream these would appear as the card-APDU payloads carried inside BC frames, with the first payload byte being the Ultralight opcode (0x30/0xA2/0x1A).

### Gaps
- Exact Ultralight-C AUTHENTICATE wire sequence (encrypted RndB length, IV handling) not quoted from the NXP datasheet (datasheet snippet did not expose it); values above from secondary/community sources.
- No public doc of how FEIG/cVEND specifically frames Ultralight commands inside IPP/BC.

---

## Q6: Public captures, GitHub projects, docs of the FEIG cVEND serial/host protocol

### Takeaway
There are public GitHub projects for FEIG's OBID standard/advanced RFID protocol, but **none found for the cVEND payment serial/"IPP" host protocol**. The cVEND protocol appears undocumented in public; the reverse-engineering effort is filling a genuine gap.

### Cited Findings
- amarok79 InlayTester.Drivers.FeigReader — C# serial driver implementing FEIG standard+advanced RFID protocol with the command table cited in Q1 — [GitHub amarok79/InlayTester.Drivers.FeigReader](https://github.com/amarok79/InlayTester.Drivers.FeigReader)
- fatzh/obidrfid — Python-ish helper exposing OBID reader functions (e.g., LAN config read) — [GitHub fatzh/obidrfid](https://github.com/fatzh/obidrfid)
- Fosstrak HAL FEIG implementation for ISC.LRU1000 / ISC.MR101-A — reference OBID integration — [Fosstrak HAL FEIG](https://fosstrak.github.io/hal/docs/user-feig.html)
- ROS `rfid_drivers` hosts a mirror of FEIG FEDM/FEISC C++ source (FEDM_ISCReaderModule.cpp includes feisc.h) — mirror, not official — [ROS rfid_drivers FEDM_ISCReaderModule](https://docs.ros.org/en/hydro/api/rfid_drivers/html/FEDM__ISCReaderModule_8cpp_source.html)
- Oracle Hospitality documents a "FEIG OBID RFID Encoder" integration (product-level, not protocol) — [Oracle FEIG OBID RFID Encoder](https://docs.oracle.com/en/industries/hospitality/cruise/property_management/20.3/dvice/c_feig_obid_rfid_encoder.htm)

### Inferences
- All public FEIG protocol code targets the OBID RFID side (STX 0x02 / FEISC). The absence of any cVEND/IPP/BC project reinforces that the "IPP" BC-framed protocol is a separate, closed payment-host protocol, so the OBID/FEISC code is useful only as a structural analogy (length-prefixed, CRC16-terminated, command/control-byte dispatch), not a drop-in reference.

### Gaps
- No public packet captures, Wireshark dissectors, or docs of the cVEND serial/host ("IPP") protocol were found.
- FEIG's official download portal (feig.de) reader-protocol PDFs are behind registration/gating; not retrieved here.
- The ROS FEISC header (full opcode list incl. any 0xB0/0xB2/0xBx names) is currently behind an Anubis bot-block and could not be fully extracted this pass; only `0x66` reader-info and the README-sourced common commands are confirmed.

---

## Cross-cutting summary for the mapping effort
- The documented FEIG OBID protocol: **STX=0x02**, 16-bit length covering the whole frame, 1-byte COM-ADR (bus address), 1-byte control byte (command), optional mode byte, data, **CRC16** trailer; advanced variant up to 65535 bytes. This is the closest *documented* FEIG framing — but it is 0x02-framed, not **0xBC**. Expect the IPP/BC protocol to share the *shape* (start byte, length, address/command, CRC) while differing in magic byte and command numbering.
- The firmware's `feclr_transceive` ≈ FEIG's `0xB0` ISO14443 transparent transceive, exposed as a local C API on the cVEND Linux OS.
- `emvco_ep_configure`/`emvco_ep_preprocess` = EMVCo Entry Point (Book B) — the device embeds an EMVCo L1 front-end + L2 kernels (cVEND L2).
- DESFire opcodes to look for in IPP payloads: 0x5A (SelectApplication), 0x0A/0x1A/0xAA (Authenticate), 0x60 (GetVersion), 0xBD/0x3D (Read/Write), 0xAF (additional frame). Ultralight-C: 0x30 (READ), 0xA2 (WRITE), 0x1A (AUTH), 0xAF (continuation).
- SAM/SAV: 4× SAM sockets; `SecurityServices.cpp` the likely controller; FEIG SAM command opcodes not publicly confirmed.
