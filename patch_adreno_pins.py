"""Point the Adreno prepare scripts at the pins file that matches the warmed cache.

Usage: python patch_adreno_pins.py <src-root> <pins-json>
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
pins = sys.argv[2]
OLD = "inputs = args.inputs or root / 'scripts' / 'data' / 'adreno-inputs.json'"
NEW = ("inputs = args.inputs or (Path(ADX_PINS) if ADX_PINS else "
       "root / 'scripts' / 'data' / 'adreno-inputs.json')")
HEADER = "ADX_PINS = os.environ.get('UNIXNU_ADRENO_PINS', %r)\n" % pins

targets = [p for p in sorted(root.glob('**/scripts/prepare-fuxi-*.py'))
           if '/out/' not in str(p).replace('\\', '/') and OLD in p.read_text()]
if not targets:
    raise SystemExit('no Adreno prepare script with the default pins lookup under ' + str(root))
print('targets:', ', '.join(str(t) for t in targets))

for path in targets:
    text = path.read_text()
    if 'UNIXNU_ADRENO_PINS' in text:
        print(path, 'already patched')
        continue
    if '\nimport os' not in text:
        text = text.replace('\nimport argparse', '\nimport os\nimport argparse', 1)
    if '\nimport os\n' not in text:
        raise SystemExit('cannot place import os in ' + str(path))
    text = text.replace('\nimport os\n', '\nimport os\n' + HEADER, 1)
    text = text.replace(OLD, NEW)
    path.write_text(text)
    print(path, 'patched')
