# PM3 ↔ FEIG cVEND "IPP" Serial Protocol: Community Reverse-Engineering

Scope: everything the hobbyist/RE community has published about the INIT PROXmobil3 (PM3) ↔ FEIG cVEND serial protocol ("IPP", 0xBC frames), with emphasis on reader init/handshake and getting the reader to scan cards and emit UID events. Primary source is `wiki.pm3.dev/cvend`. All exact bytes/message types are quoted with URLs.

---

## Key Question 1: What does wiki.pm3.dev document about the cVEND "IPP" protocol, init sequence, message types, and the two 0xBC init messages? Is a prior init/cert handshake or "INITIALIZED" state required to enable card reading?

### Takeaway
`wiki.pm3.dev/cvend` is the single most detailed public source. It fully documents the 0xBC frame format and a large message-type table, and it describes an enable-card flow (host sends `0xE4` ProxCardFunction `00 07 01 01` to enable DESFire at startup). It does **not** mention any certificate handshake, any "INITIALIZED" state, or any requirement to init before card reading — the only documented prerequisite to card reading is enabling the card type with 0xE4. The "two 0xBC messages" are explicitly the only two message types the host sends *after* initialization, and they are DESFire GetVersion (`0x60`) and SelectApplication (`5A2BC3F9`), i.e. application-level reads, not a generic init/handshake.

### Cited Findings

