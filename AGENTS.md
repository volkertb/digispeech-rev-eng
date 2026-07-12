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
  ~17 MB, untracked). Also untracked there: LGR Oddware DS311 video transcript and
  its YouTube comments (`lgr-digispeech-youtube-video-{transcript,comments}.txt`),
  DS301A board photos (`ds301-board-{front,back}.jpg`, recovered from archive.org;
  originally VOGONS p427977), and the May-1993 Usenet review (`PORTABLE`,
  `PORTABLE.1`, from `portable.arj` via VOGONS p628871) — third-party material,
  keep out of the public repo; the docs cite the public VOGONS posts instead.
- `tools/mzdis.py` — MZ loader + 16-bit disasm helpers (`info` / `io` / `dis` /
  `strings`). `tools/vxddis.py` — 32-bit LE/VxD disasm that skips the DDK
  `int 20h`+dword `VxDcall` so it doesn't desync (use for `VDS*.386`). Pure
  stdlib + capstone. For DSP-payload work, mame-tools' `unidasm -arch tms320c5x`
  is installed (capstone has no C5x support).

Packed-file details, if you ever need to unpack the floppies: `*.XX$` payloads use
the `EDILZSS1` container = 8-byte signature + NUL-terminated original filename +
1 header byte + Okumura LZSS (4096-byte window, threshold 2, ring pre-filled with
spaces, write cursor starts at `0xFEE`, flag bit 1 = literal / 0 = back-ref).
`UNINSTAL.INF` is the same but XOR-obfuscated with key `0x9C`.

## Port model (summary; full detail in the guide)

Standard **SPP only — no EPP/ECP.** `base` = Data (LPT1 `0x378` / LPT2 `0x278` /
LPT3 `0x3BC`, discovered from BIOS Data Area `0040:0008`); `base+1` = Status (four
lines — b3/b4/b5/b7 — carry data back in nibble mode; b6 ACK is the handshake/IRQ);
`base+2` = Control
(b0 STROBE = write clock, b4 IRQ-enable). Read-back is plain nibble mode over the
status lines.

## Sources and the corrections they made

- **Manual** (`source-docs/`): corrected two static-RE conclusions — FM and PCM
  *can* mix, but only in **mono**; and FM is a **device DSP** capability
  (OPL2-*functional*, ~11-voice, **no discrete OPL chip**).
- **LGR Oddware video + comments** (DS311): chip is **TI-fabricated** (board also
  carries a second ASIC marked GPS `MVA70018`, no public datasheet); showed DOS
  `BMASTER` **mixing** FM+PCM in Wolfenstein 3D but **serializing** in Super
  Fighter / Duke Nukem II (all mono titles — audio evidence, not the transcript,
  which even contradicts it at 22:33), and Windows mixing via the opt-in Mix
  Wave/Synth; comments resolved the apparent 22 kHz-recording spec conflict (the
  UI setting silently reverted — manual's 8/11.025 kHz stands). SB-ADPCM as a
  Duke II stressor is community knowledge (VOGONS / dosemu2 #1060), not from the
  video.
- **v4.00 / Win95 software**: protocol unchanged across the family and versions;
  adds Win95 support + an OS-visible mixer/aux; still no OPL3/SB16.
- **VOGONS t=62280** (teardowns/tests, 2018–24): DS311 = rehoused Port·Able Sound
  Plus; the TI DS301 + GPS `MVA70018` pair also shipped as the **Sony PRD-155SB
  PCMCIA** card and the **DS103J** combo sound+network card. Decisive test (Bondi
  2021): on the PCMCIA card, Duke Nukem II and Super Fighter **mix FM+PCM fine** —
  the same titles serialize over LPT — so serialization is an **LPT-stack**
  property, not the chip. Wayback holds DSP Solutions' last FTP file library
  (June 1998). (Serial **DS201/DS201A** — earlier generation; no FM, reportedly a
  PCjr/Tandy-style 3-voice SN76496-like tone generator, noise channel not
  emulated — out of scope beyond asides.)
- **Board photos** (VOGONS p427977, attachments recovered): "DS301" chip =
  **custom-mask TI TMS320C53** (`D32053FNL`; 16K-word ROM + 4K-word RAM on chip);
  "GPS" chip = **GEC Plessey** semi-custom gate array (`CLA74022CG`, later
  `MVA70018CG`); Philips TDA1543 16-bit DAC; 40.960 MHz clock; **no external
  RAM**. Settles VOGONS t=67205; refutes the ESS-chip claim (p628871/p629254).
- **May-1993 Usenet review** (`portable.arj` via VOGONS p628871): PS+ spec sheet
  claims *simultaneous* synth+digitized playback and "9 melodic or 7 melodic and
  4 percussive voices" (non-OPL2 split ⇒ FM is a reimplementation); early BMASTER
  needed XMS/himem.sys and failed under QEMM/EMS; per-title SB/AdLib chart
  (Wolf3D/X-Wing/A-Train full "SB"); $198.95 list.

## Open questions — need a dynamic capture, not more static RE

The DOS `BMASTER` host/device FM division and on-wire FM encoding; exact command
opcodes (native PDIGI API, ADPCM, power up/down, master volume); onboard buffer
depth (bounded: C53 4K-word on-chip RAM, no external RAM); the downloaded-DSP
image *encoding* (ISA known: TMS320C5x; `PDRV*.DAT` payload blobs don't
disassemble cleanly under `unidasm -arch tms320c5x` — mame-tools is installed);
the recording ADC's location; the `0x10` format-modifier bit; and the
load-bearing one for a "better device" — **what in the LPT stack forces
`BMASTER`'s per-title serialization** (Wolf3D mixes FM+PCM; Super Fighter / Duke
Nukem II serialize over LPT yet mix on the same chip via PCMCIA ⇒ `BMASTER`'s
CPU/trap budget or the LPT link, not the silicon) and what a mixed stream looks
like on the wire. The Wolf3D vs Duke II capture pair is the most diagnostic
single experiment; the Sony PRD-155SB drivers are a second protocol source.

**Resolve via** a logic-analyzer LPT capture (detection / PCM tone / FM-only /
mixed) or iterative bring-up (guide §13). Caveat: stock DOSBox / DOSBox-X do **not**
emulate a DS301 on the LPT port, so a bare trace dies at the probe — use
real-hardware passthrough or a stub responder that satisfies detection.

## Methodology lesson

In `BMASTER`'s obfuscated 32-bit VCPI code, address-pattern greps give false
positives — a promising "synthesis-table reference" at `0xe600` was actually
`mov al,[0x15xx]; out 0x0a/0b/0c` (8237 DMA emulation), not a table lookup.
Second instance: a table peaking at `0x7FFF` was long described as a "16-bit
sine" (implying host synthesis); shape analysis shows an exponential **antilog**
curve saturating at `0x7FFF` — a level table. All FM data shared between
`BMASTER` and `DS301.DRV` is MIDI/AdLib→OPL *translation* material (operator
offset map, patch bytes, 2^(1/32) pitch table, antilog); no waveform table
exists anywhere in the stack, incl. the `PDRV*.DAT`/`DS301.DAT` payloads.
**Disassemble / verify raw bytes and table *shapes* before trusting a pattern
grep or a peak value.**

## Constraints (keep for any future work)

- **Royalty-free / patent-expired algorithms only** — a compatible device/driver
  must be buildable free and open-source.
- **No verbatim** reproduction of the manual or binary text — state facts in your
  own words (facts and interfaces are not copyrightable).
- **Prioritize playback** (DOS-game / Windows-app PCM + ADPCM + FM) over recording.
