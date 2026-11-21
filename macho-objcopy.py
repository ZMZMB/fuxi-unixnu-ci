#!/usr/bin/env python3
"""A Mach-O capable stand-in for llvm-objcopy.

Apple's llvm-objcopy handles Mach-O; the one Ubuntu installs refuses both options the owner's builders use, with
"option is not supported for MachO":

    --remove-section=__DATA,__mod_init_func      drop a C++ static initialiser section
    --globalize-symbol=__GLOBAL__sub_I_Foo.cpp   make its initialiser callable from a second object

Both are realised here on the object file itself:

  * the named section keeps its index (so every n_sect stays valid) but is renamed to a dead name and its flags
    are cleared, which stops ld64/ld will merging it back into __mod_init_func;
  * the named symbol gets N_EXT set, so the link sees it as a global definition.

Anything else is handed to the real llvm-objcopy unchanged.

Usage: llvm-objcopy [--remove-section=SEG,SECT] [--globalize-symbol=NAME] <in> <out>
"""
import os
import struct
import sys

REAL = '/usr/bin/llvm-objcopy'
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x02
N_EXT = 0x01
MH_MAGIC_64 = 0xfeedfacf


def parse_args(argv):
    remove, globalize, files, passthrough = [], [], [], False
    for arg in argv:
        if arg.startswith('--remove-section='):
            remove.append(arg.split('=', 1)[1])
        elif arg.startswith('--globalize-symbol='):
            globalize.append(arg.split('=', 1)[1])
        elif arg.startswith('-'):
            passthrough = True
        else:
            files.append(arg)
    return remove, globalize, files, passthrough


def rewrite(path, out, remove, globalize):
    with open(path, 'rb') as handle:
        data = bytearray(handle.read())
    magic, = struct.unpack_from('<I', data, 0)
    if magic != MH_MAGIC_64:
        raise SystemExit(f'llvm-objcopy stand-in: {path} is not a 64-bit little-endian Mach-O object')
    _, _, _, _, ncmds, sizeofcmds, _, _ = struct.unpack_from('<IIIIIIII', data, 0)
    offset = 32
    end = 32 + sizeofcmds
    touched = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, offset)
        if cmd == LC_SEGMENT_64:
            nsects = struct.unpack_from('<I', data, offset + 64)[0]
            sect_at = offset + 72
            for _ in range(nsects):
                sectname = data[sect_at:sect_at + 16].split(b'\0', 1)[0].decode()
                segname = data[sect_at + 16:sect_at + 32].split(b'\0', 1)[0].decode()
                if f'{segname},{sectname}' in remove:
                    # 16 bytes of name plus the flags word: a dead name and S_REGULAR keep the linker out of it.
                    # Rename to __DATA,__data with S_REGULAR, the same trick the owner's own builders use where
                    # llvm-objcopy cannot rename a Mach-O segment: the pointer stays in the object, but nothing
                    # registers it as an initialiser.
                    dead = b'__data'.ljust(16, b'\0')
                    data[sect_at:sect_at + 16] = dead
                    struct.pack_into('<I', data, sect_at + 64, 0)
                    touched.append(f'{segname},{sectname}')
                sect_at += 80
        elif cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', data, offset + 8)
            for i in range(nsyms):
                at = symoff + i * 16
                strx, ntype, nsect, ndesc, nvalue = struct.unpack_from('<IBBHQ', data, at)
                name = data[stroff + strx:stroff + strx + 64].split(b'\0', 1)[0].decode(errors='replace')
                if name in globalize and not ntype & N_EXT:
                    struct.pack_into('<B', data, at + 4, ntype | N_EXT)
                    touched.append(f'global {name}')
        offset += cmdsize
        if offset >= end:
            break
    if not touched:
        raise SystemExit(f'llvm-objcopy stand-in: nothing matched in {path} '
                         f'(remove={remove} globalize={globalize})')
    with open(out or path, 'wb') as handle:
        handle.write(data)
    print('llvm-objcopy stand-in:', path, '->', out or path, '|', ', '.join(touched))


def main():
    argv = sys.argv[1:]
    remove, globalize, files, passthrough = parse_args(argv)
    if passthrough or not (remove or globalize):
        os.execv(REAL, [REAL] + argv)
    if len(files) < 1:
        raise SystemExit('llvm-objcopy stand-in: no input object')
    rewrite(files[0], files[1] if len(files) > 1 else None, remove, globalize)


if __name__ == '__main__':
    main()
