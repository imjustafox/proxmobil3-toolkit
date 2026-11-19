# FEIG Reader Power Management, RF-Field Control, and Sleep/Standby/Wake Behavior

Scope note: FEIG does not publish the cVEND payment-terminal protocol openly (it is behind
`cvend-support@feig.de` and a PCI-constrained "secure protocol"). The strongest documented
mechanisms come from the FEIG OBID ID ISC reader family system manuals (ID ISC.LR1002,
ID ISC.PR/MR/PRH101, ID ISC.PRH200), which share FEIG's "advanced protocol" command set and
operating-mode architecture. Where a finding is from the ID ISC family and only *inferred* to
apply to cVEND, that is flagged. Several promising source PDFs were UHF readers (IUR-F800,
ID ISC.MRU102) — those use a different command set and were not relied on for HF/NFC specifics.

---

## Q1: RF-field control and polling/mode commands (RF on/off, Host vs. Buffered/Notification/Scan)

### Takeaway
FEIG OBID ID ISC readers document a full set of control-byte commands for RF-field and controller
control — most importantly **[0x6A] RF Output ON/OFF**, **[0x69] RF Reset**, **[0x63] RF-Controller
Reset**, and **[0x64] System Reset** — and four distinct operating modes (Host, Buffered Read,
Notification, Scan). Crucially, the effect of the RF-output command "depends on the active operating
mode," and a reader in Buffered-Read/Notification mode emits unacknowledged **keepalive** messages,
which is a strong candidate explanation for the observed "3-second heartbeat."

### Cited Findings
- **[0x6A] RF Output ON/OFF** switches the antenna output on or off; *its effect depends on the active
  operating mode* — [FEIG ID ISC.LR1002 System Manual (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- **[0x69] RF Reset** resets the RF section; transponders in the field must be re-selected afterward;
  the command response is sent only after the reset completes — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html). Also listed as section "7.5 [0x69] RF Reset" in a FEIG-OEM reader manual — [Pepperl+Fuchs IUR-F800 (FEIG-based) tdoct8610](https://files.pepperl-fuchs.com/webcat/navi/productInfo/doct/tdoct8610__eng.pdf)
- **[0x63] RF-Controller Reset** resets the RF controller; *the RF field switches off after the CPU
  reset, but the communication interface is NOT reset* — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html); listed as "7.2 [0x63] RF Controller Reset" in [Pepperl+Fuchs IUR-F800 tdoct8610](https://files.pepperl-fuchs.com/webcat/navi/productInfo/doct/tdoct8610__eng.pdf). (Note: on some older OBID classic-pro / i-scan manuals the same **[0x63]** is labeled "CPU Reset" — [OBID classic-pro Series manual (manualslib)](https://manualslib.com/manual/1633605/Feig-Electronic-Obid-Classic-Pro-Series.html))
- **[0x64] System Reset**: MODE 0x00 resets the main controller; resetting the controller *switches the
  RF field off AND resets the communication interface* (full reboot path) — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- **[0x66] Get Reader Info** returns firmware/hardware type, revisions, licensed options, and RX/TX
  buffer sizes — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- **[0x6E] Reader Diagnostic** MODE 0x01 reports status flags including temperature, control, impedance,
  noise, and power — useful as a non-destructive health probe — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- **Operating modes** — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html):
  - **Host Mode** (default): host sends a command, reader answers each one; ISO15693 host commands such
    as [0x01] Inventory and [0x23] Read Multiple Blocks are available here. This is the "polling"
    model — the host drives every read.
  - **Buffered Read Mode (BRM)**: reader scans autonomously and stores results in a buffer; host polls
    with [0x22] Read Buffer, checks fill with [0x31] Read Data Buffer Info, clears with [0x32] Clear
    Data Buffer. Requires Scan Mode disabled.
  - **Notification Mode**: works with BRM; reader *pushes* buffered data to a configured host; host must
    acknowledge each notification with [0x32] Clear Data Buffer. **Keepalive messages are never
    acknowledged.**
  - **Scan Mode**: reader emits transponder data as formatted text (USB = HID keyboard). "Only
    transponder read operations are available with the Scan Mode." Requires BRM disabled.
- The RF antenna also has a **hardware RF button** on some HF readers: a short press toggles antenna RF
  power on/off — [FEIG OBID i-scan ID ISC.PRH200 manual (manualshive p.22)](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)

### Inferences
- The observed "3-second heartbeat with no scanning" is most consistent with the reader being in
  **Buffered Read Mode / Notification Mode emitting unacknowledged keepalives**, rather than actively
  answering host-mode polls. If so, the fix is to confirm/force the mode (read CFG via [0x80]/[0x81],
  or switch to Host Mode) and to **poll with [0x22] Read Buffer / [0x31]** plus [0x32] to drain and keep
  it live, instead of only sending a status frame.
- Because [0x6A]'s effect "depends on the active operating mode," sending RF-on in the wrong mode may be
  a no-op — this likely explains why "sending a status frame does not reliably wake its scan."
- **[0x69] RF Reset** (RF section only, field returns on completion) is the least disruptive way to
  restart the antenna/scan without touching the comm interface; **[0x63]** goes further (field off, then
  CPU restarts, comm interface preserved); **[0x64] MODE 0x00** is the full reboot that also drops the
  serial link.

### Gaps
- Exact byte frame of [0x6A] (the on/off parameter byte and any mode argument) was not quoted in the
  accessible text — confirm in the model-specific manual. cVEND's secure protocol may rename/relocate
  these; not verified for cVEND.

---

## Q2: Power-saving / standby / sleep / power-down modes — entry and exit

### Takeaway
FEIG ID ISC readers do document an **automatic RF/power timeout** (not a host "sleep command"):
the antenna RF field auto-switches off after a configured on-time, and the whole reader can power down
after a "Power on-time" expires — all configured in **CFG21**. There is no documented host-protocol
"Sleep"/"Power Down"/"Wake" opcode in the ID ISC command set; the explicit standby state is simply
"no host connection, waiting for commands." This auto-timeout is the most likely documented cause of a
reader going quiet "after being idle."

### Cited Findings
- The RF power of the antenna is **automatically switched off after a certain time if no transponder has
  been detected**; this timing is the **"RF-Field: minimum on-time"** parameter in **CFG21** — [FEIG ID ISC.PRH200 manual (manualshive p.22)](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)
- The antenna cuts power *in every case* once the **"RF-Field: maximum on-time"** expires; after antenna
  power drops and the CFG21 **"Power on-time"** ends, *"the complete Reader will turn off automatically"*
  — [FEIG ID ISC.PRH200 manual (manualshive p.22)](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)
- Without a host connection the reader is "in standby and waits for commands" (idle-waiting, not a
  low-power sleep state) — [FEIG CPR70 Manual (Scribd)](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)
- No power-save / standby / sleep / power-down command appears in the ID ISC.LR1002 documented command
  list (commands run 0x52, 0x63, 0x64, 0x66, 0x69, 0x6A, 0x6D, 0x6E, 0x72, 0x74, 0x85, 0xA0, 0x80/0x81/0x83…;
  no sleep opcode present) — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)

