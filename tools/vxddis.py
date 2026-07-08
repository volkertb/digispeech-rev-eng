#!/usr/bin/env python3
"""VxD-aware 32-bit disassembler for LE files.

Handles the DDK `int 20h` + 4-byte service-ID convention: after a CD 20 the
next 4 bytes are data (the VMM/VxD service dword), not code, so we print the
decoded service and resume disassembly past it. Without this, capstone's
linear sweep desyncs for the rest of the routine.

Usage: vxddis.py FILE.386 START END      (START/END are offsets into obj1)
"""
import sys, struct
from capstone import Cs, CS_ARCH_X86, CS_MODE_32


def load_obj1(path):
    d = open(path, 'rb').read()
    le = struct.unpack('<H', d[0x3c:0x3e])[0]
    u32 = lambda o: struct.unpack('<I', d[le + o:le + o + 4])[0]
    datapagesoff = u32(0x80)
    pagesize = u32(0x28)
    objtab = le + u32(0x40)
    vsize = struct.unpack('<I', d[objtab:objtab + 4])[0]
    return d[datapagesoff:datapagesoff + vsize + pagesize]


def dis(path, start, end):
    code = load_obj1(path)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.skipdata = True
    addr = start
    while addr < end:
        chunk = code[addr:min(end, addr + 32)]
        insns = list(md.disasm(chunk, addr, count=1))
        if not insns:
            print(f'{addr:05x}: db {code[addr]:02x}')
            addr += 1
            continue
        insn = insns[0]
        if insn.bytes[:2] == b'\xcd\x20':  # int 20h => VxD service call
            svc = struct.unpack('<I', code[addr + 2:addr + 6])[0]
            print(f'{addr:05x}: VxDcall  {svc:#010x}  '
                  f'(dev={svc >> 16:#06x} svc={svc & 0xffff:#06x})')
            addr += 6
            continue
        print(f'{addr:05x}: {insn.bytes.hex():<14} {insn.mnemonic} {insn.op_str}')
        addr += insn.size


if __name__ == '__main__':
    dis(sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0))
