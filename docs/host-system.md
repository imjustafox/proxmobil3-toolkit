# The PM3 host system (i.MX6) — software deep dive

The PROXmobil3 is really **two computers**: the FEIG cVEND reader (its own ARM +
Buildroot, documented in `docs/feig-firmware.md`), and the **host** — an NXP
i.MX6 Solo running INIT's PTXdist Linux, which drives the screen, talks to the
reader and the PIC32 over serial, and runs the transit application. This document
covers the host software top to bottom. The hardware/peripherals are in
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
  - `mtdblock0` — 16 MB SPI flash (U-Boot + environment).
  - Imaged copies: `dumps/sda.img`, `dumps/sdb.img`, `dumps/mtdblock0.img`
    (git-ignored), extracted under `dumps/extracted/`.
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

## 5. Cross-references

- Hardware, peripherals (PIC32, barcode, audio, framebuffer, networking, the
  dongle EEPROM): `INTERFACE.md`.
- The FEIG cVEND reader's own firmware: `docs/feig-firmware.md`.
- nx reverse-engineering techniques and the reader frame formats:
  `docs/reversing-nx.md`.
