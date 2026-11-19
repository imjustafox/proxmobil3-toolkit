# Cross-checking the wiki against our unit

Running the commands documented on `wiki.pm3.dev/cvend` against our actual
PROXmobil3 and recording what the hardware really does — confirmations,
corrections, and the runtime details static disassembly can't show. Our
reverse-engineering was mostly live (LD_PRELOAD sniffing + behavioral testing);
the wiki's opcode map was mostly static (disassembling the `feig` firmware), so
the two are complementary and worth reconciling.

## Method notes (how to get a clean signal)

- **The `0xD1` stream is card-independent; `0xBE` is not.** `0xD1` (idle
  EMVStatus / poll heartbeat) ticks on its own, so it's the clean indicator of
  whether a polling subsystem is running. `0xBE` only appears when a card is in
  the field — so a card left sitting on the reader will generate `0xBE` frames
  that have nothing to do with the command under test. Clear the field (or watch
  only `0xD1`) before attributing an effect to a command.
- **Watch `0xED`.** The reader emits ASCII log lines (type `0xED`,
  `[level][text]`) that often state outright what a command did or why it
  failed, including the firmware source file and line. This is the cheapest
  ground truth available — capture it around any command you're probing.
- The unit's base ISO14443A scan goes to sleep after long idle; `0x07`
  heartbeats continue but `0xD1`/`0xBE` stop. See the NFC recipe in
  `INTERFACE.md` for waking it.

## Verification sweep (2026-11-19)

Going message-type by message-type through the wiki against our unit. Confirmed,
corrected, or newly pinned down:

| Wiki item | Result on our unit |
|---|---|
| CRC-32 trailer ("no polynomial I recognize") | **CRC-32/JAMCRC**, confirmed |
| `0x02`/`0x03` Version fields | deviceid `17ee5468`, model `cS01.05.45-49.00-2-2`, fw `02.35`, cwd `/home/app0` |
| `0x04`/`0x05` Status | confirmed |
| `0x07` Heartbeat interval (wiki: none) | **exactly 3.0 s** |
| `0x0F` Startup | confirmed (~60 s after power-on) |
| `0x22` Buzzer | big-endian `[u16 freq][u16 ms]`; ~2700 Hz loudest |
| `0x20` LEDs (wiki knew only bits `0x40`/`0x80`) | **all 8 low-byte bits mapped** on the opened board: `0x01`–`0x08` = 4-LED green status row; `0x10`/`0x20` = row-3 amber / row-4 red (bi-colour); `0x40`/`0x80` = logo right/left. Upper 3 bytes **inert** (swept all 32 bits) |
| `0x98` GetFile (wiki: blank) | **`[u16 len][path][u32 off][u16 cnt]` → `[u32 len][data]`** |
| `0xA4` FileList (wiki: blank) | **`[u16 len][path]` → `[u32 len][name\0mtime\0…]`** |
| `0x9C` FileInfo | **solved** (via disasm): request `[u16 pathlen][path][u32][u32]`; reply `0x9D` (10 bytes) `[status:u16][size:u32 BE][crc32:u32 BE]` (CRC is a FEIG variant). The two u32s are the CRC range (`0,0` = whole file) |
| `0x10` Reset subcode `2` | **clean software restart** — `0x11` reply, `0x0F` Startup in ~6 s, serial preserved, scanning fresh (the sleep recovery) |
| `0xAA`/`0xAB` SetTime (wiki: blank) | payload = timestamp; reply `0xAB 0000` |
| `0xD1` EMVStatus ("not understood") | BER-TLV dissected (see `reversing-nx.md`) |
| `0xE4`/`0xE5` enable | confirmed; nx enables Mifare(5)+Desfire(7)+UltralightC(10) |
| `0xE8` sub 0 (wiki: GetVersionOfKey) | **confirmed** — `SecurityServices.cpp:328`; sub 4 returns the cert |
| `0xEA` (wiki: unknown) | handler **fails** (`IPP handler for cmd 0xea failed [Ipp.cpp:262]`); reply is `0xEB` (wiki omits `0xEB`) |
| `0xED` Log levels 1/2/3 | confirmed (INFO/WARN/ERROR) |
| `0xBE` UnhandledCard / `0xD5` CARD IN | confirmed (UID carriers) |
| `0xBC` DESFireCommand (wiki: "sends DESFire command") | **works on a real DESFire card** — `0xBC [native cmd]` → `0xBD [00][status][data]`; the reader runs the command and its `0xAF` multi-frame chaining internally. GetVersion (`0x60`) returned HW/SW version + 7-byte UID + batch/date; GetApplicationIDs (`0x6A`) returned the card's AID. Pre-auth metadata only (we hold no keys) |
| `0xB4` APDUProx | reply shape confirmed — `0xB5 [devsel][echo][status][SW1][SW2][data]`, status `0x70` = no card (matches wiki) — but `DeviceSelect 0x00` never routes to the contactless card (even with ISO handler enabled); correct DeviceSelect **unknown** |

