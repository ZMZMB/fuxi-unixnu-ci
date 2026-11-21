"""Read the prelinked fileset kernelcache that the iOS 17 archive builders audit.

The builders (build-ios17-hid-input.py, build-ios17-legacy-display.py, build-adreno740-accelerator.py) need the
original 21H16 image for three things: the per-kext segments, the chained-fixup targets of a vtable, and raw words
at a fixed virtual address. This module reads the decompressed fileset kernelcache in place:

    Image(raw)            the MH_FILESET container; .entries maps a bundle id to (vmaddr, fileoff)
    Image(raw, fileoff)   one kext inside it; .segments carries the per-kext segment table
    .read(va, size)       the file bytes that back a virtual address
    .fixups()             {va: (target, authenticated, key, diversity, addr_div)}

Chained fixups are the kernel arm64e form: a 32-bit target added to the image's __TEXT virtual address,
a 16-bit PAC diversity, the addr-div bit, the 2-bit key, an 11-bit stride in 4-byte units, and the bind/auth bits
at 62/63. A zero word ends a chain.
"""
import struct

MH_MAGIC_64 = 0xfeedfacf
MH_FILESET = 0xC
LC_SEGMENT_64 = 0x19
LC_FILESET_ENTRY = 0x80000035
LC_DYLD_CHAINED_FIXUPS = 0x80000034

PTR_ARM64E_KERNEL = 7
PTR_64_KERNEL_CACHE = 8
PTR_ARM64E = 1
START_NONE = 0xFFFF
START_LAST = 0x8000
START_MULTI = 0x8000


