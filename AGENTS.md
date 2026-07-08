# AGENTS.md — Digispeech "Port·Able Sound" (DS301) Parallel-Port RE

Map + "how to continue" for anyone (human or agent) picking this up. The core
deliverable is complete; read the guide first, then this.

## What this is

Reverse-engineering of the Digispeech / Port·Able Sound (**DS301**; models
DS301A / DS311 / DS311A; driver family "DS3XX") parallel-port audio devices
(DSP Solutions, c. 1993–94), to enable clean-room compatible devices, drivers, or
emulator backends. Deliverable is **documentation, not drivers.**

## Deliverable (done)

**`docs/DS301-Protocol-Implementation-Guide.md`** (also the repo README) — a
clean-room, royalty-free, non-verbatim guide covering: detection; the SPP
write-word / nibble-read primitives + decode tables; command/format codes;
timing / PIT calibration; playback and recording; DSP code download; the
SB/AdLib/MIDI layer and the mono-only mixer; the codec suite and native
PDIGI/LPC-speech paths; and reimplementation guidance (minimum-viable subset for
e.g. Picovox; an OPL3 + stereo-16 superset; an SBEMU/VSBHDA-style emulator
backend). Read it first — the technical detail lives there, not here.

## Assets in this repo

- `PORTSND/` — installed DOS software, already unpacked: `DS301.SYS`,
  `SOUND301.EXE`, `PDIGI.EXE` + `PDRV*.DAT`, `BMASTER.EXE`, `DGSETUP.EXE`,
  `SOUNDPWM.EXE`, etc.
- `DISK1/`, `DISK2/` — original v2.0 install floppies. Payloads are LZSS-packed as
  `*.XX$`; the Windows `DS301.DRV` / `VDS301.386` are stored uncompressed.
- `DOS_WIN3.X_WIN95_Install_v4.00/` — later v4.00 / Windows-95 set (`DS3XX.*`,
  `VDS3XX.386`). Wire protocol identical; still OPL2/SB-class.
- `source-docs/…Digispeech_Plus.pdf` — manufacturer manual (primary source;
  ~17 MB, untracked).
- `tools/mzdis.py` — MZ loader + 16-bit disasm helpers (`info` / `io` / `dis` /
  `strings`). `tools/vxddis.py` — 32-bit LE/VxD disasm that skips the DDK
  `int 20h`+dword `VxDcall` so it doesn't desync (use for `VDS*.386`). Pure
  stdlib + capstone.

Packed-file details, if you ever need to unpack the floppies: `*.XX$` payloads use
the `EDILZSS1` container = 8-byte signature + NUL-terminated original filename +
1 header byte + Okumura LZSS (4096-byte window, threshold 2, ring pre-filled with
spaces, write cursor starts at `0xFEE`, flag bit 1 = literal / 0 = back-ref).
`UNINSTAL.INF` is the same but XOR-obfuscated with key `0x9C`.

## Port model (summary; full detail in the guide)

Standard **SPP only — no EPP/ECP.** `base` = Data (LPT1 `0x378` / LPT2 `0x278` /
LPT3 `0x3BC`, discovered from BIOS Data Area `0040:0008`); `base+1` = Status (five
input lines carry data back in nibble mode plus handshake/IRQ); `base+2` = Control
(b0 STROBE = write clock, b4 IRQ-enable). Read-back is plain nibble mode over the
status lines.

## Sources and the corrections they made

- **Manual** (`source-docs/`): corrected two static-RE conclusions — FM and PCM
  *can* mix, but only in **mono**; and FM is a **device DSP** capability
  (OPL2-*functional*, ~11-voice, **no discrete OPL chip**).
- **LGR Oddware video** (DS311): chip is **TI-fabricated**; demonstrated the
  FM / stereo-PCM exclusivity; flagged SB-ADPCM as a game stressor.
- **v4.00 / Win95 software**: protocol unchanged across the family and versions;
  adds Win95 support + an OS-visible mixer/aux; still no OPL3/SB16.

## Open questions — need a dynamic capture, not more static RE

The DOS `BMASTER` host/device FM division and on-wire FM encoding; exact command
opcodes (native PDIGI API, ADPCM, power up/down); onboard buffer depth;
downloaded-DSP image/ISA format; full format-code bitfields; and the load-bearing
one for a "better device" — whether the original drivers emit FM+PCM concurrently
or serialize them.

**Resolve via** a logic-analyzer LPT capture (detection / PCM tone / FM-only /
mixed) or iterative bring-up (guide §13). Caveat: stock DOSBox / DOSBox-X do **not**
emulate a DS301 on the LPT port, so a bare trace dies at the probe — use
real-hardware passthrough or a stub responder that satisfies detection.

## Methodology lesson

In `BMASTER`'s obfuscated 32-bit VCPI code, address-pattern greps give false
positives — a promising "synthesis-table reference" at `0xe600` was actually
`mov al,[0x15xx]; out 0x0a/0b/0c` (8237 DMA emulation), not a table lookup.
**Disassemble / verify raw bytes before trusting a pattern grep.**

## Constraints (keep for any future work)

- **Royalty-free / patent-expired algorithms only** — a compatible device/driver
  must be buildable free and open-source.
- **No verbatim** reproduction of the manual or binary text — state facts in your
  own words (facts and interfaces are not copyrightable).
- **Prioritize playback** (DOS-game / Windows-app PCM + ADPCM + FM) over recording.
