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

The DS301 is an external **programmable DSP + audio codec** (DS301 ASIC, fabricated
by TI) with its own RAM, DAC, ADC, and a hardware interrupt line, hanging off the PC
**parallel (LPT) port** and externally powered (9 V). It is *not* a Covox/Disney-class
one-way DAC: it is bidirectional (records), raises IRQs, accepts downloaded DSP
code, and plays from an onboard buffer under flow control. Think "small sound card on
an LPT bus." It reports both a DSP and an ASIC version.

### 1.1 Hardware vs. host software

| Capability | Where | Conf. |
|---|---|---|
| PCM playback 8/16-bit, mono/stereo, ≤44.1 kHz | Device DAC | O |
| PCM recording (ADC), mono, 8/11 kHz | Device | O |
| FM synthesis (OPL2-*functional*, ~11-voice, no OPL chip) | **Device DSP firmware**; host forwards OPL register writes | O (manual) |
| MIDI (Win `MODMESSAGE`; DOS XMIDI via `PDRVXM`) | Host → same emulated-FM path as AdLib | O |
| Sound Blaster *digitized* emulation | Host traps SB ports → streams PCM to device | O |
| Codecs: µ/A-law, SB/OKI/DVI/MS-ADPCM, CVSD | Device DSP (decode/encode) | O names / ? wire |
| Speech coders RELP, CELP, LPC10; LPC vocabulary | Device DSP | O / ? wire |
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
well-reasoned but **unproven**; validate them (bus capture or iterative bring-up,
§13) before relying on them. The binding unknown is whether the original drivers emit
FM and PCM concurrently or serialize them.

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

Data sends bytes; Control clocks them (STROBE) and holds the transfer state; the five
Status inputs carry data *back* (nibble mode) and the handshake/interrupt. **A
compatible reimplementation must treat SPP register bit-banging as the sole required
transport.**

---

## 3. The two core primitives

### 3.1 write-word (host → device) [O — identical in `DS301.SYS`, `DS301.DRV`, VxD]

Sends one 16-bit word (used for commands *and* sample data):

```
write DATA    = low_byte
write CONTROL = 0x0E        ; AUTOFEED+INIT+SELECT-IN asserted, STROBE idle
wait  Δ1
write CONTROL = 0x0F        ; raise STROBE → latch low byte
wait  Δ2
write DATA    = high_byte
wait  Δ3
write CONTROL = 0x0E        ; drop STROBE → latch high byte
```

STROBE (Control b0) is the write clock; a word is two byte-latches (low on the rising
edge, high on the falling edge). `0x0E` is the transfer-enabled/strobe-idle state. The
**low control nibble is a stream/sub-command selector** carried alongside the strobe:
`0x0E` base for sample data, a "+6" variant for command words, "+0xC/+0xD" to switch
to read mode. The Δ delays pace the host to the device's word-acceptance rate and are
CPU-calibrated (§6).

### 3.2 nibble-read (device → host) [O — `DS301.SYS` @`0x40c0`/`0x416c`, +DRV/VxD]

The device returns data over the five Status lines, one nibble per select:

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
control-nibble ("+6"). A separate **download** message class writes DSP
code/coefficients to addressable device memory: records `{target addr, len ≤ 0x79,
data}` with marker `0xCE01` [O @`0x4526`] — how speech engines etc. are installed
(payload DSP ISA [?]).

**Format codes [O @`0x1e74`]:** `0x00` mono-8, `0x03` mono-16, `0x48` stereo-16,
`0x49` stereo-8, `0x4A` stereo variant; bit `0x40` = stereo (other low/`0x10`/`0x08`
bits select width/sub-mode [I]). Manual rates: **stereo** 8/16-bit (or 8-bit µ-law) at
11.025/22.05/44.1 kHz; **mono** 8-bit lin/µ/A-law or 16-bit lin, 4 kHz–44.1 kHz.

---

## 6. Timing and calibration

- Δ delays are busy-wait loops **calibrated by `DGSETUP.EXE` using a PIT channel-2
  stopwatch** (program `0x43`, gate `0x61`, count the fixed 1.193182 MHz timer — not
  cycle-counting) [O @`0x49c4`]. Because the PIT frequency is fixed, the delays are
  correct in real time on *any* CPU, so raw CPU speed does **not** break it; re-run
  `DGSETUP` after a speed change.
- Playback pacing is **IRQ-driven** (device asks for the next block); Δ governs
  transfer speed, the IRQ governs audio timing.
- **The write path is open-loop** — it never polls a BUSY/ACK line, just waits the
  calibrated delay [O — no `IN` in the write path]. This is the main fragility on
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
& 11.025 kHz, 8/16-bit lin/µ/A-law or DVI/OKI/SB-ADPCM.

---

## 8. Sound Blaster / AdLib / MIDI and the mono mixer

### 8.1 SB digitized emulation (DOS `BMASTER`)

VCPI 386 protected-mode TSR. Installs V86 **I/O-port traps** on the SB DSP ports
(`0x22x`), AdLib ports (`0x388/0x389`), and PIC (`0x20/0x21`, to virtualize the SB
IRQ) [O — `bts` trap bitmap; per-port handler table `[0x400+port*4]`, `0x388→0x141c`,
`0x389→0x142c`]. It reconstructs the intended PCM and streams it to the device. (A 386
+ EMM/VCPI is required to *trap* ports in V86 mode — independent of synthesis cost.)

