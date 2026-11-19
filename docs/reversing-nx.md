# Reverse-engineering nx

Techniques used to understand `nx` (INIT's stock app, `NxProx`) and the cVEND
reader protocol, kept here so the steps don't have to be rediscovered. Ordered
roughly cheapest and least invasive first.

## The toolkit

### 1. `strings` on the binary (offline, from the dump)

`NxProx` is stripped, but strings exposed most of its structure:

- **Source paths** like `/mnt/nx/src/base/com/ipp/NxIppFeig.cpp` — a free table of
  contents of the codebase. Grepping these maps out every `NxIpp*`, `NxFeig*`,
  `NxBarcodeScanner*` module.
- **Validation regexes** — e.g. `Fahrzeugadresse\s*=\s*[1-9][0-9]*`, which is
  exactly what nx checks to decide it has a vehicle address and can go in service.
- **Error strings** ("No vehicle.dat inside parameter archive", "External EEPROM
  Hardware err") — each is a signpost to a code path and a condition.
- **Command tables** — the `NxExe` subcommands (`eepromdump`, `watchdog`), the
  shell commands (`led`, `ledseq`, `ledtest`), and `NxRemoteShellService: PortNo = 26`.
- **Feature handles** — `SelectIdleCard`, `NxIppBuzzerRequest`, `NxIppLEDsRequest`.

```
strings -n 4 NxProx | grep -iE '<thing>'
strings -n 4 NxProx | grep -E '/mnt/nx/src/'   # the module map
```

### 2. nx's own config and scripts

`env.ini`, `gui.xml`, `opscript.nxs`, `rc5.tab`, `inittab.ini` under
`/init/efad/pgm/` are human-readable. "What does nx do" is often simply written
down there, no reversing needed.

### 3. Runtime logs — the richest cheap signal

`journalctl -u nx` is extremely verbose. It handed us:

- the FEIG reader state machine: `cVEND state change to CONNECTED` → `INITIALIZED`;
- the key dependency: `POST /v1/device/keys … Failed to get Keys (H901)`;
- live card events: `Desfire card detected` / `removed`.

Reading nx's log while poking it answered more than disassembly would have.

### 4. `/proc/<pid>/fd` introspection

Listing nx's open file descriptors showed it opens only `fb0`, `ttymxc2`,
`ttymxc3`, `ttyUSB0`. That *proved* there is no touchscreen (no input device is
ever opened) and confirmed which UART is which peripheral.

```
ls -l /proc/$(pgrep -f NxProx)/fd | grep /dev/
```

### 5. Framebuffer capture

`cat /dev/fb0` → interpret as 800×480 BGRX → PNG lets you *see* nx's actual screen
(OUT OF SERVICE vs the live SCAN/TAP screen). Its visible state machine, observed
directly.

### 6. `LD_PRELOAD` syscall interception — what cracked the protocol

A tiny C shim (`sniffer/cvsniff.c`) that wraps `read()`/`write()` and logs any
traffic on the reader's fd. Three details made it work here:

- it uses raw `syscall()` calls only, so it needs just **glibc 2.4** base symbols
  and loads on the 2019 userland;
- it identifies the target fd by `readlink`-ing `/proc/self/fd/N` for `ttymxc3`
  (and `ttymxc2`);
- it is preloaded via a **systemd drop-in** so nx runs robustly and keeps feeding
  the watchdog, instead of a fragile hand-launched copy:

```
mkdir -p /run/systemd/system/nx.service.d
printf '[Service]\nEnvironment=LD_PRELOAD=/init/cvsniff.so\n' \
  > /run/systemd/system/nx.service.d/sniff.conf
systemctl daemon-reload && systemctl restart nx
```

This captured the exact bytes nx sends the reader — the init sequence, and the
fact that it sends nothing afterward to sustain scanning.

### 7. Component substitution

`keyserver/keyserve.c` replacing `abtproxy` on port 80 is reverse-by-substitution:
swap a dependency, watch nx's reaction. It confirmed the key-fetch gating and drove
nx fully in service offline.

### 8. The unstripped sibling

`NxProx` is stripped but `proxy_server` (abtproxy) is built with debug_info. The
unstripped sibling's symbols and strings gave the shared JSON schema and HTTP routes
for free.

## Two gotchas

- Run nx **under systemd, not by hand.** A hand-launched copy holds the hardware
  and blocks the service from starting, and it dies with your SSH session — taking
  the watchdog feed with it, which powers the unit off.
- **Disable the PIC32 watchdog the instant you stop nx**, in the same command, not
  a step later.

## The streaming reader frames

While the cVEND scans (continuously, see `INTERFACE.md`), it pushes a stream of
frames. Two matter.

### `0xD1` card record — the idle/state stream

Streams continuously whether or not a card is present. EMV-style BER-TLV: an outer
container tag `ff fe e0 04` holding FEIG proprietary tags `df fe e0 NN`.

```
05 fffee004 39              count=05, container tag fffee004, len=0x39
  df fe e0 08  01  10       poll/state counter A  (seen 10 → 15 → 19)
  df fe e0 09  01  01       poll/state counter B  (seen 01 → 02 → 05)
  df fe e0 0a  03  000000
  df fe e0 0e  08  00…00    card token / UID slot (8 bytes) — zero when unhandled
  df fe e0 0b  01  00
  df fe e0 0c  06  00…00
  df fe e0 0d  02  0000
```

The `08`/`09` fields change frame to frame — that is the "stream ticking" between
scans; they look like the reader's poll or RF-field state counters. All the data
fields are zero while scanning an unhandled or absent card. The `df fe e0 0e` slot
(8 bytes) is where a *handled* card's token/UID lands once nx has the application
keys and processes the tap; without keys it stays zero and the UID arrives via
`0xBE` instead. (The community `rust-feig-app` labels `0xD1` "EMV transaction
success", consistent with this being the fare/token record.)

### `0xBE` unhandled card — the UID carrier

For card types not enabled (our standalone case), each card arrives as `0xBE`:

```
00        status (card present)
0c        length
00×9      reserved
04 50 67 0a 81 22 90   7-byte ISO14443A UID (NXP cards start 0x04)
44 03     ATQA (~0x0344, typical of DESFire)
```

The UID reliably starts at the first `0x04` byte in the payload. `pm3.py`'s
`_find_uid()` scans for that. For *enabled* card types the UID instead comes in a
`0xD5` (card in/out) or `0xB1` (ISO14443A read) frame; see `INTERFACE.md` for those.

### Takeaway for reading UIDs

The `0xD1` stream is the reader's own heartbeat/state and carries no UID in the
keyless case — don't wait on it. Watch for `0xBE` (or `0xD5`/`0xB1` if you enable
card types) and pull the UID from there. Keep the `0x04` status keepalive going so
the `0xD1` stream (and the scanning behind it) never stops.
