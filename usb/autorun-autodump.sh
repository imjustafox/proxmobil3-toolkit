#!/bin/sh
# PROXmobil3 boot script: standalone access + a one-time auto-dump to this USB.
# Does everything autorun.sh does (root SSH on, PIC32 watchdog off, nx left
# stopped, .pm3-nodump marker) and then, on the first boot only, dd|gzips the
# unit's internal disks to pm3-dump/ on the stick with sha256sums. Later boots
# skip the dump once pm3-dump/device.sha256 exists.
# Install it with: make_dongle.py --autodump
HERE=$(cd "$(dirname "$0")" && pwd)
LOG="$HERE/pm3-autorun.log"
exec >"$LOG" 2>&1
set -x
date

# disable PIC32 watchdog (no nx to feed it)
stty -F /dev/ttymxc2 115200 cs8 -cstopb -parenb raw -echo 2>/dev/null
printf '\274\001\000\004\000\004H@\003\000\000' > /dev/ttymxc2

# enable root SSH (persists)
mount -o remount,rw /
[ -f /etc/ssh/sshd_config.stock ] || cp /etc/ssh/sshd_config /etc/ssh/sshd_config.stock
{
  echo "Port 22"; echo "PermitRootLogin yes"; echo "PubkeyAuthentication yes"
  echo "AuthorizedKeysFile .ssh/authorized_keys"; echo "Subsystem sftp internal-sftp"
} > /etc/ssh/sshd_config
mkdir -p /root/.ssh
cat "$HERE/authorized_keys" > /root/.ssh/authorized_keys
chmod 0700 /root/.ssh; chmod 0600 /root/.ssh/authorized_keys
systemctl enable sshd.socket
systemctl restart sshd.socket
mount -o remount,ro /

# never capture the dongle itself
touch "$HERE/.pm3-nodump" 2>/dev/null

# one-time auto-dump of the unit's internal disks onto the stick
DUMP="$HERE/pm3-dump"
if [ -f "$DUMP/device.sha256" ]; then
  echo "pm3-dump/device.sha256 exists -- skipping auto-dump (already captured)"
else
  mkdir -p "$DUMP"
  strings /sys/bus/i2c/devices/2-0050/eeprom 2>/dev/null | head -1 > "$DUMP/serial.txt"
  { uname -a; echo; cat /proc/partitions; } > "$DUMP/meta.txt"
  STICK=$(mount | grep "$HERE" | head -1 | cut -d' ' -f1)   # e.g. /dev/sdc1 (do not dump this)
  : > "$DUMP/device.sha256"
  for dev in mtdblock0 sda sdb sdc sdd sde; do
    [ -b "/dev/$dev" ] || continue
    case "$STICK" in *"$dev"*) echo "skip /dev/$dev (this stick)"; continue;; esac
    echo "dumping /dev/$dev -> pm3-dump/$dev.img.gz"
    dd if="/dev/$dev" bs=1M 2>/dev/null | gzip -1 > "$DUMP/$dev.img.gz"
    sha=$(gzip -dc "$DUMP/$dev.img.gz" | sha256sum | cut -d' ' -f1)
    echo "$sha  $dev.img.gz (sha256 of decompressed image)" >> "$DUMP/device.sha256"
  done
  sync
  echo "auto-dump complete -> $DUMP"
fi

date
echo "ssh enabled, watchdog off, nx left stopped; auto-dump -> pm3-dump/ on the stick"
