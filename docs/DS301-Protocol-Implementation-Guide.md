# Digispeech / Port·Able Sound (DS301) — Parallel-Port Protocol Implementation Guide

*Clean-room, language-agnostic description of how the Digispeech "Port·Able Sound
Plus" / "Digispeech Plus" family (chip **DS301**; models DS301A / DS311 / DS311A;
generalized driver family "DS3XX") talks to a host over the parallel port.
Recovered by static reverse-engineering of the DOS, Windows 3.1, and Windows 95
drivers and cross-checked against the manufacturer's manual. It describes behavior,
not ported code, and reproduces no source/binary/manual text verbatim.*

**Confidence markers:** **[O]** observed (read directly, ≥2 binaries or the
manual); **[I]** inferred; **[?]** open (not resolved by static analysis).

**Royalty-free rule (whole document):** every algorithm recommended here is
royalty-free or long patent-expired; do not introduce any patent-encumbered method.
A goal is that a fully free/open-source implementation can be built from this guide.

---

## 1. Device model

The DS301 is an external **programmable DSP + audio codec** hanging off the PC
**parallel (LPT) port**, externally powered (9 V adapter, or through the
speaker/battery unit of the "Plus" bundle — the RJ-45 on the board is that
proprietary speaker-unit link). It is *not* a Covox/Disney-class
one-way DAC: it is bidirectional (records), raises IRQs, accepts downloaded DSP
code, and plays from an onboard buffer under flow control. Think "small sound card on
an LPT bus." It reports both a DSP and an ASIC version.

