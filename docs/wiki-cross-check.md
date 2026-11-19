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

## Pending — needs specific hardware

- **`0x32` CardRelease / `0x46` AbortCardHandling.** Wiki documents these with no
  payload; reply is `0xB3` ISOCardReleased. Directly relevant to the "same card
  only reads once until removed" behavior — releasing the card may let the base
  scan re-report it on a second tap without physically lifting it. Testable with
  any card in the field.
- **`0xD4` UltralightCommand.** Read `02 <start_page> <num_pages>`, Write
  `03 <page> <4 bytes>`, Authenticate `04/05/06`, Abort `07`; reply `0xD5`
  `[subcmd][status][payload]`, status `00` ok / `01` op error (no card) / `02`
  bad params. Needs a MIFARE Ultralight-family tag — an **amiibo (NTAG215)** or a
  **Flipper Zero** emulating one. Our ORCA/DESFire cards won't answer Ultralight
  commands.
- **`0x10` Reset subcmds.** Wiki: `2` restart app, `3` reboot, `4` poweroff,
  `33–36` reset SAM 1–4. We already know a reset wedges the reader (power-cycle
  to recover), so these stay untested unless there's a reason — avoid `3`/`4` on
  a unit you can't physically power-cycle.
