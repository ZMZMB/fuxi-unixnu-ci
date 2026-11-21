#!/usr/bin/env python3
"""Expand the 21H16 kernelcache the ios17 archive builders read.

build-adreno740-accelerator.py, build-ios17-hid-input.py and build-ios17-legacy-display.py all open
out/ipsw/21H16/kernelcache.decompressed and the held-out ABI plans assert its sha256. The IPSW carries it as an
IM4P (krnl) whose payload is an LZFSE 'bvx2' stream, so the CI expands it here and refuses to continue unless the
bytes hash to the 21H16 digest the plans were audited against.
"""
import hashlib
import pathlib
import sys

EXPECT = '9bd1028796b0baa12922ab44fda1805b11595981338288c7881c669238d352e5'

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])

import lzfse
import pyimg4

im4p = pyimg4.IM4P(src.read_bytes())
if str(im4p.fourcc) != 'krnl':
    sys.exit(f'{src}: expected a krnl IM4P, got {im4p.fourcc!r}')
raw = lzfse.decompress(bytes(im4p.payload.data))
digest = hashlib.sha256(raw).hexdigest()
if digest != EXPECT:
    sys.exit(f'{src}: kernelcache sha256 {digest} is not the 21H16 digest {EXPECT}')
if raw[:4] != b'\xcf\xfa\xed\xfe':
    sys.exit(f'{src}: expanded payload is not a 64-bit Mach-O ({raw[:4].hex()})')
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_bytes(raw)
print(f'kernelcache: {src.name} -> {dst} ({len(raw)} bytes, sha256 {digest})')
