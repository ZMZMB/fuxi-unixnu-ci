#!/usr/bin/env python3
"""Apply one xnu patch hunk by hunk, tolerating hunks upstream already carries.

The owner's patch set was written against his tree. Some of its hunks are now upstream verbatim (for example
zz-msg-probe.patch inserts #include <ipc/ipc_service_port.h>, which xnu-10063 already ships), so a whole-file
`git apply` refuses the patch and the remaining hunks never land. This applies each hunk on its own:

  * locate the hunk's old lines in the file (exact, else nearest occurrence) and rewrite them;
  * if the old lines are gone but every added line is already present, treat the hunk as applied;
  * a patch that creates a file (--- /dev/null) writes it, and skips it when it is already there;
  * anything else is a real mismatch: report it and exit non-zero.

Usage: apply-xnu-patch.py <patch> <source-root>
"""
import pathlib
import sys

OLD_PREFIX = 'a/'
NEW_PREFIX = 'b/'


def strip(raw, prefix):
    return None if raw == '/dev/null' else (raw[len(prefix):] if raw.startswith(prefix) else raw)


def parse(path):
    files = []
    current = None
    hunk = None
    for line in path.read_text(errors='surrogateescape').splitlines(keepends=True):
        if line.startswith('diff --git '):
            if current:
                files.append(current)
            parts = line.split()
            current = {'old': strip(parts[2], OLD_PREFIX), 'new': strip(parts[3], NEW_PREFIX), 'hunks': []}
            hunk = None
        elif line.startswith('--- '):
            old = strip(line.split()[1], OLD_PREFIX)
            if current is None or current['hunks']:
                if current:
                    files.append(current)
                current = {'old': old, 'new': None, 'hunks': []}
                hunk = None
            else:
                current['old'] = old
        elif line.startswith('+++ ') and current is not None and current['new'] is None:
            current['new'] = strip(line.split()[1], NEW_PREFIX)
        elif line.startswith('@@') and current is not None:
            head = line.split('@@')[1].strip()
            old_part, new_part = head.split(' ')[:2]
            hunk = {'old_start': int(old_part[1:].split(',')[0]), 'new_start': int(new_part[1:].split(',')[0]),
                    'lines': []}
            current['hunks'].append(hunk)
        elif current is not None and hunk is not None and line[:1] in (' ', '+', '-', '\\'):
            hunk['lines'].append(line)
    if current:
        files.append(current)
    return files


def split(hunk):
    old, new = [], []
    for line in hunk['lines']:
        tag, text = line[0], line[1:]
        if tag == ' ':
            old.append(text)
            new.append(text)
        elif tag == '-':
            old.append(text)
        elif tag == '+':
            new.append(text)
    return old, new


def find(lines, old, near):
    """Index of old as a contiguous block in lines, preferring the place closest to the recorded position."""
    if not old:
        return near
    exact = []
    first = old[0]
    for i in range(len(lines)):
        if lines[i] != first:
            continue
        if lines[i:i + len(old)] == old:
            exact.append(i)
    if not exact:
        return None
    return min(exact, key=lambda i: abs(i - near))


def apply_hunk(lines, hunk, rel, name, report):
    old, new = split(hunk)
    near = max(0, hunk['old_start'] - 1)
    at = find(lines, old, near)
    if at is not None:
        lines[at:at + len(old)] = new
        return True
    # Already there? Every added line present and every removed line gone.
    added = [line[1:] for line in hunk['lines'] if line[0] == '+']
    removed = [line[1:] for line in hunk['lines'] if line[0] == '-']
    if all(text in lines for text in added) and not any(text in lines for text in removed):
        report.append(f'{rel}:{hunk["old_start"]} already applied upstream, skipped')
        return True
    raise SystemExit(f'{name}: {rel}:{hunk["old_start"]} does not match; this hunk is not upstream and not applied')


def create(entry, root, name, report):
    """A patch that creates a file: write it whole, or accept that it is already there."""
    target = root / entry['new']
    body = []
    for hunk in entry['hunks']:
        body.extend(split(hunk)[1])
    if target.is_file():
        existing = target.read_text(errors='surrogateescape').splitlines(keepends=True)
        if existing == body or all(line in existing for line in body if line.strip()):
            report.append(f'{entry["new"]} already created')
            return
        raise SystemExit(f'{name}: {entry["new"]} exists and differs; this new file is not applied')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(''.join(body), errors='surrogateescape')
    report.append(f'{entry["new"]} created ({len(body)} line(s))')


def main():
    patch = pathlib.Path(sys.argv[1])
    root = pathlib.Path(sys.argv[2])
    report = []
    entries = parse(patch)
    hunks = 0
    for entry in entries:
        hunks += len(entry['hunks'])
        if entry['old'] is None:
            create(entry, root, patch.name, report)
            continue
        target = root / entry['new']
        if not target.is_file():
            raise SystemExit(f'{patch.name}: {entry["new"]} is missing under {root}')
        lines = target.read_text(errors='surrogateescape').splitlines(keepends=True)
        for hunk in entry['hunks']:
            apply_hunk(lines, hunk, entry['new'], patch.name, report)
        target.write_text(''.join(lines), errors='surrogateescape')
    for line in report:
        if 'created' in line or 'already created' in line:
            print(line)
    print(f'{patch.name}: applied {hunks} hunk(s), {len(report)} already upstream')


if __name__ == '__main__':
    main()
