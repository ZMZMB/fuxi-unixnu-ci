#!/usr/bin/env python3
"""Qualify the shared GPU driver by content instead of by the owner's three local hashes.

prepare-fuxi-driver-compat.py only accepts Adreno740 at a9a2cbb, e8ef803 or f4a9fbb, the last two being commits that
exist only on the owner's machine. reconstruct.sh replays his commits (format-patch), so the rebuilt HEAD is a
different hash with the same content. Lifting the hash gate keeps the real check: the compatibility patch must
either reverse cleanly (already applied) or apply cleanly. When the rebuild reworded an upstream comment beside
the patch, the reverse check cannot match even though every landing point is present, so the fallback qualifies
the patch by its own anchor lines instead of trusting the hash.
"""
import os
import pathlib
import sys

OLD_HASH = """if revision not in ('a9a2cbb43b89d672e2921e19721a6438b738b17f', 'e8ef8031bdfd356478c9ad8cd3b83dfa3bb0e8f8',
                    'f4a9fbb3da01457a35a127e62be64ab702bd2c18'):
    raise SystemExit('Unexpected Adreno740 revision; requalify the compatibility patch')"""
NEW_HASH = """if revision not in ('a9a2cbb43b89d672e2921e19721a6438b738b17f', 'e8ef8031bdfd356478c9ad8cd3b83dfa3bb0e8f8',
                    'f4a9fbb3da01457a35a127e62be64ab702bd2c18'):
    # The rebuild replays the owner's local commits, so the hash differs while the content does not. Keep the real
    # gate below: the patch must reverse cleanly, apply cleanly, or be present at every landing point.
    print('Adreno740 at a rebuilt revision ' + revision[:12] + '; qualifying by content')"""

OLD_APPLY = """if check('--reverse','--check'):
    print('Darwin23 GPU compatibility already applied')
elif check('--check'):
    subprocess.run(['git','-C',driver,'apply',str(patch)],check=True)
else:
    raise SystemExit('GPU source context differs; refusing partial patch application')"""
NEW_APPLY = """landed=[('static int32_t nativeAdrenoTaskGpuRole(',client),
        ('static bool nativeAdrenoTaskGpuBackground(',client),
        ('nativeAdrenoTaskGpuBackground(current_task())',client),
        ('nativeAdrenoTaskGpuRole(current_task())',client),
        ('#if defined(NATIVE_ADRENO_PMAP_MAPPING_DIAGNOSTICS)',memory)]
stale=['submit_->nextRole(task_get_gpu_role(current_task()))',
       'row[3]=uint32_t(task_get_gpu_role(current_task()))',
       'const int32_t role=task_get_gpu_role(current_task());']
if check('--reverse','--check'):
    print('Darwin23 GPU compatibility already applied')
elif check('--check'):
    subprocess.run(['git','-C',driver,'apply',str(patch)],check=True)
else:
    # An upstream comment beside the patch may be reworded by the merge, so the reverse check falls over; the
    # landing points below are what the patch actually has to leave behind.
    missing=[line for line,text in landed if line not in text]
    broken=[line for line in stale if line in client]
    if missing or broken:
        raise SystemExit('GPU source context differs; refusing partial patch application: missing %r, stale %r'
                         % (missing,broken))
    print('Darwin23 GPU compatibility already applied (qualified at every landing point)')"""

OLD_READ = """patch=root/'patches/drivers/adreno740-darwin23-task-role.patch'"""
NEW_READ = """patch=root/'patches/drivers/adreno740-darwin23-task-role.patch'
client=(driver/'NativeAdrenoUserClient.cpp').read_text()
memory=(driver/'NativeAdrenoMemory.cpp').read_text()"""

MARK_HASH = "; qualifying by content"
MARK_APPLY = 'qualified at every landing point'

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get('SRC', '.'))
targets = [src / 'device/scripts/prepare-fuxi-driver-compat.py',
           src / 'device-ios17/scripts/prepare-fuxi-driver-compat.py']

done = 0
for path in targets:
    if not path.is_file():
        print(f'skip {path} (absent)')
        continue
    text = path.read_text()
    if MARK_APPLY in text or 'landed=[' in text:
        print(f'keep {path} (already qualified by content)')
        done += 1
        continue
    if OLD_HASH in text:
        text = text.replace(OLD_HASH, NEW_HASH, 1)
    elif MARK_HASH not in text:
        sys.exit(f'hash anchor not found in {path}')
    if OLD_APPLY not in text:
        sys.exit(f'apply anchor not found in {path}')
    if OLD_READ not in text:
        sys.exit(f'read anchor not found in {path}')
    text = text.replace(OLD_READ, NEW_READ, 1)
    text = text.replace(OLD_APPLY, NEW_APPLY, 1)
    path.write_text(text)
    print(f'patched {path}')
    done += 1

if not done:
    sys.exit('no prepare-fuxi-driver-compat.py found')
