"""Seed fuxi_adreno_common.ensure_adreno_cache() from a pre-warmed cache before it touches the network.

Usage: python patch_adreno_cache.py <source-root>
The source root is the rebuilt device checkout (its .cache/adreno-source is filled by the workflow).
"""
import pathlib
import sys

MARK = 'UNIXNU_ADRENO_CACHE_SOURCE'
ANCHOR = '    if all((cache / name).is_file() for name in required):\n        return\n'
INSERT = (
    '    prefetch = os.environ.get("UNIXNU_ADRENO_CACHE_SOURCE", "")\n'
    '    if prefetch and Path(prefetch).is_dir():\n'
    '        base = Path(prefetch)\n'
    '        for src in base.rglob("*"):\n'
    '            if src.is_file():\n'
    '                dst = cache / src.relative_to(base)\n'
    '                dst.parent.mkdir(parents=True, exist_ok=True)\n'
    '                dst.write_bytes(src.read_bytes())\n'
)

root = pathlib.Path(sys.argv[1])
targets = [p for p in sorted(root.glob('**/scripts/fuxi_adreno_common.py'))
           if '/out/' not in str(p).replace('\\', '/')]
if not targets:
    raise SystemExit('no fuxi_adreno_common.py under ' + str(root))
print('targets:', ', '.join(str(t) for t in targets))

for path in targets:
    text = path.read_text()
    if MARK in text:
        print(path, 'already patched')
        continue
    if ANCHOR not in text:
        raise SystemExit('anchor not found in ' + str(path))
    text = text.replace(ANCHOR, INSERT + ANCHOR, 1)
    path.write_text(text)
    print(path, 'patched')
