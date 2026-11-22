#!/usr/bin/env python3
"""Shrink the payload FAT volume so the boot image fits what fuxi's ABL will load.

fuxi (Xiaomi 13) measurements from the iOS16 bring-up notes:

  * 176 / 192 / 118 MiB ramdisk  -> "Failed to Find an Operating System!" (both `fastboot boot` and boot_b)
  * 100.7 MB image               -> "Failed to load/authenticate boot image: Load Error"
  *  95,375,360 B image, ramdisk=1 -> UEFI menu came up
  *  90.96 MB image              -> UEFI menu came up

The 21H16 payload's real content is 84,560,548 B (kernel.macho 67,895,296 + kernel.macho.gpuaddon
15,721,096 + kernel.macho.adt 14,236 + scratch-data.img 929,920 + unixnu.toml), so an 84 MiB volume keeps
3.3 MiB of slack and puts the boot image at 89,892,727 B - inside the window the bootloader has accepted.

Usage: patch-payload-size.py <src-root> [--size 84]
"""

import argparse
import pathlib
import re
import sys

OLD = 176


def patch(path, size):
    text = path.read_text()
    # Only the fuxi iOS 17 board (volume = "FUXIESP") is retargeted; other boards keep their sizes.
    if 'FUXIESP' not in text:
        return 0
    new_text, n = re.subn(r'(?m)^([ \t]*size_mib[ \t]*=[ \t]*)\d+[ \t]*$',
                          lambda m: '%s%d' % (m.group(1), size), text)
    if not n:
        return 0
    if text != new_text:
        path.write_text(new_text)
    return n


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--size', type=int, default=84)
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)
    if not root.is_dir():
        raise SystemExit('not a directory: %s' % root)
    total = 0
    for board in sorted(root.rglob('board.toml')):
        n = patch(board, args.size)
        if n:
            total += n
            for line in board.read_text().splitlines():
                if 'size_mib' in line:
                    print('%s: %s' % (board, line.strip()))
    if not total:
        raise SystemExit('no board.toml with size_mib found under %s' % root)
    print('patched %d size_mib value(s) to %d' % (total, args.size))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