class Image:
    def __init__(self, raw, at=0):
        if raw[:4] != b'\xcf\xfa\xed\xfe':
            raise ValueError('not a 64-bit little-endian Mach-O: %r' % (raw[:4],))
        self.raw = raw
        self.at = at
        self.segments = []
        self.entries = {}
        self.filetype = None
        self._fixup_ranges = []
        self._parse()

    # ---- parsing ----
    def _parse(self):
        raw, at = self.raw, self.at
        magic, _cpu, _sub, self.filetype, ncmds, _sz, _fl, _res = struct.unpack_from('<IiiIIIII', raw, at)
        if magic != MH_MAGIC_64:
            raise ValueError('bad Mach-O magic %#x at %#x' % (magic, at))
        off = at + 32
        for _ in range(ncmds):
            cmd, size = struct.unpack_from('<II', raw, off)
            if cmd == LC_SEGMENT_64:
                name = raw[off + 8:off + 24].rstrip(b'\0').decode()
                va, vsize, foff, fsize = struct.unpack_from('<QQQQ', raw, off + 24)
                nsects = struct.unpack_from('<I', raw, off + 64)[0]
                sections = []
                for s in range(nsects):
                    so = off + 72 + 80 * s
                    sect = raw[so:so + 16].rstrip(b'\0').decode()
                    saddr, ssize = struct.unpack_from('<QQ', raw, so + 32)
                    sections.append(dict(seg=name, sect=sect, va=saddr, size=ssize))
                self.segments.append(dict(name=name, va=va, size=vsize, fileoff=foff,
                                          filesize=fsize, sections=sections))
            elif cmd == LC_FILESET_ENTRY:
                vmaddr, fileoff, _eid_off = struct.unpack_from('<QQQ', raw, off + 8)
                eid = raw[off + 32:off + size].rstrip(b'\0').decode()
                self.entries[eid] = (vmaddr, fileoff)
            elif cmd == LC_DYLD_CHAINED_FIXUPS:
                dataoff, datasize = struct.unpack_from('<II', raw, off + 8)
                self._fixup_ranges.append((dataoff, datasize))
            off += size

    @property
    def vm_base(self):
        for seg in self.segments:
            if seg['name'] == '__TEXT':
                return seg['va']
        raise ValueError('no __TEXT segment')

    def segment(self, name):
        for seg in self.segments:
            if seg['name'] == name:
                return seg
        raise KeyError(name)

    # ---- virtual address access ----
    def _offset(self, va, size=1):
        for seg in self.segments:
            if seg['va'] and seg['va'] <= va < seg['va'] + seg['size']:
                delta = va - seg['va']
                if delta + size > seg['filesize']:
                    raise ValueError('va %#x runs past the file-backed part of %s' % (va, seg['name']))
                return seg['fileoff'] + delta
        raise KeyError('va %#x is outside every segment' % va)

    def read(self, va, size):
        off = self._offset(va, size)
        return self.raw[off:off + size]

    def word(self, va):
        return struct.unpack_from('<Q', self.raw, self._offset(va, 8))[0]

    # ---- chained fixups ----
    def fixups(self):
        """{va: (target, authenticated, key, diversity, addr_div)} for every rebased pointer in the image.

        The fileset carries one chained-fixup table for the whole image; its per-segment starts cover __DATA_CONST,
        __DATA_SPTM and __DATA, and the segment offsets are file offsets, so the container's own segment table maps
        every chain word back to a virtual address."""
        result = {}
        self._collect(result)
        return result

    def _collect(self, result):
        raw = self.raw
        for dataoff, _datasize in self._fixup_ranges:
            base = self.at + dataoff
            _ver, starts_off, _imp_off, _sym_off, _imp_cnt, _imp_fmt, _sym_fmt = struct.unpack_from('<7I', raw, base)
            starts = base + starts_off
            seg_count = struct.unpack_from('<I', raw, starts)[0]
            for i in range(seg_count):
                rel = struct.unpack_from('<I', raw, starts + 4 + 4 * i)[0]
                if not rel:
                    continue  # no chained starts for this segment
                info = starts + rel
                _size, page_size, pointer_format = struct.unpack_from('<IHH', raw, info)
                segment_offset = struct.unpack_from('<Q', raw, info + 8)[0]
                _maxptr = struct.unpack_from('<I', raw, info + 16)[0]
                page_count = struct.unpack_from('<H', raw, info + 20)[0]
                if pointer_format not in (PTR_ARM64E_KERNEL, PTR_64_KERNEL_CACHE, PTR_ARM64E):
                    raise ValueError('unsupported pointer format %d' % pointer_format)
                target_mask = 0x3FFFFFFF if pointer_format == PTR_64_KERNEL_CACHE else 0xFFFFFFFF
                for page in range(page_count):
                    start = struct.unpack_from('<H', raw, info + 22 + 2 * page)[0]
                    if start == START_NONE:
                        continue
                    if start & START_MULTI:
                        raise ValueError('multi-start chains are not handled (page %d)' % page)
                    pos = self.at + segment_offset + page * page_size + start
                    va = None
                    while True:
                        w = struct.unpack_from('<Q', raw, pos)[0]
                        if not w:
                            break
                        if va is None:
                            va = self._container_va(pos)
                        auth = w >> 63
                        bind = (w >> 62) & 1
                        if bind:
                            nxt = (w >> 51) & 0x7FF
                            if not nxt:
                                break
                            pos += nxt * 4
                            va += nxt * 4
                            continue
                        target = (w & target_mask) + self.vm_base
                        diversity = (w >> 32) & 0xFFFF
                        addr_div = (w >> 48) & 1
                        key = (w >> 49) & 3
                        result[va] = (target, bool(auth), key, diversity, addr_div)
                        nxt = (w >> 51) & 0x7FF
                        if not nxt:
                            break
                        pos += nxt * 4
                        va += nxt * 4

    def _container_va(self, fileoff):
        for seg in self.segments:
            if seg['fileoff'] and seg['fileoff'] <= fileoff < seg['fileoff'] + seg['filesize']:
                return seg['va'] + (fileoff - seg['fileoff'])
        raise ValueError('file offset %#x is outside every segment' % fileoff)
