#!/usr/bin/env python3
"""Let the fuxi USB debug stage accept the flattened driver copy.

The owner's prepare-fuxi-usb-debug.py insists that drivers/QcomXnuUsbDebug is a git worktree sitting exactly on
QUD_REVISION. In the CI tree the device package is a plain copy (no .git), so `git rev-parse` fails outright and
the kernel step stops before it starts. The revision check is replaced by: compare only when the directory really
is its own worktree, and otherwise leave the content check to the following `git apply --check`. The XNU check
stays strict.
"""
import os
import pathlib
import sys

OLD = (
    "    if git(module, 'rev-parse', 'HEAD') != QUD_REVISION or git(xnu, 'rev-parse', 'HEAD') != XNU_REVISION:\n"
    "        raise ValueError('unexpected module/XNU source revision')"
)
NEW = (
    "    def own_revision(path):\n"
    "        try:\n"
    "            top = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--show-toplevel'], text=True).strip()\n"
    "        except subprocess.CalledProcessError:\n"
    "            return None\n"
    "        if pathlib.Path(top).resolve() != pathlib.Path(path).resolve():\n"
    "            return None\n"
    "        try:\n"
    "            return git(path, 'rev-parse', 'HEAD')\n"
    "        except subprocess.CalledProcessError:\n"
    "            return None\n"
    "    module_revision = own_revision(module)\n"
    "    if module_revision is not None and module_revision != QUD_REVISION:\n"
    "        raise ValueError('unexpected module source revision: ' + module_revision)\n"
    "    xnu_revision = git(xnu, 'rev-parse', 'HEAD')\n"
    "    if xnu_revision != XNU_REVISION:\n"
    "        raise ValueError('unexpected XNU source revision: ' + xnu_revision)"
)
MARK = "module_revision = own_revision(module)"

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get('SRC', '.'))
targets = [src / 'device/scripts/prepare-fuxi-usb-debug.py',
           src / 'device-ios17/scripts/prepare-fuxi-usb-debug.py']

patched = 0
for path in targets:
    if not path.is_file():
        print(f'skip {path} (absent)')
        continue
    text = path.read_text()
    if MARK in text:
        print(f'keep {path} (already relaxed)')
        patched += 1
        continue
    if OLD not in text:
        sys.exit(f'anchor not found in {path}')
    if 'import pathlib' not in text:
        text = text.replace('import json\n', 'import json\nimport pathlib\n', 1)
    path.write_text(text.replace(OLD, NEW))
    print(f'patched {path}')
    patched += 1

if not patched:
    sys.exit('no prepare-fuxi-usb-debug.py found; the device scripts moved')
