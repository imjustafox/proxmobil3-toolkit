#!/usr/bin/env python3
"""PROXmobil3 tap-to-UID demo.

Arms the cVEND reader (reverse-engineered sequence), then on every card tap:
  - draws the card UID large on the device framebuffer (/dev/fb0)
  - chirps the cVEND piezo buzzer (IPP 0x22) as feedback

Runs on your Mac; drives the device over SSH. Needs the reader already
powered and responsive (nx not required). Pillow is used to render text.

    ./tap_demo.py            # uses PM3_HOST or 10.0.1.102
    PM3_HOST=x.x.x.x ./tap_demo.py
"""
import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pm3
from PIL import Image, ImageDraw, ImageFont

HOST = os.environ.get("PM3_HOST", pm3.HOST)
pm3.HOST = HOST
W, H = 800, 480


def _font(sz):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/SFNS.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            pass
    return ImageFont.load_default()


def render(uid: str, count: int) -> bytes:
    """800x480 screen: gradient + big UID. Returns BGRX bytes for /dev/fb0."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):            # vertical gradient, one line per row (fast)
        d.line([(0, y), (W, y)], fill=(10 + 30 * y // H, 40 + 20 * y // H, 90 - 40 * y // H))
    d.text((40, 40), "PROXmobil3  ·  tap reader", font=_font(34), fill=(150, 200, 255))
    d.text((40, 150), "CARD UID", font=_font(40), fill=(120, 255, 170))
    d.text((40, 210), uid, font=_font(76), fill=(255, 255, 255))
    d.text((40, 400), f"tap #{count}", font=_font(30), fill=(190, 190, 210))
    rgb = img.tobytes()
    out = bytearray(W * H * 4)
    out[0::4] = rgb[2::3]   # B
    out[1::4] = rgb[1::3]   # G
    out[2::4] = rgb[0::3]   # R
    return bytes(out)


def draw_fb(buf: bytes):
    p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", f"root@{HOST}", "cat > /dev/fb0"],
                         stdin=subprocess.PIPE)
    p.communicate(buf)


def main():
    print(f"connecting to {HOST} ...")
    s = pm3.SshSerial(pm3.CVEND_TTY)
    # Do NOT re-init the reader -- that disrupts its autonomous post-boot scan.
    # Just listen, and send a 0x04 status every ~1s so it never goes idle. It
    # streams 0xBE frames (UID) for every tap, indefinitely. No nx, no keys.
    draw_fb(render("—  tap a card  —", 0))
    print("listening (1s keepalive, no re-init). tap a card (Ctrl-C to quit).")

    count = 0
    last_uid = None
    last_t = 0.0
    last_status = 0.0
    try:
        while True:
            if time.time() - last_status > 1.0:
                s.send(0x04)             # steady keepalive keeps scanning alive
                last_status = time.time()
            f = s.recv(0.4)
            if not f or f["type"] in (0x05, 0x07, 0xED, 0xD1):
                continue
            uid = pm3._find_uid(f["data"])
            if not uid:
                continue
            # debounce: same card within 2s is one tap
            if uid == last_uid and time.time() - last_t < 2.0:
                continue
            count += 1
            last_uid, last_t = uid, time.time()
            print(f"tap #{count}: {uid}  (frame {f['type']:02x})")
            s.send(0x22, struct.pack(">HH", 1800, 35))  # tiny 35ms chirp (quiet; not nx's loud tone)
            draw_fb(render(uid, count))
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        s.close()


if __name__ == "__main__":
    main()