Reader identity established via the file ops: **FEIG cVEND Development Kit,
Buildroot 2014.05, firmware 02.35** — see `INTERFACE.md` "Reader internals". Deep
research mapping public FEIG/NXP/EMVCo docs to our RE is in
`reports/FEIG cVEND reader research.md`. `0xBC` DESFire reads now confirmed on a
real card (above). Still untested / needs hardware: `0xB1`/`0xB9` ISO/DESFire
auto-read events, `0xB4` card routing (needs the right DeviceSelect), `0xB6`
SAMCtrl and `0xAC`/`0xAE` ITSO (need a SAM fitted). Deliberately still skipped:
the write ops `0x96`/`0x9A` and reset subcodes `0x10 03`/`04`.

## The feig firmware binary — command dispatch map (static analysis)

Pulled `/home/app0/feig` off the reader with the file ops (`pm3.py cvend-cat`,
1.6 MB) and ran `objdump`/`c++filt` on it. It is an **unstripped** `elf32-littlearm`
C++ binary, so every IPP opcode maps to a named `*::handleIppTele(IppHeader, const
unsigned char*)` handler — the entire dispatch, by name:

| Opcode | Handler class (`::handleIppTele`) |
|---|---|
| `0x02` Version | `IppHandlerVersion` |
| `0x04` Status | `IppHandlerStatus` |
| `0x10` Reset | `IppHandlerReset` |
| `0x20` LEDs | `LedsIppHandler` |
| `0x22` Buzzer | `BuzzerIppHandler` |
| `0x32`/`0x46` CardRelease/Abort | `ProxCardCtrlHandlerCardReleaseGeneric`, `ProxCardIso::handlerCardReleaseIso` |
| `0x96`/`0x98`/`0x9A`/`0x9C`/`0xA4` file ops | `IppHandlerPutFile` / `GetFile` / `DeleteFile` / `FileInfo` / `FileList` |
| `0xAA` SetTime | `IppHandlerSetTime` |
| `0xAC`/`0xAE` ITSO | `ItsoIppHandler` (+ a large `ITSO*` module family) |
| `0xB4` APDUProx | `ProxCardCtrlHandlerApduProx`, `ProxCardIso::handlerApduProx` |
| `0xB6` SAMCtrl | `SamCtrl` |
| `0xBC`/`0xB9` DESFire | `ProxCardDesfire` |
| `0xD4`/`0xD5` Ultralight-C | `ProxCardUltralightC` |
| Mifare Classic | `ProxCardMifareClassic` |
| `0xD0`/`0xD1` EMV | `EmvIppHandler`, `EmvReader` |
| Girogo | `GirogoIppHandler` |
| `0xE4` enable | `ProxCardCtrlHandlerFunction` |
| `0xE8` SecurityServices | `SecurityServicesIppHandler` |
| generic | `IppHandlerGenericCommand` |