### Inferences
- "Entering sleep" on a FEIG ID ISC reader is most plausibly the **CFG21 RF-Field min/max on-time and
  Power on-time timers firing** after idle, not a commanded sleep. "Exit" is therefore configuration-
  driven: lengthen/disable the on-time limits, or periodically stimulate the RF (Inventory / RF Reset /
  RF Output ON) before the timer expires, i.e. a host keepalive. (Inference from CFG21 timers + lack of a
  wake opcode.)
- The twice-observed "stuck asleep, needs power cycle" symptom is consistent with the reader having
  powered-down its RF (or CPU) via the timeout while the host kept sending only status frames that do not
  re-arm the timer or re-enable RF in the current mode.

### Gaps
- CFG21 parameter numbers/defaults and whether cVEND exposes the same RF-Field on-time timers were not
  confirmed for firmware 02.35 cVEND specifically (PRH200 is an HF sibling, not the cVEND). The exact
  default min/max on-time values were not found.
- Whether any FEIG firmware supports a true low-power CPU sleep with a timed or character wake is not
  documented in the accessible sources (none found) — treat as unknown.

---

## Q3: cVEND / ID ISC.PR.MR idle-without-stimuli behavior and how the host keeps it awake

### Takeaway
No cVEND-specific keepalive/idle spec was found in public docs. The transferable ID ISC mechanism is:
drive it in **Host Mode** and issue a periodic benign command (Inventory [0x01], Get Reader Info [0x66],
or Reader Diagnostic [0x6E]) and/or [0x6A] RF Output ON before the CFG21 on-time timer elapses; in
Buffered/Notification mode, the host must drain the buffer ([0x22]/[0x31]/[0x32]) and the reader's own
keepalives are *not* acknowledged.

