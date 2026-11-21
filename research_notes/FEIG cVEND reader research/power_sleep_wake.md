# FEIG reader power management, RF control, and sleep/standby/wake

FEIG does not publish the cVEND payment-terminal protocol openly. It sits behind
`cvend-support@feig.de` and a PCI-constrained secure protocol. The strongest
documented mechanisms come from the FEIG OBID ID ISC reader family system manuals
(ID ISC.LR1002, ID ISC.PR/MR/PRH101, ID ISC.PRH200), which share FEIG's advanced
protocol command set and operating-mode architecture. Where a finding is from the
ID ISC family and only inferred to apply to cVEND, that is flagged. Several
promising source PDFs were UHF readers (IUR-F800, ID ISC.MRU102). They use a
different command set and were not relied on for HF/NFC specifics.

## RF-field control and polling modes

FEIG OBID ID ISC readers document a full set of control-byte commands for RF field
and controller control. The important ones are `[0x6A]` RF Output ON/OFF, `[0x69]`
RF Reset, `[0x63]` RF-Controller Reset, and `[0x64]` System Reset. They also
document four operating modes: Host, Buffered Read, Notification, and Scan. The
effect of the RF-output command depends on the active operating mode. A reader in
Buffered Read or Notification mode emits unacknowledged keepalive messages, which
is a strong candidate explanation for the observed 3-second heartbeat.

Findings:

