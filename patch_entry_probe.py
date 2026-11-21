#!/usr/bin/env python3
"""Rewrite kernel_symbols() in the tree's patch-xnu-entry-probe.py so it reads the Mach-O fileset itself.

The prelinked kernel.macho is MH_FILESET: the top-level header carries no LC_SYMTAB, the symbol
tables live in the LC_FILESET_ENTRY headers (com.apple.kernel alone has ~198k symbols). llvm-nm on
Linux does not walk the fileset and prints a header line, so the board script dies with
"ValueError: invalid literal for int() with base 16: 'Symbols'". This replaces the llvm-nm parse
with a direct read: top header + every fileset entry header, LC_SYMTAB nlist_64 entries.
"""
import sys
import py_compile
from pathlib import Path

NEW = '''def kernel_symbols(kernel):
    """Address -> name for the kernel's symbols, read straight from the Mach-O fileset."""
    data = Path(kernel).read_bytes()
    table = {}
    headers = []
    if len(data) >= 32 and struct.unpack_from('<I', data, 0)[0] == 0xFEEDFACF:
        headers.append(0)
        if struct.unpack_from('<I', data, 12)[0] == 0xC:              # MH_FILESET
            count = struct.unpack_from('<I', data, 16)[0]
            offset = 32
            for _ in range(count):
                command, size = struct.unpack_from('<II', data, offset)
                if command == 0x80000035 and size >= 32:              # LC_FILESET_ENTRY
                    headers.append(struct.unpack_from('<Q', data, offset + 16)[0])
                offset += size
    for header in headers:
        if header + 32 > len(data) or struct.unpack_from('<I', data, header)[0] != 0xFEEDFACF:
            continue
        count, offset = struct.unpack_from('<I', data, header + 16)[0], header + 32
        for _ in range(count):
            command, size = struct.unpack_from('<II', data, offset)
            if command == 0x2 and size >= 24 and offset + 24 <= len(data):   # LC_SYMTAB
                symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', data, offset + 8)
                strings = data[stroff:stroff + strsize]
                for index in range(nsyms):
                    at = symoff + index * 16
                    if at + 16 > len(data):
                        break
                    strx, ntype, nsect, ndesc, nvalue = struct.unpack_from('<IBBHQ', data, at)
                    if (nvalue and strx and not ntype & 0xE0
                            and (ntype & 0x0E) in (0x2, 0x0E) and strx < len(strings)):
                        end = strings.find(b'\\0', strx)
                        name = strings[strx:end if end >= 0 else len(strings)].decode('utf-8', 'replace')
                        if name:
                            table.setdefault(nvalue, name)
            offset += size
    print(f'entry-probe: {len(table)} symbols from the Mach-O fileset', file=sys.stderr)
    return table
'''

START = 'def kernel_symbols(kernel):'
END = '\n\ndef function_range(symbols, name):'


def patch_one(path):
    if not path.is_file():
        print(f'{path}: not found, skipped')
        return
    text = path.read_text()
    if 'from the Mach-O fileset' in text:
        print(f'{path}: already reads the fileset, nothing to do')
        return
    begin = text.index(START)
    finish = text.index(END, begin)
    path.write_text(text[:begin] + NEW + text[finish:])
    py_compile.compile(str(path), doraise=True)
    print(f'{path}: kernel_symbols now parses LC_SYMTAB of every LC_FILESET_ENTRY')


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: patch_entry_probe.py TREE/scripts/patch-xnu-entry-probe.py ...')
    for name in sys.argv[1:]:
        patch_one(Path(name))


if __name__ == '__main__':
    main()