### Cited Findings
- cVEND offers an "easy to use secure protocol" and can run in **payment mode** or **transparent card
  reader mode**; protocol questions go to `cvend-support@feig.de` — [FEIG cVEND plug user manual (manualmachine)](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual)
- cVEND plug/box/box+ hold PCI PTS 5.1 certification (context: payment terminal, protocol is access-
  controlled) — [Vending Times: FEIG cVEND PCI PTS 5.1](https://www.vendingtimes.com/blogs/feig-electronics-cvend-terminal-secures-pci-51-certification-delivering-future-proof-payment-applications-to-its-customers/)
- In Notification Mode the reader pushes data and keepalives; the host acknowledges real notifications
  with [0x32] but keepalives are never acknowledged — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- Host Mode is command/response: each host command gets exactly one answer; ISO15693 Inventory [0x01] is
  the standard "is a card present" poll — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)

### Inferences
- A robust host keepalive for an ID-ISC-style reader: in Host Mode send a lightweight command on a fixed
  cadence (shorter than CFG21 min-on-time), e.g. periodic Inventory or [0x66]/[0x6E]; treat any missed
  response as "reader wedged" and run the recovery ladder (Q5). This is inferred from the modes +
  CFG21 timers, not a cVEND-documented procedure.

### Gaps
- The cVEND "secure protocol" frame format, its actual heartbeat/keepalive interval (the observed 3 s),
  and whether cVEND's scan is driven by a FEIG BRM/Notification analog are **not publicly documented** —
  confirmation requires FEIG's cVEND SDK/manual via `cvend-support@feig.de`.

---

## Q4: EMVCo contactless polling duty cycle and NFC Low Power Card Detection (LPCD)

### Takeaway
LPCD/low-power polling replaces continuous full-power polling with brief periodic field pulses; a card
entering the field perturbs it and triggers a full poll/wake. Public vendor notes give representative
timing (e.g. ~400 ms inter-poll delay) but the exact EMVCo specification numbers were not retrieved.

### Cited Findings
- LPCD is a mode for battery-limited applications where regular polling pulses are replaced by **very
  short LPCD pulses**; it is a low-power polling mode for searching/detecting other NFC device(s) —
  [Renesas PTX205R LPCD application note](https://www.renesas.com/en/document/apn/ptx205r-low-power-card-detection-lpcd-application-note?r=25612866)
- Duty cycling saves power by keeping the detection signal active only a fraction of each period; a
  "hybrid mode" runs a full polling loop every second period to also catch tags LPCD misses — [US patent on LPCD (ppubs.uspto.gov 12382266)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12382266)
- To reduce polling power, "add a programmable delay between sequential polling attempts"; the note's
  example uses a **400 ms inter-polling delay** as a compromise between power savings and customer
  experience; it warns that overly aggressive empty-field thresholds reduce detection sensitivity, and
  that EMV contactless spec changes **increased required power** — [Analog Devices: Low Power Polling with Secure NFC Microcontrollers](https://www.analog.com/en/resources/design-notes/low-power-polling-with-maxim-secure-nfc-microcontrollers.html)

### Inferences
- For a continuously-polling validator, the trade-off is sensitivity vs. power/EMI: too-infrequent or
  too-insensitive LPCD pulses can make a card "not seen" and look like the reader is asleep. If cVEND
  uses an LPCD-style idle, lengthening the active poll window or raising sensitivity may reduce false
  "asleep" states. (Inference — not confirmed for cVEND.)

### Gaps
- The exact EMVCo contactless polling duty-cycle requirement (e.g. maximum interval between polls / field
  reset timing) was not found; the EMVCo Contactless Interface / terminal specification itself was not
  retrieved. The NXP PN5180 LPCD app note (specific standby-current and timing numbers) returned HTTP 403.

---

## Q5: Known gotchas, reset/reboot commands, and safe recovery procedure; serial-line behavior

### Takeaway
FEIG provides a graded set of resets — RF Reset (least disruptive) → RF-Controller Reset → System Reset
(full reboot, drops serial link) — and an important addressing gotcha: **Baud Rate Detection ([0x52])
only works with the reader's real COM-ADR, not the broadcast 0xFF**. Documented serial baud in the ID
ISC timing examples is 38.4 kBaud. The accessible docs did not confirm whether a malformed/incomplete
frame hangs the reader (likely a frame timeout, but unverified).

### Cited Findings
- Reset ladder (least → most disruptive) — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html):
  - **[0x69] RF Reset** — RF section only; re-select transponders after; response returns when reset done.
  - **[0x63] RF-Controller Reset** — RF field off after CPU reset; **communication interface is NOT reset**
    (serial link survives).
  - **[0x64] System Reset (MODE 0x00)** — resets main controller; **RF field off AND communication
    interface reset** (equivalent to reboot; expect serial re-init).
- **[0x52] Baud Rate Detection** works **only with the actual COM-ADR, not 0xFF** — a common cause of a
  reader appearing unresponsive if the host guesses the address — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- Timing examples are measured at **38.4 kBaud**; a modified baud rate "will slightly increase the
  timing." The asynchronous-interface timing is specified in Annex B ("Time Behavior of the Asynchronous
  Interface"), keyed to **TR-RESPONSE-TIME** and CFG1 (Interface) settings — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- CFG1 (Interface) contains a stop-bit setting marked "do not use"; a transparent-command no-transponder
  timeout of ~20 ms and a CMD-RES-DELAY response-sampling setting exist — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)
