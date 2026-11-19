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

**Takeaway:** enabling a handler + reaching `INITIALIZED` is necessary but not
sufficient to make the reader *hold* a card for host commands; nx evidently does
more to start handled-card polling. The clean next step is to **LD_PRELOAD-sniff
nx while it actually handles a card** (drive it in service via `keyserver/`, tap
a card, capture the exact frames between `INITIALIZED` and the card-read) — that
will reveal the missing "start polling / select-and-hold" step, after which
`0xD4` and `0x32` become testable. See `docs/reversing-nx.md` for the sniffer.

## Pending

- **`0x32` CardRelease / `0x46` AbortCardHandling.** Wiki: no payload, reply
  `0xB3` ISOCardReleased. Blocked on the same gap as `0xD4` — needs the reader
  holding a card. Revisit after the nx handled-card sniff above. Relevant to the
  "same card only reads once until removed" behavior.
- **`0xD4` Write/Authenticate.** Once a card can be held, test Write (`03`) and
  the Authenticate variants (`04/05/06`) against a writable NTAG.
- **`0x10` Reset subcmds.** Wiki: `2` restart app, `3` reboot, `4` poweroff,
  `33–36` reset SAM 1–4. We know a reset wedges the reader (power-cycle to
  recover), so these stay untested — avoid `3`/`4` on a unit you can't
  physically power-cycle.