**Authoritative opcode list** (read from the `Ipp::setDataHandler(u8 opcode,
IppHandler*)` registration calls — dispatch is a 256-entry table indexed by the
msgType byte): `0x02` Version, `0x04` Status, `0x10` Reset, `0x20` LEDs, `0x22`
Buzzer, `0x32` CardRelease, `0x46` AbortCardHandling, `0x96` PutFile, `0x98`
GetFile, `0x9A` DeleteFile, `0x9C` FileInfo, `0xA4` FileList, `0xAA` SetTime,
`0xAC` ITSOData, `0xAE` ITSOCtrl, `0xB4` APDUProx, `0xB6` SamCtrl, `0xBA`
(DESFire-area, wiki "unknown"), `0xBC` DESFireCommand, `0xCE` (IppHandling, wiki
"unknown"), `0xD0` EMV, `0xD4` UltralightCommand, `0xE4` ProxCardFunction,
`0xE6` Girogo (wiki "unknown"), `0xE8` SecurityServices, `0xEA` (Mifare — the
handler exists but errors, as observed), and a `0x00` registration. This confirms
every opcode numerically and resolves the wiki's unknowns `0xBA`/`0xCE`/`0xE6`/
`0xEA` as real registered handlers in the DESFire / IppHandling / Girogo / Mifare
modules respectively.

Infrastructure: `IppChannel`/`IppHandling` (framing, `_sendHeartbeat`,
`sendStartup`), `CMDProcessor` (`GetNextCommand`, `SendOK`/`SendErr`/`SendResponse`),
`msg_factory.cpp`, `CommBuffer`, `Crc8`/`Crc16`/`Crc32`, `DesfireCrypto`, `aes`/`des`.
Because the binary keeps symbols, any opcode format can be recovered by
disassembling its named handler. The binary also carries INIT's **source tree**
(`//home/jah/git/init/proxcontroller-feig2/src/…`), which maps the whole codebase:
`ipp/` (Ipp, IppHandling, IppHeader, IppBaseTelegram, ItsoIppHandler), `card/`
(the eight handlers — `ProxCardVdvKa`(4), `MifareClassic`(5), `Iso`(6),
`Desfire`(7), `Girogo`(8), `Itso`(9), `UltralightC`(10), plus `ProxCardCtrl`),
`emv/`, `girogo/`, `sam/` (SAM, SamAV1AV2, SamCtrl), `securityServices/`,
`crypto/DesfireCrypto`, `device/{Buzzer,Leds}`, `serial/Serial`, `RFIDReaderMultiApp`.

Decoded by disassembly this session:

- **`0x9C` FileInfo** — `IppHandlerFileInfo::handleIppTele` reads `[u16 pathlen]
  [path]`, needs two trailing u32s, calls `getFileSizeAndCrc32(path,u32,u32,
  &size,&crc)`; reply as in the table above.
- **`0xB4` APDUProx** — `ProxCardCtrlHandlerApduProx::handleIppTele` checks the
  card-controller state: only when an **ISO14443-4 card is handled by
  `ProxCardIso`** (state `2`) does it `dynamic_cast` and call
  `ProxCardIso::handlerApduProx`; otherwise it returns `0xB5` with the echoed
  first byte and status `0x70` "no card". So the first byte is **echoed, not a
  device selector** at this layer, and a **DESFire won't work** (it's claimed by
  `ProxCardDesfire`, not `ProxCardIso`). The handler builds
  `IsoAPDU(CLA,INS,P1,P2,Lc,data,Le)` from payload bytes `[1..]` and transceives;
  failure writes status `0x6C` "no session" (both status codes match the wiki).
  To exercise `0xB4`, present a plain ISO-4 card (e.g. an EMV card), not a DESFire.
