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
| `0x9C` FileInfo | request `[0x00][u16 len][path]` → `0x9D`, but reply bytes vary per call — **format partially open** |
| `0x10` Reset subcode `2` | **clean software restart** — `0x11` reply, `0x0F` Startup in ~6 s, serial preserved, scanning fresh (the sleep recovery) |
| `0xAA`/`0xAB` SetTime (wiki: blank) | payload = timestamp; reply `0xAB 0000` |
| `0xD1` EMVStatus ("not understood") | BER-TLV dissected (see `reversing-nx.md`) |
| `0xE4`/`0xE5` enable | confirmed; nx enables Mifare(5)+Desfire(7)+UltralightC(10) |
| `0xE8` sub 0 (wiki: GetVersionOfKey) | **confirmed** — `SecurityServices.cpp:328`; sub 4 returns the cert |
| `0xEA` (wiki: unknown) | handler **fails** (`IPP handler for cmd 0xea failed [Ipp.cpp:262]`); reply is `0xEB` (wiki omits `0xEB`) |
| `0xED` Log levels 1/2/3 | confirmed (INFO/WARN/ERROR) |
| `0xBE` UnhandledCard / `0xD5` CARD IN | confirmed (UID carriers) |

Reader identity established via the file ops: **FEIG cVEND Development Kit,
Buildroot 2014.05, firmware 02.35** — see `INTERFACE.md` "Reader internals". Deep
research mapping public FEIG/NXP/EMVCo docs to our RE is in
`reports/FEIG cVEND reader research.md`. Still untested / needs hardware: the
DESFire/APDU card paths (`0xB1`/`0xB9`/`0xBC`/`0xB4`/`0xB6`, need real cards/SAM).
Deliberately still skipped: the write ops `0x96`/`0x9A` and reset subcodes
`0x10 03`/`04`.

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
