# The cVEND `feig` application — firmware deep dive

A top-to-bottom map of the FEIG cVEND reader's application (`/home/app0/feig`,
firmware 02.35), reverse-engineered statically. The binary is a 1.6 MB
**unstripped** `elf32-littlearm` C++ program, so most of this is read directly
from its symbols, `.rodata` constants, and targeted disassembly (`objdump` +
`c++filt`). It is INIT's own code — the source tree embedded in the binary is
`//home/jah/git/init/proxcontroller-feig2/src/`.

Pull a fresh copy anytime with `pm3.py cvend-cat /home/app0/feig > feig.bin`;
a retained copy is in the git-ignored `dumps/feig-app-02.35.bin`.

This complements `docs/wiki-cross-check.md` (which tracks the live protocol tests)
and `INTERFACE.md` (the practical how-to). Here the focus is *how the firmware
works internally*, feature by feature.

## 1. Architecture and the IPP command loop

The app is a multi-application contactless reader. Its layers:

- **`serial/Serial`** — the UART to the host (the PM3), 115200 8N1.
- **`ipp/IppChannel`** — frames the `0xBC`-magic "IPP" telegrams on the serial
  line: `_readData`, `send(...)`, `setIppHandler`. `IppHeader` parses the 7-byte
  header (`getDataLen`, seq, replyTo, msgType).
- **`ipp/Ipp`** (singleton, `Ipp::get()`) — the dispatcher. Handlers register with
  `Ipp::setDataHandler(u8 opcode, IppHandler*)` into a **256-entry table indexed by
  the msgType byte**; `Ipp::handleIppTele` looks up and calls the handler's
  `handleIppTele(IppHeader, const u8*)`. `unsetDataHandler` removes one.
- **`ipp/IppHandling`** — lifecycle: `sendStartup` (the `0x0F` frame), a 3-second
  heartbeat thread (`startHeartbeat`/`_sendHeartbeat`/`stopHeartbeat`), and it
  registers `0x04` Status and `0xCE`.
- **`CMDProcessor`** — a second command path (`GetNextCommand`, `SendOK`/`SendErr`/
  `SendResponse`) used by the file/batch side.
- **`main.cpp`** → `EmvReader::mainLoop` and the reader threads.

### Authoritative opcode registration map

Every `setDataHandler` call site, with the module whose constructor registers it:

| Opcode | Registered by | Meaning |
|---|---|---|
| `0x02` Version, `0x10` Reset, `0x96/0x98/0x9A/0x9C/0xA4` file ops, `0xAA` SetTime | `IppBaseTelegram` | base/system telegrams |
| `0x04` Status, `0xCE` | `IppHandling` | status + a control command |
| `0x20` LEDs | `LedsIppHandler(Leds&)` | front LEDs |
| `0x22` Buzzer | `BuzzerIppHandler(Buzzer&)` | piezo |
| `0x32` CardRelease, `0x46` Abort, `0xB4` APDUProx, `0xE4` ProxCardFunction | `ProxCardCtrl(RFIDReader&)` | card-control |
| `0xBA`, `0xBC` | `ProxCardDesfire(RFIDReader&)` | DESFire (two opcodes) |
| `0xD4` UltralightC | `ProxCardUltralightC(RFIDReader&)` | Ultralight-C |
| `0xEA` | `ProxCardMifareClassic(RFIDReader&)` | Mifare Classic (handler errors in practice) |
| `0xAC`/`0xAE` ITSO | `ItsoIppHandler(ProxCardItso&)` | ITSO data/ctrl |
| `0xB6` SamCtrl | `SamCtrl()` | SAM |
| `0xD0` EMV | `EmvIppHandler()` | EMV entry point |
| `0xE6` Girogo | `GirogoIppHandler(RFIDReader&, ProxCardGirogo*)` | girogo purse |
| `0xE8` SecurityServices | `SecurityServicesIppHandler()` | PKCS#11 key/cert |

