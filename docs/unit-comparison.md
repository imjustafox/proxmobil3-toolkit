# Comparing the three unit captures

The repo has full images for three PROXmobil3 units:

- `unit154`: module serial 72968085
- `unit98`: module serial 73437401
- `unit73914987`: module serial 73914987, the current live unit

`unit154` and `unit98` are full captures with hardware scans and reader firmware.
`unit73914987` came from the access dongle's one-time auto-dump, so it has the
storage images but no `hwscan.txt` or `reader-live/` pull.

This compares the decompressed `sda` (rootfs), `sdb` (`/init`), and SPI-flash
images. File contents were hashed and compared. Backend credentials, card keys,
ticket rows, denylist entries, and queued transaction contents are not reproduced
here.

## Hardware and capture coverage

All three units identify as `TQ TQMa6S on PM3`, with the device-tree compatible
string `fsl,imx6dl`, 512 MB RAM, and one CPU online. The module serial and Ethernet
MAC are the per-unit differences.

| | unit154 | unit98 | unit73914987 |
|---|---|---|---|
| Module serial | 72968085 | 73437401 | 73914987 |
| Capture | full dump | full dump | dongle auto-dump |
| Hardware scan | yes | yes | no |
| Reader firmware | yes, from `V0200.C72` | yes, from `V0200.C72` | image only |
| Reader live pull | no | yes | no |

The missing reader live pull is a capture difference, not a device difference.

## The base system is the same

The SPI-flash images are byte-identical. All three decompress to the same 16 MB
image, starting with `efa1467f...`. U-Boot and its environment do not vary between
these units.

The rootfs is also effectively identical. Of 3,980 regular files in `sda`, only
eight differ across the three units:

- the systemd journal
- `etc/machine-id`
- `etc/shadow` and `etc/shadow-`
- the ECDSA and Ed25519 SSH host keys, private and public

Everything else matches byte for byte. That covers the kernel, modules, userland,
packages, init scripts, and configuration. These are the same OS build, not three
different variants.

The application layer is the same as well. All three have `efad/pgm/arcinfo.dat`
at `V2325.X72`, and the application binaries and config files under `efad/pgm/`
match. Only `NvValues.ini` differs, and that file holds runtime counters and
timestamps.

The cVEND reader package is also the same. `V0200.C72` has the same hash on all
three units, and the reader reports application version 02.35 and model string
`cS01.05.45-49.00-2-2`.

## Install history

The current application version is the same, but the retained installer archives
show different update paths.

`unit154` has:

```
V0100.S72 V0128.S72 V2027.X72 V2028.S72 V2029.S72 V2034.S72
V2035.S72 V2037.S72 V2142.X72 V2143.X72 V2323.X72 V2325.X72
```

`unit98` has:

```
V0101.S72 V0128.S72 V2028.S72 V2029.S72 V2037.S72 V2142.S72
V2143.S72 V2323.X72 V2325.X72
```

`unit73914987` has:

```
V0100.S72 V0128.S72 V2028.S72 V2029.S72 V2034.S72 V2035.S72
V2037.S72 V2142.S72 V2143.S72 V2323.S72 V2325.S72
```

Two differences stand out. `unit154` has the early `V2027.X72` full application
install. `unit98` has `V0101.S72` instead of `V0100.S72`, and it skipped the
intermediate `V2034`/`V2035` releases. `V0101` adds `eth0.network` with
`DHCP=ipv4`; `V0100` only installs `arcinfo.dat` and `_install.sh`.

All three finish on `V2325.X72`, so these archive sets are history, not a current
code difference.

## Provisioning data

The provisioning dataset does differ.

| | unit154 | unit98 | unit73914987 |
|---|---|---|---|
| Base dataset | F20220817_V0400 | F20220817_V0400 | F20220824_V0400 |
| Update | U0289 | U0297 | U0039 |
| Base ticket rows | 233,781 | 233,781 | 234,352 |
| Update ticket rows | 8,898 | 8,907 | 4,291 |

`unit154` and `unit98` share the same `F20220817` base. `unit73914987` uses a newer
`F20220824` base with 571 more base ticket rows, but its update batch is much
smaller, 4,291 rows versus roughly 8,900.

The other dataset files are not meaningfully different. `BYTEMARKKEYS`,
`BYTEMARKLABELS`, and the proximity key/label files are identical once the
`#!version=` header line is ignored. The ticket table is the part that changed.

## Runtime state

The `/init` partition also carries operational history. The core application and
config match, but the accumulated state does not.

| | unit154 | unit98 | unit73914987 |
|---|---|---|---|
| Denylist entries | 5,258 | 5,239 | 6,691 |
| Offline transaction rows | 0 | 0 | 161 |
| Outbound IMS files | none | none | 6 files |
| Timestamped abtproxy logs | 38 | 18 | 72 |
| Log date range | 2024-07-12 to 2024-12-13 | 2024-07-30 to 2024-12-13 | 2024-07-21 to 2026-11-19 |
| Ring-buffer account files | 1,210 | 229 | 1,146 |

`unit73914987` is the only one with queued offline transactions. Its
`abtproxy/proxyDB.db` has 161 rows in `OfflineTransactions`; the other two have
zero. It also has six queued outbound IMS files in `ims/frveh` (three `.L72` and
three `.hdr`), while the other units have none.

Its denylist is larger, its log history runs through the capture date, and it has
more runtime files under `efad/var`. The other two stop logging in December 2024,
which fits units that were retired and sat in surplus.

## Deployment tweak on unit98

`unit98` has one extra autorun script that the other two do not:

```sh
#!/bin/sh

sleep 1
ethtool -s eth0 autoneg off
sleep 1
ethtool -s eth0 speed 100
```

It forces the link to 100 Mbit with autonegotiation off. That suggests a
site-specific link problem or switch that would not negotiate cleanly. It is not
part of the stock image.

`unit154` and `unit73914987` use the stock autorun scripts, and their retained
installer sets start at `V0100`. `unit98` starts at `V0101`, which adds the
`eth0.network` DHCP configuration, and then runs this link-speed script.

## What the comparison says

- These are three copies of the same OS and application build, with the same
  bootloader and reader firmware. The differences are provisioning data, runtime
  history, and one network workaround.
- `unit73914987` is not just a later update of the other two. It is on a different
  provisioning base (`F20220824`) with a different ticket table.
- `unit73914987` has real queued state that should not be published: 161 offline
  transaction rows and outbound IMS files.
- `unit98` carries a 100 Mbit autonegotiation workaround that is absent from the
  other captures.

The comparison is based on file content hashes. The filesystems were extracted
with `7z`, so this is not a forensic comparison of inode timestamps, extended
attributes, or slack space.
