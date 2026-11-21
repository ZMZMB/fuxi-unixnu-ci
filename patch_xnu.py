#!/usr/bin/env python3
"""Make fuxi-kernel-baseline.sh apply the arm64e patch set hunk by hunk.

A whole-file `git apply` refuses a patch as soon as one hunk is stale, and the owner's set already has such
hunks (zz-msg-probe.patch inserts an include that xnu-10063 ships), which stops every later hunk from landing.
Both apply loops (the plain one and the arm64e one) are pointed at apply-xnu-patch.py, which applies each hunk
on its own and treats a hunk whose added lines are already present as applied.
"""
import os
import pathlib
import re
import sys

LOOP = re.compile(
    r'(?P<i> *)if ! git -C \.cache/xnu-work apply --reverse --check "\$PATCH" >/dev/null 2>&1; then\n'
    r'\1  git -C \.cache/xnu-work apply --check "\$PATCH"\n'
    r'\1  git -C \.cache/xnu-work apply "\$PATCH"\n'
    r'\1fi\n')
NEW = '{indent}python3 "${{XNU_PATCH_HELPER:-$ROOT/scripts/apply-xnu-patch.py}}" "$PATCH" "$ROOT/.cache/xnu-work"\n'
MARK = 'apply-xnu-patch.py'

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get('SRC', '.'))
targets = [src / 'device-ios17/scripts/fuxi-kernel-baseline.sh',
           src / 'device/ios17/overlay/scripts/fuxi-kernel-baseline.sh']

done = 0
for path in targets:
    if not path.is_file():
        print(f'skip {path} (absent)')
        continue
    text = path.read_text()
    if MARK in text:
        print(f'keep {path} (already hunk-wise)')
        done += 1
        continue
    count = len(LOOP.findall(text))
    if not count:
        sys.exit(f'apply loop not found in {path}')
    text = LOOP.sub(lambda m: NEW.format(indent=m.group('i')), text)
    path.write_text(text)
    print(f'patched {path} ({count} apply loop(s))')
    done += 1

if not done:
    sys.exit('no fuxi-kernel-baseline.sh found')
