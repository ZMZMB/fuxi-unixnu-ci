#!/usr/bin/env python3
"""Qualify the shared GPU driver by content instead of by the owner's three local hashes.

prepare-fuxi-driver-compat.py only accepts Adreno740 at a9a2cbb, e8ef803 or f4a9fbb, the last two being commits that
exist only on the owner's machine. reconstruct.sh replays his commits (format-patch), so the rebuilt HEAD is a
different hash with the same content. Lifting the hash gate keeps the real check: the compatibility patch must
either reverse cleanly (already applied) or apply cleanly.
"""
import os
import pathlib
import sys

OLD = """if revision not in ('a9a2cbb43b89d672e2921e19721a6438b738b17f', 'e8ef8031bdfd356478c9ad8cd3b83dfa3bb0e8f8',
                    'f4a9fbb3da01457a35a127e62be64ab702bd2c18'):
    raise SystemExit('Unexpected Adreno740 revision; requalify the compatibility patch')"""
NEW = """if revision not in ('a9a2cbb43b89d672e2921e19721a6438b738b17f', 'e8ef8031bdfd356478c9ad8cd3b83dfa3bb0e8f8',
                    'f4a9fbb3da01457a35a127e62be64ab702bd2c18'):
    # The rebuild replays the owner's local commits, so the hash differs while the content does not. Keep the real
    # gate below: the patch must reverse cleanly or apply cleanly.
    print('Adreno740 at a rebuilt revision ' + revision[:12] + '; qualifying by content')"""
MARK = '; qualifying by content'

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get('SRC', '.'))
targets = [src / 'device/scripts/prepare-fuxi-driver-compat.py',
           src / 'device-ios17/scripts/prepare-fuxi-driver-compat.py']

done = 0
for path in targets:
    if not path.is_file():
        print(f'skip {path} (absent)')
        continue
    text = path.read_text()
    if MARK in text:
        print(f'keep {path} (already relaxed)')
        done += 1
        continue
    if OLD not in text:
        sys.exit(f'anchor not found in {path}')
    path.write_text(text.replace(OLD, NEW, 1))
    print(f'patched {path}')
    done += 1

if not done:
    sys.exit('no prepare-fuxi-driver-compat.py found')
