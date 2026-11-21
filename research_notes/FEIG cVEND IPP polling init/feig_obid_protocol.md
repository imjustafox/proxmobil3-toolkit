# FEIG OBID and cVEND serial protocol: reader init and ISO14443 polling

FEIG runs two parallel product and protocol worlds. The OBID / ID ISC classic-pro /
i-scan RFID readers use a fully public serial "Reader Protocol" with ASCII or binary
frames and command bytes like `0x69`, `0xB0`, and `0x0B`. The cVEND payment
terminals (plug, plug flex, compact II) are a separate secure-payment line whose
host/application interface (certificate handshake, INITIALIZED state, `feclr`-style
API) is distributed only under NDA or on request.

Claims below are marked as FEIG-generic (OBID reader protocol, which applies to the
RF front end under cVEND) or cVEND-specific (payment terminal app layer). Where
cVEND internals could not be confirmed from public sources, that is stated.

## OBID protocol family and standard commands

FEIG's OBID readers speak the documented FEIG Reader Protocol: the OBID classic-pro
and ID ISC "Advanced Protocol" and "Standard Protocol" frame formats. Core host
commands are identified by a single control byte. RF Reset is `0x69`, the ISO15693
host-command group is `0xB0` (subcommand `0x01` is Inventory), the newer unified ISO
Standard Host Command is `0x0B` (subcommand `0x01` is Inventory across
ISO14443A/B/15693), the configuration block is `0x80`-`0x83`, and there are
Buffered Read Mode and Notification Mode protocols.

Public findings:

- FEIG ships two frame formats: Standard Protocol and Advanced Protocol
  (`FeigProtocol.Standard` and `FeigProtocol.Advanced` in the open-source C#
  driver that re-implements the protocol). A request carries Address (bus address,
  COM-ADR), Command, and Data. A response carries Status and Data. Transfer status
  includes Success, Timeout, Canceled, ChecksumError, and reader status
  `FeigStatus.OK`
  ([Amarok79/InlayTester.Drivers.FeigReader](https://github.com/Amarok79/InlayTester.Drivers.FeigReader)).
- That C# driver documents these control-byte commands: `0x52` Baud Rate Detection
  (`TestCommunication()`), `0x63` CPU Reset (`ResetCPU()`), `0x65` Get Software
  Version/Info (`GetSoftwareInfo()`), `0x69` RF Reset (`ResetRF()`), `0x80` Read
  Configuration, `0x81` Write Configuration, `0x82` Save Configuration, `0x83` Set
  Default Configuration, and `0x0B 0x01` Inventory (ISO Standard Host Command).
- The FEISC function library defines `FEISC_RF_RESET = 0x69` and
  `FEISC_ISO_COMMAND = 0xB0`, with a prototype
  `FEISC_0x69_RFReset(int iReaderHnd, unsigned char cBusAdr)`. This comes from the
  ROS `rfid_drivers` doxygen for FEIG's `feisc.h` (search-extracted; the page is
  behind a bot wall)
  ([docs.ros.org feisc.h](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h.html)).
- The `0xB0` group is "Host Commands for ISO15693," and within it `[0x01]` is
  Inventory (mandatory). The OBID i-scan ID ISC.PR101/MR101 manual lists
  `[0xB0]` host commands with `[0x01]` Inventory and lists `[0x69]` RF Reset as a
  separate section
  ([Feig OBID i-scan ID ISC.PR101/MR101/PRH101 manual](https://manualmachine.com/feigelectronic/obidiscanidiscmr101/23026941-user-manual)).
- Pepperl+Fuchs, an OBID OEM reseller, documents the same `[0xB0]` host commands
  with `[0x01]` Inventory as the first subcommand
  ([Pepperl+Fuchs OBID manual tdoct8610](https://files.pepperl-fuchs.com/webcat/navi/productInfo/doct/tdoct8610__eng.pdf)).
- The classic-pro CPR30.xx manual groups other command sets by protocol, for
  example `[0xBE]` ISO14443B Transparent Command and `[0xC0]` SAM Commands,
  confirming that command bytes are organized per card standard
  ([Feig OBID classic-pro Series Manual](https://manualslib.com/manual/1633605/Feig-Electronic-Obid-Classic-Pro-Series.html)).
- The FEDM C++ layer exposes Host-Mode inventory results keyed by command
  `[0xB0][0x01]` through `FEDM_ISOTabItem`, the per-tag table item holding the UID
  and other fields
  ([docs.ros.org FEDM_ISOTabItem](https://docs.ros.org/en/hydro/api/rfid_drivers/html/classFEDM__ISOTabItem.html)).
- Operating modes: OBID readers support Host Mode, Scan Mode, Buffered Read Mode
  (BRM), and Notification Mode, selected by configuration bits. Per the
  ID ISC.LR1002 manual, BRM is available only if Scan Mode is disabled, and
  Notification Mode is enabled by a config bit and works only with BRM
  ([Feig OBID ID ISC.LR1002 Manual](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- In BRM and Notification Mode the host retrieves collected tags with `[0x22]` Read
  Buffer
  ([RF-R400 System Manual](https://www.scribd.com/document/550696239/RF-R400-System-Manual)).
- Inventory can be configured to stop once the UIDs of all ISO14443A or
  ISO14443B transponders in range have been read, controlled by an Inventory-abort
  config parameter, per the CPR70 manual
  ([FEIG CPR70 Manual](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)).
- FEIG's official SDK datasheet confirms two API families: a Reader Control API and
  an Auto Read Mode API for getting collected data from a reader working in BRM or
  Notification Mode
  ([FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)).

Inference: there are two Inventory encodings in the FEIG world, and the correct one
depends on reader firmware and command set. The classic per-standard group is
`0xB0 0x01` for ISO15693 Inventory, with an analogous ISO14443 host-command group
in the same byte range, around `0xB2`/`0xBE`. The unified ISO Standard Host Command
is `0x0B` with subcommand `0x01`, which selects the air standard (ISO14443A/B or
15693) through a mode byte in the payload. For a modern reader, `0x0B 0x01` is the
single call that returns ISO14443 UIDs. On older firmware you use the per-standard
group.

The control byte is the FEIG command/control byte. A full frame also wraps it with
STX, length, COM-ADR, status byte, and CRC16. The C# driver's ChecksumError status
implies a checksum, though the exact CRC16 polynomial was not captured.

Gaps: the exact byte-level frame layout (STX `0x02`, 2-byte length, COM-ADR,
control byte, LEN/DATA, 1-byte status, CRC16-CCITT polynomial and seed) was not
captured from a primary FEIG manual here. The authoritative frame tables live in
the FEIG ID ISC system manuals and in `feisc.h`, both of which were bot-walled or
not opened in full. RF Output ON/OFF as a dedicated command, sometimes cited as
`0x6A`, was not confirmed from any source here. Public OBID docs expose RF antenna
power control through `0x69` RF Reset and through configuration (`0x80`/`0x81`,
RF-power config block) rather than a simple on/off opcode. Treat `0x6A` as
unverified.

## Does cVEND use a transparent layer on OBID?

cVEND is a secure payment terminal, not a bare OBID reader. It exposes a
FEIG-proprietary secure host protocol with a payment mode and a transparent card
reader mode, and its startup performs a device-certificate or secure-session step
before it will read cards. That application layer, including the certificate
validity report and INITIALIZED transition, is documented only in NDA SDK and
integration material available on request. It was not found in any public source.

Public findings:

- The FEIG cVEND user manual says the reader "offers an easy to use secure
  protocol" and "can be used in payment mode as well as in transparent card reader
  mode," confirming a transparent raw-card mode layered on the secure payment
  stack. Support is gated behind `cvend-support@feig.de` (technical) and
  `cvend@feig.de` (commercial)
  ([Feig cVEND User Manual](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual)).
- cVEND terminals carry manufacturer-issued X.509 device certificates used for key
  encryption and device authentication
  ([SFEY TPS Device API, Key Management](https://sfeydocs.sfey.com/docs/doc-api-spec/API%20v3.0/TPS%20Device%20API/Terminal%20Registration/03%20Key%20Management%20Automatic)).
- cVEND compact II supports ISO/IEC 14443-A/B and ISO/IEC 15693 at the card layer,
  with card detection for MIFARE, Calypso, Sony FeliCa, and NFC devices in
  card-emulation mode. It is a secure device designed for local or remote
  application and key loading, with L2 customization
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- cVEND host and physical interfaces include RS232, USB 2.0 OTG, and Ethernet,
  plus LTE on compact II. The serial/UART host interface in scope is the
  RS232/USB-CDC link
  ([FEIG cVEND compact II datasheet](https://www.feig.de/wp-content/uploads/FEIG_Data-sheet-cVEND-compact-II-Platform-for-App-Development.pdf)).
- cVEND datasheets for plug flex and NMI state "Development devices, tools and SDK
  available on request," so the protocol and SDK are distributed privately
  ([cVEND plug flex datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_flex_EN.pdf);
  [cVEND plug NMI datasheet](https://feig.de/wp-content/uploads/Data_sheet_cVEND_plug_NMI_EN.pdf)).
- cVEND runs a renewable payment kernel (EMV L2) that FEIG updates in the field,
  indicating a firmware/application layer distinct from the raw RFID front end
  ([FEIG cVEND kernel renewal](https://www.FEIG.de/fileadmin/user_upload/Downloads/News/2022-06-15_cVEND_kernel_renewal_is_complete_en.pdf)).

Inference: the observed boot behavior ("device certificates valid until <date>"
then INITIALIZED before card reads) is consistent with a PCI/EMV secure-boot and
device-attestation handshake. The terminal validates its X.509 device/key
certificates at power-up, unlocks the secure app and keys, and only then enables
the contactless field and card polling. That matches the X.509 device-certificate
and local/remote key-loading design FEIG documents. The specific log string and the
INITIALIZED state machine are cVEND firmware internals and are not public.

Transparent card reader mode is the path to a raw ISO14443 UID without payment
authentication on cVEND. The secure payment protocol wraps the same OBID RF front
end, and transparent mode exposes near-raw reader behavior once the terminal has
reached INITIALIZED.

Gaps: no public document describes the cVEND startup certificate handshake byte
sequence, the "device certificates valid until" report, or the INITIALIZED state
transition. These are in the NDA cVEND SDK / FEIG Service Interface documentation
only. Whether transparent mode is reachable before certificate validation
completes, or only after INITIALIZED, is unconfirmed; inference says after.

## SDK APIs for polling and raw UID

Two SDK stacks exist. For OBID readers, the public FEIG stack is FEISC (C function
library), then FEDM (C++ class library), then FETCP/FECOM transport. `FEISC_0x0B`
or `0xB0` Inventory plus `FEDM_ISOTabItem` gives the raw UID with no application
keys. For cVEND, FEIG uses a separate contactless-reader library, the `feclr`-style
FEIG Contactless Reader API. Its function names and the get-UID-in-transparent-mode
call are NDA-only and were not found publicly.

Public findings:

- FEISC is a function library (DLL/SO), and FEDM is the C++ class library built on
  top (FEDM Core/CoreAPI alongside FEISC and FETCP). FEDM's `FEDM_ISCReaderModule`
  drives readers. Its changelog references `FEISC_TASKID_FIRST_NEW_TAG`
  (continuous/async inventory task) and `TagInventory` with TagHandler support for
  up to 10-byte UIDs, covering 4-, 7-, and 10-byte ISO14443A UIDs
  ([docs.ros.org FEDM_ISCReaderModule.cpp](https://docs.ros.org/en/hydro/api/rfid_drivers/html/FEDM__ISCReaderModule_8cpp_source.html)).
- Raw UID, pre-auth: `[0xB0][0x01]` or `0x0B 0x01` Inventory performs ISO
  anticollision and returns the transponder serial number (UID) itself. No MIFARE
  or application key is needed for Inventory; keys are only required for later
  block Read/Write/Authenticate. `FEDM_ISOTabItem` is the result record holding
  each tag's UID from a Host-Mode `[0xB0][0x01]` inventory
  ([docs.ros.org FEDM_ISOTabItem](https://docs.ros.org/en/hydro/api/rfid_drivers/html/classFEDM__ISOTabItem.html);
  [Amarok79 InlayTester](https://github.com/Amarok79/InlayTester.Drivers.FeigReader)).
- FEIG's official SDK (GEN3) provides a common API across C++, C#, and Java, with a
  Reader Control API (direct commands including Inventory) and an Auto Read Mode
  API (BRM/Notification collection)
  ([FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf)).
- Open-source reimplementations confirm raw-UID polling over serial without keys.
  The C# `IFeigReader.Inventory()` returns tag IDs for ISO14443A/B and ISO15693. A
  Node.js driver's `reader.inventory()` returns `{status, raw, tags}` with tag IDs,
  tested on ID CPR40.xx and CPR74.xx over USB VID 0x0AB1/2737
  ([Amarok79 InlayTester](https://github.com/Amarok79/InlayTester.Drivers.FeigReader);
  [joostkamphuisnl/feig-driver README](https://worker-github.zxx930427.workers.dev/joostkamphuisnl/feig-driver)).

Inference: for raw ISO14443 UID from an OBID/cVEND RF front end pre-auth, the
minimal host sequence is optionally `0x52` Baud Rate Detection to sync, `0x65` Get
Software Info, `0x69` RF Reset to energize/reset the field, then `0x0B 0x01` (or
`0xB0 0x01`) Inventory, and parse `FEDM_ISOTabItem` or the response data for the
UID. No keys are involved. For continuous detection, use BRM/Notification Mode plus
`0x22` Read Buffer, or the Auto Read Mode API
(`FEISC_TASKID_FIRST_NEW_TAG`).

`feclr` is almost certainly FEIG's FEIG Contactless Reader C library, specific to
the cVEND/transit payment stack and parallel to FEISC for OBID. Its existence is
implied by FEIG's architecture but could not be sourced. The raw-UID call in cVEND
transparent mode is the `feclr` analog of FEISC Inventory.

Gaps: no public source names any `feclr_*` function, such as a hypothetical
`feclr_startCardPolling` or `feclr_getCardInfo`. `feclr` and `libfecom` returned
zero public hits. These are NDA cVEND SDK symbols; confirm with FEIG. The exact
FEISC/FEDM spelling for one-shot inventory (`FEISC_0x0B_ISOCmd` versus
`FEISC_0xB0_ISOCmd`, and the FEDM method such as
`FEDM_ISCReader::sendProtocol(0xB0)` or `::inventory()`) was not captured verbatim
because the doxygen pages were bot-walled.

## Command codes: enable card type, start/stop polling, LED, buzzer, card detection

On OBID readers these are mostly configuration-register writes plus Inventory and
mode commands, not one-off opcodes. Card types are enabled in a configuration block
(`0x80`/`0x81`). "Start polling" means entering BRM/Scan/Notification mode or
issuing `0x0B`/`0xB0` Inventory; "stop" means RF Reset or a mode change. LED and
buzzer are driven through output/notification configuration. cVEND exposes
payment-terminal LED, buzzer, and card detect through its secure app protocol,
which is NDA.

Public findings:

- Enable card type: done through the Read/Write Configuration block. `0x80` Read
  Configuration, `0x81` Write Configuration, `0x82` Save Configuration, `0x83` Set
  Default Configuration. The config parameters select which transponder
  drivers/standards (ISO14443A/B, ISO15693, and others) are active
  ([Amarok79 InlayTester](https://github.com/Amarok79/InlayTester.Drivers.FeigReader);
  [FEIG CPR70 Manual](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)).
- Start/stop polling: "start" is issuing `0x0B 0x01` or `0xB0 0x01` Inventory (a
  single scan), or enabling Buffered Read/Scan/Notification Mode through config.
  The reader then auto-polls and the host reads tags with `0x22` Read Buffer. Mode
  bits are mutually constrained: BRM needs Scan off, Notification needs BRM on
  ([Feig OBID ID ISC.LR1002 Manual](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html);
  [RF-R400 System Manual](https://www.scribd.com/document/550696239/RF-R400-System-Manual)).
- Card-detected notification: in Notification Mode the reader asynchronously
  pushes a Notification frame when a new tag enters the field. It works only with
  BRM. FEIG's SDK Auto Read Mode API and the `FEISC_TASKID_FIRST_NEW_TAG` task
  deliver these new-tag events
  ([FEIG SDK GEN3 datasheet](https://feig.de/wp-content/uploads/Data_sheet_Software_Development_Kit_GEN3.pdf);
  [docs.ros.org FEDM_ISCReaderModule.cpp](https://docs.ros.org/en/hydro/api/rfid_drivers/html/FEDM__ISCReaderModule_8cpp_source.html)).
- RF reset and field control: `0x69` RF Reset resets or re-energizes the RF field,
  effectively stop plus restart polling
  ([Amarok79 InlayTester](https://github.com/Amarok79/InlayTester.Drivers.FeigReader);
  [feisc.h](https://docs.ros.org/en/hydro/api/rfid_drivers/html/feisc_8h.html)).

Inference: there is no single "enable card type" or "start polling" opcode on
classic OBID. Integration is: write config (card drivers and mode), save, RF reset,
then Inventory/BRM. This is the FEIG-generic pattern cVEND inherits at the RF layer.

LED and buzzer: OBID readers that have them drive them through output/notification
configuration parameters, and some expose an output-port or Set Output command, not
a universally named opcode. On cVEND, LED and buzzer are part of the
payment-terminal UI controlled by the secure app protocol (display, LED, beep
commands), which is cVEND-specific.

Gaps: no public source gives a dedicated LED-control or buzzer-control command
opcode for OBID or cVEND. OBID uses config/output parameters; cVEND uses its NDA
app protocol. A FEIG Set Output or port-control command exists on some readers but
was not pinned to a hex code here. The cVEND-specific enable-card-reading,
start-poll, card-present, LED, and buzzer opcodes in the secure payment protocol
are not public. They are in the NDA cVEND SDK / FEIG Service Interface spec.

## Source quality

The most authoritative primary sources (FEIG ID ISC system manuals, the
`feisc.h`/`fedm` headers, and the cVEND SDK) were partially inaccessible.
docs.ros.org, which mirrors FEIG's `rfid_drivers`/FEDM doxygen, is behind an Anubis
bot wall, and the cVEND SDK is NDA or on request.

Command-code facts here are corroborated across FEIG OEM manuals (i-scan,
classic-pro, CPR70, LR1002 via manualslib/manualmachine/scribd), FEIG's own SDK
datasheet, and independent open-source reimplementations (Amarok79 C#,
joostkamphuisnl Node). Convergence is good for `0x69`, `0x52`, `0x63`, `0x65`,
`0x80`-`0x83`, `0xB0 0x01`, `0x0B 0x01`, and `0x22`.

One conflict remains flagged, not silently resolved. Inventory is cited as
`0xB0 0x01` (ISO15693 host-command group, FEIG i-scan/Pepperl+Fuchs manuals) and
as `0x0B 0x01` (ISO Standard Host Command, Amarok79 C# driver). These are two
different but real command encodings in FEIG firmware generations. For ISO14443 UID
on modern firmware, prefer `0x0B 0x01` with the air standard selected in the
payload.
