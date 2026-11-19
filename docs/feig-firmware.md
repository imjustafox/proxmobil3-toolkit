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