(There is no `0x00` handler — an earlier read of a stray `mov r1,#0` was a false
positive; that site actually registers `0xD4`.) This resolves the wiki's "unknown"
opcodes `0xBA`/`0xCE`/`0xE6`/`0xEA` as real registered handlers.

## 2. Card control and the RF poll engine

- **`RFIDReaderMultiApp`** is the RF layer (built on FEIG's `feclr`). It runs the
  polling thread (`_pollCards`/`_waitForCard`/`isPolling`/`_stopPolling`), finds a
  card (`_foundCard`/`_cardFound`), tracks the technology (`_tech`/`_techData`,
  `selectProtocol`), resets/surrenders cards (`resetCard`/`_resetCard`/`_surrender`),
  and crucially exposes **`enableDesfireNativeMode`** — the switch that lets the
  host talk native DESFire (what `0xBC` rides on). `Picc::_identify` is the
  per-card identification.
- **`ProxCardCtrl`** is the multi-application orchestrator. `addProxHandler`
  registers a scheme handler; **`enableProxHandler`/`disableProxHandler`** are what
  the `0xE4` ProxCardFunction command toggles (by the function IDs VdvKa 4 …
  UltralightC 10). `startPolling`/`stopPolling` drive the RF engine; `_handlePicc`
  routes a detected card to the first handler whose `isValid(Picc&)` claims it (so a
  DESFire goes to `ProxCardDesfire`, not `ProxCardIso`); `getActiveCtrl` is the
  currently-handling scheme; `_createUnhandledCardTelegram` emits the `0xBE`
  UnhandledCard frame when nobody claims it; `_abortCardHandling`/`waitForCardRemoved`
  finish a tap. Each scheme handler implements the same shape: `isValid`, `process`,
  `handleIppTele`, `cardRemoved`, `abort`, `getProxFunc`/`getCtrlType`/`getName`.

## 3. Card schemes

- **DESFire (`ProxCardDesfire` + `MifareDesfire` + `DesfireCrypto`)** — a complete
  DESFire EV1 engine, not just a reader. `MifareDesfire` implements
  `authenticate`/`authenticateAES`/`authenticateISO`/`AuthenticateFromHSM`,
  `createBackupDataFile`, `changeFileSettings`/`changeKeySettings`,
  `commitTransaction`/`abortTransaction`, and per-operation comm-mode selection
  (plain / MAC / fully-enciphered: `_getReadCommMode`, `_getWriteCommMode`,
  `_getCreditCommMode`, …). `ProxCardDesfire` adds the transit operations:
  `_createApplication`, `_createDataFile`/`_createValueFile`/`_createRecordFile`,
  `_credit`/`_debit`/`_limitedCredit`, `_changeKey`, `_writeData`,
  `_clearRecordFile`, and authentication from either the SAM (`_authenticateFromSAM`)
  or the HSM (`_authenticateFromHSM`). `DesfireCrypto` does the secure-messaging
  math — AES/3DES CMAC (`_cmacPadding`, `_cmacLeftShiftArrayOneBit`, `_xor`, IV
  state) and `calcCrc32`. Auth error strings confirm it: *"DESFire Authent-Step(2)
  failed - RndA does not match"*, *"Desfire Authenticate_AES_part_1/2 failed"*.
  The two opcodes: `0xBC` DESFireCommand (host-driven native command, what we read
  GetVersion/GetApplicationIDs with) and `0xBA` (a second DESFire entry on the same
  handler).
- **Mifare Classic (`ProxCardMifareClassic`, opcode `0xEA`)** — full block ops:
  `_handleCardAuthenticate` (sector key auth), `_handleCardRead`/`_handleCardWrite`,
  `_handleCardValueCmd`/`_valueCmd` (value-block inc/dec), `_handleCardTransfer`,
  `_handleCardRelease`. (`0xEA` erroring in our live test just meant no Classic card
  / wrong subcommand, not an unimplemented opcode.)
- **Ultralight-C (`ProxCardUltralightC` + `MifareUltralightC`, opcode `0xD4`)** —
  `isUltralightCCard`/`isValid`/`process`, with `MifareUltralightC::authenticate`
  the 3DES auth. This is the handler we exercised with `0xD4` (READ/WRITE/AUTH),
  which a plain NTAG can't satisfy (no 3DES).
- **ISO 14443-4 (`ProxCardIso`, opcode `0xB4`)** — generic APDU: `isIsoCard`,
  `handlerApduProx` (builds `IsoAPDU` and transceives), `handlerCardReleaseIso`.
- **VDV-KA (`ProxCardVdvKa`, function ID 4)** — German (((eTicket; mostly
  `_isValidCard`/`isValid` detection here (the heavy lifting is scheme config/SAM).

## 4. Girogo (`ProxCardGirogo` + `Girogo`, opcode `0xE6`)

A complete German prepaid-purse (GeldKarte girogo) payment kernel: `Girogo::prepare`,
`debit`, `confirm`, `reverse`, `reconciliation`, `terminate`, `vendingLoop`,
`enable`/`disable`, `getStatus`/`girogoStatusChanged`, `getKernelVersion`/
`getLibVersion` (via `libfegirogo.so`, the shared lib we saw in `/home/app0`, and
`epn_getGiroGoVersion`). `ProxCardGirogo` wraps it for the card-control framework
(`cardPresent`/`setCardPresent`, `_sendCardDetect`/`_sendCardRemoved`, `process`).
Legacy — girogo was wound down ~2020–2025 — but fully present in firmware.

## 5. ITSO (`ItsoIppHandler` + the `ITSO*` family, opcodes `0xAC`/`0xAE`)

A full implementation of the UK ITSO ticketing spec, by far the largest subsystem.

- **Transport:** `ItsoIppHandler::_handleItsoDataReq` (`0xAC`) and
  `_handleItsoCtrlReq` (`0xAE`); `ProxCardItso` drives a card through an **ISAM**
  (`_connectSamReader`, `setIsamPasswd`, `hl2DataRequest`, `_getPostSAM`).
- **Card model:** `ITSOShell`, `ITSODir` (directory), `ITSOIpe` (the IPEs =
  ticket products), `ITSOInstID`/`ITSONodeID` (operator identity), `ITSO_DataBlob`.
- **Typed data objects:** a whole value-type system — `ITSOAsciiValue`,
  `ITSOBcdValue`, `ITSOBinValue`, `ITSOBitMapValue`, `ITSOCrcValue`,
  `ITSODateValue`/`ITSODtsValue`/`ITSORdateValue`, `ITSOHexValue`, `ITSOFlagValue`,
  `ITSOLoyaltyPointsValue`, etc., assembled via `ITSOMessage`/`ITSOMessageDF`.
- **SAM / back office:** `ITSO_HopsSAM`, `ITSO_PostSAM`, and a **software SAM**
  `ITSO_SoftSAM` (CreateIPE/ModifyIPE/DeleteIPE/OpenIPE/SealDir, GenerateMAC/
  VerifyMAC, ExternalAuth, CreateBatchHeader/VerifyBatchHeader). It generates
  `ITSO_POST_to_HOPS_File` **XML** messages (embedded DTD) for the back office.

## 6. EMV (`EmvIppHandler` + `EmvReader`, opcode `0xD0`)

Open-loop contactless payment via FEIG's **FETPF** framework (the EMVCo L1/L2
stack). `EmvReader` holds the kernel: `loadConfig(filename)` / a built-in
`DEFAULT_CONFIG`, `setup`, `startPolling`/`stopPolling`, `initTransaction`,
`onlineRequest`, `track2`, `surrender`, `printAmount`, and a persistent
`TRANSACT_COUNTER` (mirrored in `/home/app0/emv/transact-counter.dat`). The IPP
subcommands (`.rodata`): `CONFIG=0`, `SETUP=1`, `POLL=2` (arg `START=0`/`STOP=1`),
results `RES_OK=0`/`RES_NOK=1`. Polling calls `fetpf_ep_configure` /
`fetpf_ep_preprocess`; with no config it logs *"Unable to start polling: no
config"* (also *"no FETPF client"*, *"Failed to parse configuration TLV
structure"*, *"Failed to open EMV config file"*). So EMV is inert on our unit only
because no config is provisioned — the kernels are present.

## 7. SAM (`SamCtrl` + `SamAV1AV2`, opcode `0xB6`)

`SamCtrl` (singleton `get()`) is a thin IPP front to **`SamAV1AV2`**, the NXP
**MIFARE SAM AV1/AV2** interface: `SAM_GetVersion`, `SAM_SelectApplication`,
`SAM_AuthenticatePICC_abort`, `isHostAuthenticated`. `0xB6` carries a subcommand
(checked against the 4 SAM slots) + an APDU to the SAM; reply `0xB7`, status
`0x72` on error. The SAM holds the DESFire/transit diversified keys used by
`_authenticateFromSAM`. Untestable without a SAM fitted. (ITSO has its own SAM
classes, §5; girogo has `SAMWrapper`.)

## 8. SecurityServices / HSM (`SecurityServicesIppHandler` + `SecurityServices`, `0xE8`)

An on-reader **PKCS#11 (Cryptoki) HSM** via `fepkcs11` tokens/slots with login/
session management (`_openSessionAndLogin`, `_logoutAndCloseSession`). Operations:
`GenerateRandom`, `AES_encrypt`/`AES_decrypt`, `GetDerivedKey` (NXP CMAC
derivation), `ImportKeyBlock` (TR-31), `ImportX509Cert`/`RemoveX509Cert`,
`_findKey`/`_findCertificate`/`_unwrapKey`, `_getTr31KeyVersionOfObject`. The `0x02`
Version cert and our `0xE8` sub-0 (GetVersionOfKey) / sub-4 (device cert read) are
the read-only corners; it's the device's secure key store and the root of
`_authenticateFromHSM`.

## 9. Crypto primitives

`crypto/DesfireCrypto.cpp` (AES/3DES CMAC + CRC32 for DESFire secure messaging),
plus standalone `aes.cpp` (`aes_encrypt`/`aes_decrypt`) and `des.cpp`
(`des_setkey`). These back DESFire/Ultralight-C/SAM authentication. The CRC used by
`0x9C` FileInfo is a FEIG variant (neither standard CRC-32 nor JAMCRC), consistent
with having its own `Crc8`/`Crc16`/`Crc32` modules.

## 10. Device: LEDs and buzzer

- **`Leds`** (opcode `0x20`) — `Set`, `TurnOn`/`TurnOff`, `GetState`, and a
  `SetBrightness` method. The host `0x20` bitmap drives the 8 LEDs in the low byte
  (4-LED status row + the two logo segments; see `INTERFACE.md`); the firmware
  carries a brightness concept but the host command and the on-board LEDs are
  effectively on/off, which matches our sweep (upper bytes inert).
- **`Buzzer`** (opcode `0x22`) — `Beep` on a dedicated `_buzzerThread`; the host
  passes `[u16 freq][u16 ms]`.

## Summary

Nothing in the reader's command surface is now unknown: every IPP opcode maps to a
named handler, the file-ops/LED/buzzer/DESFire/Ultralight/FileInfo formats are
decoded, and the fare subsystems (DESFire transaction engine, Mifare Classic,
Ultralight-C, ISO-APDU, girogo, VDV-KA, ITSO, EMV) and their security backends
(MIFARE SAM AV2, PKCS#11 HSM, ITSO soft/post/hops SAM, AES/3DES/CMAC crypto) are
identified at the API level. What cannot be exercised on this unit is only what
needs hardware we don't have (a fitted SAM/ISAM) or provisioning we don't hold (an
EMV config, scheme keys) — not anything undiscovered.

## 11. Provisioning: what the hardware/secret-gated features need

The features we can't exercise aren't mysteries — we can state exactly what each
would require, from the firmware.

### EMV config (`0xD0` CONFIG / `EmvReader::loadConfig`)

How it loads, from disassembly of `EmvReader::loadConfig(const char* path)`:

1. `fopen(path, "r")` — a **text** file. The default path is **`emv/default.conf`**
   (`EmvReader::DEFAULT_CONFIG`), i.e. `/home/app0/emv/default.conf`. The `0xD0`
   subcommand `CONFIG` (0) passes a null-terminated filename to load instead.
2. `fscanf(fp, "%02x", …)` in a loop — the file is **ASCII hex**, two hex digits
   per byte, decoded into a binary buffer.
3. `fetpf_ep_configure(buf, len)` then `tlv_parse(buf, len)` — the decoded bytes
   are the **EMVCo entry-point configuration as BER-TLV**, handed to FEIG's FETPF
   EMV framework.

So an EMV config file is a hex dump of a BER-TLV structure encoding the **EMVCo
Book A/B "reader combinations"**: per supported brand, an AID + Kernel ID +
transaction type + terminal floor limit + CVM-required limit + contactless
transaction limit + TTQ/terminal-capability flags. Error paths confirm the shape:
*"Failed to parse configuration TLV structure"*, *"Malformed config string
received"*, *"Failed to configure EMV entrypoint"*, *"Failed to open EMV config
file '%s'"*.

**On our unit the file is absent** (`/home/app0/emv/` holds only
`transact-counter.dat`), so `fetpf_ep_configure` is never called and polling
refuses with *"no config"*. That is consistent with a closed-loop / account-based
(CapMetro) deployment that never provisioned the open-loop EMV kernels, even
though the FETPF kernels (`fetpf_new`/`_ep_configure`/`_ep_preprocess`/
`_ep_transaction`/`_process_card`) are all present in the binary. To bring EMV up
one would drop a valid hex-TLV combination file at `emv/default.conf` (or name one
via `0xD0` CONFIG) — which needs real EMVCo brand/AID configuration we don't have
and isn't our goal.

### SAM (`0xB6` / `SamAV1AV2`)

Needs a physical **NXP MIFARE SAM AV2** fitted in one of the module's four ID-000
(SIM-size) SAM sockets (the cVEND SAM extension board). The SAM holds the
diversified scheme keys; `ProxCardDesfire::_authenticateFromSAM` and the transit
handlers authenticate cards through it. `0xB6` = `[subcommand/slot (checked
against 4)][ISO7816 APDU to the SAM]` → `0xB7` (status `0x72` on error). With no
SAM seated, every `0xB6` and every `_authenticateFromSAM` path errors. The
host-visible API is `SAM_GetVersion` / `SAM_SelectApplication` /
`SAM_AuthenticatePICC` with a host-authentication step (`isHostAuthenticated`).

### ITSO (`0xAC`/`0xAE` / `ProxCardItso`)

Needs an **ISAM** (ITSO Security Access Module) reachable via
`ProxCardItso::_connectSamReader`, unlocked with an ISAM password
(`setIsamPasswd`). A card presents an **ITSO Shell** (a directory `ITSODir` of IPE
products `ITSOIpe`); `hl2DataRequest` does the HL2 exchange, and transactions are
MAC'd by `ITSO_SoftSAM`/`ITSO_PostSAM`/`ITSO_HopsSAM` and serialized as
`ITSO_POST_to_HOPS_File` **XML** for the back office. Without an ISAM and ITSO
cards none of this runs, but the data model (typed `ITSO*Value` objects assembled
into `ITSOMessage`) and the SAM operations (`CreateIPE`/`ModifyIPE`/`SealDir`/
`GenerateMAC`/`VerifyMAC`) are fully present.

### Scheme keys (DESFire/Ultralight-C/Mifare Classic)

Reading a card's **UID and pre-auth metadata** (DESFire GetVersion/GetApplicationIDs
via `0xBC`, UID via `0xBE`) needs nothing. Reading stored **fare data** needs the
scheme's diversified keys, held in the SAM or the PKCS#11 HSM — which this unit
doesn't carry for other agencies' cards, and which we would not use against cards
that aren't ours. This is a key/authorization gate, not a missing feature: the
`authenticate*`/`_credit`/`_debit`/`_writeData` engines are all there.