Serial link & frame format — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
- Link: `/dev/ttymxc3`, 115200 8N1 on the PM3's Linux.
- Byte 0 = always `0xBC` (frame magic).
- Byte 1 = `seq` (increments from 1, skips 0 on rollover).
- Byte 2 = `replyTo` (the `seq` being answered, or 0 for unsolicited).
- Byte 3 = `msgType`.
- Bytes 4–5 = `msgLen` (payload length, big-endian; sample `00 68`).
- Byte 6 = `hdrCRC`, CRC-8 Dallas/Maxim over the previous 6 bytes.
- Payload (`msgData`) follows.
- For `msgType >= 0x80` only, a trailing 4-byte `msgCRC` follows (described as little-endian bit-inverted CRC-32/JAMCRC over the payload; author says it doesn't match a recognized polynomial; length field excludes these bytes).

Message-type table (Dir: → host→reader, ← reader→host), names verbatim — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
- `0x02` → Version / `0x03` ← VersionReply (length-prefixed strings: device ID, firmware, cwd)
- `0x04` → Status / `0x05` ← StatusReply (suggested to keep the reader awake)
- `0x07` ← Heartbeat (periodic)
- `0x0F` ← Startup — "sent by reader after startup, approx 1 minute after power on, e.g. `\x00`"
- `0x10` → Reset / `0x11` ← ResetReply (first byte: 2=restart app, 3=reboot, 4=poweroff, 33–36=reset SAM 1–4)
- `0x20` → LEDs (u32 bitmap; e.g. `00 00 00 40`, `00 00 00 80`)
- `0x22` → Buzzer (u16 frequency, u16 duration; e.g. `06 00 01 00`)
- `0x32` → CardRelease
- `0x46` → AbortCardHandling
- `0x96`–`0xA5` → file ops (PutFile/GetFile/DeleteFile/FileInfo/FileList + replies)
- `0xAA` → SetTime / `0xAB` ← SetTimeReply
- `0xAC`–`0xAF` → ITSO (ITSOData/ITSOCtrl + replies)
- `0xB1` ← ISORead ("card UID at offset 2")
- `0xB3` ← ISOCardReleased
- `0xB4` → APDUProx / `0xB5` ← APDUProxReply
- `0xB6` → SAMCtrl / `0xB7` ← SAMCtrlReply
- `0xB9` ← DESFireRead (DESFire card presented)
- `0xBA` → (unknown)
- `0xBB` ← DESFireCardRemoved
- `0xBC` → DESFireCommand / `0xBD` ← DESFireCommandReply
- `0xBE` ← UnhandledCard ("card type not enabled", with UID + historical/historical bytes)
- `0xCE` → (unknown)
- `0xD0` → EMV / `0xD1` ← EMVStatus
- `0xD4` → UltralightCommand / `0xD5` ← UltralightReply
- `0xE4` → ProxCardFunction / `0xE5` ← ProxCardFunctionReply
- `0xE6` → (unknown)
- `0xE8` → SecurityServices / `0xE9` ← SecurityServicesReply
- `0xEA` → (unknown)
- `0xED` ← Log (level byte 1=INFO/2=WARN/3=ERROR, then null-terminated message)

0xE4 ProxCardFunction (enable card type) — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
- Payload = 2 bytes function ID, then `0x01`, then `0x00` (disable) or `0x01` (enable).
- Function IDs: 4=VdvKa, 5=MifareClassic, 6=Iso, 7=DESFire, 8=Girogo, 9=ITSO, 10=UltralightC.
- The PM3 host sends `00 07 01 01` at startup "to enable DESFire reading at startup."
- 0xE5 reply payload = 4 bytes: `00`, function number, `00`, `00`.

0xD5 UltralightReply — card in/out + UID — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
- `replyTo` = 0 for unsolicited events.
- Byte 0 = `0x00` card entered / `0x01` card left.
- Byte 1 = `0x00`.
- Bytes 2–8 = 7-byte UID (e.g. `04 21 B9 01 10 04 03` for an NTAG 215).
- (Note: the table names 0x05/0xD5 "UltralightReply"; the prose attaches the card-entered/left + UID semantics to it.)

The two 0xBC messages (the "init messages" from the task) — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
- Verbatim: "Host only sends two types of messages after initialization - both of type 0xBC. One is length 1 and the body is always 0x60 (+ negated CRC 2A714F60), the other is of length 4 and the body is always 5A2BC3F9 (+ negated-CRC 11A8A56A)."
- Full frames given: `BC2200BC000158602A714F60` (body `0x60` = DESFire **GetVersion**, hdrCRC `58`, trailing CRC `2A714F60`) and `BC2300BC0004AA5A2BC3F911A8A56A` (body `5A2BC3F9` = DESFire **SelectApplication** for app `5A2BC3F9`, hdrCRC `AA`, trailing CRC `11A8A56A`).
- Page notes the DESFire application ID varies by issuer.

"Sample reader flow" (verbatim steps) — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
1. "Host enables desired card type with `ProxCardFunction`."
2. "Reader acknowledges with `ProxCardFunctionReply`."
3. "Reader waits for card, seems like it eventually goes to sleep without any stimuli. Might have to keep it awake by sending packets occasionally (e.g. `Status`)."
- Then (DESFire): reader sends `0xB9` DESFireRead; if type disabled it sends `0xBE`; host sends DESFire commands as `0xBC`, reader replies `0xBD`.

Cert handshake / INITIALIZED state — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend):
- No certificate handshake is described. No "INITIALIZED" state is mentioned. No requirement to initialize before card reading is stated.
- `0xE8` SecurityServices lists key/cert subcommands (ImportX509Cert, GenerateKSKPair, etc.) but with **no flow**.
- A boot-up logic-analyzer capture `cvend-bootup.sal` is linked but the boot sequence is not transcribed into text on the page.

### Inferences
- The wiki frames the two 0xBC messages as DESFire application reads (GetVersion + SelectApplication of the ORCA/issuer app), not as a reader init/handshake. So the "init messages (0xBC body 0x60 / 5A2BC3F9)" in the task are really the steady-state card-read commands the stock firmware emits once a DESFire card is present — they presuppose the reader is already enabled and a card detected.
- Per the wiki's own flow, the only documented step needed to make the reader scan for and report a card (and emit UID via 0xD5/0xB1/0xBE) is sending `0xE4` ProxCardFunction to enable a card type; keeping it awake may require periodic `0x04` Status. The wiki gives no evidence a cert handshake gates basic UID reporting.

