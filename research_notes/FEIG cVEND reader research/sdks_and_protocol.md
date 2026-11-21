# FEIG reader SDKs, host libraries, and DESFire/APDU interfaces

This looks at what is publicly documented about how a host talks to FEIG readers:
SDKs, libraries, the FEIG standard/advanced serial protocol, DESFire and Ultralight
command wrapping, and APDU/SAM exchange. The goal is to map that against the
reverse-engineered `BC`-framed IPP protocol in a FEIG cVEND reader (fw 02.35) inside
an INIT PROXmobil3.

Sourcing note: FEIG's authoritative reader-protocol and FEDM/FEISC manuals are not
freely indexed in full. Much of the detail below comes from an open-source C#
reimplementation of FEIG's protocol, FEIG product datasheets, a Scribd copy of a
FEIG CPR70 manual surfaced through search snippets (unofficial, treat with care),
and NXP/public DESFire and Ultralight references. The cVEND-specific SDK and the
`feclr` API are distributed on request or under NDA and are not publicly documented.
That is a recurring gap.

## SDKs, the advanced/standard protocol, and the BC frame

FEIG's public reader family (OBID) uses a well-defined serial host protocol with
two framing variants, standard and advanced. Both begin with an STX `0x02` start
byte and end with CRC16. The SDK stack is FEDM (C++ data-exchange module) over
FEISC (protocol/command codec) over the transport libraries FECOM (serial), FEUSB,
and FETCL (TCP). No public FEIG source documents a `0xBC` magic start byte. That
strongly indicates the cVEND IPP protocol is a different, proprietary framing, not
the standard OBID advanced protocol.

Findings:

- FEIG's GEN3 Software Development Kit targets C++, .NET, and Java with an
  identical API across languages
  ([FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)).
