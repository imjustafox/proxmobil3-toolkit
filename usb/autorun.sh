#!/bin/sh
# PROXmobil3 boot script: SAFE baseline for standalone card-reading tests.
# Enables root SSH, disables the PIC32 watchdog (so the unit stays up with no
# nx), and does NOT start nx — leaving the reader's fresh-boot auto-scan free for
# our own tool to read, with no nx and no loud validator beep.
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

date
echo "ssh enabled, watchdog off, nx NOT started (reader auto-scan free for our tool)"
