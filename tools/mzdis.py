#!/usr/bin/env python3
"""MZ loader + 16-bit disassembly helpers for the Digispeech RE effort.

Usage:
  mzdis.py info FILE              - parse MZ header, print load-image layout
  mzdis.py io FILE [start [end]]  - linear-sweep disassemble load image,
                                    print every IN/OUT/INT with context
  mzdis.py dis FILE START END [--org N] - disassemble a range (file offsets
                                    into the load image)
  mzdis.py strings FILE [minlen]  - printable strings in the load image
"""
import sys, struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_16


def parse_mz(path):
    data = open(path, 'rb').read()
    if data[:2] not in (b'MZ', b'ZM'):
        return None, data  # raw binary (e.g. plain .SYS)
    (sig, cblp, cp, crlc, cparhdr, minalloc, maxalloc, ss, sp, csum, ip, cs,
     lfarlc, ovno) = struct.unpack('<H13H', data[:28])
    hdrsize = cparhdr * 16
    total = (cp - 1) * 512 + cblp if cblp else cp * 512
    image = data[hdrsize:total]
    relocs = []
    for i in range(crlc):
        off, seg = struct.unpack_from('<HH', data, lfarlc + i * 4)
        relocs.append((seg, off))
    info = dict(cblp=cblp, cp=cp, crlc=crlc, hdrsize=hdrsize, total=total,
                minalloc=minalloc, maxalloc=maxalloc, ss=ss, sp=sp, ip=ip,
                cs=cs, filesize=len(data), imagesize=len(image),
                overlay=len(data) - total, relocs=relocs)
    return info, image


def disasm(image, start, end, org=None):
    md = Cs(CS_ARCH_X86, CS_MODE_16)
    md.skipdata = True
    org = start if org is None else org
    return md.disasm(bytes(image[start:end]), org)


def cmd_info(path):
    info, image = parse_mz(path)
    if info is None:
        print(f'raw binary, {len(image)} bytes')
        return
    for k, v in info.items():
        if k == 'relocs':
            print(f'relocs ({len(v)}):', ' '.join(f'{s:04x}:{o:04x}' for s, o in v[:40]),
                  '...' if len(v) > 40 else '')
        else:
            print(f'{k}: {v:#x}' if isinstance(v, int) else f'{k}: {v}')


def cmd_io(path, start=0, end=None):
    info, image = parse_mz(path)
    end = len(image) if end is None else end
    md = Cs(CS_ARCH_X86, CS_MODE_16)
    md.skipdata = True
    window = []
    for insn in md.disasm(bytes(image[start:end]), start):
        window.append(insn)
        if len(window) > 8:
            window.pop(0)
        if insn.mnemonic in ('in', 'out', 'insb', 'insw', 'outsb', 'outsw'):
            print(f'--- {insn.mnemonic} at image {insn.address:#06x}')
            for w in window:
                print(f'  {w.address:06x}: {w.bytes.hex():<16} {w.mnemonic} {w.op_str}')


def cmd_dis(path, start, end, org=None):
    info, image = parse_mz(path)
    for insn in disasm(image, start, end, org):
        print(f'{insn.address:06x}: {insn.bytes.hex():<16} {insn.mnemonic} {insn.op_str}')


def cmd_strings(path, minlen=5):
    info, image = parse_mz(path)
    cur, curoff = [], 0
    for i, b in enumerate(image):
        if 32 <= b < 127:
            if not cur:
                curoff = i
            cur.append(chr(b))
        else:
            if len(cur) >= minlen:
                print(f'{curoff:06x}: {"".join(cur)}')
            cur = []
    if len(cur) >= minlen:
        print(f'{curoff:06x}: {"".join(cur)}')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'info':
        cmd_info(sys.argv[2])
    elif cmd == 'io':
        args = [int(a, 0) for a in sys.argv[3:]]
        cmd_io(sys.argv[2], *args)
    elif cmd == 'dis':
        a = sys.argv[3:]
        org = None
        if '--org' in a:
            i = a.index('--org'); org = int(a[i+1], 0); a = a[:i]
        cmd_dis(sys.argv[2], int(a[0], 0), int(a[1], 0), org)
    elif cmd == 'strings':
        ml = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        cmd_strings(sys.argv[2], ml)