- **`0xB6` SAMCtrl** — `SamCtrl::handleIppTele`: first payload byte is a subcommand
  (compared against `4`, the four SAM slots), followed by an APDU to the SAM;
  reply `0xB7`, status `0x72` on error (`_sendApduError`), using
  `SAM`/`SamAV1AV2` with `C_OpenSession`/`C_CloseSession`. Needs a SAM fitted —
  untestable on our unit.

Scheme-handler internals recovered from symbols + `.rodata`:

- **`0xD0` EMV** — `EmvIppHandler` subcommand enum read straight from `.rodata`:
  `CONFIG=0`, `SETUP=1`, `POLL=2`; the POLL argument is `POLL_START=0`/
  `POLL_STOP=1`, and results are `RES_OK=0`/`RES_NOK=1`. This confirms the wiki
  and our live `0xD0 02 00`/`02 01` test exactly. `EmvReader` has
  `loadConfig(filename)`, a built-in `DEFAULT_CONFIG`, `startPolling`/
  `stopPolling`, `initTransaction`, `onlineRequest`, `track2` — so the "can't poll
  without a config" behaviour is by design, and a `DEFAULT_CONFIG` exists.
- **`0xE8` SecurityServices** — a **PKCS#11 (Cryptoki)** key/cert store
  (`fepkcs11` tokens/slots, sessions/login). Methods: `GenerateRandom`,
  `AES_encrypt`/`AES_decrypt`, `GetDerivedKey` (NXP CMAC), `ImportKeyBlock`
  (TR-31), `ImportX509Cert`/`RemoveX509Cert`, `_findKey`/`_findCertificate`/
  `_unwrapKey`. Our tested sub-0 (`GetVersionOfKey`) and sub-4 (cert read) are the
  read-only corners of this API; the import/derive/generate subcommands are
  key-management writes and are left alone.
- **`0xAC`/`0xAE` ITSO** — `ItsoIppHandler::_handleItsoDataReq` (`0xAC`) and
  `_handleItsoCtrlReq` (`0xAE`); `ProxCardItso` drives it through an **ISAM**
  (`_connectSamReader`, `setIsamPasswd`, `hl2DataRequest`, `_getPostSAM`). Needs a
  fitted ISAM, so untestable here; the large `ITSO*` module set implements the
  Shell/IPE/HOPS logic.

## `0xD0` EMV — toggle-polling (tested 2026-11-19)

**Wiki:** `0xD0` first byte selects a subcommand (`0` load config, `1`
preprocess, `2` toggle polling); for subcmd 2 a following byte is `0 = start
polling, 1 = stop polling`. We tested it as a possible cleaner replacement for
our "keep the base scan alive with a `0x04` keepalive" recipe.

**What the hardware does:**

- The command is real and acknowledged. Every `0xD0 02 xx` gets a reply
  `02 <flag>` where `<flag>` is the *resulting* polling state: send `02 00`
  (start) → reply `02 01` ("now polling"); send `02 01` (stop) → reply `02 00`
  ("now stopped"). This matches the wiki's `0 = start / 1 = stop` sense. (An
  early read of ours that called the byte "inverted" was wrong — it was the
  parked-card `0xBE` confound, not the toggle.)
- But polling never actually starts, because it needs an EMV config loaded
  first (subcmd `0`, `emvco_ep_configure`). With none loaded the reader logs:

  ```
  Error: EMV: Unable to start polling: no config [EmvReader.cpp:195]
  ```

  We have no EMV config in the keyless standalone setup, so `0xD0` subcmd 2 is a
  no-op for us.

**Conclusion — two separate polling subsystems.** This pins down an architecture
point: the reader polls two independent ways.

| Path | Control / output | Needs config/keys? | Used by |
|---|---|---|---|
| EMV entry-point polling | `0xD0` ctrl → `0xD1` EMVStatus | **yes** — load config first | the transit/fare path (nx) |
| Base ISO14443A scan | autonomous → `0xBE` / `0xD5` / `0xB1` | **no** | our standalone UID reader |

