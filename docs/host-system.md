# The PM3 host system (i.MX6) — software deep dive

The PROXmobil3 is really **two computers**: the FEIG cVEND reader (its own ARM +
Buildroot, documented in `docs/feig-firmware.md`), and the **host** — an NXP
i.MX6 Solo running INIT's PTXdist Linux, which drives the screen, talks to the
reader and the PIC32 over serial, and runs the transit application. This document
covers the host software. The hardware/peripherals are in
`INTERFACE.md`; the stock UI app's RE techniques are in `docs/reversing-nx.md`;
here the focus is the system layout and the **account-based-ticketing (ABT)
backend client**, which is the host's most substantial piece.

> Secrets note: the backend config holds CapMetro's OAuth client secret, access
> token, and card keys, and the local DB/denylist hold rider card tokens. Those
> live only in the git-ignored `dumps/` and are **never** committed. Everything
> below is architecture and schema, with the production hostname, client id, and
> all secret values redacted.

## 1. Boot and storage

- **SoC/kernel:** i.MX6 Solo, `Linux 4.9.166-fsl-imx-INIT-004` (armv7l, PTXdist
  2019.03). Kernel cmdline: `root=/dev/sda1 ro rootfstype=ext4 rootwait cma=128M
  imx-fbdev.legacyfb_depth=32 consoleblank=0 quiet`.
- **Storage (three block devices + SPI flash):**
  - `/dev/sda1` → `/` — rootfs, **ext4, mounted read-only** (the PTXdist system).
  - `/dev/sdb1` → `/init` — ext4, read-write: all the app payload (`efad/` = nx,
    `abtproxy/`, `autorun/`, `system/`, `tools/`, …).
  - `/dev/sdc1` → `/init/efad/mp_sd` — the dongle/USB, vfat.
  - `mtdblock0` — 16 MB SPI NOR (Micron **N25Q128**, `m25p80`), holding U-Boot +
    environment (and the kernel/DTB for the `sf read` boot path).
  - Imaged copies: `dumps/sda.img`, `dumps/sdb.img`, `dumps/mtdblock0.img`
    (git-ignored), extracted under `dumps/extracted/`.
- **Crypto:** the i.MX6 **CAAM** engine (Era 4) with a hardware RNG4 is active
  (`caam` in `/proc/crypto`) — available to the host for crypto/entropy,
  independent of the reader's HSM.
- **Init:** systemd. The two app services are `init-abtproxy.service` (enabled)
  and `nx.service` (disabled by default; `FailureAction=poweroff`, so be careful —
  see `docs/feig-firmware.md`/`INTERFACE.md`). Our SSH/autorun path runs instead of
  nx via the dongle EEPROM.

## 2. The software stack

```
 [FEIG cVEND reader] --IPP/serial(ttymxc3)--> nx (NxProx, the UI/validator)
                                               |  HTTP to localhost:80
                                               v
                                        proxy_server (abtproxy)
                                               |  HTTPS + OAuth2 (libcurl)
                                               v
                                   Bytemark ABT cloud ("UVAPI")
```

- **nx / `NxProx`** (`/init/efad/pgm/`, 11.3 MB) — the on-screen validator: draws
  the framebuffer, runs the reader state machine, and for each tap asks the local
  backend whether to accept. It fetches card keys/labels and posts transactions to
  `http://127.0.0.1:80/v1/device/*`. RE notes: `docs/reversing-nx.md`.
- **`proxy_server` / abtproxy** (`/init/abtproxy/`, 13.5 MB, **V1.3.6**) — a local
  HTTP server **and** cloud client that implements account-based ticketing. This is
  the piece reversed below.

## 3. The ABT backend client (`proxy_server`)