- `[0x6A]` RF Output ON/OFF switches the antenna output on or off. Its effect
  depends on the active operating mode
  ([FEIG ID ISC.LR1002 System Manual](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- `[0x69]` RF Reset resets the RF section. Transponders in the field must be
  re-selected afterward, and the response is sent only after the reset completes.
  Also listed as "7.5 [0x69] RF Reset" in a FEIG-OEM reader manual
  ([Pepperl+Fuchs IUR-F800 tdoct8610](https://files.pepperl-fuchs.com/webcat/navi/productInfo/doct/tdoct8610__eng.pdf)).
- `[0x63]` RF-Controller Reset resets the RF controller. The RF field switches off
  after the CPU reset, but the communication interface is not reset
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html);
  also "7.2 [0x63] RF Controller Reset" in
  [Pepperl+Fuchs IUR-F800 tdoct8610](https://files.pepperl-fuchs.com/webcat/navi/productInfo/doct/tdoct8610__eng.pdf)).
  On some older OBID classic-pro and i-scan manuals, the same `[0x63]` is labeled
  "CPU Reset"
  ([OBID classic-pro Series manual](https://manualslib.com/manual/1633605/Feig-Electronic-Obid-Classic-Pro-Series.html)).
- `[0x64]` System Reset, MODE 0x00, resets the main controller. Resetting the
  controller switches the RF field off and resets the communication interface, so
  it is the full reboot path
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- `[0x66]` Get Reader Info returns firmware/hardware type, revisions, licensed
  options, and RX/TX buffer sizes
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- `[0x6E]` Reader Diagnostic, MODE 0x01, reports status flags including
  temperature, control, impedance, noise, and power. Useful as a non-destructive
  health probe
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- Operating modes:
  - Host Mode (default): the host sends a command and the reader answers each
    one. ISO15693 host commands such as `[0x01]` Inventory and `[0x23]` Read
    Multiple Blocks are available. This is the polling model, where the host
    drives every read.
  - Buffered Read Mode (BRM): the reader scans autonomously and stores results in a
    buffer. The host polls with `[0x22]` Read Buffer, checks fill with `[0x31]`
    Read Data Buffer Info, and clears with `[0x32]` Clear Data Buffer. Requires
    Scan Mode disabled.
  - Notification Mode: works with BRM. The reader pushes buffered data to a
    configured host, and the host must acknowledge each notification with `[0x32]`
    Clear Data Buffer. Keepalive messages are never acknowledged.
  - Scan Mode: the reader emits transponder data as formatted text (USB HID
    keyboard). Only transponder read operations are available. Requires BRM
    disabled.
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html))
- The RF antenna also has a hardware RF button on some HF readers. A short press
  toggles antenna RF power on or off
  ([FEIG OBID i-scan ID ISC.PRH200 manual p.22](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)).

Inference: the observed "3-second heartbeat with no scanning" is most consistent
with the reader being in BRM or Notification Mode and emitting unacknowledged
keepalives, rather than actively answering host-mode polls. If so, the fix is to
confirm or force the mode (read config through `[0x80]`/`[0x81]`, or switch to Host
Mode) and to poll with `[0x22]` Read Buffer and `[0x31]`, plus `[0x32]` to drain,
instead of only sending a status frame.

Because `[0x6A]` has a mode-dependent effect, sending RF-on in the wrong mode may
be a no-op. That likely explains why a status frame does not reliably wake the
scan. `[0x69]` RF Reset is the least disruptive way to restart the antenna and scan
without touching the comm interface. `[0x63]` goes further: field off, then CPU
restart, with the comm interface preserved. `[0x64]` MODE 0x00 is the full reboot
that also drops the serial link.

Gap: the exact `[0x6A]` frame, including the on/off parameter byte and any mode
argument, was not quoted in the accessible text. Confirm it in the model-specific
manual. cVEND's secure protocol may rename or relocate these commands. This is not
verified for cVEND.

## Power-saving, standby, sleep, and power-down

FEIG ID ISC readers document an automatic RF/power timeout, not a host sleep
command. The antenna RF field auto-switches off after a configured on-time, and the
whole reader can power down after a "Power on-time" expires. Both are configured in
CFG21. There is no documented host-protocol sleep, power-down, or wake opcode in
the ID ISC command set. The explicit standby state is just "no host connection,
waiting for commands." This auto-timeout is the most likely documented cause of a
reader going quiet after being idle.

Findings:

- The antenna RF power switches off automatically after a certain time if no
  transponder is detected. This timing is the "RF-Field: minimum on-time" parameter
  in CFG21
  ([FEIG ID ISC.PRH200 manual p.22](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)).
- The antenna cuts power in every case once the "RF-Field: maximum on-time"
  expires. After antenna power drops and the CFG21 "Power on-time" ends, "the
  complete Reader will turn off automatically"
  ([FEIG ID ISC.PRH200 manual p.22](https://manualshive.com/en/manual/obid/id-isc-prh200/3157489?page=22)).
- Without a host connection the reader is "in standby and waits for commands."
  That is idle-waiting, not a low-power sleep state
  ([FEIG CPR70 Manual](https://www.scribd.com/document/721525509/FEIG-CPR70-Manual)).
- No power-save, standby, sleep, or power-down command appears in the ID
  ISC.LR1002 documented command list. Commands run 0x52, 0x63, 0x64, 0x66, 0x69,
  0x6A, 0x6D, 0x6E, 0x72, 0x74, 0x85, 0xA0, 0x80/0x81/0x83, and so on. No sleep
  opcode is present
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).

Inference: entering sleep on a FEIG ID ISC reader is most plausibly the CFG21
RF-Field min/max on-time and Power on-time timers firing after idle, not a commanded
sleep. Exiting is therefore configuration-driven: lengthen or disable the on-time
limits, or periodically stimulate the RF (Inventory, RF Reset, RF Output ON) before
the timer expires, which is a host keepalive.

The twice-observed "stuck asleep, needs power cycle" symptom is consistent with the
reader having powered down its RF or CPU through the timeout while the host kept
sending only status frames that do not re-arm the timer or re-enable RF in the
current mode. For the cVEND specifically, `0x10 02` (restart application) is a
working software recovery. A bare `0x10` wedges it.

Gaps: CFG21 parameter numbers, defaults, and whether cVEND exposes the same
RF-Field on-time timers were not confirmed for firmware 02.35. PRH200 is an HF
sibling, not the cVEND. The exact default min/max on-time values were not found.
Whether any FEIG firmware supports a true low-power CPU sleep with a timed or
character wake is not documented in the accessible sources.

## Idle behavior and host keepalive

No cVEND-specific keepalive or idle spec was found in public docs. The transferable
ID ISC mechanism is to drive the reader in Host Mode and issue a periodic benign
command (Inventory `[0x01]`, Get Reader Info `[0x66]`, or Reader Diagnostic
`[0x6E]`) and/or `[0x6A]` RF Output ON before the CFG21 on-time elapses. In
Buffered or Notification mode, the host must drain the buffer
(`[0x22]`/`[0x31]`/`[0x32]`), and the reader's own keepalives are not acknowledged.

Findings:

- cVEND offers an "easy to use secure protocol" and can run in payment mode or
  transparent card reader mode. Protocol questions go to
  `cvend-support@feig.de`
  ([FEIG cVEND plug user manual](https://manualmachine.com/feigelectronic/cvend/11347140-users-manual)).
- cVEND plug, box, and box+ hold PCI PTS 5.1 certification. The protocol is
  access-controlled
  ([Vending Times: FEIG cVEND PCI PTS 5.1](https://www.vendingtimes.com/blogs/feig-electronics-cvend-terminal-secures-pci-51-certification-delivering-future-proof-payment-applications-to-its-customers/)).
- In Notification Mode the reader pushes data and keepalives. The host acknowledges
  real notifications with `[0x32]`, but keepalives are never acknowledged
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- Host Mode is command/response. Each host command gets exactly one answer.
  ISO15693 Inventory `[0x01]` is the standard "is a card present" poll
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).

Inference: a robust host keepalive for an ID-ISC-style reader is to stay in Host
Mode and send a lightweight command on a fixed cadence shorter than the CFG21
min-on-time, such as periodic Inventory or `[0x66]`/`[0x6E]`, and treat a missed
response as "wedged" and run the recovery ladder. This is inferred from the modes
and CFG21 timers, not a cVEND-documented procedure.

Gap: the cVEND secure protocol frame format, its actual heartbeat or keepalive
interval (the observed 3 seconds), and whether cVEND's scan is driven by a FEIG
BRM/Notification analog are not publicly documented. Confirmation requires the
cVEND SDK/manual through `cvend-support@feig.de`.

## EMVCo contactless duty cycle and LPCD

LPCD, or low-power card detection, replaces continuous full-power polling with
brief periodic field pulses. A card entering the field perturbs it and triggers a
full poll or wake. Public vendor notes give representative timing, such as a 400 ms
inter-poll delay, but the exact EMVCo specification numbers were not retrieved.

Findings:

- LPCD is a mode for battery-limited applications where regular polling pulses are
  replaced by very short LPCD pulses. It is a low-power polling mode for searching
  for and detecting other NFC devices
  ([Renesas PTX205R LPCD application note](https://www.renesas.com/en/document/apn/ptx205r-low-power-card-detection-lpcd-application-note?r=25612866)).
- Duty cycling saves power by keeping the detection signal active only a fraction
  of each period. A hybrid mode runs a full polling loop every second period to
  also catch tags LPCD misses
  ([US patent 12382266](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12382266)).
- To reduce polling power, "add a programmable delay between sequential polling
  attempts." The note's example uses a 400 ms inter-poll delay as a compromise
  between power savings and customer experience. It warns that overly aggressive
  empty-field thresholds reduce detection sensitivity and that EMV contactless spec
  changes increased the required power
  ([Analog Devices: Low Power Polling with Secure NFC Microcontrollers](https://www.analog.com/en/resources/design-notes/low-power-polling-with-maxim-secure-nfc-microcontrollers.html)).

Inference: for a continuously polling validator, the trade-off is sensitivity
versus power and EMI. Too-infrequent or too-insensitive LPCD pulses can make a card
go unseen and look like the reader is asleep. If cVEND uses an LPCD-style idle,
lengthening the active poll window or raising sensitivity may reduce false "asleep"
states. This is not confirmed for cVEND.

Gap: the exact EMVCo contactless polling duty-cycle requirement, such as the
maximum interval between polls and field reset timing, was not found. The EMVCo
Contactless Interface / terminal specification was not retrieved. The NXP PN5180
LPCD app note, which has specific standby-current and timing numbers, returned
HTTP 403.

## Gotchas, reset commands, and safe recovery

FEIG provides a graded set of resets: RF Reset (least disruptive), RF-Controller
Reset, and System Reset (full reboot, drops the serial link). There is an important
addressing gotcha: Baud Rate Detection `[0x52]` only works with the reader's real
COM-ADR, not the broadcast `0xFF`. Documented serial baud in the ID ISC timing
examples is 38.4 kBaud. The accessible docs did not confirm whether a malformed or
incomplete frame hangs the reader. It is likely a frame timeout, but unverified.

Findings:

- Reset ladder, least to most disruptive
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)):
  - `[0x69]` RF Reset: RF section only. Re-select transponders afterward. The
    response returns when the reset is done.
  - `[0x63]` RF-Controller Reset: RF field off after CPU reset. The communication
    interface is not reset, so the serial link survives.
  - `[0x64]` System Reset MODE 0x00: resets the main controller. RF field off and
    communication interface reset, equivalent to a reboot. Expect serial re-init.
- `[0x52]` Baud Rate Detection works only with the actual COM-ADR, not `0xFF`. A
  common cause of a reader appearing unresponsive is the host guessing the address
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- Timing examples are measured at 38.4 kBaud. A modified baud rate "will slightly
  increase the timing." Asynchronous-interface timing is specified in Annex B,
  "Time Behavior of the Asynchronous Interface," keyed to TR-RESPONSE-TIME and CFG1
  (Interface) settings
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- CFG1 (Interface) contains a stop-bit setting marked "do not use." There is a
  transparent-command no-transponder timeout of about 20 ms and a CMD-RES-DELAY
  response-sampling setting
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).
- Continuous output activations (`[0x72]` Set Output) are cleared by a reset or
  power failure. A reset clears latched I/O state
  ([FEIG ID ISC.LR1002](https://manualslib.com/manual/1732092/Feig-Electronic-Obid-Id-Isc-Lr1002.html)).

Recovery ladder for a wedged HF ID-ISC-style reader:

1. Probe, do not assume dead. Send `[0x66]` Get Reader Info or `[0x6E]` Reader
   Diagnostic (mode 0x01) to read power and control status flags. If keepalives are
   arriving, the comm link is alive and the problem is mode or RF, not the UART.
2. Re-arm RF or scan without rebooting. `[0x6A]` RF Output ON in the correct mode,
   then `[0x69]` RF Reset to restart the RF section. In BRM or Notification mode,
   drain with `[0x22]`/`[0x31]`/`[0x32]`.
3. Escalate. `[0x63]` RF-Controller Reset keeps the serial link. Then `[0x64]`
   System Reset MODE 0x00, a full reboot, and re-open or re-detect the serial port
   afterward, before resorting to a hardware power cycle.
4. Prevent recurrence. Verify CFG21 RF-Field min/max on-time and Power on-time are
   not timing the reader into power-down during idle. Add a host keepalive shorter
   than that window. Confirm the configured operating mode matches how the host
   drives it. Address with the real COM-ADR, not 0xFF.

All step details are inferred from the cited command and config behavior. The exact
cVEND sequence is unverified, except for `0x10 02`, which is the known clean
restart.

Gaps: whether an unexpected or incomplete command hangs the reader versus timing
out is not confirmed. The docs imply frame-based timeouts (20 ms transparent
command timeout, TR-RESPONSE-TIME) rather than a hang, but there is no explicit
statement. Annex B's full numeric timing table was not accessible. The supported
baud-rate list and flow control (RTS/CTS versus none) for the serial interface were
not quoted; only 38.4 kBaud as the default measurement rate was confirmed. cVEND
firmware 02.35 specifics (its secure-protocol reset opcodes, exact recovery
sequence, and whether it maps one-to-one to ID ISC
`[0x63]`/`[0x64]`/`[0x69]`/`[0x6A]`) are not public.

## Source reliability

- manualslib ID ISC.LR1002 and manualshive ID ISC.PRH200 are FEIG OEM system
  manuals. They are primary and high confidence for the ID ISC advanced-protocol
  command set and CFG21 RF/power timers, but they are HF reader models, not the
  cVEND payment terminal. Command names and codes are highly likely shared because
  FEIG reuses its advanced protocol, but that is an inference for cVEND.
- Pepperl+Fuchs tdoct8610 (IUR-F800) and ID ISC.MRU102 are FEIG-based UHF readers.
  Their section numbering corroborates the `0x63`/`0x69` command structure, but
  their RF/UHF details do not transfer to an HF/13.56 MHz cVEND.
- The FEIG CPR70 manual and OBID classic-pro documentation are on Scribd and
  manualslib as unofficial mirrors. The content is consistent with FEIG
  conventions, but verify against an official FEIG download if precision matters.
- LPCD and EMVCo numbers come from vendor app notes and patents, not the EMVCo spec
  itself. They are directional, not authoritative for the exact requirement.