So `0xD0` toggle-polling is **not** a replacement for the keepalive recipe — it
drives the EMV fare path, which is gated on a config we deliberately don't run.
Our base-scan recipe (don't re-init, keep the `0x04` keepalive going) remains the
correct way to read UIDs without keys. The wiki's command is confirmed as
documented; we add the runtime fact that it's inert without an EMV config.

Incidental: this confirms the FEIG firmware uses the EMVCo L2 entry-point kernel
(`emvco_ep_configure` / `emvco_ep_preprocess`, `EmvReader.cpp`).

## Driving tags with a Flipper Zero (works)

A Flipper Zero in front of the reader is a programmable ISO14443A tag source —
useful because our only physical cards are DESFire/EMV. Drive it from its USB
CLI (`/dev/cu.usbmodemflip_*`, raw serial, prompt `>: `):

- `storage list /ext/nfc` / `storage read /ext/nfc/<f>.nfc` — list and inspect
  saved tags; the header's `Device type:` tells you the family (e.g.
  `RickRoll.nfc` is an **NTAG216**, Ultralight-family; `Orca.nfc` is DESFire;
  `NFCU_5405.nfc` is actually an EMV bank card, not Ultralight).
- `loader open NFC /ext/nfc/<f>.nfc` then `input send ok short` — load a saved
  tag and start emulating it.
- **Don't `loader close` while it is actively emulating — it crashes/reboots the
  Flipper.** Back out with `input send back short` first, or just leave it.

**Confirmed:** emulating the NTAG216, the PM3 base scan read its UID
`04 85 92 8A A0 61 81` straight off a `0xBE` frame. So Flipper-emulated tags are
a valid input to everything in `INTERFACE.md`'s NFC section. Use the PM3 reader
itself as the feedback loop — if it reports the emulated UID, emulation is live.

## `0xD4` UltralightCommand (tested 2026-11-19)

**Wiki:** Read `02 <start_page> <num_pages>`, Write `03 <page> <4 bytes>`,
Authenticate `04/05/06`, Abort `07`; reply `0xD5` `[subcmd][status][payload]`,
status `00` ok / `01` op error (no card) / `02` bad params. Tested against a
Flipper emulating an NTAG216 (Ultralight-family) in the field.

**Result:** the command is reachable and well-formed — every `0xD4` gets a
`0xD5 [02][status]` reply — but **status was `01` (no card) in every mode we
tried**, including 1261 rapid-fire reads. Root cause: `0xD4` operates on a
*selected/activated* card, and nothing we drove left a card selected:

- **Keyless base scan** (the standalone UID recipe): detects the tag, emits
  `0xBE` UnhandledCard, then immediately **releases** it (it's "unhandled"
  because no handler owns its type). Firing `0xD4` the instant a `0xBE` arrives
  is already too late — the card is gone.
- **Enable the UltralightC handler** (`0xE4 00 0a 01 01` → `0xE5 000a0000`, log
  `Enabling prox handler 'ProxCardUltralightC' [ProxCardCtrl.cpp:110]`) and run
  the full init through the cert read to `INITIALIZED`: this **stops** the
  autonomous base scan and does **not** start handled-card polling — the reader
  then detects nothing at all (no `0xBE`/`0xD5`), even for a card that enters the
  field fresh after init. So `0xD4` still sees no card.

**Why (investigated 2026-11-19 by sniffing nx and reproducing its init).** We
LD_PRELOAD-sniffed nx (`sniffer/cvsniff.so`) while it was driven in service via
`keyserver/`, with a Flipper emulating an NTAG216 in the field. nx's reader init,
captured exactly, is:

```
0xEA 0100          wake/prime
0x02               version
0xE4 00 05 01 01   enable Mifare
0xE4 00 07 01 01   enable Desfire
0xE4 00 0a 01 01   enable UltralightC
0xAA <timestamp>   SetTime
0xE8 04fe0a0000    read device cert  -> 0xE9 (~1.1 KB X.509)
```