- The OBID/FEDM C++ class library ("ID FEDM C++ Class Library", doc H10202-32e-ID-B,
  v4.06.06, 2014) is the "Part B.ISC" software-support document for OBID i-scan and
  OBID classic-pro readers. It embeds and uses the `feisc.h` FEISC command layer
  ([FEDM C++ manual](https://community.st.com/ysqtg83639/attachments/ysqtg83639/st25-nfc-rfid-tags-readers-forum/6729/1/C++%20FEDM%20-%20H10202-32e-ID-B.pdf);
  FEDM header mirror in
  [ROS rfid_drivers FEDM_ISCReaderID_8h](https://docs.ros.org/en/hydro/api/rfid_drivers/html/FEDM__ISCReaderID_8h.html)).
- A FEISC command code example from the ROS mirror: `FEISC_READER_INFO 0x66`
  ([ROS rfid_drivers feisc_8h](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h.html);
  the page now returns an Anubis bot block, and the value was surfaced through the
  search index).
- The open-source C# reimplementation (amarok79 InlayTester.Drivers.FeigReader)
  states it "supports all Feig RFID reader/modules that run Feig's standard or
  advanced protocol." The protocol is a global or per-call setting,
  `Protocol = FeigProtocol.Advanced` or `.Standard`
  ([GitHub amarok79/InlayTester.Drivers.FeigReader](https://github.com/amarok79/InlayTester.Drivers.FeigReader)).
- Documented FEIG common command codes, as the control byte in the command
  position, from the FeigReader README "Common Commands" table:
  - `0x52` Baud Rate Detection (TestCommunication)
  - `0x63` CPU Reset
  - `0x65` Get Software Version
  - `0x66` Reader Info (from the ROS mirror)
  - `0x69` RF Reset
  - `0x80` Read Configuration / `0x81` Write Configuration / `0x82` Save
    Configuration / `0x83` Set Default Configuration
  - `0x0B 0x01` Inventory (ISO Standard), a two-byte command (mode plus
    subcommand)
- Standard versus advanced frame capacity: the standard protocol is limited to 255
  bytes total and is "not recommended for new applications." The advanced protocol
  frame can transfer up to 65535 bytes per frame, and the reader answers an
  advanced-protocol request with an advanced-protocol frame
  ([FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual);
  corroborated for OBID classic-pro, where the reader selects an advanced frame when
  the response exceeds 255 bytes
  ([OBID classic-pro series manual](https://manualslib.com/manual/1633605/Feig-Electronic-Obid-Classic-Pro-Series.html))).
- Advanced protocol frame layout, request:
  `STX(0x02) | ALENGTH(2 bytes, big-endian, whole frame including STX and CRC) |
  bus address (COM-ADR) | control byte (command) | [mode] | data... | CRC16(2)`.
  Response: `STX(0x02) | ALENGTH(2) | COM-ADR | control byte | STATUS | data... |
  CRC16(2)`
  ([FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)).
- Worked example traffic from the CPR70 copy: request
  `02 00 09 FF B0 01 00 18 43`; response
  `02 00 13 00 B0 00 01 03 D1 E0 04 02 00 00 01 AA 76 B1 94`. Here `02` is STX,
  `00 09`/`00 13` is length covering the whole frame, `FF`/`00` is bus address,
  `B0` is the control byte (ISO14443 host command), `01` is mode on the request,
  and response `00` after B0 is STATUS OK.
- Notation convention in FEIG manuals: a hex value in brackets, such as `[0x52]`,
  denotes a control byte or command
  ([FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)).

Inference: the FEIG standard/advanced OBID protocol uses STX `0x02`, not `0xBC`.
The cVEND IPP/`BC`-magic framing is therefore almost certainly a separate FEIG
payment-side protocol, not the OBID RFID host protocol. The two may coexist. The
RFID front end is spoken internally through FEISC-style `0xB0` commands, while the
external host link to the PROXmobil3 uses `BC`/IPP.

`feclr_transceive` and `Ipp.cpp` in the firmware suggest the cVEND runs a Linux app
stack where the application talks to the contactless front end through the `feclr`
library, while the external serial link uses the IPP/BC protocol. That is a layering
distinct from FEDM/FEISC. The `0xB0` control byte with a leading mode byte is FEIG's
generic "ISO14443 host command" dispatcher. The firmware's `feclr_transceive` is
the functional analogue, sending raw bytes to the PICC and getting a response, as
exposed at the cVEND SDK level.

Gaps: no public source confirms a `0xBC` start byte or "BC magic" anywhere in
FEIG's documented protocol. The IPP framing appears undocumented publicly. The
exact CRC16 polynomial and seed for the FEIG advanced protocol was not extracted
from a primary source. FEIG uses CRC16 per ISO; typical readers use CRC16-CCITT
with preset 0xFFFF and polynomial 0x8408 or 0x1021, but that was not verified
against a FEIG doc here. The full FECOM/FEUSB/FETCL transport API was not
retrieved; the download portal is gated.

## The feclr prefix

"feclr" is almost certainly FEIG ContactLess Reader, the cVEND-side library and API
for driving the contactless front end, analogous to "transceive to card." It is not
publicly documented. The cVEND SDK ("cVEND.OS & SDK") is Linux-based and provided
only on request or under NDA. No public headers for `feclr_transceive` were found.

Findings:

- cVEND plug flex runs a "secure Linux OS" and "comes with an SDK on request." It
  is positioned for system integrators writing their own Level 3 payment
  application
  ([cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf);
  [cVEND plug flex product page](https://www.feig.de/en/products/payment/product/cvend-plug-flex/)).
- cVEND compact II is a "flexible secure Linux platform" with a "Linux-based
  cVEND.OS & SDK" for developers
  ([cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- Architecture: "secure Linux operating system and an architecture of eight
  independent application directories" to run open-loop payment and closed-loop
  ticketing in parallel
  ([Pressebox: FEIG Multi-Application](https://www.pressebox.com/pressrelease/feig-electronic-gmbh/FEIGs-Multi-Application-technique-gives-a-boost-to-transaction-speed-of-mass-transit-systems/boxid/851978)).
- The cVEND flex I variant ships "a fully configured payment operating system,
  without level 2 kernel or level 3 host applications," so the integrator supplies
  their own kernels and L3. Flex II includes certified L2 kernels
  ([cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf);
  [FEIG cVEND L2](https://www.feig.de/en/cvend-l2/)).
- The support contact for the cVEND SDK is `cvend-support@feig.de`
  ([FEIG cVEND user manual](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual);
  the body returned 403 on fetch).

Inference: `feclr_*` is the FEIG ContactLess Reader library. `feclr_transceive` is
raw ISO14443-4 and lower send/receive to the PICC, the building block the EMV L2
kernel and any closed-loop DESFire/Ultralight app use. This mirrors the role of
FEISC's `0xB0` ISO command on OBID readers, but is exposed as a C library on the
cVEND Linux OS rather than over the wire.

`emvco_ep_configure` and `emvco_ep_preprocess` are EMVCo Entry Point (Book B)
function names, the preprocessing and combination-selection stage of a contactless
transaction. That confirms the firmware embeds an EMVCo Entry Point and L2 kernels,
consistent with cVEND L2 certification. `RFIDReaderMultiApp.cpp` aligns with FEIG's
advertised Multi-Application / eight-application-directory design.

Gaps: no public `feclr` header, function signature, or man page was found. The API
surface (`feclr_transceive`, reader open/close/field control) is NDA/SDK-gated. No
public doc ties `Ipp.cpp` to a named FEIG protocol. "IPP" is not resolved from
public FEIG materials. The `feig` app loader and application-directory loading
mechanism are not publicly documented beyond marketing descriptions.

## DESFire and the native command set

`m075031` is an NXP document-number-style identifier. `m075031_desfire.pdf` is
almost certainly an NXP MIFARE DESFire functional or command specification, in
NXP's internal doc-number format, usually NDA. The native DESFire datasheet is
NDA-classified, but the command opcodes are well known from public
reimplementations.

Findings:

- NXP confirms the native DESFire datasheet is NDA-classified and points developers
  to public ISO7816 commands
  ([MIFARE.net forum reply](https://www.mifare.net/support/forum/reply/27490/)).
- DESFire native command codes, from python-desfire supported commands and NXP
  AN12752
  ([python-desfire supported commands](https://python-desfire.readthedocs.io/en/latest/supported-commands/)):
  - Authenticate (legacy DES/3DES): `0x0A`
  - AuthenticateISO (3K3DES): `0x1A`
  - AuthenticateAES: `0xAA`
  - AuthenticateEV2First: `0x71`; AuthenticateEV2NonFirst: `0x72`
  - GetVersion: `0x60`, with `0xAF` additional-frame continuations
  - SelectApplication: `0x5A` (3-byte AID)
  - GetApplicationIDs: `0x6A`; CreateApplication: `0xCA`; DeleteApplication:
    `0xDA`
  - GetFileIDs: `0x6F`; GetFileSettings: `0xF5`; CreateStdDataFile: `0xCD`;
    DeleteFile: `0xDF`
  - ReadData: `0xBD`; WriteData: `0x3D`
  - ChangeKey: `0xC4`; GetKeySettings: `0x45`; ChangeKeySettings: `0x54`;
    GetKeyVersion: `0x64`
  - GetRealUID/GetCardUID: `0x51`; ChangePICCConfiguration: `0x5C`;
    FormatPICC: `0xFC`
  - Additional Frame / continuation: `0xAF`, also the "more data" status
  ([NXP AN12752](https://www.nxp.jp/docs/en/application-note/AN12752.pdf))
- GetVersion is supported on EV1/EV2/EV3. Authenticate `0x0A` is supported on
  EV1/EV2/EV3
  ([NXP AN12752](https://www.nxp.jp/docs/en/application-note/AN12752.pdf)).
- A selected application stays active until an error or another AID is selected
  ([MIFARE.net forum reply](https://www.mifare.net/support/forum/reply/27490/)).
- DESFire supports both native command framing and ISO7816-4 APDU wrapping.
  DESFire Light is "fully compliant with ISO/IEC 14443-4 and ISO/IEC 7816-4."
  Native commands can be wrapped in ISO7816 APDUs with `CLA=0x90`, `INS=command
  code`, `P1=P2=0x00`, data, `Le=0x00`, the wrapped mode, with status `SW1SW2 =
  91 00` (OK) or `91 AF` (additional frame)
  ([MIFARE application programming guide for DESFire rev.e](https://scancode.ru/upload/iblock/de4/mifare_application_programming_guide_for_desfire_rev.e.pdf)).

Inference: `ProxCardUltralightC` and DESFire references in the firmware indicate
the cVEND closed-loop app layer implements native DESFire and Ultralight-C command
flows over `feclr_transceive`, beyond EMV. `m075031_desfire.pdf` being referenced
in firmware strings means the FEIG developers worked from NXP's DESFire functional
spec (NDA) to implement the command set. The number format `mNNNNNN` is
characteristic of NXP document IDs.

Gaps: the precise title and edition of `m075031_desfire.pdf` cannot be confirmed;
the NDA doc is not public. The opcodes above are corroborated from independent
public reimplementations, not that document. The DESFire status/error code table
(0x0C, 0x0E, 0x1C, 0x1E, 0x9D, 0x9E, 0xAE, 0xAF, 0xBE, 0xCA, 0xF0, and others)
was not fully enumerated from a primary source.

## APDU proxy, transparent channel, and SAM control

FEIG readers expose raw ISO14443-4 / ISO7816 APDU exchange to the host through a
transparent transceive command, and provide SAM/SAV sockets controlled by dedicated
host commands. The exact FEIG opcode values for the transparent and SAM commands
were not confirmed from a primary FEIG source. The concept and the SAM hardware are
documented. The cVEND's `feclr_transceive` is the on-device equivalent of the
transparent APDU channel.

Findings:

- cVEND readers offer four SAM sockets, optionally through a SAM Extension Board
  ([cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf);
  [cVEND Vending Extension Board datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_Vending_Extension_Board_EN.pdf)).
- A FEIG CPR70 manual lists a "Supported Host Commands" section with a
  "Transparent" entry, snippet only, no byte detail
  ([FEIG CPR70 manual copy, Scribd](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)).
- Comparative industry context, not FEIG-specific: PC/SC transparent transceive
  uses `CLA=0xFF INS=0xC2` (ENVELOPE-modeled), returning card data transparently
  and allowing protocol switching between ISO14443-3 and -4
  ([PC/SC part 3 v2.02.00 supplement](https://kolegite.com/EE_library/standards/pcsc3_v2.02.00_sup2.pdf)).
  Microsoft NFC storage-card APDUs use `INS 0xB0` (Read Binary) and a
  transparent-exchange `INS 0xC2`
  ([Microsoft storage card requirements](https://learn.microsoft.com/en-us/windows-hardware/drivers/nfc/storage-card-requirements)).
  NXP MIFARE SAM AV3 transparent exchange uses `INS 0x7E`
  ([NXP SAM/DESFire AN](https://www.nxp.com.cn/docs/en/application-note/AN12705.pdf)).
  Baltech provides a raw ISO14443-4 APDU exchange channel where the reader does not
  interpret the data
  ([Baltech ISO14B transparent command](https://docs.baltech.de/refman/cmds/iso14b/index.html)).

Inference: on OBID readers the FEIG transparent/APDU exchange is reached through
the `0xB0` ISO14443 host command family, where the mode byte selects
Request/Anticollision/Select/Authenticate/Read/Write/Transparent. FEDM exposes this
as a `FEISC_0xB0_ISOCmd`-style call. The cVEND replaces the over-the-wire `0xB0`
with the local `feclr_transceive` C call. `SecurityServices.cpp` in the firmware is
the likely home of SAM/SAV socket control and key/crypto services, consistent with
the four SAM sockets and the "SAV" (Secure Authentication/Access) naming.

Gaps: the exact FEIG control-byte values for the transparent APDU command and for
SAM/SAV socket access (open slot, APDU to SAM, power/select) were not confirmed
from a FEIG primary source. On FEIG these are commonly in the `0xB0`/`0xB2`/`0xBx`
range, but that was not verified against a FEIG doc. There is no public doc on how
the cVEND maps host IPP commands to SAM sockets.

## MIFARE Ultralight / Ultralight-C and FEIG wrapping

The Ultralight and Ultralight-C native command set is public: READ `0x30`, WRITE
`0xA2`, AUTHENTICATE `0x1A`. FEIG wraps these either in its `0xB0` ISO14443-3 or
transparent command on OBID, or, on cVEND, through `feclr_transceive` of the raw
PICC frames. `ProxCardUltralightC` in the firmware is the cVEND's Ultralight-C
handler.

Findings:

- MIFARE Ultralight C (NXP MF0ICU2) has 3DES authentication. The 3DES key resides
  in pages 0x2C to 0x2F, and the AUTH0 config byte is set through WRITE
  ([NXP MF0ICU2 datasheet](https://www.nxp.com/docs/en/data-sheet/MF0ICU2.pdf);
  [NXP community: Ultralight C password/protection](https://community.nxp.com/docs/DOC-341606)).
- The AUTHENTICATE command for Ultralight-C is `0x1A`, cited to datasheet section
  7.5.5. It is a two-part exchange: `0x1A`, then `0xAF` for the encrypted RndB and
  RndA steps
  ([NXP community](https://community.nxp.com/docs/DOC-341606)).
- READ is `0x30` (returns four pages or 16 bytes from a start page). WRITE is
  `0xA2` (writes one 4-byte page, ACK `0x0A`). AUTH is `0x1A`, Ultralight-C only
  ([nfc-tools Ultralight C reference](https://nfc-tools.github.io/resources/rfid-tags/mifare-ultralight-c)
  and a secondary
  [RFID/NFC guide ch.4](https://gaelle-candel.neocities.org/ai-books/rfid-nfc-guide/04-mifare-ultralight.html);
  verify against the NXP datasheet).
- Ultralight EV1 adds FAST_READ `0x3A`, COMPATIBILITY_WRITE `0xA0`, PWD_AUTH
  `0x1B`, and READ_CNT `0x39`. These are standard, but were not separately
  re-sourced and are flagged as not verified here.

Inference: the firmware's `ProxCardUltralightC` implements the `0x1A`/`0xAF` 3DES
mutual auth handshake plus `0x30`/`0xA2` page I/O over `feclr_transceive`. In a
captured IPP/BC stream these would appear as card-APDU payloads inside BC frames,
with the first payload byte being the Ultralight opcode (`0x30`, `0xA2`, or
`0x1A`).

Gaps: the exact Ultralight-C AUTHENTICATE wire sequence (encrypted RndB length, IV
handling) was not quoted from the NXP datasheet; the datasheet snippet did not
expose it. The values above come from secondary and community sources. There is no
public doc of how FEIG or cVEND frames Ultralight commands inside IPP/BC.

## Public captures and projects

There are public GitHub projects for FEIG's OBID standard/advanced RFID protocol,
but none found for the cVEND payment serial IPP host protocol. The cVEND protocol
appears undocumented in public, and this reverse-engineering effort is filling a
gap.

Findings:

- amarok79 InlayTester.Drivers.FeigReader: a C# serial driver implementing FEIG
  standard and advanced RFID protocol with the command table above
  ([GitHub](https://github.com/amarok79/InlayTester.Drivers.FeigReader)).
- fatzh/obidrfid: a Python helper exposing OBID reader functions, such as LAN
  config read
  ([GitHub fatzh/obidrfid](https://github.com/fatzh/obidrfid)).
- Fosstrak HAL FEIG implementation for ISC.LRU1000 and ISC.MR101-A: a reference
  OBID integration
  ([Fosstrak HAL FEIG](https://fosstrak.github.io/hal/docs/user-feig.html)).
- ROS `rfid_drivers` hosts a mirror of FEIG FEDM/FEISC C++ source
  (`FEDM_ISCReaderModule.cpp` includes `feisc.h`), a mirror, not official
  ([ROS rfid_drivers FEDM_ISCReaderModule](https://docs.ros.org/en/hydro/api/rfid_drivers/html/FEDM__ISCReaderModule_8cpp_source.html)).
- Oracle Hospitality documents a "FEIG OBID RFID Encoder" integration at the
  product level, not protocol
  ([Oracle FEIG OBID RFID Encoder](https://docs.oracle.com/en/industries/hospitality/cruise/property_management/20.3/dvice/c_feig_obid_rfid_encoder.htm)).

Inference: all public FEIG protocol code targets the OBID RFID side (STX `0x02`,
FEISC). The absence of any cVEND/IPP/BC project reinforces that the IPP
BC-framed protocol is a separate, closed payment-host protocol. OBID/FEISC code is
useful only as a structural analogy: length-prefixed, CRC16-terminated,
command/control-byte dispatch. It is not a drop-in reference.

Gaps: no public packet captures, Wireshark dissectors, or docs of the cVEND serial
IPP protocol were found. FEIG's official download portal reader-protocol PDFs are
behind registration and gating and were not retrieved. The ROS FEISC header, with
the full opcode list including any `0xB0`/`0xB2`/`0xBx` names, is behind an Anubis
bot block and could not be fully extracted. Only `0x66` reader info and the
README-sourced common commands are confirmed.

## Summary for the mapping effort

- The documented FEIG OBID protocol: `STX=0x02`, 16-bit length covering the whole
  frame, 1-byte COM-ADR, 1-byte control byte (command), optional mode byte, data,
  CRC16 trailer. The advanced variant goes up to 65535 bytes. This is the closest
  documented FEIG framing, but it is `0x02`-framed, not `0xBC`. Expect IPP/BC to
  share the shape (start byte, length, address/command, CRC) while differing in
  magic byte and command numbering.
- The firmware's `feclr_transceive` is roughly FEIG's `0xB0` ISO14443 transparent
  transceive, exposed as a local C API on the cVEND Linux OS.
- `emvco_ep_configure` and `emvco_ep_preprocess` are EMVCo Entry Point (Book B).
  The device embeds an EMVCo L1 front end and L2 kernels (cVEND L2).
- DESFire opcodes to look for in IPP payloads: `0x5A` SelectApplication,
  `0x0A`/`0x1A`/`0xAA` Authenticate, `0x60` GetVersion, `0xBD`/`0x3D` Read/Write,
  `0xAF` additional frame. Ultralight-C: `0x30` READ, `0xA2` WRITE, `0x1A` AUTH,
  `0xAF` continuation.
- SAM/SAV: four SAM sockets. `SecurityServices.cpp` is the likely controller. FEIG
  SAM command opcodes are not publicly confirmed.