- Continuous output activations ([0x72] Set Output) are cleared by a reset or power failure — useful to
  know a reset clears latched I/O state — [FEIG ID ISC.LR1002 (manualslib)](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)

### Inferences (recovery ladder for a wedged reader, HF ID-ISC-style)
1. **Probe, don't assume dead:** send [0x66] Get Reader Info or [0x6E] Reader Diagnostic (mode 0x01) to
   read power/control status flags. If keepalives are arriving, the comm link is alive — the problem is
   mode/RF, not the UART.
2. **Re-arm RF/scan without rebooting:** [0x6A] RF Output ON (in the correct mode), then [0x69] RF Reset
   to restart the RF section; in BRM/Notification, drain with [0x22]/[0x31]/[0x32].
3. **Escalate:** [0x63] RF-Controller Reset (keeps serial link), then [0x64] System Reset MODE 0x00 (full
   reboot; re-open/re-detect the serial port afterward) before resorting to a hardware power cycle.
4. **Prevent recurrence:** verify CFG21 RF-Field min/max on-time and Power on-time are not timing the
   reader into power-down during idle; add a host keepalive shorter than that window; confirm the
   configured operating mode matches how the host drives it; address with the real COM-ADR, not 0xFF.
   (All step details inferred from the cited command/CFG behavior; the exact cVEND sequence is unverified.)

### Gaps
- Whether an unexpected/incomplete command *hangs* the reader vs. times out: **not confirmed**. The docs
  imply frame-based timeouts (20 ms transparent-command timeout, TR-RESPONSE-TIME) rather than a hang,
  but no explicit statement was found. Annex B's full numeric timing table was not accessible.
- Supported baud-rate list and flow-control (RTS/CTS vs none) for the serial interface were not quoted;
  only 38.4 kBaud (default/measurement rate) was confirmed.
- cVEND firmware 02.35 specifics (its secure-protocol reset opcodes, exact recovery sequence, and whether
  it maps 1:1 to ID ISC [0x63]/[0x64]/[0x69]/[0x6A]) are **not public** — confirm via FEIG cVEND SDK /
  `cvend-support@feig.de`.

---

## Source reliability notes
- **manualslib ID ISC.LR1002** and **manualshive ID ISC.PRH200** are FEIG OEM system manuals (primary,
  high confidence for the ID ISC advanced-protocol command set and CFG21 RF/power timers), but these are
  HF *reader* models, not the cVEND payment terminal — command names/codes are highly likely shared
  (FEIG reuses its advanced protocol) but are an inference for cVEND.
- **Pepperl+Fuchs tdoct8610 (IUR-F800)** and **ID ISC.MRU102** are FEIG-based **UHF** readers; their
  section numbering corroborates the 0x63/0x69 command structure but their RF/UHF command details do not
  transfer to HF/13.56 MHz cVEND.
- **FEIG CPR70 manual** and **OBID classic-pro** are on Scribd/manualslib (unofficial mirrors) — content
  consistent with FEIG conventions but verify against an official FEIG download if precision matters.
- LPCD/EMVCo numbers are from **vendor app notes and patents**, not the EMVCo spec itself — directional,
  not authoritative for the exact EMVCo requirement.