The moment the enables + SetTime land (even before the cert reply), the reader
emits **`0xD5` CARD IN** with the UID and *holds* the card — the handled state we
needed. We reproduced this with `pm3.cvend_enable(s, ["mifare","desfire",
"ultralightc"])`: on an **awake** reader with the card present, it fires the same
`0xD5` CARD IN. nx then read the card (confirmed: the validator toned and showed
"show pass to operator").

But host-driven `0xD4` reads **still fail (status 01)**, for two reasons that
together make the host-read path unworkable here:

1. **The reader's handler grabs then releases the card.** The UltralightC handler
   runs its own transceive (a 3DES auth) against the tag and, on a plain NTAG216,
   fails — `feclr_transceive() failed: status 0x00000002 [RFIDReaderMultiApp.cpp:159]`
   — and releases it. The selected window is milliseconds.
2. **Polling `0xD4` suppresses the reader's own scan.** During a max-rate `0xD4`
   blast (2240 reads) the card-independent `0xD1` stream and `0xD5` events drop to
   **zero** — the reader services host commands *or* scans autonomously, never
   both. So while you poll `0xD4`, the reader never selects the card, and every
   read returns "no card."

**Conclusion.** Reading a card on this reader goes through its **internal
handlers** (enable the type, let the reader transceive and report via
`0xD1`/`0xB1`/`0xD5`) — which is exactly what nx does; nx never issues `0xD4`.
Host-driven `0xD4`/`0x32` would need an explicit host-mode "select/activate card
by UID and hold" primitive that keeps the reader from auto-releasing and doesn't
fight the scan. We did not find one in the wiki or in nx's traffic. Also note the
reader's handled-scan is **not autonomous**: stopping nx idles it (drops back to
`0x05`/`0x07` only), so a standalone app must keep driving it.

A Flipper is a fine ISO14443A **UID** source (it reliably triggers `0xBE`/`0xD5`),
but a plain NTAG216/NTAG215(amiibo) can't satisfy the UltralightC handler's auth,
so it's always released. A genuine Mifare **Ultralight-C** card would be needed to
exercise the handler's read path — and even then, host `0xD4` faces the
select-and-hold gap above.

## Pending

- **`0x32` CardRelease / `0x46` AbortCardHandling, and `0xD4` Write/Auth.** All
  blocked on the same gap as `0xD4` Read: no host-mode select-and-hold. They only
  become testable if a "select/activate card by UID" primitive turns up (keep
  watching nx traffic against a card type the reader's handler *accepts*, e.g. a
  real Mifare Ultralight-C), or by catching the card mid-handling without the
  scan-vs-poll contention. Lower priority now that the read path is understood.
- **`0x10` Reset subcmds — `2` tested, clean.** `0x10 02` (restart application)
  is a **clean software restart**: `0x11` ResetReply, then an Abort + INIT log,
  then `0x0F` Startup at ~6 s, serial link preserved, scanning resumes. This is
  the software recovery for the sleep-lock (`pm3.py cvend-restart`) and corrects
  our earlier "0x10 wedges" note — a *bare* `0x10` (no subcode) wedges, but the
  subcode-2 form is clean. Subcodes `3` reboot / `4` poweroff and `33–36` SAM
  reset remain untested; avoid `4` (poweroff needs a physical power cycle).

## Bonus finding: driving nx in service, headless

The `keyserver/` + sniffer path now works end to end and is worth recording: run
`keyserve` as a **durable** process (`systemd-run --unit=keyserve --collect
/init/keyserve` — a bare `&`/`setsid` from an ssh command does **not** survive),
preload the sniffer via an `nx.service.d` drop-in, and start nx. nx fetches keys
and labels from the local server (`loaded 51 valid labels`) and goes fully in
service. Two safety notes learned here: the nx unit has `FailureAction=poweroff`,
so add `FailureAction=none` to the drop-in while experimenting; and stopping nx
idles the reader, so disable the watchdog in the same breath (`pm3.py nx-stop`).