### Gaps
- The wiki does not transcribe the `cvend-bootup.sal` capture, so the exact byte-by-byte power-on handshake (Version exchange, any security/0xE8 traffic before enable) is not published in text.
- The `0x60`/`5A2BC3F9` msgCRC algorithm is not fully pinned down (author says the CRC-32 variant "doesn't match any polynomial they recognize"), so independently generating valid 0xBC frames' trailing CRC may not be reproducible from the page alone.

---

## Key Question 2: What do the listed repos/pages contain? Any code that opens the cVEND serial port and successfully reads a card UID? What exact bytes do they send to start polling?

### Takeaway
Two repos touch the cVEND bus: `checkraisefold/rust-feig-app` (a **passive parser/sniffer** that only reads, never writes) and `Jarynnnn/PROXMobil3-HOP` (an idle-screen emulator that **relies on NX to initialize the hardware** and passively sniffs taps). **No published repo sends its own init/enable-polling bytes to the cVEND and gets a UID standalone.** The other repos (proxmobil-stuff, board, proxbeacon) are unrelated to the serial protocol.

### Cited Findings

github.com/checkraisefold/rust-feig-app — passive IPP parser, no sends:
- Listed on the wiki projects page as the project doing "PM3↔cVEND protocol analysis" — [wiki.pm3.dev/projects](https://wiki.pm3.dev/projects).
- Public Rust repo, 3 commits on `main`, no README; `src/` has `main.rs` and `ipp.rs` — [github.com/checkraisefold/rust-feig-app](https://github.com/checkraisefold/rust-feig-app), [api.github.com contents/src](https://api.github.com/repos/checkraisefold/rust-feig-app/contents/src).
- `main.rs`: opens `serialport::new("/dev/ttyS3", 115_200)` with `.timeout(Duration::MAX)`, allocates a receive buffer `vec![0u8; 65536 + 4 + 8]`, loops on `port.read`, parses each frame as `IppMessage` (binrw) and prints it. **It never writes any bytes to the port** — no init, no ProxCardFunction, no frame building, no UID extraction logic — [raw main.rs](https://raw.githubusercontent.com/checkraisefold/rust-feig-app/main/src/main.rs).
- `ipp.rs`: defines `IppMessage` with `#[brw(big, magic = 0xbcu8)]` then fields `sequence_number: u8`, `unk: u8` (the replyTo position, role undocumented), `message_type: u8`, `data_length: u16`, `crc_header: u8`, `data: Message`, and `data_crc: u32` present only when `(message_type >> 7) > 0`. `Message` enum values: Version=0x2, VersionReply=0x3, Status=0x4, StatusReply=0x5, Heartbeat=0x7, Startup=0xF, PICCRead=0xBE (comment "// >=0x80 has crc"), EMVTransactionSuccessUnk=0xD1, plus an `Unknown` catch-all. No UID parsing, no enable/init constants — [raw ipp.rs](https://raw.githubusercontent.com/checkraisefold/rust-feig-app/main/src/ipp.rs).

github.com/Jarynnnn/PROXMobil3-HOP — idle-screen emulator, relies on NX for init, passive tap sniff:
- README: a standby/idle screen emulator for PROXMobil3 with HOP-style animations/feedback on barcode or NFC events; "does not connect to trimet, hop, or any real fare systems"; repo "only exists to host the installer script source" (assets shipped in a GitHub release) — [github.com/Jarynnnn/PROXMobil3-HOP](https://github.com/Jarynnnn/PROXMobil3-HOP).
- `autorun.sh` details — [raw autorun.sh](https://raw.githubusercontent.com/Jarynnnn/PROXMobil3-HOP/main/autorun.sh):
  - NFC device: `NFC_DEV="/dev/ttymxc3"` @115200; barcode `/dev/ttyS5` (symlinked to `/dev/ttyUSB0` if missing).
  - **Does NOT write to the serial ports** — only configures them with `stty` (raw, 8N1, no flow control/echo) and reads with `dd`.
  - `nfc_watch` reads up to 256 bytes, hexdumps them, and treats the substring `"00d1"` as a tap (passive detection). Note: `00 d1` corresponds to a frame with `msgType 0xD1` (EMVStatus), i.e. it keys off the EMV-status reply, not a raw UID.
  - The **only** hardware-init step is `prime_nx`: `systemctl start --no-block nx`, wait ≤10 s for `NxProx` in `pidof`, sleep 20 s ("to init devices (create ttyS5 link, etc)"), `systemctl stop nx`, then `NxExe watchdog 0` (disables PIC32 watchdog). All device/reader setup happens inside NX; the script just starts NX, waits, stops it.

Other repos/pages (not serial-protocol relevant) — [wiki.pm3.dev/projects](https://wiki.pm3.dev/projects):
- `git.uninsane.org/shelvacu/proxmobil-stuff`: "miscellaneous collection, currently mainly DOOM builds for static arm32" (pulls a fork of fbdoom). Not cVEND-related.
- `github.com/haylinmoore/board`: a transit arrival board using the OneBusAway API. App-level only.
- `github.com/mikekutzma/proxbeacon`: an MTA countdown clock. App-level only.
- `git.doof.net/proxdongl3`: a power-adapter PCB (rear D-Sub → 9–33 V passive PoE, USB, I²C EEPROM, power button) + EEPROM payload `flash.py` — hardware/power only, no protocol — also referenced from [kevin.wallace.seattle.wa.us/pm3](https://kevin.wallace.seattle.wa.us/pm3/).

### Inferences
- Every known card-touching project either (a) passively sniffs the 0xBC bus while the stock NX firmware drives the reader (rust-feig-app, HOP's nfc_watch) or (b) boots NX for ~20 s specifically to initialize the NFC/barcode hardware and create the serial device links, then kills NX (HOP). None performs its own cVEND init/enable handshake.
- `/dev/ttyS3` (rust-feig-app) and `/dev/ttymxc3` (HOP + wiki) refer to the same cVEND UART under different names/device links; the HOP note that NX "create[s] required serial device links" explains why a standalone program may not even find the port until NX has run once.

### Gaps
- No public repo demonstrates opening the cVEND UART cold (without NX having initialized it) and driving it to a UID. Whether `0xE4` + `0x04` keep-alive alone suffices from a clean boot is untested in any published code.
- `proxmobil-stuff` was not read file-by-file beyond the wiki's description; if any serial code exists it is not advertised (described as "mainly DOOM").

---

## Key Question 3: Any Reddit / Hackaday / Hackster / Discord / mailing-list / blog coverage of PM3 / cVEND reverse engineering or reading cards?

### Takeaway
Very little published community narrative beyond the wiki and Kevin Wallace's project page. The wiki projects page links three Reddit posts (r/IThinkYouShouldLeave, r/soundtransit, r/Seattle) that are transit-themed PM3 **card/emulator demos**, not protocol write-ups. No Hackaday/Hackster article, no public Discord/mailing-list thread, and no blog with protocol bytes was found in searches.

### Cited Findings
- The wiki projects page links three Reddit posts in r/IThinkYouShouldLeave, r/soundtransit, and r/Seattle described as "transit-themed PM3 card projects"; their content is only inferable from the URLs (demos, not protocol docs) — [wiki.pm3.dev/projects](https://wiki.pm3.dev/projects).
- `kevin.wallace.seattle.wa.us/pm3/` is a personal RE project page. Stated goal: reverse engineer INIT PROXmobil3 variants "to make them suitable for non-transit uses." Key hardware finding: "Dongles dated 2025-12-30 or later contain an EEPROM chip with a payload that enables code execution off of a USB storage device." Boot: supply CL30 continuously, then momentarily supply CL15 (or press the internal power button). Describes the FEIG cVEND plug NFC module as connecting "via UART" but gives **no** serial protocol bytes. No Reddit/Discord/blog links on the page (only a KUT news article about CapMetro retiring the hardware, and the RIPTA system design PDF) — [kevin.wallace.seattle.wa.us/pm3](https://kevin.wallace.seattle.wa.us/pm3/).
- Web searches for Hackaday/Hackster/Discord/Reddit coverage of PROXmobil3/cVEND RE returned only FEIG product datasheets, INIT marketing/product sheets, an ITSO certificate (PROXmobil3 RSP Rail Validator v20.36, ITSO TS 1000 v2.1.4), the 2018 RIPTA system design document, and generic Proxmark3/vending-RE articles — nothing with protocol details — [WebSearch results](https://kevin.wallace.seattle.wa.us/pm3/).

### Inferences
- The reverse-engineering community for this device is small and centralized on `wiki.pm3.dev` + Kevin Wallace's page; there is no mainstream maker-press (Hackaday/Hackster) coverage, and discussion likely happens in private/invite channels not indexed by search (the wiki has an account-request email but no public Discord link was surfaced).

### Gaps
- No public Discord invite, mailing list, or forum thread was located; if one exists it is not discoverable via web search and may be gated behind the wiki account-request process (email `@wiki.pm3.dev`).
- The three linked Reddit posts' actual text was not fetched (URLs only on the wiki); they appear to be demo/show-and-tell, not protocol sources.

---

## Key Question 4: Does anyone describe the cVEND startup certificate handshake, or a way to bypass it / enable raw UID polling without nx and without application keys?

### Takeaway
**No public source describes a cVEND certificate handshake, nor a bypass, nor a confirmed standalone raw-UID-polling sequence.** The wiki documents the enable-and-read flow (0xE4 ProxCardFunction + card events 0xD5/0xB1/0xBE) with no cert step, but no one has published working code that drives the reader to a UID without NX having initialized it first. This is the central unanswered question in the community material.

### Cited Findings
- `wiki.pm3.dev/cvend` documents the full enable/read flow with **no certificate handshake and no INITIALIZED-state requirement**; the only 0xE8 SecurityServices entry lists cert subcommands (ImportX509Cert, GenerateKSKPair) with no flow — [wiki.pm3.dev/cvend](https://wiki.pm3.dev/cvend).
- `wiki.pm3.dev/nx` describes NX as the stock UI that interacts with cvend/barcode/pic32/framebuffer/alsa/init-abtproxy, stoppable via `systemctl stop nx` (also run `NxExe watchdog 0` to stop the PIC32 powering off after 60 s); configured via `/init/efad/pgm/`; a CLI (`./NxProx`) exists. It gives **no** cVEND init/handshake/cert/key details — [wiki.pm3.dev/nx](https://wiki.pm3.dev/nx).
- In practice the one working deployment (HOP emulator) sidesteps the init problem by **booting NX for ~20 s to initialize the NFC hardware and create serial links**, then killing NX and passively reading `/dev/ttymxc3` — i.e. it lets the stock cert-bearing firmware do whatever init is needed, rather than reproducing it — [raw autorun.sh](https://raw.githubusercontent.com/Jarynnnn/PROXMobil3-HOP/main/autorun.sh).

### Inferences
- Taken together, the published record suggests UID/card events (0xD5 card-in/out with 7-byte UID, 0xB1 ISORead UID, 0xBE UnhandledCard UID) are emitted by the reader for *enabled* card types without any application keys — raw UID does not require ORCA/issuer DESFire keys (those are only needed to read the DESFire *application*, i.e. the 0x60/5A2BC3F9 command flow). But because no one has published a from-cold-boot standalone enable sequence, whether a cert/0xE8 exchange is silently required before 0xE4 takes effect remains unconfirmed.

### Gaps
- Whether the cVEND performs a mandatory certificate/security handshake at power-on (visible in the un-transcribed `cvend-bootup.sal` capture) before it will honor 0xE4/report UIDs is **not documented in text anywhere found**. This is the key open question.
- No published, reproducible "open the port cold, send these exact bytes, get a UID without NX" recipe exists. Explicitly: **no working standalone card-read / enable-polling sequence has been published by the community** — all known successes rely on NX to initialize the reader.