**Board-level identification** (DS301 MAIN UNIT rev 0.4 photos, Jan 1993 — posted
on [VOGONS](https://www.vogons.org/viewtopic.php?p=427977#p427977), attachments
recovered from archive.org): the "DS301" chip is a **custom-mask TI
TMS320C53** 16-bit fixed-point DSP (marked `D32053FNL / DS301`, date code wk50/1992;
C5x family: 16K-word mask ROM + 4K-word on-chip RAM), clocked by a **40.960 MHz**
crystal. The companion "GPS" chip is a **GEC Plessey Semiconductors semi-custom gate
array** — `CLA74022CG` on this early board, `MVA70018CG` on later DS311/DS103J
units — the LPT front-end / DSP-host glue [I role]. Playback runs through a
**Philips TDA1543** dual 16-bit DAC; a 74HC4053 analog mux fits the output-routing
mixer modes of §8.3 [I]; a MAX758 buck regulator derives 5 V from the 9 V input.
**There is no external RAM**: downloaded code and audio buffers must fit the C53's
4K-word on-chip RAM — bounding the onboard buffer depth (§13) and matching the 4 KB
streaming block (§5) and the tiny ≤`0x79`-word download records. No discrete ADC is
visible; recording likely digitizes inside the gate array or via the DSP's serial
port [?] — a 1997 FAQ's claim that recording is "14-bit" points at a TI AIC-class
converter (TLC3204x family: 14-bit, the standard C5x companion) [I]. This settles two community disputes: the chips are *not* ESS parts, and
the DSP is exactly the "TMS32053" once guessed on VOGONS. The same chip set shipped
in at least two more form factors (VOGONS teardowns): the **Sony PRD-155SB PCMCIA**
card (a real SB-register interface — see §8.3) and the **DS103J** combo
sound+network card. (The earlier serial **DS201/DS201A** is a different generation,
out of scope here beyond PDIGI back-compat (§8.5) — no FM; it reportedly offers a
PCjr/Tandy-style three-voice SN76496-like tone generator, noise channel not
emulated.)

### 1.1 Hardware vs. host software

| Capability | Where | Conf. |
|---|---|---|
| PCM playback 8/16-bit, mono/stereo, ≤44.1 kHz | Device DAC | O |
| PCM recording (ADC), mono, 8/11 kHz | Device | O |
| FM synthesis (OPL2-*functional*, ~11-voice, no OPL chip) | **Device DSP firmware**; host forwards OPL register writes | O (manual) |
| MIDI (Win `MODMESSAGE`; DOS XMIDI via `PDRVXM`) | Host → same emulated-FM path as AdLib | O |
| Sound Blaster *digitized* emulation | Host traps SB ports → streams PCM to device | O |
| Codecs: µ/A-law, SB/OKI/DVI/MS-ADPCM, CVSD | Device DSP (decode/encode) | O names / ? wire |
| Speech coders: LPC ("LPC10" in binaries) & CELP **playback-only**, RELP record+playback (manual §E); LPC vocabulary | Device DSP | O / ? wire |
| Text-to-speech (First Byte engine) | Host text→phoneme; device synth | O / ? wire |
| Native "Digispeech" API (`PDIGI`+`PDRV*.DAT`) | Host driver, same LPT protocol | O / ? opcodes |

**Key constraint:** the device mixes FM/synth music and digitized PCM **only in
mono** (its output mixer is *either* stereo-digital, *or* mono-synth + mono-digital,
each plus stereo line-in). So **16-bit stereo PCM and FM cannot play together**, and
in practice the DOS stack often serializes the two. §8.3 details this; §10 lifts it.

### 1.2 Software stacks (all speak the same wire protocol)

- `DS301.SYS` / `DS3XX.SYS` — DOS char driver (IBM **AUDIODD** interface, device
  name `AUDIO$`). Cleanest view of the raw protocol.
- `PDIGI.EXE` + `PDRV*.DAT`, `SOUND301.EXE`, `DIGIPLAY`/`DIGIREC` — native Digispeech
  audio and First-Byte apps.
- `DS301.DRV`/`DS3XX.DRV` + `VDS301.386`/`VDS3XX.386` — Windows 3.1/95 multimedia
  driver (Wave/MIDI/Mixer/Aux) and its VxD.
- `BMASTER.EXE` — DOS Sound Blaster / AdLib emulator (VCPI protected-mode TSR).

Agreement across these independently-written paths is why the protocol can be stated
with confidence.

### 1.3 Epistemic status

The protocol **mechanics** (register model, primitives, decode tables, detection,
SPP-only transport, IRQ pacing, PIT calibration, and the mono-only mixing rule) are
solid — read directly and corroborated by the manual and hardware demos. The
**forward-looking design claims** in §10 — chiefly that a new device can do *flawless*
simultaneous FM+PCM while staying *fully* compatible with the original software — are
now **supported but not fully proven**: the same DS301 silicon demonstrably mixes
FM+PCM for the very titles that serialize over LPT when driven through a PCMCIA
SB-register interface (§8.3), so the limit is in the LPT stack, not the chip. Still
validate over the LPT transport itself (bus capture or iterative bring-up, §13)
before relying on them. The binding unknown has narrowed to: is it `BMASTER`'s
CPU/trap budget or the LPT link that forces serialization, and what does a mixed
stream look like on the wire.

---

## 2. Parallel-port register model

Three **standard SPP registers** only — no EPP/ECP anywhere (verified across all
binaries). `BASE` = data port (LPT1 `0x378`, LPT2 `0x278`, LPT3 `0x3BC`; discovered
at runtime, §4).

| Reg | Addr | Dir | DS301 use |
|---|---|---|---|
| Data | `BASE+0` | write (read in nibble mode) | D0–D7 |
| Status | `BASE+1` | read | b7 /BUSY(inv), b6 ACK, b5 PAPER-OUT, b4 SELECT, b3 ERROR |
| Control | `BASE+2` | write | b0 STROBE(inv), b1 AUTOFEED(inv), b2 INIT, b3 SELECT-IN(inv), b4 IRQ-en |

Data sends bytes; Control clocks them (STROBE) and holds the transfer state; **four**
of the five Status inputs (b3/b4/b5/b7) carry data *back* (nibble mode) while b6
(ACK) is the handshake/interrupt line — the decode tables in §3.2 treat it as a
don't-care. **A compatible reimplementation must treat SPP register bit-banging as
the sole required transport.**

---

## 3. The two core primitives

### 3.1 write-word (host → device) [O — identical in `DS301.SYS`, `DS301.DRV`, VxD]

Sends one 16-bit word (used for commands *and* sample data):

```
write DATA    = low_byte
write CONTROL = 0x0E        ; transfer state, STROBE bit clear (idle)
wait  Δ1
write CONTROL = 0x0F        ; set STROBE bit → latch low byte
wait  Δ2
write DATA    = high_byte
wait  Δ3
write CONTROL = 0x0E        ; clear STROBE bit → latch high byte
```

STROBE (Control b0) is the write clock; a word is two byte-latches (low when the
STROBE bit sets, high when it clears). **Register vs. pin polarity** (matters to a
device implementer): Control b0/b1/b3 are inverted by the port hardware, b2 is not.
So `0x0E` puts the connector at /STROBE **high** (idle), /AUTOFD low, /INIT high
(inactive — not resetting), /SELECTIN low; writing `0x0F` drives the /STROBE **pin
low**. On the wire the low byte therefore latches on the *falling* edge of /STROBE
and the high byte on its *rising* edge. The
**low control nibble is a stream/sub-command selector** carried alongside the strobe:
`0x0E` base for sample data, a "+6" variant for command words, "+0xC/+0xD" to switch
to read mode. The Δ delays pace the host to the device's word-acceptance rate and are
CPU-calibrated (§6).

### 3.2 nibble-read (device → host) [O — `DS301.SYS` @`0x40c0`/`0x416c`, +DRV/VxD]

The device returns data over the Status lines (four data lines + ACK, §2), one
nibble per select:

```
for n in 0,1,2,3:
    write DATA = n            ; select which nibble to present
    wait Δ
    s = read STATUS
    v = s >> 3               ; b3(ERROR)→b0, b4..b7 → b1..b4
    nibble = TABLE[v]        ; low table for even n, high table for odd n
assemble 4 nibbles → 16-bit word
```

Two 32-entry tables (image `[0x2f4]` low, `[0x314]` high) map the aligned status value
to a nibble — these fix exactly which status line carries which returned bit:

```
LOW  (index (status>>3)&0x1f):
 01 09 05 0d 03 0b 07 0f 01 09 05 0d 03 0b 07 0f
 00 08 04 0c 02 0a 06 0e 00 08 04 0c 02 0a 06 0e
HIGH = LOW << 4:
 10 90 50 d0 30 b0 70 f0 10 90 50 d0 30 b0 70 f0
 00 80 40 c0 20 a0 60 e0 00 80 40 c0 20 a0 60 e0
```

The tables' structure is self-consistent with the port hardware: index bit 3
(Status b6, ACK) is a don't-care (both 8-entry halves repeat), so ACK carries no
data — it is the handshake/IRQ line; and output bit 0 is the *inverse* of index
bit 4 (Status b7), matching BUSY's hardware inversion. Returned data rides on
status lines b3/b4/b5/b7 only. The same two tables appear byte-identical in
`BMASTER.EXE`, `DGSETUP.EXE`, and `PDIGI.EXE` (file offsets `0xea88`, `0xedb9`,
`0x69ee`) — four independently shipped binaries agree.

---

## 4. Detection, initialization, IRQ

**Port discovery [O @`0x59bc`/`0x545c`]:** read candidate LPT bases from the BIOS
Data Area (`0040:0008`, four words), validate against legal ranges, set
DATA/STATUS/CONTROL = BASE/+1/+2, then probe.

**Probe = echo test [O @`0x439c`/`0x54c6`]:** a short knock/wake sequence (writes of
`0xF0F0`, `0x0F0F`, rolling values), then echo probes — write `0xAAAA`, `0x5555`,
`0x0F0F`, `0xF0F0` via write-word and read each back via nibble-read; a device is
present iff every pattern echoes bit-exact. **A compatible device must therefore
implement a loopback.**

**IRQ [O @`0x6154`]:** playback/record are interrupt-paced. The IRQ is the *host LPT
port's* interrupt (conventionally LPT1→IRQ7, LPT2→IRQ5), **not a device setting** —
the device drives ACK and the port hardware raises the IRQ. Driver enables Control b4,
unmasks the 8259 (`0x21`/`0xA1`), EOIs to `0x20`/`0xA0`. A compatible device assumes
no IRQ number; a driver can fall back to polling the status line (§6, §10).

Manual-confirmed resources: I/O `278–27B` / `378–37B` / `3BC–3BE`; IRQ5 or IRQ7; **no
DMA, no memory** used. There are also **power-down/up commands** (the host parks the
device when idle and wakes it to resume) — a compatible device/driver should implement
them (encoding [?]).

---

## 5. Command / format layer

Above the word channel the driver sends structured messages. The playback command
[O @`0x1c40`] carries: format code, buffer base, rate parameter, block size `0x1000`
(4 KB streaming granularity), length. It is shipped word-by-word with the command
control-nibble ("+6"). A separate **download** message class writes to addressable
device memory. The stream [O — routine fully disassembled @`0x4526`] is a list of
records `{u16 targetAddr, u16 lenWords, data[lenWords]}`, terminated by
`addr=0xFFFF,len=0`; `targetAddr ≥ 0xFF00` is a directive (the loader adds `0x300`,
so `0xFF00` → device address `0x200`). Each record is split into sub-blocks of
**≤0x79 words**; the per-block device header carries `targetAddr`, `len−1`, a bank
toggle, and a marker word = **`0xCE01` on the first sub-block of a record, `0` on
continuations** — i.e. `0xCE01` means "start of a new download record", not a fixed
file signature. Unlike the open-loop *audio* write path, the download path is
**closed-loop**: after each block it drives a status handshake and a read-back
verify loop (nibble-read, §3.2) — a compatible device must ack these.

The target DSP is a masked **TMS320C53** (§1), so payloads are C5x code and/or
coefficient/parameter data at C53 on-chip addresses. But the payload bytes are
**not recoverable statically**: they are dense, high-entropy, non-plaintext, and
**not a standard compression format** [O — tested a 19 KB payload against
gzip/zlib/deflate/lzma/bz2, DOS-era PKZIP/LHA/ARJ/LZEXE/PKLITE, and the device's
own EDILZSS1 LZSS: no header, nothing decodes, incompressible]. Whether they are
custom-packed, enciphered, or simply a dense data table is undetermined from the
bytes alone; the unpacker (if any) lives in the C53's on-die mask ROM. The
`PDRV*.DAT` files themselves are MZ-framed **x86** overlays whose code disassembles
normally — only these embedded payload blobs are opaque. Note a parallel-port bus
capture does **not** help here: the payload crosses the wire in exactly this stored
form, so a capture only reproduces bytes we already have; interpreting them needs the
C53 mask-ROM contents (decap/ROM readout) or vendor materials. Either way this is a
*nice-to-have*, not a prerequisite for a compatible device (see §10).

**Format codes [O — classifier disassembled @`0x1e74`–`0x1f5c`]:** mono `0x00`
8-bit linear, `0x01` µ-law, `0x02` A-law, `0x03` 16-bit linear; stereo (bit `0x40`)
`0x48` 16-bit linear, `0x49` 8-bit linear, `0x4A` µ-law — exactly the manual's three
stereo formats. The classifier also keeps a codec-family side variable (0 = linear,
1 = µ-law, 2 = A-law) and ORs in a modifier bit `0x10` when two further request
fields match a sub-mode (what it selects [I]). Manual rates: **stereo** 8/16-bit (or
8-bit µ-law) at 11.025/22.05/44.1 kHz; **mono** 8-bit lin/µ/A-law or 16-bit lin,
4 kHz–44.1 kHz. The manual also specs **effective bandwidth**: playback 16 kHz,
recording 3.4 kHz — the analog path is band-limited well below the maximum sample
rates (recording is telephone-band), which sets realistic fidelity expectations for
any emulator or replacement device. Corroboration and a likely mechanism: a hardware
demo ([VWestlife](https://www.youtube.com/watch?v=t7VxWbCgWHk)) measured 44.1 kHz
playback lowpass-filtered at ~13 kHz and suspected internal downsampling (while
crediting the device for having a proper anti-aliasing filter at all); and from the
40.960 MHz master clock, 8/16/32 kHz divide exactly while 44.1 kHz does not. So the
device plausibly **resamples high rates to an exact-divisor internal rate**, making
"44.1 kHz" a transport-format claim rather than a DAC-clock claim [I].

---

## 6. Timing and calibration

- Δ delays are busy-wait loops **calibrated by `DGSETUP.EXE` using a PIT channel-2
  stopwatch** (program `0x43`, gate `0x61`, count the fixed 1.193182 MHz timer — not
  cycle-counting) [O @`0x49c4`]. Because the PIT frequency is fixed, the delays are
  correct in real time on *any* CPU, so raw CPU speed does **not** break it; re-run
  `DGSETUP` after a speed change. The calibration result is stored as `SD1=`…`SD4=`
  (four delay constants) in `DGSPEECH.INI`, alongside `Port`, `IRQ` and `Sync`
  [O — v4.05 default INI]. The mechanism survived unchanged into the final 1996
  release: the v4.05 `DS3XX.SYS` write path still uses the same memory-loaded
  `loop` busy-waits and no driver in the family touches the PIT at play time — so
  calibration handles any *static* CPU speed (which is why Win95-era drivers could
  ship without a redesign), and only *changing* speed after calibration (turbo
  toggles, moving the unit to another machine) breaks it until recalibration.
- Playback pacing is **IRQ-driven** (device asks for the next block); Δ governs
  transfer speed, the IRQ governs audio timing.
- **The write path is open-loop** — it never polls a BUSY/ACK line, just waits the
  calibrated delay [O — no `IN` in the write path]. Field corroboration (a period
  owner, in the VWestlife video's comments): the unit was "very speed sensitive" —
  turbo switches broke it, and after moving from an 8088 to a 386 his previously
  recorded files *played back at the wrong pitch*, implying the effective sample
  rate is host-paced in at least some paths [I]. This is the main fragility on
  later hardware; risks are: uncalibrated port latency; **USB→parallel adapters don't
  expose register-level SPP** (they emulate the printer protocol) so bit-banging
  fails; and dependence on a working LPT **IRQ**. The Disney Sound Source survives
  modern PCs because it is *closed-loop* (a FIFO-full status flag) — the lesson a
  better device (§10) should copy, all within plain SPP.

**Portability:** Δ constants are host+device specific and must be re-derived; a
compatible device should expose or document its max word rate.

---

## 7. Playback, recording, download

**Playback:** detect/init → (download DSP firmware if the mode needs it) → send play
command → stream sample words with the sample-data nibble in contiguous ~4 KB blocks
[O block-writer @`0x3ede`] → refill on each device IRQ (driver tracks play vs. write
position) [O ISR @`0x4cc6`]. Stereo/16-bit only changes the format code and
bytes-per-frame.

**Recording (secondary):** put the device in capture mode, then read 16-bit words
with the nibble-read primitive, IRQ-paced [O @`0x416c`]. Manual: **mono only**, 8 kHz
& 11.025 kHz, 8/16-bit lin/µ/A-law or DVI/OKI/SB-ADPCM. (The Windows Sound Station
UI offers 22.05 kHz/16-bit recording, but in the LGR footage that setting silently
reverted to 11.025 kHz/3-bit ADPCM before recording — viewer frame analysis — so
nothing observed contradicts the manual's recording rates. A May-1993 Usenet
reviewer likewise found no stereo recording and nothing above 11.025 kHz exposed.)
The ceiling rose with software: the v4.05-era drivers "record now at 22 Khz instead
of 11 Khz" (1997 [mini-FAQ](https://www.newtale.com/pp/article215.html)) — so the
22.05 kHz option in the Windows Sound Station UI was real v4.x capability. The same
FAQ says recording "only at 14-bit" — plausibly the converter's true resolution
behind the 16-bit data format, matching TI's 14-bit AIC codec family (TLC3204x),
the standard C5x companion [I → §1, §13].

---

## 8. Sound Blaster / AdLib / MIDI and the mono mixer

### 8.1 SB digitized emulation (DOS `BMASTER`)

VCPI 386 protected-mode TSR. Installs V86 **I/O-port traps** on the SB DSP ports
(`0x22x`), AdLib ports (`0x388/0x389`), and PIC (`0x20/0x21`, to virtualize the SB
IRQ) [O — `bts` trap bitmap; per-port handler table `[0x400+port*4]`, `0x388→0x141c`,
`0x389→0x142c`]. It reconstructs the intended PCM and streams it to the device. (A 386
+ EMM/VCPI is required to *trap* ports in V86 mode — independent of synthesis cost.)
Period usage constraints (May-1993 Usenet review of the shipping product, preserved
as `portable.arj` on [VOGONS](https://www.vogons.org/viewtopic.php?p=628871#p628871)):
BMASTER demanded **XMS/himem.sys and failed under
QEMM/EMS** (another v2.0 owner reports it accepting EMS *or* XMS — driver builds
differed — and that the resident portion lives in extended memory, using almost no
conventional RAM); DMA-driven titles (demos, MOD players) usually failed; and the
workaround for EMS-needing games was a Windows 386-enhanced DOS box, where the
**VxD** provides the trap layer with a configurable virtual SB/AdLib/none
personality and virtual address/IRQ/DMA settings. Under Windows 95 that same VxD
path even covers **DOS-extender games**: a 1997
[mini-FAQ](https://www.newtale.com/pp/article215.html) reports Doom running "with
music and sound" in a Win95 DOS box — coverage `BMASTER` never had (§10.4). Resolution [O — strings in both
builds]: BMASTER (self-identified "ABLE Sound" **V2.00** in 1993 → **V2.07** in the
final 1996 release) is **VCPI-aware by design** — it diagnoses "unknown VCPI
version" and warns about old EMM386 builds — so it runs under an EMM's VCPI or on
a himem-only setup; the 1993 QEMM failure was a version quirk, not an XMS-only
design. The virtual-SB parameters live in `DGSPEECH.INI` (`[Blaster Master]`:
`VsbBase`/`VsbIRQ`/`VsbDMA`).

### 8.2 AdLib/FM and MIDI

The AdLib handlers latch the OPL register/data into a host shadow (`~0x1670`) rather
than forwarding each write live [O]. The FM-related data `BMASTER` carries — shared
byte-identically with `DS301.DRV` in five regions [O — e.g. `BMASTER` `0xe750` =
DRV raw `0x7b96`] — is a **translation layer, not a synthesizer**: an OPL
operator-offset map (`00–05`/`08–0D`/`10–15`), OPL patch/level byte tables, an
exponential pitch table (step ratio 2^(1/32), i.e. MIDI note+bend → F-number math),
and an exponential level table saturating at `0x7FFF`. (An earlier pass read that
last table as a "16-bit sine peaking `0x7FFF`" — shape analysis shows it is an
antilog curve, not a waveform.) **No waveform table exists anywhere in the stack**
— `BMASTER.EXE` + its overlays, `DS301.DRV`, `VDS301.386`, `DS301.SYS`, and the
`PDRV*.DAT`/`DS301.DAT` download payloads were all scanned — and no per-sample
render loop has been identified. The static evidence therefore agrees with the
manual: the hosts do **parameter math and register-level FM programming only**, and
the **device** synthesizes on the TMS320C53 (OPL2-functional, no discrete OPL chip).
On voice counts: the Digispeech Plus manual says "11-voice OPL2"; the earlier
Port·Able Sound Plus spec sheet says "**9 melodic or 7 melodic and 4 percussive
voices**" — note the 7+4 split differs from a real OPL2's rhythm mode (6 melodic +
5 percussion), marking the FM engine as a *functional reimplementation*, not a
register-exact OPL2 — consistent with its audibly dropped instruments (e.g. in
CANYON.MID). Exactly how much
`BMASTER` processes host-side before handing off is **[?]**, but now bounded:
parameter translation yes, waveform generation no. **MIDI** uses the same
emulated-FM path: `DS301.DRV` is the MIDI driver (`MODMESSAGE`) and shares those
translation tables with `BMASTER`; DOS MIDI comes via the `PDRVXM` (XMIDI) overlay.
MIDI therefore inherits FM's limits (dropped instruments) and the mono-mix rule.

### 8.3 The mono-mixer rule (why FM+stereo-PCM don't coexist)

The device's output mixer offers **either** stereo digital + line-in **or** mono
synth + mono digital + line-in (manual). So FM/synth mixes with PCM **only in mono**;
*stereo* 16-bit PCM + FM is not a supported combination. A 1997 power-user
[mini-FAQ](https://www.newtale.com/pp/article215.html) quantifies the bound: with
mixing active you get "8 bit 22Khz sound and Adlib music at the same time", while
16-bit sound excludes AdLib — i.e. the wave+synth mix path caps the digitized
stream at **8-bit/22 kHz**. That also explains the audible quality drop LGR noted
when toggling Mix Wave/Synth (not just level attenuation).

**Field behavior (LGR DS311 footage):** under DOS `BMASTER`, Wolfenstein 3D plays FM
music and digitized SFX *simultaneously*, while Super Fighter and Duke Nukem II
audibly **serialize** (music suspends whenever a sample plays). The Wolf3D
observation is triply sourced: LGR's DS311 audio, a 1993 reviewer's "works
completely with music and speech/sound effects" chart entry (§8.1's `portable.arj`
source), and a [2016 DS301A install video](https://youtu.be/9r6t-c7q-94)
demonstrating the same on a 486 laptop under the v2.0 stack. All three are mono
AdLib+SB titles, so mono-vs-stereo alone does not decide it — the differentiator is
unknown [?]; Duke II's ADPCM-coded SFX and per-title SB-DSP usage patterns are the
prime suspects, which makes a Wolf3D-vs-Duke II capture the single most diagnostic
experiment (§13).

**Counter-experiment (VOGONS, Bondi 2021):** the Sony PRD-155SB PCMCIA card is built
on the *same DS301 chip* behind a real SB-register interface, and there Duke Nukem II
and Super Fighter — the very titles that serialize over LPT — play music and
digitized effects together with no interruptions. So the serialization is a property
of the **LPT stack** (the `BMASTER` trap/reconstruct layer and/or the LPT transport
budget), **not of the DS301 silicon** — consistent with Wolf3D managing to mix under
`BMASTER` when the pipeline keeps up. (Xargon lacked digitized SFX on the PCMCIA card
too — a game-side quirk, not a Digispeech one.) This is the strongest evidence for
§10's premise that a compatible device/driver can lift the limits.

Under Windows, wave+synth play together only with the opt-in
**Mix Wave/Synth** setting; a listener report that enabling it drops both streams'
volume by ~half is simply headroom management ("halve and add") and does not say
*where* the sum happens — attenuate-and-sum is as natural on the device DSP as in
host software. The likelier reading is the **device's own mono mixer**: the manual
puts the FM engine on the device, DOS `BMASTER` already uses it there, a
Win3.x-era CPU has little headroom for a second, software FM synth — and §8.2's
static finding that the Windows driver contains only FM *translation* tables (no
waveform data, no render loop) actively supports it. Host pre-mixing
remains formally unexcluded [?]; the two are trivially distinguishable on the wire
(host pre-mix ⇒ FM register traffic replaced by one PCM stream in mix mode; device
mix ⇒ both keep flowing).

**Period corroboration:** the manufacturer's own Port·Able Sound Plus spec sheet
claims "**simultaneous synthesized music and digitized audio playback**", and the
May-1993 Usenet review's compatibility chart (same `portable.arj` source, §8.1) shows full
music+SFX operation ("SB") for Wolfenstein 3D, A-Train, The Incredible Machine,
Kaeon and X-Wing, while other titles ran AdLib-only or broke — so mixing worked for
many titles on the day-one stack, and the per-title split was visible from the
start. The same review notes the stereo **line-in is an always-on analog
mix-through** to line-out/speaker (CD-audio mixing use case), matching the mixer
model's "plus stereo line-in" path.

A *separate* limit (v4.00 docs): **full-duplex play+record** requires
wave/synth mixing **off** — i.e. the device has a small fixed number of simultaneous
audio paths. The manual also specs a **master volume control** (0–94.5 dB range),
i.e. a host-settable volume command (encoding [?]).

### 8.4 Playback formats — prioritized for DOS games / Windows apps

1. **8-bit mono PCM** — the common SB case; get this right first.
2. **16-bit and/or stereo PCM.**
3. **SB-ADPCM (4 / 2.6 / 2-bit)** — required by some DOS games (e.g. Duke Nukem II).
   Cleanest handling: **decode SB-ADPCM → PCM in the host SB-emulation layer** and feed
   the device PCM; the device then needs only its PCM path. (The device DSP *can* also
   decode ADPCM; whether original `BMASTER` decodes host-side or on-device is [?].)
4. **AdLib FM + MIDI** for music (§8.2).

Also present but not game-critical (recording/telephony/speech): µ-law, A-law, OKI &
DVI/Intel ADPCM, Microsoft ADPCM, CVSD, and speech coders RELP/CELP/LPC10 — device DSP
capabilities [O names], wire encodings [?]. Manual §E: LPC and CELP are
**playback-only**; RELP does record **and** playback.

### 8.5 Native "Digispeech" API and speech

`PDIGI` is a resident loader for overlay drivers `PDRVA..E` (codec personalities),
`PDRVTD` (tone), `PDRVXM` (XMIDI), configured via `DGSPEECH.INI`. It uses the same LPT
protocol (opcodes [?]) and back-supports the serial DS201. Period materials also
advertise compatibility with **IBM Speech Adapter** software (needs additional
drivers that the LGR demo could not locate) — presumably one more host-driver
personality over the same wire [?]. **LPC speech** (the flagship
"Digispeech" capability) sends low-bandwidth LPC/CELP parameters the device vocodes
(~1.1 kbps). **TTS** (First Byte engine, `DOSREAD`/`DOSTALK`, dictionary/rules) is a
host text→phoneme pipeline driving the device synth. Engine file roles [I — from
structure]: `V*ENG*.PCM` = voice sample data; `V*ENG*.DMI` = DSP *data*-memory
images (constant tables, `0xFFFF` fills, header carries the engine sample rate);
`V*ENG*.INS` = index tables (6-byte records with monotonically increasing
addresses, `0xFFFF` group separators) — none are plainly-encoded C5x instruction
streams. These are characterized, not
reverse-engineered to the wire; lower priority than PCM playback.

---

## 9. Portability: device-specific vs. generic

- **Generic SPP conventions:** the register model, STROBE-clocked writes, nibble
  read-back over status lines.
- **DS301-specific, must match exactly:** the `0x0E` transfer state and low-nibble
  stream selector; two-bytes-per-word STROBE latching; the nibble decode tables; the
  echo-test patterns/order; the format codes; the command/download message shapes; the
  IRQ flow-control model.
- **Host/CPU-specific, must be re-derived:** every Δ delay constant.

---

## 10. Building a compatible / better device

The FM+stereo-PCM and serialization limits live in the **device firmware and driver
choices, not the wire** — the transfer layer is a general word channel. So a clean-room
device can stay detectable/drivable by the original software yet remove the limits.
*(Backed by the PCMCIA counter-experiment, §8.3 — the same chip mixes when driven
over a different bus; final validation over the LPT transport per §1.3/§13.)*

### 10.1 SPP is the baseline; EPP/ECP is optional

Depend only on plain SPP (what every original driver emits). Get **robustness** from a
**closed-loop SPP handshake** — a device-driven BUSY/ready flag the host polls
(DSS-style) plus an IRQ-optional refill path — which removes the open-loop timing
fragility entirely, no advanced port mode needed. Offer EPP/ECP only as an
auto-negotiated bonus for new drivers where it demonstrably cuts host CPU; never
require it; keep SPP fully functional.

### 10.2 Minimum-viable subset (run the original DOS/Windows software)

In dependency order:

1. **SPP core** — write-word + nibble-read with the exact tables.
2. **Detection loopback** — echo the probe patterns bit-exact. *(Most important; nothing
   proceeds without it.)*
3. **IRQ/handshake** — drive ACK for the LPT IRQ, or support polling.
4. **PCM playback** — 8-bit mono minimum; add 16-bit/stereo for coverage.
5. **SB-ADPCM** — decode in the SB-emulation/host layer → PCM (device may need PCM
   only; if interoperating with unmodified `BMASTER`, capture to see whether it
   forwards coded data, §13).
6. **FM** — accept AdLib/SB OPL register programming and synthesize. On **Picovox**
   (RP2350 + PIO, already emulating DSS/OPL2LPT/Covox), reuse the existing OPL2LPT core
   as the FM engine — DS301 support is a new protocol personality on infrastructure it
   already has, and a fast MCU latches whatever the host bit-bangs (the "host too fast"
   failure mode vanishes).
7. **Mono synth+PCM mixing** — matches the original.
8. **Download-record handling** — accept the `{addr,len,data}` records (§5) and
   **satisfy the closed-loop read-back verify** the driver runs after each block
   (echo the written words, as detection does), then **discard the payload
   content**. A clean-room device on different silicon (e.g. Picovox) does *not*
   execute the TMS320C5x blob — it reimplements the mode the download selects
   (stereo path, a codec, a speech engine) natively, keyed off the format/command
   codes. The blob is opaque and irrelevant (§5); only the framing + handshake
   must be honoured so the original software believes the install succeeded.

Not required: recording, stereo-synth mixing, the speech/LPC codecs and native `PDIGI`
API, the telephony codecs, and **decoding the downloaded DSP firmware** (§5 — you
acknowledge it, you don't run it). Bring-up order: detection → 8-bit mono tone → 16-bit/stereo
→ FM → mono mix → (only for unmodified `BMASTER`) coded-data handling. The SPP
mechanics and PCM streaming *shape* are known; exact higher-level command opcodes
(FM forwarding, format select, power) are **[?]** — recover by capture (§13).

### 10.3 Superset mode: stereo-16 PCM *with* OPL3 (opt-in, not backward-compatible)

An extended, opt-in "second personality" (legacy mode still serves the original
drivers). Reached via an identity handshake the original drivers never issue.

- **Targets:** concurrent up-to-16-bit-stereo PCM **+ OPL3** FM (18-voice/4-op), summed
  in a stereo mix on-device (or pre-mixed by an emulator); optional ADPCM decode across
  the SB…SB16 lineage (Creative 4/2.6/2-bit + IMA/DVI 4-bit); optional richer
  mixer/line-in.
- **Transport:** plain SPP required. Even 44.1k/16/stereo raw is reachable over SPP on a
  fast host (CPU-bound, not beyond the wire — the original has no EPP/ECP and still
  claims those rates). EPP/ECP only where it clearly helps.
- **Device-side efficiency (pure SPP, low latency):** a **few-ms FIFO + autonomous
  sample clock** (≈4–8 ms ≈ 0.7–1.4 KB at 44.1k/16/stereo — imperceptible), and a
  **status-line "room in FIFO" flag** so the host bursts flat-out and self-paces with
  no fixed delays. These cut host CPU and kill the timing fragility.
- **On-the-fly compression for 386/486 hosts (royalty-free):** send fewer bytes so the
  host bit-bangs less. **G.711 µ-law/A-law (2:1)** — table lookup, essentially free;
  **IMA/DVI ADPCM (4:1)** — predictor + step table, ~a dozen ops/sample, real-time on a
  386, and it *is* the SB16's compressed family. Encode cost is far below the bit-bang
  time saved. Expose both PCM and compressed; the device decodes. Do not use any
  currently patent-encumbered codec (heavyweight perceptual codecs are also far too
  costly for period CPUs and unnecessary).

Patents (guidance, not legal advice): FM synthesis, G.711, and IMA/DVI ADPCM are
royalty-free / patent-expired; verify current status for your product.

### 10.4 Modern Sound Blaster emulator backend (SBEMU / VSBHDA-style)

`BMASTER` fails on protected-mode / DOS-extender games. A modern emulator traps
SB/AdLib access and does OPL synthesis, SB-DSP emulation, ADPCM decode, and mixing **in
host software**, using the device purely as a **PCM sink**. This sidesteps every device
limitation (the mono-mix and duplex constraints vanish because the host pre-mixes) and
supports protected-mode games. The device-facing surface is tiny: `detect()`,
`set_format(rate,ch,bits)`, `write_block(pcm)`, `on_irq()/poll()`, `close()` — a new
output target alongside their AC'97/HDA backends. Pick a rate the wire sustains and
resample down if needed.

**Startup calibration** (the step that most decides whether a given port works): (1)
express Δ delays in real microseconds via a fixed-frequency clock (PIT ch2 on DOS, any
monotonic timer elsewhere) so timing is CPU-independent; (2) find the device's minimum
safe delay by binary-searching against the echo loopback (require many bit-exact
passes, then back off 25–50%). Prefer a closed-loop handshake if the device offers one.
Bound probes with a timeout; report ports that don't answer at register level (USB
dongles) as unusable.

---

## 11. Quick-start checklist

- [ ] Resolve LPT base (BIOS Data Area `0040:0008`); set DATA/STATUS/CONTROL.
- [ ] Implement **write-word** (§3.1) and **nibble-read** (§3.2) with adjustable Δ.
- [ ] Run **echo detection** (§4): `0xAAAA/0x5555/0x0F0F/0xF0F0`.
- [ ] Calibrate Δ (§10.4).
- [ ] Send a **play command** (§5) with a format code.
- [ ] Stream a tone; refill on **IRQ** (§7).
- [ ] (Optional) recording via nibble-read.
- [ ] (Emulator) wrap as a PCM output backend (§10.4).
- [ ] (Hardware) add FIFO + flow-control + on-device stereo mix (§10).

---

## 12. Evidence appendix (`DS301.SYS` unless noted; offsets into the load image)

The `.SYS` is an MZ file with a `0x200`-byte header, so file offset = image offset
+ `0x200` (e.g. the §3.2 tables: image `0x2f4`/`0x314` = file `0x4f4`/`0x514`).

| What | Where |
|---|---|
| Port vars DATA/STATUS/CONTROL = BASE/+1/+2 | @`0x545c` |
| write-word strobe sequence | @`0x3e9a`; VxD @`0x175c`; DRV: core byte pattern at **raw file** `0x243d` (v2.0 `DS301.DRV`) / `0x6a75` (v4.00 `DS3XX.DRV`), also `BMASTER.EXE` raw `0x210a` — the `.DRV` is an **NE** file `mzdis.py` cannot map, so DRV offsets here are raw-file, not segment-relative |
| Block writer (contiguous `lodsw`/`out`) | @`0x3ede` |
| nibble-read + 32-entry tables `[0x2f4]`/`[0x314]` | @`0x40c0`/`0x416c` |
| Streaming ISR; PIC-mask helper | @`0x4cc6`; @`0x6154` (EOI `0x20`/`0xA0`) |
| Detection echo test | @`0x439c`/`0x54c6` |
| Format classifier; command builder (block size `0x1000`) | @`0x1e74`; @`0x1c40` |
| DSP download: `{addr,len,data}` records, ≤0x79-word sub-blocks, `0xCE01` first-block marker, `0xFF00+` directives, closed-loop verify | @`0x4526` (full routine) |
| Port-range validation | @`0x59bc` |
| `BMASTER` SB/AdLib traps (`bts` bitmap; `[0x400+port*4]`; `0x388→0x141c`) | 32-bit VCPI |
| `DGSETUP` PIT-ch2 calibration | @`0x49c4` |
| Windows `DS301.DRV`/`VDS301.386` same primitives + `MODMESSAGE`; VxD `Install_IO_Handler` traps | — |

---

## 13. Open questions and validation

**Open:** DOS `BMASTER` host/device FM division and on-wire FM encoding (§8.2); command
opcodes for the native API, ADPCM, power, and master volume (§5/§8/§10.2); onboard
buffer depth (now bounded by the C53's 4K-word on-chip RAM, §1); the downloaded-DSP
payload contents — **settled as far as static RE can go** (§5): the download
transport/record format is fully recovered, but the payload bytes are dense,
incompressible, non-plaintext, and not a standard compression format, so the actual
C53 code/data is unrecoverable from the software alone. A parallel-port bus capture
would **not** help (the payload crosses the wire in this same stored form, which we
already hold); the only routes are the C53's on-die mask ROM or vendor materials.
This is *not blocking* for a compatible device (§10) — a clean-room device
reimplements the behaviours a download selects rather than executing the original
bytes; the useful host-side follow-up is only to correlate *which* download record
accompanies *which* mode (stereo/codec/speech), which is visible in the x86 drivers
without decoding the DSP payload. Also open: where the recording ADC
lives (§1; a period "14-bit" recording claim suggests a TI AIC-class converter [I]);
the `0x10` format-modifier bit's meaning
(§5); the IBM Speech Adapter compatibility path (§8.5); and — the load-bearing one for
§10 — **what in the LPT stack forces `BMASTER`'s per-title serialization** (§8.3:
Wolfenstein 3D mixes FM+PCM, Super Fighter / Duke Nukem II serialize over LPT yet
mix on the same chip via PCMCIA — so it's `BMASTER`'s CPU/trap budget or the LPT
link, not the silicon) and what a mixed stream looks like on the wire. A second
protocol source worth mining: the **Sony PRD-155SB PCMCIA** card's drivers talk to
the same chip family over a simpler bus.

**Validate by:** (1) *best* — a logic-analyzer capture of the LPT lines during
detection, a PCM tone, FM-only, and a mixed game — ideally the **Wolf3D vs Duke
Nukem II pair**, since one mixes and one serializes under the same TSR: confirms
timing/buffer depth, shows
whether FM-only puts sparse register writes (device FM) or a PCM stream (host FM) on the
wire, and reveals what triggers serialization. (2) *iterative bring-up* — implement SPP, verify
detection then PCM against the original drivers *before* mixing; then add FM+mixing and
test under both the original stack and a purpose-written driver to separate a device
limit from a host-driver limit.

---

*Provenance & licensing: derived by reverse-engineering the original DOS/Windows
3.x/95 driver and utility binaries, cross-checking the manufacturer manual, and
corroborating against public hardware demonstrations (the LGR Oddware DS311 video,
its viewer reports, and the manufacturer's period materials). Contains
no source/binary code and no verbatim passages from the software or manual; facts,
specs, and interface details (not themselves copyrightable) are stated in the author's
own words. Written so a free, open-source, royalty-free compatible device and driver can
be built from it; every recommended algorithm is royalty-free or patent-expired.
Product/company/trademark names are used only for identification. Do your own
patent/trademark diligence — this is not legal advice.*
