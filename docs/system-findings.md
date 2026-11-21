# System findings: provenance, latent hardware, posture

Things learned from the storage and SPI-flash images (`dumps/`, extracted under
`dumps/extracted/`) and from the live system, beyond the per-subsystem docs.

## Build provenance

The device runs INIT's own `INIT-004` board support package:

- U-Boot `2018.03-INIT-004` (built Mar 1 2019) and kernel
  `4.9.166-fsl-imx-INIT-004` (Feb 28 2019), both INIT forks of the Freescale/NXP
  i.MX6 vendor trees.
- Built with OSELAS.Toolchain-2018.12.0 (gcc 8.2.1,
  `arm-v7a-linux-gnueabihf`) on PTXdist 2019.03.1, the Pengutronix embedded-Linux
  build system.
- The module is a TQ-Systems TQMa6S (i.MX6 Solo) on INIT's PM3 carrier board.
  U-Boot is built multi-board for the whole TQMa6 family (S/DL/D/Q).
- Embedded source-tree paths identify the two application codebases: INIT's nx /
  `proxcontroller-feig2` tree (the reader app and nx), and a Bytemark tree (the ABT
  `proxy_server`).

## Latent onboard wireless (not fitted here)

The device tree carries a `wlcore@2 { compatible = "ti,wl1837"; }` node for a TI
WiLink WL1837 WiFi and Bluetooth combo on SDIO. The rootfs ships the full stack:
`wlcore`/`wlcore_sdio`/`wl18xx` kernel modules, the `wl18xx`/`wl127x` firmware,
and Bluetooth `TIInit_*.bts` init blobs.

On this unit the module is not populated or active. There is no `wlan` interface,
no SDIO device enumerates, and the drivers are not loaded. Only `eth0` and `lo`
exist, with the two SD cards on the usdhc controllers. The PM3 platform is designed
to optionally carry onboard WiFi/BT, which is useful to know for a variant that has
it and a candidate to add on a board that routes the SDIO lines.

## Kernel and platform capabilities

- Filesystems compiled or available: ext4 (root), vfat/`fat` (dongle/SD), plus
  modules for `btrfs`, `cifs`, `nfs`/`nfsv3`/`nfsv4`, `ntfs`, and `squashfs`.
  That is more than the device itself uses; it NFS-boots in the dev/bench U-Boot
  path.
- Peripherals via modules: `ftdi_sio` (the Honeywell/Code barcode scanner on
  `ttyUSB0`), `lcd`, and `cmac`/`crc8` crypto helpers.
- Hardware crypto: the i.MX6 CAAM engine (Era 4) with RNG4 is active in
  `/proc/crypto`, available to the host independently of the reader's HSM.
- The application layer is INIT's COPILOTpc / nx transit on-board-computer
  platform: IMS vehicle messaging (`/init/ims` and `/init/transfer`, each with
  `frveh`/`toveh` from/to-vehicle queues), the ISI management interface
  (`:51001`, see `docs/host-system.md`), mDNS/IBIS-IP advertising, and a Kafka
  telemetry client. Most of it is dormant on a bench unit with no vehicle bus.

## Boot and access posture

- Read-only rootfs (`sda1` mounted `ro`), writable app partition (`/init`).
- No verified or secure-boot gate was observed. U-Boot loads the kernel and DTB
  from SD or SPI with no signature check in the path, and there is no `dm-verity`
  on the rootfs. Modified code boots unimpeded, which is how the `[TestMode]`
  access path works at all. That is fine for a fleet device behind physical
  control, but worth knowing if you repurpose one.
- Access path: the `/init/autorun/90-testmode.sh` script executes a shell script
  embedded in the maintenance dongle's EEPROM (`[TestMode]` block) with nx stopped
  and the watchdog disabled. It is the supported maintenance hook, and it is how
  root/SSH is installed here (`README.md`, `docs/host-system.md`).
- Remaining gates on the running system: the login-prompted maintenance shell on
  `127.0.0.1:26` (FVSCrypt service-level password, see `docs/host-system.md`) and
  SSH key auth. The i.MX6 fuses and HAB state were not read out. The boot-chain
  observations above come from behavior, not a fuse dump.

## Still out of reach (hardware-gated)

The PIC32MX795 power/watchdog controller's own firmware is not accessible over its
serial protocol. There is no memory-read command and no image on the host. A
JTAG/ICSP dump of that MCU is the open item. SAM/ISAM-gated and EMV-config-gated
reader features are understood but cannot be exercised without that hardware or
provisioning; see `docs/feig-firmware.md`.