### 8.2 AdLib/FM and MIDI

The AdLib handlers latch the OPL register/data into a host shadow (`~0x1670`) rather
than forwarding each write live [O]; `BMASTER` also carries synthesis-style tables
(16-bit sine peaking `0x7FFF`, `2^(-n/8)` antilog). The manual attributes the FM
synthesis to the **device** (OPL2-functional, ~11-voice, so no discrete OPL chip), so
the shadow state ultimately drives the device's own FM synth. Exactly how much
`BMASTER` processes host-side before handing off is **[?]**. **MIDI** uses the same
emulated-FM path: `DS301.DRV` is the MIDI driver (`MODMESSAGE`) and carries the same
antilog table as `BMASTER`; DOS MIDI comes via the `PDRVXM` (XMIDI) overlay. MIDI
therefore inherits FM's limits (dropped instruments) and the mono-mix rule.

### 8.3 The mono-mixer rule (why FM+stereo-PCM don't coexist)

The device's output mixer offers **either** stereo digital + line-in **or** mono
synth + mono digital + line-in (manual). So FM/synth mixes with PCM **only in mono**;
*stereo* 16-bit PCM + FM is not a supported combination. This explains the field
behavior: mono games (e.g. Wolfenstein 3D) mix fine, while stereo titles or ones whose
driver path doesn't engage the mono mix mode serialize the two. A *separate* limit
(v4.00 docs): **full-duplex play+record** requires wave/synth mixing **off** — i.e. the
device has a small fixed number of simultaneous audio paths.

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
capabilities [O names], wire encodings [?].

### 8.5 Native "Digispeech" API and speech

`PDIGI` is a resident loader for overlay drivers `PDRVA..E` (codec personalities),
`PDRVTD` (tone), `PDRVXM` (XMIDI), configured via `DGSPEECH.INI`. It uses the same LPT
protocol (opcodes [?]) and back-supports the serial DS201. **LPC speech** (the flagship
"Digispeech" capability) sends low-bandwidth LPC/CELP parameters the device vocodes
(~1.1 kbps). **TTS** (First Byte engine, `DOSREAD`/`DOSTALK`, dictionary/rules) is a
host text→phoneme pipeline driving the device synth. These are characterized, not
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
*(This is a design hypothesis — validate per §1.3/§13.)*

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

Not required: recording, stereo-synth mixing, the speech/LPC codecs and native `PDIGI`
API, the telephony codecs. Bring-up order: detection → 8-bit mono tone → 16-bit/stereo
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
  sample clock** (≈4–8 ms ≈ ~1.5 KB at 44.1k/16/stereo — imperceptible), and a
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

| What | Where |
|---|---|
| Port vars DATA/STATUS/CONTROL = BASE/+1/+2 | @`0x545c` |
| write-word strobe sequence | @`0x3e9a`; VxD @`0x175c`; DRV @`0x21d0` (byte-identical) |
| Block writer (contiguous `lodsw`/`out`) | @`0x3ede` |
| nibble-read + 32-entry tables `[0x2f4]`/`[0x314]` | @`0x40c0`/`0x416c` |
| Streaming ISR; PIC-mask helper | @`0x4cc6`; @`0x6154` (EOI `0x20`/`0xA0`) |
| Detection echo test | @`0x439c`/`0x54c6` |
| Format classifier; command builder (block size `0x1000`) | @`0x1e74`; @`0x1c40` |
| DSP download `{addr,len≤0x79,data}` marker `0xCE01` | @`0x4526` |
| Port-range validation | @`0x59bc` |
| `BMASTER` SB/AdLib traps (`bts` bitmap; `[0x400+port*4]`; `0x388→0x141c`) | 32-bit VCPI |
| `DGSETUP` PIT-ch2 calibration | @`0x49c4` |
| Windows `DS301.DRV`/`VDS301.386` same primitives + `MODMESSAGE`; VxD `Install_IO_Handler` traps | — |

---

## 13. Open questions and validation

**Open:** DOS `BMASTER` host/device FM division and on-wire FM encoding (§8.2); command
opcodes for the native API, ADPCM, and power (§5/§8/§10.2); onboard buffer depth;
downloaded-DSP image format; full format-code bitfields; and — the load-bearing one for
§10 — whether the original drivers emit FM+PCM concurrently or serialize them.

**Validate by:** (1) *best* — a logic-analyzer capture of the LPT lines during
detection, a PCM tone, FM-only, and a mixed game: confirms timing/buffer depth, shows
whether FM-only puts sparse register writes (device FM) or a PCM stream (host FM) on the
wire, and reveals serialization. (2) *iterative bring-up* — implement SPP, verify
detection then PCM against the original drivers *before* mixing; then add FM+mixing and
test under both the original stack and a purpose-written driver to separate a device
limit from a host-driver limit.

---

*Provenance & licensing: derived by reverse-engineering the original DOS/Windows
3.x/95 driver and utility binaries and cross-checking the manufacturer manual. Contains
no source/binary code and no verbatim passages from the software or manual; facts,
specs, and interface details (not themselves copyrightable) are stated in the author's
own words. Written so a free, open-source, royalty-free compatible device and driver can
be built from it; every recommended algorithm is royalty-free or patent-expired.
Product/company/trademark names are used only for identification. Do your own
patent/trademark diligence — this is not legal advice.*
