#!/usr/bin/env python3
"""EDILZSS1 unpacker for Digispeech install payloads (*.XX$ / *.EX$ / *.DA$ ...).

Container: 8-byte signature 'EDILZSS1' + NUL-terminated original filename +
1 header byte + Okumura LZSS (4096-byte ring pre-filled with spaces, write
cursor starts at 0xFEE, threshold 2, flag bit 1 = literal / 0 = back-ref).

Usage: unpack_xx.py FILE [-o OUTDIR]   (prints stored name; writes OUTDIR/NAME)
       unpack_xx.py FILE -             (decoded bytes to stdout)
"""
import sys, os


def unpack(data):
    if data[:8] != b'EDILZSS1':
        raise ValueError('not an EDILZSS1 container')
    nul = data.index(0, 8)
    name = data[8:nul].decode('ascii', 'replace')
    pos = nul + 1 + 1                     # skip NUL + 1 header byte
    ring = bytearray(b' ' * 4096)
    r = 0xFEE
    out = bytearray()
    flags = 0
    while pos < len(data):
        flags >>= 1
        if not flags & 0x100:
            flags = data[pos] | 0xFF00
            pos += 1
            if pos >= len(data):
                break
        if flags & 1:                     # literal
            b = data[pos]; pos += 1
            out.append(b)
            ring[r] = b; r = (r + 1) & 0xFFF
        else:                             # back-reference
            if pos + 1 >= len(data):
                break
            lo, hi = data[pos], data[pos + 1]; pos += 2
            off = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + 3      # threshold 2 -> +3
            for _ in range(length):
                b = ring[off]
                out.append(b)
                ring[r] = b
                r = (r + 1) & 0xFFF
                off = (off + 1) & 0xFFF
    return name, bytes(out)


if __name__ == '__main__':
    path = sys.argv[1]
    name, out = unpack(open(path, 'rb').read())
    if len(sys.argv) > 2 and sys.argv[2] == '-':
        sys.stdout.buffer.write(out)
    else:
        outdir = sys.argv[sys.argv.index('-o') + 1] if '-o' in sys.argv else '.'
        os.makedirs(outdir, exist_ok=True)
        dest = os.path.join(outdir, name)
        open(dest, 'wb').write(out)
        print(f'{path}: {name} -> {dest} ({len(out)} bytes)')
