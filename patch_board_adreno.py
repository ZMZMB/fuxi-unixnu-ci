"""Point the Adreno prepare archives at one cache/pins pair so verify_source() sees what was fetched.

Usage: python patch_board_adreno.py <device-root> <cache-dir> <pins-json>
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
cache = sys.argv[2]
pins = sys.argv[3]
NAMES = ('prepare-fuxi-gmu-votes.py', 'prepare-fuxi-gmu.py', 'prepare-fuxi-command-db-oracle.py')

boards = [p for p in sorted(root.glob('**/ios17/board.toml'))
          if '/out/' not in str(p).replace('\\', '/')]
if not boards:
    raise SystemExit('no ios17/board.toml under ' + str(root))
print('boards:', ', '.join(str(b) for b in boards))

for board in boards:
    text = board.read_text()
    changed = 0
    out = []
    for line in text.splitlines(True):
        for name in NAMES:
            bare = '"' + name + '"'
            token = '"' + name + ' '
            if '--cache ' in line:
                break
            if token in line:
                line = line.replace(token, '"%s --cache %s --inputs %s ' % (name, cache, pins), 1)
                changed += 1
                break
            if bare in line:
                line = line.replace(bare, '"%s --cache %s --inputs %s"' % (name, cache, pins), 1)
                changed += 1
                break
        out.append(line)
    if changed:
        board.write_text(''.join(out))
    print(board, 'rewrote', changed, 'archive line(s)')