A symbol-rich `elf32-littlearm` C++ binary (INIT/Bytemark code; embedded source
tree `…/Bytemark/…`). Modules (`.cpp`): `httpd` (the local HTTP server),
`HttpResponse`, `HTTPClient`/`CurlHandle` (libcurl to the cloud), `ProxyClient`
(the backend API), `ProxyValidation`, `ProxyPassback`, `ProxyDecryption` /
`ProxyKeysMapper`, `ProxySynchronization`, `ProxyDatabase`, `Config`, jsoncpp,
`xml`, `Utilities`.

### Local HTTP API (served to nx on `:80`)

`httpd` serves three routes — these are exactly what nx polls and what our
`keyserver/` fakes:

- `GET/POST /v1/device/keys` — the card decryption/application keys.
- `GET/POST /v1/device/labels` — the fare-product label table.
- `POST /v1/device/transactions` — tap/validation events from nx.

### Cloud side — Bytemark "UVAPI" over OAuth2

`ProxyClient` speaks Bytemark's validation API ("UVAPI"):
`GetAccessToken` (OAuth2 client-credentials → bearer, `CURLOPT_XOAUTH2_BEARER`),
then `MapInitRequestToUvapiRequest` → `SendUvapiRequest` →
`ProcessUvapiResponse` / `GetResponseCode`. The endpoints (from `config.json`,
hostname redacted) are a REST set on the Bytemark backend:

| Config key | Endpoint (path) | Purpose |
|---|---|---|
| Validate Now URL | `…/validate_now` | online per-tap validation |
| Offline Upload URL | `…/validation_event_batches` | batch-upload queued offline taps |
| Sync Deny List URL | `…/validation_lists` | pull the card denylist/hotlist |
| Sync Labels URL | `…/validator_operating_data` | pull fare-product labels |
| Sync Keys URL | `…` (redacted) | pull card keys |
| Access Token URL | `…` (redacted) | OAuth2 token endpoint |

Sync periods from the config: denylist 5 min, labels 5 min, offline transactions
5 min, keys (period redacted). Other non-secret config: `HTTP Server Port = 80`,
`Device ID`, `Default Route ID`, agency allow-flags (`Allow AUSTINCC`,
`Allow UTAUSTIN` — this is a Central-Texas/CapMetro deployment), `Validator
Request Timeout = 2000 ms`, and passback timeout/message.

### Online vs offline validation

- **Online:** nx tap → `proxy_server` → `validate_now` (OAuth2 bearer) → backend
  decides accept/deny → shown on screen.
- **Offline:** if the backend is unreachable, `ProxyValidation` decides locally
  from the synced **denylist** (`denylist.json`, ~1.3 MB of blocked card tokens)
  and keys, shows the configured offline messages (success: *"Validator offline,
  please board the bus."*; fail: *"Card has been blocked"*), and queues the tap in
  the local DB for later upload.
- **`ProxyPassback`** enforces anti-passback (a configurable timeout preventing the
  same card re-validating immediately).
- **`ProxyDecryption`/`ProxyKeysMapper`** decrypt the card payload with the synced
  keys before validation.

### Local database (`proxyDB.db`, SQLite)

`ProxyDatabase` (`OpenDatabase`/`CloseDatabase`, `GetSavedTransactionCount`,
`TransactionIsUploaded`) manages a single table:

```sql
CREATE TABLE OfflineTransactions (TRANSACTION_DATA TEXT NOT NULL);
```

Each row is a JSON tap/validation event captured while offline, uploaded in
batches to `validation_event_batches` and then cleared. (Rows are rider card data
— not examined or published.)

### Synced data files (`/init/abtproxy/`)

The files `proxy_server` caches from the backend, with their shapes (values are
rider/agency data — schema only):

- **`labels.json`** — `{"labels": [ { "id": int, "type": str, "value": str,
  "group": null, "additional_items": [] }, … ]}` (79 entries on our unit; nx loads
  the subset with a valid designator). The fare-product label table shown on
  screen (e.g. day passes, concessions).
- **`denylist.json`** (~1.3 MB) — a Bytemark API envelope `{"data": …,
  "errors": [], "server_time": …}` where `data` is the card hotlist pulled from
  `/validation_lists`. Blocked card tokens; not examined/published.
- **`keys.json`** — the `/v1/device/keys` payload (card application keys);
  **secret**, git-ignored.
- **`VERSION.info`** — `V1.3.6`. `proxyDB.db` is the SQLite queue (above).

### Driving it offline ourselves

`keyserver/keyserve.c` is a tiny stand-in for this whole thing: it serves cached
`/v1/device/keys` and `/v1/device/labels` locally so nx goes in service with no
cloud and no OAuth. It does **not** reach the Bytemark backend or use the real
credentials (which stay in `dumps/`). See `docs/reversing-nx.md` and
`docs/wiki-cross-check.md` for driving nx in service headlessly.

## 4. Boot chain and the access mechanism

**U-Boot `2018.03-INIT-004`** (Mar 2019) on the TQMa6S module, debug console on
`ttymxc1` (the "ARMcons" header), `bootdelay` 1–3 s. Boot flow:

- `bootcmd = run sdboot; run failover; run sdboot; run panicboot`.
- `sdboot`/`mmcboot` → `loadimage` + `loadfdt` fetch the kernel (`${kernel_name}`)
  and device tree (`${fdt_name}`) either from the SD boot partition
  (`ext4load usb …:boot/…`) or from **SPI flash** (`sf probe; sf read` at
  `${kernel_start}`/`${kernel_sectors}`), then boot.
- **A/B failover:** `failover=setenv kernel_name ${kernel_name}.old; setenv
  fdt_name ${fdt_name}.old` — on a bad boot it retries the `.old` kernel/DTB, so a
  failed update rolls back. `panicboot` resets if nothing boots.
- `netboot` (TFTP from `serverip`, NFS `rootpath=/srv/nfs/tqma6`) is a dev-only
  fallback. `mmcargs = run addmmc addtty addfb addcma` assembles the kernel
  cmdline (root=`/dev/sda1 ro`, console, framebuffer, `cma=128M`).

**Userland init** (systemd): mounts `/init` (`sdb1`), runs `init-rc.service` which
executes the `/init/autorun/*.sh` scripts in order, then normally starts
`nx.service` + `init-abtproxy.service`. The autorun scripts are the device's
**maintenance/access mechanism**:

1. `10-eeprom.sh` — dumps the dongle's EEPROM to `/tmp/eeprom.dat` via
   `NxExe eepromdump` (the "NX Toolbox" CLI; other subcommands include `watchdog`),
   with a 5 s timeout, then normalizes it to text.
2. `20-ext-sdcard.sh` — mounts the mounting-plate external SD/USB
   (`platform-ci_hdrc.1-usb-…-part1`) at `/init/efad/mp_sd`; if absent it replaces
   the mountpoint with a plain *file* so nx notices rather than silently writing to
   the internal SD.
3. `90-testmode.sh` — **the access trigger**: if `/tmp/eeprom.dat` contains a
   `[TestMode]` section, it `systemctl stop nx`, runs `NxExe watchdog 0`, extracts
   the shell script lines under `[TestMode]`, and **executes them**. This is how a
   PROXdongl3 with a `[TestMode]` EEPROM payload gets arbitrary boot-time code with
   nx stopped and the watchdog disabled — i.e. how our `usb/autorun.sh` installs an
   SSH key (see `README.md` / `PROCESS.md`).
4. `99-devmode.sh` — fallback: if `NxProx` is missing, stop nx and disable the
   watchdog (dev mode), else just `chmod +x` it.

So the trust path into the device is: dongle EEPROM `[TestMode]` → `90-testmode.sh`
runs it → root shell / SSH, persisting because the installed key survives on
`/init`. No bootloader password or secure-boot gate is in the way on this unit.

## 5. The nx application (`NxProx`)

`NxProx` is not a purpose-built validator — it's INIT's **general transit
on-board-computer platform**, configured here as a PROXmobil fare validator for
operator **ABM1**. The binary is stripped, so this is from its `/mnt/nx/src/…`
source-path strings and its config files. The subsystems (by module count):

- **Ticketing / fare engine** — `ticketing/vdvka` (German VDV-KA, the largest),
  `ticketing/prox`, `ticketing/itso`, `ticketing/barcode`, `ticketing/data`,
  `ticketing/control`, `ticketing/driveraccounting`, plus `appl/asn1c` (an ASN.1
  codec for the transit data structures).
- **AVL / telematics** — `avl/*` (INIT `M128`/`M134`/`M152`/`N150`–`N154`
  telegrams, GPS/distance-time triggers, tech logon) and `j1708/*` (the SAE
  **J1708/J1587 vehicle bus**, with Trapeze and Avail ITS integrations). So the
  same app normally runs a bus's AVL/CAD computer; here most of that is dormant.
- **Comms (`base/com`)** — the host side **mirrors the reader's IPP command set**:
  `NxIppFeig`, `NxIppDesfire`, `NxIppFeigEmv`, `NxIppFeigItso`, `NxIppGirogo`,
  `NxIppMifareClassic`, `NxIppUltralightC`, `NxIppUnhandledCardTele`,
  `NxIppPic32Tele` (the PIC32), `NxIppIso7816Tele`, `NxIppCvendLogReceiver`, plus
  `NxIppJsonRpc`. Also `at/` (AT commands), `din66019/` (German transit serial),
  `isi/` (INIT Service Interface), `remoteconfig/` (remote config client/server),
  `slipencoding/`, and `httponboarddata/` (onboard data over HTTP).
- **GUI** — `gui/component`, `gui/control`, `gui/dialog`, driven by `gui.xml` /
  `gui.ini` (drawn to the framebuffer; no touch — see `INTERFACE.md`).
- **Device drivers** — `device/prox` (the cVEND reader), `device/barcodescanner`,
  `device/audio`, and `spic/pic32mx795` — confirming the power/watchdog MCU is a
  **PIC32MX795**.
- **Framework** — `base/{data,sys,control,net,crypto,io,util}`, with
  `base/control/expression/*` an embedded **C-like expression/scripting engine**.

### The operational script (`opscript.nxs`)

`opscript.nxs` is the fare/validation logic, written in nx's scripting language
and run by the expression engine. It defines the result codes (`NXPROX_ERROR_*`:
AUTH_FAILED, TICKET_EXPIRED, NO_TICKET, `CI_ALREADY_DONE` = check-in already done,
VALID_FUTURE…), the `DCC_*` **Device Control Commands** pushed from the back office
(`REBOOT`, `DISABLE_SERVICE`/`ENABLE_SERVICE`, `USE_STANDARD_FARES`/
`USE_SPECIAL_FARES`), buzzer day/night modes, and the Bytemark account-based error
set (`BMTK_ACC_ERR_DESFIRE_SELECT_APPLICATION_FAIL`, `…_CARD_AUTHENTICATION_FAIL`,
`…_CARD_READ_FAIL`). So the tap-decision policy lives in this editable script, not
hard-compiled.

### Config and in-service gating

A large `.ini` set under `/init/efad/pgm/` configures it: `env.ini`
(`[Environment]`: operator `BetriebsKennung=ABM1`, `Waehrung=USD`, sales channel,
payment type, and the commented `FahrzeugNr`/`GeraeteNr`), plus `gui.ini`/`gui.xml`,
`prox.ini`, `pay.ini`, `proto.ini`, `sto.ini`, `nixe.ini`, `NvValues.ini`,
`vendor.ini`, `rc5.tab`/`rc6.tab`, and the operator kernel plugin
`libnxk_ABM1.so`/`nxk_ABM1.dll`. nx refuses to go **in service** until it has a
vehicle address (`Fahrzeugadresse` — see `docs/reversing-nx.md`), which on a
bus comes from the AVL/J1708 side; on our bench unit that, plus the card keys from
`proxy_server`, is what the key-server/in-service work supplies.

End to end: a tap goes reader → `NxIppFeig` → `opscript.nxs` policy → the local
ABT backend (`proxy_server`, §3) → accept/deny → GUI + buzzer, with the result and
any offline transaction recorded.

## 6. Network and management interfaces

What the host exposes, and how it's meant to be managed. With nx stopped only the
system services listen (`:22` SSH, systemd-resolve `:53`/`:5355`, DHCP). With nx
running it opens exactly two more ports:

- **`127.0.0.1:26` — `NxRemoteShellService`** (localhost-only; "Allow NxRemoteShell
  only for localhost"). A login-gated **maintenance shell** (`Login:` / `Password:`
  → `Welcome` / "Attention! Wrong Password!"). It runs nx's internal shell
  (`NxShell`/`NxShellFuncService`) — see the command set below.
- **`0.0.0.0:51001` — ISI** (`NxIsiService`, network-exposed). An XML management/
  data interface for INIT's **COPILOTpc** platform: it answers with
  `<IsiGet><Items>AppName</Items></IsiGet>` and, once the client sends
  `<IsiId><AppName>…</AppName></IsiId>`, serves `<IsiGet>`/`<IsiPut>`/`<IsiExecute>`
  over the on-board data model (items like `AppName`/`AppVersion` =
  `COPILOTpcSrv`, `DeviceId`, `GpsData`, `Position`, `VehicleAddress`, `LineNr`,
  `Status`, `SystemTime`, `Uptime`, `State`, plus a `Device`/`Driver`/`Door`/
  `Line`/`Service` model). Mostly empty on our bench unit (no GPS/vehicle, out of
  service). nx also carries an Avahi/mDNS advertiser (`_ibisip_http._tcp`,
  IBIS-IP), a websocket, SSL sockets, UDP/multicast listeners, and even a **Kafka
  telemetry client** — most dormant here.
- **`:80` — `proxy_server`** (the ABT API, §3), when `init-abtproxy` runs.

### Every way to talk to nx directly

A full map of the control/data surfaces of the running nx, most to least direct:

1. **ISI (`:51001`)** — the primary programmatic interface (`NxIsiService`,
   network-exposed on all interfaces). After the `<IsiId><AppName>…</AppName></IsiId>`
   handshake it is a get/set/**subscribe** data bus over XML: `<IsiGet>` reads
   items, `<IsiPut>` writes them, `<IsiRegister>` subscribes (nx then pushes
   `<IsiPut>` updates on change, via its OnChange/Cyclic tag processors), and
   `<IsiExecute>` runs commands. Items are the COPILOT transit data model —
   `AppName` (=`COPILOTpcSrv`), `State`, `RouteId`, and the config-mapped
   `IsiRouteVariation`/`IsiBlockNo`/`IsiCurrentDirectionNo`/`IsiStopNumbers` (wired
   to nx's internal `Tick*` state by `nixe.ini` `NxSharedMapper` lines). Reads and
   Register/subscribe work for **any** client AppName (confirmed live). **Writing**
   (`<IsiPut>`, well-formed: `<IsiPut><IsiBlockNo>7</IsiBlockNo></IsiPut>`) and
   **commands** (`<IsiExecute><op>operation args</op></IsiExecute>`, which call
   nx's `NxOpCmd*` operations — `TicketAccess`, `TariffAccess`, `TableAccess`,
   `OperationDay`, `ShiftSum*`, `ProvideCardNumber`…) are **gated per client**:
   each item has a designated publisher and the server owns the route/block/state
   items, so an unauthorized AppName (ours) gets read + subscribe only — our
   `IsiPut`s to nx-owned items were silently ignored across several AppNames. So
   ISI gives full visibility into nx's live state to anyone, and write/control to
   the configured on-board apps.
2. **IMS file queues** — nx ingests CRC32-checked provisioning archives dropped
   into `/init/ims/toveh/PROXmobil_72` (`NxImsFileScanService` /
   `NxDataProvisionService`, per data domain) and uploads results to `ims/frveh`.
   A file-based config/data channel: write a valid archive and nx picks it up.
3. **`:26` maintenance shell** — login-gated (FVSCrypt, not accessible); but as
   root the same nx shell functions are reachable through `NxExe` (below).
4. **systemd / signals** — `systemctl start`/`stop nx`, plus nx's Start/Stop/Kill
   listeners.
5. **Config + restart** — edit the `/init/efad/pgm/*.{ini,tab,xml}` set as root and
   restart nx (the behaviour is config-driven; `rc5.tab` is its service table).
6. **Peripheral IPP** — the reader/PIC32 serial links nx mediates (what `pm3.py`
   drives directly while nx is stopped).

Compiled in but **not instantiated** in this config (per `rc5.tab`): JSON-RPC
(`NxIppJsonRpc`), several HTTP servers (`NxDebugHttpControllerService` — a debug
web UI on `127.0.0.1:8080` with a "Demo Mode"; `NxOnboardDataOverHttpServerService`;
`NxHttpServerSimpleService`; IBIS-IP HTTP server), the remote-config server, the
AT-command and DIN 66019 serial protocols, and the websocket. Enabling one takes
**two halves**: adding its `*Service` class to `rc5.tab` (which *does* instantiate
it — nx logs `Missing service … ignored` only for truly-absent classes, not these),
**and** its port/enable config, which comes from numbered operator parameters
(`param:NNNNN`) in the proprietary `.p72` parameter dataset. On this unit those
params aren't set for the HTTP/RPC services, so adding the class name alone opens
no port — verified by enabling the three HTTP services above and watching them load
but never listen. Bringing one up would mean setting its params in the `.p72`
dataset (a proprietary INIT format) or a param override. nx also drives the buzzer
on state transitions (a tone when it goes out of service), so ISI/state changes can
make sound.

### The nx shell / `NxExe` command set

The `:26` shell and the `NxExe` CLI expose the same "NX Toolbox" functions. We
reach them as **root** without the maintenance login. Notable commands:
`extshell <cmd> <timeout>` (run an arbitrary external shell command), `config`,
`network`, `neighbors`, `state` (state-machine dump), `reboot`/`rebootAll`
(controller + all PROXmobil), `uploadStatus` (firmware-update status),
`eepromdump`, `watchdog <n>`, `memoryUsage`, `led`/`ledseq`/`ledtest`,
`getsystime`/`geti2ctime`/`seti2ctime`, `list` (archives), `exprfile` (run the
expression engine on a file); an `emvPay` sub-shell (`init`/`commit`/`cancel`/
`validate`, gate `profiles`/`setProfile`); VDV-KA `getid`/`setid`, `resetSession`;
and firmware flashers `loadpic` (flashes the PIC32 from `sc.hex`), `loadfpga`,
`loadbios`, `loaddsp` and `loadpic{display,ioticket,mona,radiobox,touchfare,
umtsgps}` (for other INIT hardware variants, not all present on a PM3).

### The maintenance password (can we recover it?)

Short answer: **there is nothing on this unit to recover.** The `:26` login is
checked by `NxFVSCryptPasswordValidator` — an FVS-crypt hash of a **service-level**
password (`NxOpCmdMaintenanceLogin`, "Password for a service level", `MAINTENANCELVL`)
tied to an INIT **factory/master key** (`NxMasterKey`/`NxFactoryKey`, "default
factory key"). No maintenance/service-level credential or hash is stored in the
config, EEPROM, or any `.dat` on this surplus unit — the validator compares against
a value provisioned at the operator/factory, not present here. So it isn't a hash
to crack locally; there's simply no local secret. And it isn't needed: we already
have **root SSH**, and the shell's powers (`extshell`, the `load*` flashers,
`config`/`network`/`led`/`eeprom`/`watchdog`) are either ours directly via `NxExe`
as root or need assets we lack (e.g. `sc.hex`). (A DESFire maintenance-card path,
`NxProxFileConfigDesfireMaintenance`, also exists but likewise needs operator keys.)

## 7. Fare media, barcodes, the GUI, and the rootfs

### Fare-media types and the validation flow

The device validates several media, all funneled into the same UVAPI/denylist
decision (§3):

- **Contactless cards** — UID/token read by the reader (DESFire etc.), decrypted
  with the synced keys (`ProxyDecryption`/`ProxyKeysMapper`, which also runs
  `MapUvapiKeysToInit`).
- **Barcodes (three kinds)** — `proxy_server` extracts a media ID per type:
  `GetMediaIDFromTVMBarcode` (ticket-vending-machine tickets),
  `GetMediaIDFromMobileTicketingBarcode` (phone tickets), and
  `GetMediaIDFromAccountBasedFareMediaBarcode`. On the nx side these are **Aztec
  2D** symbols (the VDV/UIC e-ticket style — `aztec` encoder with ASN.1 "sysfields",
  `barcodeValidityPeriod`/`beginOfBarcodeValidity`) read through the `ttyUSB0`
  barcode scanner.

Each tap/scan becomes an "init request" that `ProxyClient::MapInitRequestToUvapiRequest`
turns into a **UVAPI** request (JSON, jsoncpp), sent to `validate_now` with an
OAuth2 bearer; `ParseUvapiResponse`/`ProcessUvapiResponse` yield the decision.
Offline, the `flash_deny_list` (populated `FromUVAPI` or `FromFile`) plus
`Passback` (anti-passback) decide locally, and the tap is queued (§3). So the
back-office contract is media-agnostic: card or barcode, it resolves to a media ID
and a UVAPI validation.

### VDV-KA (German e-ticket) data model

nx's `ticketing/vdvka` is a full VDV-KA / (((eTicket implementation, ASN.1/OID
based (`_oidArrayToRaw`/`_oidArrayToText`, the `appl/asn1c` codec). It keeps a
**key registry** and an **application logbook** (`NxVdvkaNm::_keyRegAddKeys`/
`_keyRegAddRef`/`_keyRegClear`/`_keyRegRemove`, `_logbookClear`), and a VDV-KA
**Terminal ID** set with `setid <type> <number> <orgId>`. Entitlements (EFS) live
on DESFire and are MAC'd through the SAM (the reader's `ProxCardVdvKa`/SAM side,
`docs/feig-firmware.md`). Dormant on our US/CapMetro unit but fully present.

### GUI (`gui.xml`)

The screen is a declarative XML UI: **~41 `<page>` elements**, each a tree of
positioned `<label>`/`<text>`/`<components>` with `<font>`/`<foreground>`/
`<pos>`/`<size>`/`<alignment>`, `%GUI_…%` localization keys (e.g.
`%GUI_OutOfService%`), and `<link>`/`<ref>` for navigation between pages. It's
rendered straight to `/dev/fb0` (800×480, no touch — `INTERFACE.md`); input is
NFC taps, barcode scans, and the power button.

### Rootfs (`/`, read-only ext4 on `sda1`)

**PTXdist 2019.03.1** (`/etc/os-release` `ID=ptxdist`). A conventional embedded
userland: BusyBox, systemd, `ssh`/`sshd`/`ssh-keygen` (our access), `curl`
(abtproxy's HTTP), ALSA (`alsactl`/`alsamixer`), **GStreamer** (`gst-*`, the audio
pipeline), **avahi-daemon** (the mDNS/IBIS-IP advertiser, §6), `i2c-tools`
(`i2cdetect`/`i2cget`/…), and `gdbserver` (on-device remote debugging is possible).
No stripped-out surprises — the custom parts are all under `/init` (`efad`=nx,
`abtproxy`), not the base rootfs.

## 8. The `.p72` parameter dataset format

nx's per-operator configuration — fare parameters, ISI setup, texts, sounds —
ships as a **`.p72` dataset**: a standard **ZIP** of INIT "KArch" text config files,
provisioned through the IMS queues (§3; `ims/toveh/PROXmobil_72`, per data domain)
and loaded by `NxDataProvisionService`/`NxParamService`. On this unit, e.g.
`F20240607_V0045.p72` under `/init/efad/data/archive/`.

**Container:** a normal ZIP (deflate). Integrity is the ZIP's own **per-file
CRC32** (what `nixe.ini`'s `CK-crc32` checks) — there is **no signature**, so a
dataset can be authored or edited with ordinary zip tools.

**Each `.dat` is structured ASCII** (CRLF): a `[Section]` header, an optional
`#!rows=N`, a typed column schema (`NAME:S` string / `NAME:N` number), then
tab-separated rows. Files and roles:

| File | Role |
|---|---|
| `arcinfo.dat` | manifest — `DevClass 72` (the PM3), `DataDomain`, `ValidFrom`, `BaseVersion`/`UpdateVersion`, `CreationTime` |
| `NxParam.dat` | the parameter table — `FZG:N MPN:N PARAM:N WERT:S` (vehicle / mpn / **param number** / value; `-1 -1` = global). The `param:NNNNN` store |
| `ISIITEMS.dat` | the ISI item definitions — `ITEM FLAG SHAREDNAME …`, each mapped to an internal shared variable. The full `IsiGet`/`IsiRegister` vocabulary |
| `ISIAPP.dat` | the ISI permission table — `APPNAME COMMAND …`: the authorized client AppNames (`BYTEMARK`, `COPILOTpcSrv`) and the exact ISI requests each may issue |
| `httpprofile.dat` | outbound HTTP client profiles (e.g. `BmtkAbtProxy` → `127.0.0.1`, timeouts, headers) |
| `TFKEYS.DAT` | TF (key-sequence) function codes — `TFNR→TFKEY` (e.g. `10103→tfShowSoftwareVersion`); the service-function map, not passwords |
| `text.dat` | localization strings (the `%GUI_…%` texts, fare labels) |
| `ProxOk/Warn/Failure.wav` | the tap-result audio prompts |
| `ImsConf.dat`, `logconf.dat`, `VK.DAT` | IMS, logging, and VDV-KA config |

This ties the interface findings (§6) together and makes them actionable:

- **ISI items (#1)** are exactly `ISIITEMS.dat`.
- **ISI write/command gating (#2)** is `ISIAPP.dat`: only the listed AppNames
  (`BYTEMARK`/`COPILOTpcSrv`) may write/execute, each with a command whitelist.
  (`BYTEMARK` subscribes `FareClasses`/passback items — the ABT backend and nx
  exchange fare/passback state over ISI.)
- **Enabling a dormant interface (#3)** is an `NxParam.dat` edit: add the service's
  port/enable `PARAM` row (the param number is defined in the nx binary) and
  re-provision.

Because the dataset is text and unsigned, a custom `.p72` can reconfigure nx
wholesale — add an AppName to `ISIAPP.dat` for ISI write access, set a service
param in `NxParam.dat`, change parameters — then drop it in `ims/toveh` for
`NxDataProvisionService` to pick up (CRC32 is the only gate). The operator's
specific parameter values are their config and are not reproduced here.

## 9. Cross-references

- Hardware, peripherals (PIC32, barcode, audio, framebuffer, networking, the
  dongle EEPROM): `INTERFACE.md`.
- The FEIG cVEND reader's own firmware: `docs/feig-firmware.md`.
- nx reverse-engineering techniques and the reader frame formats:
  `docs/reversing-nx.md`.
