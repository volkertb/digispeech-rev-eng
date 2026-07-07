# Digispeech / Port·Able Sound (DS301) — Parallel-Port Protocol Implementation Guide

*A clean-room, language-agnostic description of how the Digispeech "Port·Able
Sound Plus" / "Digispeech Plus" family (chip designator **DS301**, models
DS301A / DS311 / DS311A) talks to a host PC over the parallel port, recovered by
static reverse-engineering of the original DOS, Windows 3.1, and Windows 95
drivers and cross-checked against the manufacturer's user manual.*

> **How to read this document.** It is written so that a software engineer or a
> coding agent who has never seen the hardware can (a) detect the device, (b)
> play PCM audio, (c) record, and (d) understand how Sound Blaster / AdLib / MIDI
> support is layered on top — and from there implement a compatible *device*, a
> compatible *driver*, or a modern Sound Blaster emulator backend. It describes
> **behavior and reasoning**, not ported code. Every non-obvious claim is tied to
> a specific instruction sequence in the Evidence Appendix (§16).
>
> **Confidence markers** appear throughout: **[Observed]** = read directly and
> corroborated across ≥2 independent binaries; **[Inferred]** = a well-supported
> deduction; **[Open]** = not resolved by static analysis alone.

---

## 1. Overview and device model

The DS301 is an external audio peripheral that hangs off the PC **parallel (LPT)
port**. Internally it is a **programmable DSP + audio codec** (the DS301 ASIC,
fabricated by Texas Instruments) with its own RAM, a DAC, an ADC, and a hardware
interrupt line back to the PC. It is externally powered (a 9 V adapter); it does
*not* run off parallel-port pins like a Covox does.

Crucially, **it is not a Covox/Disney-class one-way DAC.** It is bidirectional
(it can record), it raises hardware interrupts, it accepts downloaded DSP
code/coefficients, and it plays from an onboard buffer under flow control. Think
of it as a small self-contained sound card whose bus happens to be an LPT port.

### 1.1 What is hardware vs. host software

This is the single most important architectural fact for anyone re-implementing
the device, so it is stated up front.

| Capability | Where it runs | Confidence | Guide coverage |
|---|---|---|---|
| PCM playback, 8/16-bit, mono/stereo, up to ~44.1 kHz | **Device** (DAC) | [Observed] | Full (§3–§8) |
| PCM recording (ADC) | **Device** | [Observed] | Full (§10) |
| Broad codec suite: µ-law, A-law, SB-ADPCM (2/2.6/4-bit), OKI & DVI/Intel ADPCM, Microsoft ADPCM, CVSD | **Device DSP firmware** (encode/decode) | [Observed] (names) / [Open] (wire detail) | Characterized (§11.6) |
| Very-low-rate speech codecs: DSP Solutions RELP (1.65 bit), CELP (1.1 / 1.625 bit), LPC10 | **Device DSP firmware** | [Observed] (names) / [Open] (wire detail) | Characterized (§11.6) |
| LPC "vocabulary" fixed-phrase speech | **Device DSP** + host-loaded vocabulary | [Observed] / [Open] detail | Characterized (§11.7) |
| Text-to-speech (First Byte TTS Engine v4.1) | **Host** text→phoneme, device speech synth | [Observed] / [Open] detail | Characterized (§11.7) |
| Native "Digispeech standard" audio API (PDIGI overlay framework) | **Host driver** (`PDIGI` + `PDRV*.DAT`) over the same LPT protocol | [Observed] / [Open] detail | Characterized (§11.7) |
| AdLib / OPL "FM synthesis" | **Device DSP firmware** — OPL2-*functional* synth (per the manual); host traps/forwards OPL register writes *(exact DOS host/device division Open — §11.4)* | [Observed] (manual) | Full (§11.1–11.5) |
| MIDI — Windows (`MODMESSAGE`) and DOS (XMIDI via `PDRVXM`) | **Host software**, routed to the *same* emulated-FM path as AdLib | [Observed] | Full (§11.5) |
| Sound Blaster *digitized* audio emulation | **Host software** traps SB ports, streams PCM to device | [Observed] | Full (§11.1) |
| Tone-generation mode (`PDRVTD`) | Host driver overlay | [Observed] (exists) / [Open] | Noted (§11.7) |
| DS201 backward compatibility (LinkWay driver) | Host driver | [Observed] (exists) | Noted (§11.7) |

> The device reports **both a DSP version and an ASIC version** — it has a
> programmable DSP *plus* a support ASIC. Models in this family: DS301A / DS311 /
> DS311A (Port·Able Sound Plus / Digispeech Plus), successors to the serial DS201.

A headline constraint (per the manual, and consistent with the binaries and real-
hardware demonstrations): the original mixes FM/synth music and digitized PCM
**only in mono** — its output mixer offers *either* stereo digital audio *or*
(mono synth + mono digital), so **16-bit stereo PCM and FM cannot play together**,
and in practice the DOS software often serializes the two so they interrupt each
other; under Windows they time-share with PCM given priority. §11.3 explains the
mixer precisely, and §13 explains how a compatible re-implementation can lift the
mono-only restriction while staying protocol-compatible.

### 1.2 The four software stacks that drive it

1. **`DS301.SYS`** — DOS character device driver implementing the **IBM AUDIODD**
   standard audio interface (it registers itself as device name `AUDIO$` /
   "DS301"). Cleanest and most complete view of the raw protocol.
2. **`SOUND301.EXE`, `PDIGI.EXE`, `DIGIPLAY/DIGIREC`** — DOS applications and the
   First-Byte/Digispeech-standard drivers.
3. **`DS301.DRV` + `VDS301.386`** — the Windows 3.1 multimedia driver (Wave +
   MIDI) and its 386-enhanced-mode virtual device driver.
4. **`BMASTER.EXE`** — the DOS **Sound Blaster / AdLib emulator** (a VCPI
   protected-mode TSR). This is the binary that makes DOS games think a Sound
   Blaster is present.

All four speak the **same** low-level parallel-port protocol (§4). That agreement
across four independently-written code paths is the main reason the protocol
below can be stated with confidence.

### 1.3 Epistemic status and required validation (read this)

This document is the product of **static reverse-engineering** — reading the
drivers, not operating the hardware. That supports two very different classes of
statement, and they must not be conflated:

- **Well-established (Observed):** the *mechanics* of the protocol — the register
  model, the write-word strobe sequence, the nibble read-back and its decode
  tables, the detection echo test, the SPP-only transport, the hardware-IRQ flow
  control, the PIT-based calibration, and the fact that the *original* mixes FM and
  digitized audio only in mono (no stereo-PCM + FM). These are read directly and
  corroborated across multiple binaries, the manufacturer's manual, and independent
  hardware demonstration, so an implementer can rely on them.

- **Engineering inference (not yet proven) — validate before relying on:** the
  forward-looking design claims in §13, **most importantly the claim that a new
  implementation can deliver *flawless* simultaneous FM + PCM while retaining
  *full* compatibility with the original Digispeech software.** That conclusion is
  well-reasoned but rests on assumptions this analysis did *not* fully confirm —
  chiefly (a) whether the original host drivers (`BMASTER`, `DS301.DRV`) actually
  *emit* FM and PCM concurrently or internally serialize them (§11.2, §13), (b)
  the exact way commands and sample data may be interleaved on the wire, (c) the
  device's real buffer depth and IRQ/flow-control timing, and (d) where FM
  synthesis ultimately executes (§11.4, still Open).

> **Caveat.** The simultaneous-FM+PCM-with-full-compatibility goal should be
> treated as a **design hypothesis to be tested, not a settled result.** Confirm
> it empirically before depending on it — **preferably with original hardware**
> (a logic-analyzer capture of the LPT lines during FM-only, PCM-only, and mixed
> playback will show exactly what the original drivers emit and how the device is
> paced), or, lacking original hardware, **iteratively during reimplementation** —
> bring up the SPP protocol first, validate detection and plain PCM against the
> original drivers and real software, then add on-device mixing and verify that
> the original driver stack (and, separately, a purpose-written driver) actually
> drives it as intended. Expect to discover details this static analysis could not
> resolve, and budget for that iteration. The §17 open-questions list doubles as a
> test plan.

---

## 2. Parallel-port register model (background)

The device is driven entirely through the three **standard (SPP) parallel-port
registers** — DATA, STATUS, CONTROL. The protocol uses **no EPP or ECP** mode
(those IEEE-1284 modes postdate the device); everything is classic
register-level signalling. Any compatible reimplementation must treat **SPP
register bit-banging as the sole required transport**. Let `BASE` be the port's
base I/O address (LPT1 = `0x378`, LPT2 = `0x278`, LPT3 = `0x3BC`; the driver
discovers it — see §5).

| Register | Address | Direction | Bits used by the DS301 |
|---|---|---|---|
| **Data** | `BASE+0` | write (and read in nibble mode) | D0–D7 = the 8 data lines |
| **Status** | `BASE+1` | read-only | bit7 /BUSY (inverted), bit6 ACK, bit5 PAPER-OUT, bit4 SELECT, bit3 ERROR |
| **Control** | `BASE+2` | write | bit0 STROBE (inv), bit1 AUTOFEED (inv), bit2 INIT, bit3 SELECT-IN (inv), bit4 IRQ-enable |

The DS301 uses the **Data** register to send bytes to the device, the **Control**
register bits to clock them (STROBE) and to hold the device in a data-transfer
state, and the **Status** register's five input lines to read data *back* from
the device (nibble mode) and to carry the device's handshake/interrupt signals.

Internally the driver keeps three port variables it computes once at init
**[Observed]**:

- `DATA = BASE` (also mirrored as the "base" it was given)
- `STATUS = BASE + 1`
- `CONTROL = BASE + 2`

---

## 3. Two building blocks you must implement first

Everything else (detection, playback, record, commands) is built from exactly
two host-side primitives. Implement these correctly and the rest falls out.

### 3.1 The "write-word" primitive (host → device)

This sends **one 16-bit word** to the device. It is used for commands *and* for
streaming sample data. The sequence, in order **[Observed — identical in
`DS301.SYS`, `DS301.DRV`, and `VDS301.386`]**:

```
1.  write DATA    = low_byte(word)
2.  write CONTROL = 0x0E                 ; AUTOFEED+INIT+SELECT-IN asserted, STROBE low
3.  wait  Δ1                              ; calibrated delay (see §7)
4.  write CONTROL = 0x0F                 ; raise STROBE bit0  -> latches the low byte
5.  wait  Δ2
6.  write DATA    = high_byte(word)
7.  wait  Δ3
8.  write CONTROL = 0x0E                 ; drop STROBE bit0   -> latches the high byte
```

Key points:

- **`0x0E` is the "transfer-enabled, strobe-idle" control state.** Bit1
  (AUTOFEED), bit2 (INIT) and bit3 (SELECT-IN) are held asserted throughout a
  transfer; they act as the device's "I am being driven / direction" enable.
- **STROBE (Control bit 0) is the write clock.** A word is two byte-latches: the
  low byte is latched on the rising edge of STROBE, the high byte on the falling
  edge. The device therefore receives two bytes per call and reassembles a 16-bit
  value. (The exact internal endianness/format is the device's business; a
  compatible device must latch low-then-high on the STROBE rising-then-falling
  edges.)
- The Δ delays are not electrical niceties you can drop; they pace the host to
  the device's word-acceptance rate and are **calibrated to CPU speed** (§7).

There are minor variants that change only the *control nibble base* (the `0x0E`
becomes `0x0E + k` for small `k`) to select **which internal register/stream** a
word targets — e.g. a "+6" variant for command words, a "+0xC/+0xD" for
switching to read mode. Treat the low control nibble as a **sub-command / stream
selector** carried alongside the strobe. **[Observed]**

### 3.2 The "nibble-read" primitive (device → host)

Because the Data register is write-only on a plain SPP port, the device returns
data over the **five Status input lines**, one nibble at a time. To read one
16-bit word the host performs **four** nibble reads **[Observed —
`DS301.SYS` @`0x40c0`/`0x416c`, `DS301.DRV`, `VDS301.386`]**:

```
for nibble_index in 0,1,2,3:
    write DATA = nibble_index          ; tell the device which nibble to present
    wait Δ
    s = read STATUS                    ; device has driven 4 data bits onto status lines
    v = s >> 3                          ; align: bit3(ERROR)->bit0, bit4,5,6,7 -> bits1..4
    nibble = XLAT_LOW[v]  (or XLAT_HIGH[v] on odd indices)
assemble the 4 nibbles into a 16-bit word
```

The device drives its 4 output bits across the Status lines ERROR/SELECT/
PAPER-OUT/(ACK|BUSY); the host aligns them with `>> 3` and maps them through a
**32-entry translation table** to recover a nibble. Two tables are used, one for
the low nibble position and one shifted left by 4 for the high nibble position.
The exact tables are reproduced in §16.3 so a compatible device knows precisely
which status line must carry which bit. **[Observed]**

> **Implementer's note.** The nibble select value written to the Data register
> (0,1,2,3) is how the host asks the device for successive nibbles. A compatible
> device must present nibble *n* on the status lines when it sees *n* on the data
> lines during a read cycle.

---

## 4. The protocol as a layered picture

```
┌──────────────────────────────────────────────────────────────────┐
│  Application / OS audio API (AUDIODD, Windows MMSYSTEM, SB ports)   │
├──────────────────────────────────────────────────────────────────┤
│  Command / message layer:  play-buffer, set-format, set-rate,      │
│                            download-code, read-status  (§6)         │
├──────────────────────────────────────────────────────────────────┤
│  Word transfer layer:  write-word (§3.1)  |  nibble-read (§3.2)     │
│                        + low-control-nibble stream selector         │
├──────────────────────────────────────────────────────────────────┤
│  Parallel port:  DATA / STATUS / CONTROL registers   (§2)           │
└──────────────────────────────────────────────────────────────────┘
        ▲  hardware IRQ (IRQ7 typ.) for playback/record flow control
```

The transfer layer is a **general bidirectional word channel**. The command layer
multiplexes several message types over it. This layering is what makes a "better"
compatible device possible (§13): the wire can carry anything; the limitations
are in the *firmware* and the *host driver's choices*, not the wire.

---

## 5. Detection and initialization

### 5.1 Finding the port

The driver does **not** hardcode `0x378`. It validates a candidate base against a
whitelist of legal port ranges (rejecting e.g. COM and video ranges) and then
probes for the device **[Observed — `DS301.SYS` @`0x59bc` range-check,
@`0x545c` port-variable setup]**. A compatible driver should:

1. Read candidate LPT bases from the BIOS Data Area at `0040:0008` (four 16-bit
   words for LPT1–4), or accept one from configuration.
2. For each candidate, set `DATA=BASE`, `STATUS=BASE+1`, `CONTROL=BASE+2` and run
   the probe handshake.

### 5.2 The probe handshake (echo test)

Detection is an **echo test**: the host sends known 16-bit patterns with the
write-word primitive and reads them back with the nibble-read primitive; a device
is present iff every pattern echoes exactly. The observed sequence
**[Observed — `DS301.SYS` @`0x439c`, @`0x54c6`]**:

1. A short "knock"/wake sequence of control-line toggles and a run of writes of
   fixed patterns (`0xF0F0`, then `0x0F0F`, then rolling values), each repeated
   up to 0x80 times, used to get the device into a known state.
2. Then the **echo probes**, in order: write `0xAAAA` → read back, expect
   `0xAAAA`; write `0x5555` → expect `0x5555`; write `0x0F0F` → expect `0x0F0F`;
   write `0xF0F0` → expect `0xF0F0`. Any mismatch is treated as "device not
   present."
3. On success the driver records the port and IRQ and reports that the adapter was
   found on that LPT and interrupt.

A compatible **device** must therefore implement a loopback: a word written via
write-word must be retrievable, bit-exact, via nibble-read, at least during the
detection phase.

### 5.3 IRQ and enable

Playback/record are interrupt-paced. The relevant IRQ is **the host parallel
port's own interrupt**, not a device setting: the device merely drives the
ACK/status line, and the host's LPT hardware turns that into whichever IRQ that
port is wired to (conventionally LPT1 → IRQ7, LPT2 → IRQ5). The driver enables the
port's interrupt (Control bit 4), unmasks the corresponding 8259 PIC bit (`0x21`
for IRQ0–7, `0xA1` for IRQ8–15), and its ISR EOIs to `0x20`/`0xA0`. **[Observed —
`DS301.SYS` @`0x6154` PIC-mask helper]** A compatible device makes no assumption
about the IRQ number; a compatible driver services whatever interrupt the chosen
LPT raises (and can fall back to polling the status line — §7.2/§13).

---

## 6. The command / message layer

Above the word channel, the driver sends **structured messages**. The message the
driver builds for playback is representative **[Observed — `DS301.SYS`
@`0x1c40` builds a command block]**:

```
word[0] = format code           ; see §6.1
word[1] = buffer base (segment/handle the device uses)  [Open: exact meaning]
word[2] = 0
word[3] = sample-rate parameter / flags   (0xFF00 sentinel in some paths)
word[4] = ...
word[.] = block size = 0x1000   ; 4096 — the streaming granularity
word[.] = length / count
```

The block is then shipped to the device word-by-word using the write-word
primitive with the **command control-nibble variant** (the "+6" form), i.e. the
low control nibble marks these words as *command*, not *sample data*.
**[Observed]** There is also a **code/coefficient download** message class (§9)
that writes to addressable device memory.

### 6.1 Format codes

The driver maps (bit depth, channel count, rate) to a one-byte **format code**
that goes to the device **[Observed — `DS301.SYS` @`0x1e74` classifier]**:

| Format code | Meaning (inferred) |
|---|---|
| `0x00` | mono, 8-bit |
| `0x01`, `0x02` | mono variants (rate/mode dependent) |
| `0x03` | mono, 16-bit |
| `0x48` | stereo, 16-bit |
| `0x49` | stereo, 8-bit |
| `0x4A` | stereo variant |

Structure of the code **[Inferred]**: bit `0x40` = stereo; the low bits select
sample width / sub-mode; bits `0x10`/`0x08` are additional modifiers seen being
OR-ed in. Codes `0x48–0x4A` take the *extended* 9-word command form; codes
`0x00–0x03` take the *short* 5-word form. Supported rates observed include the
usual 8000 / 11025 / 22050 / 44100 Hz, each special-cased, with a general
rate→divisor computation for arbitrary rates up to ~44.1 kHz. **[Observed]**

---

## 7. Timing, clocking, and calibration

### 7.1 Calibrated delays and IRQ pacing

- The Δ delays inside write-word / nibble-read are **busy-wait loops whose counts
  are calibrated to the host CPU speed** by the setup utility **`DGSETUP.EXE`**.
  There are separate counts for the different phases (`Δ1..Δ3`, plus a distinct
  read-phase delay). **[Observed — counts live in driver variables, e.g.
  `DS301.SYS` `[0x2ea..0x2f2]`; VxD `[0x83c4/0x83cc/0x83d0]`]**
- **This is why the manual insists you re-run `DGSETUP` if you change CPU/turbo
  speed.** The device has a fixed maximum word-acceptance rate; the host must not
  clock faster than the device can latch. The calibration finds the smallest
  safe delay for *your* CPU. `DGSETUP` even suggests adding a long parallel cable
  on very fast machines — i.e. deliberately slowing edges.
- Playback pacing is **IRQ-driven**, not delay-driven: the device raises its IRQ
  when it needs the next block; the driver's ISR streams more sample words. The
  Δ delays govern *transfer* speed; the IRQ governs *audio* pacing. **[Observed]**

**Portability implication:** the delay constants are *host-and-device specific*
and must be re-derived for any new host or device. A compatible device should
document (or make queryable) its maximum word rate so a driver can calibrate.

### 7.2 Sensitivity to modern / later-era hardware

A natural question is how well this protocol survives on much later PCs (a 2010s
machine with a parallel port). The honest answer: **more fragile than a Disney
Sound Source, but not for the reason you'd guess** — raw CPU speed is *not* the
main problem. Two structural facts, both verified in the binaries, explain the
behavior:

1. **The byte transfer is fully open-loop (no handshake).** The write-word and
   block-write routines interleave `OUT`s with fixed, calibrated delays and
   **never poll a BUSY/ACK/status line** to confirm the device accepted a byte
   **[Observed — no `IN` instruction anywhere in the write path]**. The host
   simply waits a calibrated time and assumes the device kept up. Contrast the
   Disney Sound Source, which is **closed-loop**: a fixed internal clock + a small
   FIFO + a "FIFO-full" status line the host polls before each write. The DSS
   physically cannot overrun and makes *zero* assumptions about host speed —
   which is exactly why it runs on a 2016 PC untouched. The DS301 has no such
   safety net on the data path.

2. **The delay calibration itself is robust.** `DGSETUP` calibrates the delay
   loops with a **PIT channel-2 stopwatch** (program `0x43`, gate via `0x61`,
   count against the fixed **1.193182 MHz** timer) — *not* by counting CPU cycles
   and *not* with `rdtsc` **[Observed — `DGSETUP.EXE` @`0x49c4`]**. Because the
   PIT frequency is fixed on every PC (and still emulated accurately on modern
   chipsets under DOS), the resulting delays are correct in *real time* on any CPU
   speed. So, pleasantly, **you do not get a "too fast CPU" failure** as long as
   the legacy PIT is present and you re-run `DGSETUP`.

Given those two facts, the real modern-hardware risks are elsewhere:

- **Uncalibrated parallel-port latency and edge response.** `DGSETUP` calibrates
  the CPU delay loops but cannot calibrate the port's own `OUT`/`IN` latency or
  how fast its lines settle. That varies enormously by port implementation:
  LPC/SuperIO "legacy" ports behave ISA-like (~1 µs/access — close to what the
  device expects, so they tend to work); PCIe parallel cards differ; and
  **USB→parallel adapters do not expose register-level SPP at all** (they emulate
  the *printer* protocol), so bit-banging this device through one simply fails.
  `DGSETUP` itself accounts for a slow parallel-port adapter even on a fast system,
  and can abort if its test runs past a time limit.
- **Open-loop bidirectional read-back.** Detection and recording read nibbles
  back (write nibble-select → delay → read STATUS). The device must drive the
  status lines within that fixed delay; a port with different I/O latency can be
  mis-sampled, yielding a wrong nibble and a failed echo test. The DSS never reads
  back for playback, so it avoids this class of failure entirely.
- **Hardware-IRQ dependency (often the deciding factor).** Playback flow control
  relies on a real LPT hardware interrupt (IRQ7 typically) **[Observed]**. Many
  modern systems ship with the parallel-port IRQ disabled in firmware, in a port
  mode that never asserts it, or on PCIe/USB ports that route interrupts
  differently. If the IRQ never fires, the original driver stalls waiting to be
  told to refill. The DSS needs no interrupt at all.

**Bottom line for running original hardware on a modern PC:** it *can* work, but
the target is narrow — you need a **genuine register-level SPP port** (an
LPC/SuperIO port, or a true SPP-capable PCIe card — *not* a USB dongle), the
**parallel-port IRQ enabled and deliverable**, and a re-run of `DGSETUP`. Miss
any of those and it fails where a DSS would shrug and work. The fragility is
concentrated in the *handshake-less data path*, the *port-hardware assumptions*,
and the *IRQ*, not in CPU-speed-dependent delays.

**Design lesson for a compatible device (feeds §13):** make the data path
**closed-loop** — expose a BUSY/ready line the host must honor per byte or per
block (a FIFO-full flag, DSS-style), and provide an **IRQ-optional polling**
refill path. A device that flow-controls the host is intrinsically insensitive to
host and port timing and will keep working on future hardware, exactly as the DSS
does. **Crucially, this is achievable in plain SPP** — the Disney Sound Source is
fully closed-loop over a standard parallel port with no EPP/ECP whatever. So
timing-robustness is a property of the *handshake design*, not of any advanced
port mode. (EPP/ECP is a separate, optional throughput optimization discussed in
§13.1; it is *not* required for robustness and was *not* part of the original
device.)

---

## 8. Playback (the output path) — step by step

1. **Detect + init** (§5): establish port, verify echo, enable IRQ.
2. **Download any required DSP firmware/coefficients** for the mode you need
   (§9), if not already resident.
3. **Send the play command** (§6) with the chosen format code and rate.
4. **Stream sample data**: repeatedly send sample words with the write-word
   primitive using the *sample-data* control-nibble variant. Samples are streamed
   as a contiguous block (a tight "load word → write-word" loop), 4096-byte
   blocks being the natural granularity. **[Observed — `DS301.SYS` block-writer
   @`0x3ede`]**
5. **Refill on IRQ**: on each device interrupt, compute how much has been
   consumed (the driver tracks a play position vs. write position) and stream the
   next block. Continue until the buffer is exhausted, then stop and quiesce the
   device. **[Observed — streaming ISR @`0x4cc6`]**

Stereo/16-bit simply changes the format code and the bytes-per-frame; the
transfer mechanics are identical.

---

## 9. Downloading code/coefficients to the device DSP

The device is programmable. The driver can push blocks into **addressable device
memory** using a download message: a table of records, each `{target address,
length (≤ 0x79 words), data...}`, terminated by a sentinel, with a marker word
(`0xCE01`) distinguishing loadable records **[Observed — `DS301.SYS`
@`0x4526`]**. This is how the speech engines (`V3ENG*/V4ENG*`, First Byte TTS)
and, by inference, the ADPCM/compression and any "AdLib-mode" DSP routines are
installed. A compatible device that wants to run original software unmodified
must accept this download format and interpret the downloaded images — **or**
emulate the *effects* of the known downloaded engines. **[Open: the internal DSP
ISA / image format of the payloads is not decoded here.]**

---

## 10. Recording (the input path)

Recording uses the **nibble-read** primitive (§3.2) as its data path: the driver
puts the device in a capture mode (a command word with the read control-nibble
variant), then repeatedly reads 16-bit words back, assembling the recorded
stream, again paced by the device IRQ. Observed record formats include PCM
(e.g. 22 kHz 16-bit mono) and compressed **DSP-ADPCM** (e.g. 3-bit, 11 kHz).
**[Observed — read-block @`0x416c`; record formats corroborated by the Windows
recorder UI]** Recording is lower priority for most re-implementations, but the
primitive is the same one used for detection read-back, so you get it almost for
free.

---

## 11. Sound Blaster / AdLib / MIDI, and the FM/PCM mixing constraints

This section explains the emulation layer and the device's FM/PCM mixing rules
(it mixes them only in mono — §11.3) — essential context for anyone building a
compatible device or a new emulator.

### 11.1 How SB *digitized* audio emulation works (DOS: `BMASTER`)

`BMASTER` is a VCPI 386-protected-mode TSR. On a 386+ it installs **I/O-port
traps** (via the V86/VCPI mechanism) on the Sound Blaster DSP ports (`0x22x`) and
the AdLib ports (`0x388`/`0x389`), and even on the PIC ports (`0x20`/`0x21`) to
virtualize the SB IRQ. **[Observed — trap-bitmap builder using `bts`;
per-port handler dispatch table indexed by port at `[0x400 + port*4]`; handlers
for `0x388`→`0x141c`, `0x389`→`0x142c`]** When a game programs the "Sound
Blaster," `BMASTER` catches the writes, reconstructs the intended PCM stream, and
ships it to the DS301 over the parallel port using the exact protocol above.
(This is why a 386 + EMM/VCPI is required — it is needed to *trap* the ports in
V86 mode, independent of any synthesis cost.) **[Observed]**

### 11.2 How AdLib/FM and MIDI are handled

The AdLib port handlers capture the OPL register index (writes to `0x388`) and
the OPL data (writes to `0x389`) into a **host-side shadow register block**
rather than forwarding each write to the device in real time **[Observed —
handlers store into the `~0x1670` shadow region, not to the LPT]**. `BMASTER` also
carries synthesis-style tables (a 16-bit sine table peaking at `0x7FFF` and an
exponential/antilog `2^(-n/8)` table). What consumes that shadow — whether the
host renders the FM to PCM, or the shadow is forwarded to the device's own FM
synthesizer (which the manual attributes to the device, §11.4) — was **not**
resolved by static analysis; the exact DOS host/device division is [Open]. Either
way the resulting music reaches the device's mono synth+PCM mixer (§11.3). Under
Windows the MIDI path is routed to the same emulated-FM machinery (§11.5).

### 11.3 FM + PCM simultaneity — a *mono-only* device mixer (corrected by the manual)

> **This section was corrected against the manufacturer's manual** (*A Guide to
> Using Digispeech Plus*, DSP Solutions, 1994). My earlier static-analysis
> conclusion — "the device cannot mix FM and PCM at all" — was **too strong.**

Per the manual's audio-mixing specification, the device's output mixer offers two
configurations **[from the manual]**:

1. **stereo** digital audio together with the stereo line-in, or
2. **mono** synthesized music **plus mono** digital audio, together with the
   stereo line-in.

So the device **can** play FM/synth music and digitized PCM at the same time — but
**only in mono** (configuration 2). There is no stereo-digital-*plus*-synth mode.
In other words, **16-bit *stereo* PCM and FM synth are mutually exclusive** —
engaging the synth restricts digital audio to *mono* (which may still be 8- or
16-bit); *mono* PCM + FM mixes fine, *stereo* PCM + FM does not. This comes
specifically from the manual's **Audio Mixing** spec, and is a *different*
constraint from the "full duplex needs Mix Wave/Synth off" note (which is about
simultaneous **playback + recording** — see §18.1). That single mixing constraint
explains all the observed playback behavior cleanly:

- Games with **mono** music + **mono** effects (e.g. Wolfenstein 3D) mix fine —
  matching the demonstration where FM and digitized sound played together.
- Games using **stereo** digital audio, or whose driver path does not engage the
  mono mix mode, fall back to time-sharing, so FM and PCM appear to interrupt each
  other. (SB-ADPCM titles add a *separate* decode burden on top — §11.6.)
- The Windows "Mix Wave/Synth" control exposes exactly configuration 2; with it
  off you get one source at a time.

So the correct statement is **not** "no mixer," but "a **mono** synth+digital
mixer, plus a stereo digital+line-in mode." The stereo-vs-synth exclusivity — not
a total inability to mix — is the real limitation, and it is the thing a "better
Digispeech" would lift (§13).

### 11.4 Where FM synthesis runs (updated by the manual)

The manual's music-synthesis specification attributes the FM synthesis to the
**device**, describing it as functionally equivalent to a two-operator,
roughly-eleven-voice OPL2 and as accepting Sound Blaster/AdLib-style FM register
programming **[from the manual]**. Two things follow:

- There is **no discrete Yamaha OPL2 chip**: the spec claims functional
  equivalence, and the stated ~11-voice count does not match a real OPL2 (9 melodic
  / 6+5 rhythm). This is an **OPL2-equivalent synthesizer implemented in the
  device's DSP firmware** — which is also why its FM is imperfect (it omits
  instruments a genuine OPL2 would play).
- Because the manual lists synthesized music as one of the device's own
  output-mix sources (§11.3), the synthesis is generated **on the device**, not
  purely rendered on the host.

This *refines* my earlier position: I could not resolve the host-vs-device locus
from `BMASTER`'s obfuscated 32-bit code (a promising lead there turned out to be
Sound Blaster **DMA-controller** emulation writing 8237 ports `0x0A/0x0B/0x0C`, not
synthesis), and I leaned too far toward "host software FM." The manufacturer's spec
is clear that the **device** provides OPL2-functional FM synthesis in firmware and
accepts AdLib/SB-style FM register programming. Your original intuition that FM
lives on the device was essentially right — it is DSP-firmware synthesis, just not
a dedicated OPL chip. **[Open]** remains only the *exact* division of labor in the
DOS `BMASTER` path (how much OPL state it processes host-side before handing off)
and the on-wire FM register/command encoding — resolvable by the §17.1 capture.
None of this affects the implementation guidance below (§14).

### 11.5 MIDI — defers to the *same* emulated FM path

**MIDI is not a separate synthesizer.** Under Windows, `DS301.DRV` is the MIDI
output driver (it exports `MODMESSAGE`) **and it contains the byte-identical
antilog/synthesis table found in `BMASTER`** (the same `0x7FFF, 0x7569, 0x6BB3, …`
2^(-1/8) curve) **[Observed]**. MIDI note events are rendered through the **same
emulated-FM-to-PCM machinery** as AdLib — not a wavetable, not a hardware synth.
In DOS, MIDI is provided by the `PDRVXM` overlay (XMIDI / Miles "XMI" support,
§11.7) and routed the same way. Consequences: MIDI inherits the AdLib emulation's
limits (dropped instruments) and the **mono-only synth+PCM mixing restriction**
(§11.3).
Implementer takeaway — to reproduce MIDI you reproduce the FM path; there is
nothing MIDI-specific at the device level.

### 11.6 Playback formats — prioritized for DOS games and Windows apps

**Scope reminder: this guide prioritizes the playback path that real DOS games and
Windows applications exercise.** In priority order those are:

1. **8-bit PCM, mono** — the overwhelmingly common Sound Blaster case; the single
   most important format to get right.
2. **16-bit and/or stereo PCM** — SB16-era games and the Windows wave path.
3. **Sound Blaster ADPCM (4-bit, 2.6-bit, 2-bit)** — **required by some DOS games**
   (they ship compressed samples and play them through the SB DSP's ADPCM commands;
   Duke Nukem II is a well-known ADPCM user). Must be handled for those titles to
   have sound.
4. **AdLib FM + MIDI** for music (§11.1–11.5).

**How ADPCM is actually handled — the key implementer point.** For Sound Blaster
game compatibility the ADPCM lives in the **SB-emulation layer, not the device wire
format**: the game hands *compressed* bytes to what it thinks is an SB DSP, and the
emulation must turn them into audio. The clean, portable way to do this — and what a
modern emulator backend should do (§14) — is **decode SB-ADPCM to PCM in the host
SB-emulation core, then stream ordinary PCM to the device.** The device then needs
only its PCM path; no special on-device ADPCM support is required to run those
games. (The DS301's DSP *can* also decode ADPCM itself, so the original stack may
push coded data to the device to save host CPU; whether original `BMASTER` decodes
host-side or on-device is **[Open]** and resolvable by the §17.1 capture. Either
way, a from-scratch compatible stack can just decode host-side.)

So for a reimplementation: **implement PCM (8/16-bit, mono/stereo) as the device
baseline, and implement SB-ADPCM *decode* in the SB-emulation/host layer** to cover
the DOS games that need it. That combination covers essentially all game and
application playback.

**Also present, but not game/app-critical (documented for completeness).** The
`DIGIPLAY`/`DIGIREC` tools expose a much wider codec menu aimed at
recording/telephony/speech rather than games: **µ-law**, **A-law**, **OKI 4-bit
ADPCM**, **DVI/Intel 4-bit ADPCM**, **Microsoft ADPCM**, **CVSD** (rate 0–5), and
the DSP Solutions speech coders **RELP (1.65 bit)** and **CELP (1.1 / 1.625 bit)**
plus **LPC10** (see §11.7). These are real device capabilities **[Observed — format
menu]** but outside the DOS-game / Windows-app playback focus; their per-format wire
encodings are **[Open]** and only worth recovering if you are targeting the native
Digispeech recording/speech tools rather than games.

### 11.7 The native "Digispeech standard" API, LPC speech, and TTS

Distinct from the AUDIODD path (§1.2 / `DS301.SYS`) and the SB-emulation path,
there is a **native Digispeech audio API** driven by `PDIGI` (the "Port·Able Sound
Audio Loader"), which Digispeech-aware software targets directly (e.g. GameTek's
*Jeopardy*, `DIGISP.COM`). Architecture **[Observed]**:

- `PDIGI` is a resident driver-loader that installs pluggable **overlay drivers** —
  `PDRVA..E.DAT` (codec/audio personalities), `PDRVTD.DAT` (tone mode),
  `PDRVXM.DAT` (XMIDI/Miles support) — each an MZ image; config comes from
  `DGSPEECH.INI` (written by `DGSETUP`).
- It uses the **same LPT protocol** as everything else (the write-word / nibble
  primitives are present in `PDIGI`), so a compatible device needs **no new
  transport** for it — only the higher-level command set differs. **[Open]** the
  native API's exact command opcodes.
- It backward-supports the older serial **DS201** ("LinkWay driver").

**LPC speech** is the device's flagship original capability (the very name
"Digispeech"): the driver can load a standard LPC vocabulary and perform
LPC10-style speech synthesis — sending low-bandwidth LPC/CELP parameters that the
**device DSP** vocodes into speech (the ~1.1 kbps figure). **[Observed]** the
feature; **[Open]**
the LPC frame/wire format.

**Text-to-speech** (`DOSREAD`/`DOSTALK`/`SPEECH`, "First Byte Text-to-Speech Engine
v4.1", plus the V3/V4 engines with dictionary `KERNEL.DIC`, letter-to-sound rules
`*.RUL`, and phoneme data `*.PCM`) is a **host-side** pipeline (text → phonemes)
that then drives the device's speech synthesis. **[Observed]** the components;
**[Open]** the phoneme→device interface.

These native/speech paths are **characterized here, not fully reverse-engineered to
the wire.** They are lower priority than PCM playback for most re-implementation
goals, but a device targeting *full* Digispeech compatibility must eventually
implement the `PDIGI` command set and the LPC speech decoder. §17.1's bus capture
is the way to recover their command encodings.

---

## 12. Portability: device-specific vs. generic

- **Generic parallel-port conventions:** the register model (§2), using STROBE as
  a write clock, and reading nibbles back over the status lines. Any SPP-mode
  parallel device does something in this family.
- **DS301-specific and must be matched exactly for compatibility:** the `0x0E`
  control-state during transfer; the *low-control-nibble stream selector*; the
  two-bytes-per-word STROBE-edge latching; the **nibble decode tables** (§16.3);
  the **echo-test detection** patterns and order (§5.2); the **format codes**
  (§6.1); the **command/message shapes** (§6, §9); and the **IRQ flow-control**
  model (§7–8).
- **Host/CPU-specific and must be re-derived:** every Δ delay constant (§7).

---

## 13. Building a *better* Digispeech (compatible, lifting the mono-only FM+PCM limit)

**This section is a design hypothesis, not a verified result** — see the caveat
in §1.3. The reasoning below is well-supported by the recovered protocol, but the
specific claim that a new device can deliver *flawless* simultaneous FM + PCM
*while remaining fully compatible with the original software* must be confirmed by
testing (original-hardware bus capture, or iterative bring-up during
reimplementation) before it is relied upon.

With that understood: it **appears entirely feasible** to build a clean-room
compatible device that removes the original's headline weakness while remaining
detectable and drivable by the original software. The limitation appears to live
in the device firmware and host-driver choices, **not** in the wire protocol —
the transfer layer is a general word channel that can, in principle, carry sample
data and control interleaved at block boundaries. The main open risk is whether
the *original* drivers will feed both streams to such a device or serialize them
internally (§11.2); new software written for the device is not subject to that
risk.

A compatible re-implementation (e.g. on a modern MCU/FPGA, or added to an
existing parallel-port sound project) should:

1. **Speak the exact protocol of §3–§10** so existing detection and drivers work:
   the write-word strobe sequence, the nibble-read tables, the echo-test
   loopback, the command shapes, and a hardware IRQ for flow control.
2. **Add a deep input FIFO / onboard buffer with autonomous sample clocking.**
   The original already buffers and uses IRQ flow control, so this is an
   *extension of degree*: a larger buffer lets the host service the device far
   less often and tolerates OS scheduling jitter. (Note: a FIFO improves
   *robustness/timing*, not raw host CPU cost — see §13.1.)
3. **Mix on-device, in stereo.** Maintain an OPL-compatible register file *and* a
   PCM stream and sum them in the device. The original already mixes synth + PCM,
   but only in *mono* (§11.3); a better device mixes them in **stereo** (and at full
   16-bit), which the original cannot. Because the wire can carry OPL register
   writes (as commands) and PCM (as sample blocks) interleaved, this is feasible on
   the same transport.
4. **Optionally expose a richer/known synth.** Since the original FM is limited
   (it omits instruments a true OPL2 would play), a compatible device is free to
   implement a full,
   correct OPL2/OPL3 (in firmware or a soft-core) behind the same register
   interface and sound *better* than the original while remaining compatible.
5. **Make the data path closed-loop and IRQ-optional (timing robustness, §7.2).**
   Expose a BUSY/ready line the host honors per byte/block (FIFO-full flag,
   Disney-Sound-Source-style) and a polling refill path that does not *require* a
   hardware IRQ. This makes the device insensitive to host CPU and parallel-port
   latency, so it keeps working on future/varied hardware where the open-loop,
   IRQ-dependent original would fail — and it is all achievable in **plain SPP**
   (the DSS proves it), with no dependency on EPP/ECP.

**The catch for *unmodified* original games:** how much of this helps a game
running through the original `BMASTER` depends on whether `BMASTER` itself sends
both streams or serializes them. Evidence (§11.2) shows `BMASTER` aggregates OPL
writes host-side and shares one output path, so it may not emit FM and PCM
concurrently even to a device that *could* mix them. **To fully realize
simultaneous FM+PCM for existing titles you must also supply a better host
driver** (see §14) that keeps forwarding OPL register writes while it streams
PCM. New software written directly to your device gets the benefit immediately.

### 13.1 SPP is the baseline; EPP/ECP is an *optional* efficiency extra

**The only transport a compatible device may *depend on* is plain SPP register
bit-banging** — that is what the original DS301 protocol uses and what every
original driver (`DS301.SYS`, `BMASTER`, `DS301.DRV`, `VDS301.386`) emits. EPP and
ECP are IEEE-1284 modes from 1994; they were **not part of the original device or
its protocol**, and many host systems either lack them or implement them
unreliably. A reimplementation that *required* EPP/ECP would fail both goals:
compatibility with the original software and broad hardware coverage. So:

- **Required:** the SPP protocol of §3–§10, verbatim. This is the compatibility
  contract.
- **Robustness:** comes from a **closed-loop SPP handshake** (a device-driven
  BUSY/ready line the host can poll, DSS-style) plus an IRQ-optional refill path —
  all within plain SPP (§7.2). No advanced port mode needed.
- **Optional throughput extra:** *if* both ends happen to support it, an EPP/ECP
  fast path can cut host CPU cost for high-rate streaming (the port silicon
  generates the handshake; the host moves data in bursts or via DMA). Offer it
  only as an auto-negotiated bonus for new drivers, **never** as a requirement,
  and always keep the SPP path fully functional.

Note on why the original is CPU-heavy: every sample byte is pushed with several
`OUT`s plus calibrated delays, with no host-side DMA. A larger FIFO relieves
*timing jitter* but not this per-byte cost; only a hardware-handshaked mode
(EPP/ECP) meaningfully cuts it. That is a nice-to-have, not the compatibility
baseline.

### 13.2 Reimplementing on a microcontroller (e.g. Picovox)

A modern MCU platform such as **Picovox** (Raspberry Pi Pico 2 / RP2350, with PIO
state machines, already emulating Disney Sound Source, OPL2LPT, Covox and others
over the LPT port) is an excellent host for a DS301-compatible mode, and the fit
is close:

- **Timing tolerance comes for free.** The original's fragility (§7.2) was largely
  the *original device* being slow to latch, which the host's calibrated delays
  had to respect. An MCU that watches the STROBE/control edges in PIO and latches
  DATA in well under a microsecond has enormous margin — it will accept whatever
  the host bit-bangs, so the "host too fast for the device" failure mode
  essentially disappears. A reimplementation is therefore *more* robust than the
  original on the write path **by construction**, without needing EPP/ECP.
- **Reuse the existing LPT plumbing.** Emulating the DSS already requires
  bidirectional data pins, status-line output, and edge-timed latching — the same
  primitives the DS301 needs (write-word strobe latch, nibble presentation on the
  status lines, an IRQ/ACK line). DS301 support is a new protocol personality on
  top of infrastructure Picovox already has.
- **You can lift the mono-only mixing limit.** Because such a platform can run an
  OPL emulation (Picovox already exposes OPL2LPT) *and* a PCM path at once, a
  DS301-compatible mode can maintain an OPL register file and a PCM stream and
  **mix them on-device in stereo** — where the original mixes synth + PCM only in
  mono (§11.3, §13). It can also present a *correct* OPL2 rather than the original's
  instrument-dropping emulation.
- **Still SPP-only on the wire.** None of this needs EPP/ECP; it is all standard
  parallel-port signalling, which is exactly why it can coexist with Picovox's
  other SPP device personalities and work on the widest range of hosts.

Combined with closed-loop flow control and on-device mixing, this yields a device
that is detection- and driver-compatible with the 1993 hardware, works on the
same broad range of systems, yet is free of the mono-only mixing restriction and
the original's timing fragility — a strictly better Digispeech, over plain SPP.

### 13.3 Minimum-viable compatibility subset (to run existing DOS/Windows software)

If the goal is the *smallest* implementation that lets an existing device (e.g.
Picovox) work with the original software — DOS games via `BMASTER`, and ideally the
Windows driver — here is the minimum, in dependency order. Everything rests on the
SPP core; the audio features layer on top.

**Tier 0 — mandatory transport & identity (without this, nothing works):**

1. **The SPP word channel** — write-word with the exact strobe sequence (§3.1) and
   nibble-read with the exact decode tables (§3.2).
2. **Detection loopback** — echo the probe patterns bit-exact (§5.2). If detection
   fails, `BMASTER`/the driver never proceeds. This is the single most important
   thing to get right first.
3. **Hardware handshake / IRQ** — drive the ACK/status line so the host's LPT IRQ
   fires for playback flow control (§5.3), or support the polling fallback.

**Tier 1 — core playback (covers most games/apps):**

4. **PCM playback** — 8-bit mono at minimum (the common Sound Blaster case); add
   16-bit and stereo for broader coverage. This is the workhorse (§6, §8).

**Tier 2 — the features your question named:**

5. **ADPCM.** For DOS games the relevant kind is **SB-ADPCM** (§11.6). The clean
   approach is to let the **SB-emulation layer decode ADPCM to PCM** and feed the
   device PCM — so a minimal *device* may need only the PCM path. Whether the
   *original* `BMASTER` decodes host-side or forwards coded data to the device is
   **[Open]**; if you must interoperate with the unmodified original `BMASTER`,
   confirm this by capture (§17.1) and, if it forwards coded data, implement the
   SB-ADPCM decoder on the device too.
6. **FM synthesis.** Accept AdLib/SB-style OPL **register programming** directed at
   the device and synthesize it (the device is OPL2-*functional*, §11.4).
   **Picovox already ships an OPL2 (OPL2LPT) core** — reuse it as the FM engine,
   fed by the FM register writes the host directs to the device. This is the piece
   that gives you music.
7. **Mono synth+PCM mixing** — sum the FM output and one mono PCM stream so music
   and effects coexist (§11.3). Trivial on an MCU; matches the original's mono
   mixer.

**Explicitly *not* required for this subset:** recording (§10, secondary),
stereo-synth mixing, the speech/LPC/CELP codecs and the native `PDIGI` educational
API (§11.7), µ-law/A-law/OKI/DVI/CVSD (unless a specific title needs them). Power
up/down commands (§18) should at least be *tolerated*.

**Bring-up order (do them in this sequence):** detection loopback → 8-bit mono PCM
tone → 16-bit/stereo PCM → FM register handling + synthesis → mono mixing → (only
if targeting the unmodified original `BMASTER`) ADPCM/coded-data handling. Validate
each tier against the real drivers before adding the next.

**Known vs. needs-capture.** The SPP mechanics, detection, and the *shape* of PCM
streaming are recovered here and can be built now. The **exact higher-level command
opcodes** `BMASTER`/the driver use — FM-register forwarding, format selection,
power commands — are **[Open]** and are exactly what the §17.1 bus capture recovers;
budget a capture-and-iterate pass for full `BMASTER` interop.

### 13.4 A superset mode: 16-bit stereo PCM *simultaneously* with OPL3 synthesis

An optional **extended mode** that goes *beyond* the original. It is **not**
backward-compatible with real Digispeech hardware and needs purpose-written drivers
or an SB16-class emulator (§14). Build it as an **opt-in second personality** so the
same device still serves the original drivers in legacy mode (§13.3, §13.4.6).
Design priorities, in order:

1. **Simultaneous up-to-16-bit-stereo PCM + OPL3 FM** — the headline capability the
   original lacks (its mixer forces mono once synth is active, §11.3).
2. **Optional ADPCM playback** covering the modes Sound Blaster through Sound
   Blaster 16 used.
3. **Maximum host compatibility: plain SPP is the required transport;** EPP/ECP only
   optional, only where it demonstrably helps (§13.4.2).
4. **Wire efficiency without hurting quality, SPP-compatibility, or latency** —
   device-side buffering, flow control, and on-the-fly compression (§13.4.3–4).

#### 13.4.1 Feature targets

- **Concurrent stereo PCM (8/16-bit, up to 44.1 kHz) + OPL3 FM**, summed in a stereo
  mix on the device (or pre-mixed by the emulator). This is the point of the mode.
- **OPL3-class FM** (18-voice / 4-operator, dual bank) — implemented as a soft synth
  core, on-device or host-side. (FM synthesis is patent-expired; §13.4.6.)
- **Optional ADPCM decode** so the host can send compressed samples for the
  SB…SB16 lineage: 4-bit / ~2.6-bit / 2-bit Creative-style ADPCM, and 4-bit
  IMA/DVI ADPCM (the SB16's compressed formats). All of these are old enough to be
  patent-expired, and IMA/DVI is royalty-free by design; §13.4.4 is the governing
  rule. The original device already decodes several of these, so keeping them is
  natural.
- Optional richer mixer + line-in to complete the SB16 analogy.

#### 13.4.2 Transport — SPP first; EPP/ECP only if it truly earns its place

- **Required: plain SPP** (the §3 primitives), working on any real register-level
  SPP port. Even 44.1 kHz/16-bit/stereo *raw* is reachable over SPP on a fast host
  (it is CPU-bound, not beyond the wire — §13.4 bandwidth discussion), so SPP does
  not block the *format*, only CPU headroom on slow hosts.
- **EPP/ECP: opt-in bonus only, and only where it adds real benefit.** Its benefit
  is narrow — cutting host CPU for *full-rate raw* PCM. But if you implement the
  device FIFO (§13.4.3) and compression (§13.4.4), the SPP path already has ample
  headroom on period hosts, so EPP/ECP often buys little. **Spend effort on the
  FIFO + compression (which help *every* host) before EPP/ECP (which helps only
  hosts that have a good implementation of it).** If offered, auto-negotiate it and
  always keep the SPP path fully functional.

#### 13.4.3 Device-side efficiency: FIFO + closed-loop flow control (pure SPP, low latency)

The biggest win is to stop the host babysitting individual samples. All of this is
plain SPP and adds no perceptible latency if sized right.

- **A modest FIFO + autonomous sample clock.** The device buffers incoming samples
  and clocks them to the DAC from its *own* rate reference; the host just keeps the
  FIFO fed in bursts. That removes the need for sample-accurate host timing, cuts
  CPU, and rides out OS scheduling jitter. **Size it for only a few milliseconds**
  (≈4–8 ms) so added latency stays imperceptible for games — at 44.1 kHz stereo-16
  that is only ~1.5 KB of buffer. A FIFO improves smoothness/robustness; pair it
  with compression for the raw-byte win.
- **A "room in FIFO" flag on a status line** (Disney-Sound-Source-style, but
  generalized). The host streams bytes back-to-back while the flag shows space, then
  pauses when it says full — **no fixed calibrated delays**, self-adapting to any
  host/port speed, and it eliminates the §7.2 timing fragility outright. Keep an
  IRQ ("FIFO low") as an optional additional refill trigger so both IRQ-driven and
  polled drivers work.
- **Tightest transfer loop.** With flow control in place, a fast host runs the write
  loop flat-out (no inter-byte delay) and a slow host self-paces — both correct. The
  per-word delays of §7 are only needed to satisfy the *original* delay-timed
  device.

#### 13.4.4 On-the-fly compression for 386/486-era hosts (royalty-free)

> **Hard rule (applies to the whole guide): use only royalty-free or
> patent-expired algorithms.** A goal of this document is that a fully **free,
> open-source, royalty-free** compatible device and driver can be built from it.
> Do **not** introduce any patent-encumbered codec or method. This is mainly a
> caution about *modern* algorithms one might be tempted to add; nearly everything
> the original device uses is decades old and long out of patent, so it is safe to
> reimplement — but any *new* choice must clear the same bar.

Fewer bytes on the wire means proportionally fewer strobes and less bit-banging —
and the encode cost can be made *smaller* than the transfer time it saves. Two
suitable coders, **both royalty-free** and decodable by a simple MCU/DSP:

- **G.711 companding (µ-law / A-law) — 2:1, cheapest.** Map 16-bit → 8-bit with a
  small lookup table (or a few shifts/compares per sample). Halves the wire traffic;
  encode is essentially free even on a 386. G.711 is a long-standing royalty-free
  ITU-T standard. Use it when CPU is scarce and you want a guaranteed, tiny-code
  win.
- **IMA / DVI ADPCM — 4:1, still cheap, better ratio.** 16-bit → 4-bit via a
  predictor + step-size table (~a dozen integer ops per sample). Quarters the wire
  traffic; comfortably real-time on a 386/486 alongside a game. IMA ADPCM was
  defined to be royalty-free, and it is the SB16's own compressed family, so it
  doubles as SB16-format support (§13.4.1). This is the recommended default.

Guidance:

- **The tradeoff to optimize** is *(encode ops per sample)* against *(port writes +
  waits saved by sending fewer bytes)*. A byte over SPP costs several port accesses;
  a table-based encode costs a few ALU ops — so compression is a net CPU win on slow
  hosts and always a bandwidth win. On a very fast host with a fast port, raw PCM is
  simpler; **expose both and let the driver pick per host**.
- **Keep it transparent to the ear.** µ-law and 4-bit IMA at these rates are
  perceptually fine for music and effects; reserve the very-low-bit ADPCM/speech
  coders for speech, not game audio.
- **Do not use any *currently* patent-encumbered codec** (the royalty-free rule
  above). Note patent status changes over time — MP3, for instance, is now
  patent-free, and many once-proprietary codecs have since become royalty-free,
  while some more recent perceptual/neural coders may still be encumbered; check
  current status rather than assuming. In any case this is moot here: heavyweight
  perceptual codecs are far too costly for a 386/486 and unnecessary — the simple
  companding/ADPCM family is both free and period-appropriate.
- The device must decode whatever the host sends; a modern MCU does µ-law/A-law and
  IMA ADPCM trivially, and these overlap the formats the original already handled.

#### 13.4.5 Two ways to drive the mode

1. **On-device OPL3 + on-device stereo mixer**, driven by a thin new driver that
   forwards OPL3 register writes and streams (optionally compressed) PCM — lowest
   host CPU, but you implement OPL3 and the mixer in the device.
2. **Emulator-rendered (recommended for breadth):** an SB16/SBEMU-style emulator
   (§14) does OPL3 + SB16-DSP emulation *and* the mix in host software and streams a
   single pre-mixed 16-bit stereo PCM stream (optionally compressed per §13.4.4);
   the device is then just a fast, flow-controlled stereo PCM sink. This reuses the
   §14 backend and sidesteps every mixing/duplex limitation by construction.

#### 13.4.6 Patents / royalties (engineering guidance, not legal advice)

- **FM synthesis:** the foundational FM-synthesis patent expired in the mid-1990s;
  OPL2/OPL3-*compatible* synthesis is implementable without royalties today, and
  open reimplementations exist. A register interface is functional, not a protected
  creative work.
- **Codecs:** G.711 µ-law/A-law and IMA/DVI ADPCM are royalty-free; the 1980s
  ADPCM variants are old enough that any patents have long expired. Prefer
  **G.711 and IMA/DVI** to stay clearly clear.
- Treat this as general guidance and verify current status for your jurisdiction
  and product before shipping.

#### 13.4.7 Identity / coexistence

Give the extended mode a detection/identity handshake the *original* drivers never
issue, so a dual-mode device is safe: original Digispeech drivers see only the
legacy device (§5.2), while new drivers explicitly opt into the SB16-class mode.
Specify that handshake as part of the superset definition.

---

## 14. Programming the device as a modern Sound Blaster emulator backend

The original `BMASTER` only works with real-mode games and needs VCPI; it fails
on protected-mode / DOS-extender titles (DOS/4GW etc.). The practical path
forward for broad game support is a **modern Sound Blaster emulator** — in the
lineage of **SBEMU** and **VSBHDA** — that traps SB/AdLib access and renders
audio in software on a modern CPU, using the Digispeech (or a compatible device)
purely as a **PCM output sink**. This section says how to write that backend.

### 14.1 Why this sidesteps every limitation above

A modern emulator does the OPL synthesis and the FM+digitized **mixing itself, in
software**, producing a single already-mixed PCM stream. On any modern CPU that
is trivial (unlike 1993). Therefore:

- The device **only needs to be a fast, reliable PCM DAC** plus detection. It does
  **not** need on-device FM or a mixer.
- The **FM/PCM mixing constraint disappears** (including the mono-only limit),
  because the host mixes before sending — the device just plays the finished mix.
- **Protected-mode games work**, because the emulator (not the device) owns the
  trapping and runs in an environment that supports them.

So for emulator authors, the entire "hardware vs. host FM" question (§11.4) is
moot: implement the **PCM output backend** and you are done.

### 14.2 What the backend must implement (minimum)

1. **Detect + init** the device (§5) and select an LPT base + IRQ.
2. **Configure format/rate** (§6): pick a fixed output format the emulator mixes
   into — e.g. the device's best common mode (stereo 16-bit if the target model
   supports it, else 8-bit mono) at a rate the wire can sustain (see §14.3).
3. **A block-streaming output routine** built on write-word (§3.1/§8): hand it a
   buffer of mixed PCM; it streams sample words with the sample-data control
   nibble, refilling on the device IRQ.
4. **Backpressure handling**: respect the device IRQ / word-rate. If the wire
   cannot keep up with the requested SB sample rate, downsample in the mixer to a
   rate it *can* sustain rather than overrunning.

That is the whole hardware-facing surface. Everything else (OPL2/OPL3 emulation,
SB DSP command emulation, ADPCM decode, DMA emulation, mixing, volume) lives in
the emulator's portable core, exactly as in SBEMU/VSBHDA today — you are adding a
new **output driver** alongside their AC'97/HDA outputs.

### 14.3 Practical constraints to design around

- **Throughput.** Bit-banged SPP realistically sustains only modest stereo-16-bit
  rates on period hardware; on a modern host driving a real DS301 you are still
  limited by the *device's* word-acceptance rate (§7). Prefer a rate the device
  reliably accepts (e.g. 11–22 kHz) and let the emulator resample. If you also
  build the compatible device of §13 with an **EPP/ECP** fast path, expose it here
  for full-rate stereo.
- **Latency / buffering.** Use the device's onboard buffer + a host-side ring;
  size the block so one device IRQ period is comfortably serviceable under your
  OS. Bigger device FIFO (§13) directly improves tolerance here.
- **Calibration.** Reuse the `DGSETUP` idea: measure the largest safe transfer
  rate at startup for the actual host+device, don't hardcode delays.
- **One output, pre-mixed.** Never try to use any residual on-device FM in this
  design; feed the device a single mixed PCM stream. This is what makes
  simultaneous music+effects "just work."

### 14.4 Startup calibration procedure (largest safe transfer rate)

This is the single step that most determines whether a given host + parallel port
will work at all, and how fast it can stream. It generalizes what `DGSETUP` did
(PIT-timed delay calibration plus a functional sound test) to any host. Two
*independent* things must be established.

**(1) A real-time delay basis — so timing is CPU-speed independent.** Express the
inter-strobe delays (Δ1..Δ3 and the read delay) in **real microseconds**, never
in raw loop counts. Establish the conversion at startup by measuring how many
busy-loop iterations fit into a known real-time interval taken from a
**fixed-frequency clock**: PIT channel 2 under DOS (program `0x43`, gate via
`0x61`, read the 1.193182 MHz counter — the method `DGSETUP` uses), or any
monotonic high-resolution timer on a modern OS. From that ratio you can hit any
target delay on any CPU. This is what stops a faster machine from clocking the
device too quickly.

**(2) The device's minimum safe per-word delay — empirical, using echo as the
oracle.** Step (1) tells you how to hit *X* microseconds; it does not tell you
what *X* the device needs on *this* port. Discover it by searching the delay
against the device's own loopback:

- Start with a generous (slow) delay known to work.
- Run the detection echo test (§5.2): write known 16-bit patterns with write-word,
  read them back with nibble-read, compare **bit-exact**. Use patterns that
  exercise every line — `0xAAAA`, `0x5555`, `0xFFFF`, `0x0000`, and walking-ones.
- Shorten the delay and repeat, ideally as a binary search. Require many
  consecutive clean passes at each candidate to catch *marginal* timing, not just
  a lucky one.
- Take the shortest delay that still passes reliably, then **back off by a safety
  margin** (e.g. 25–50 %) to absorb OS scheduling jitter and port variation. That
  becomes the streaming delay.

**Closed-loop shortcut (preferred for new hardware).** If the target device
exposes a BUSY/ready handshake line (a compatible device per §13/§7.2), *poll it*
instead of using fixed delays — calibration collapses to "wait for ready, don't
guess," and the result is inherently robust to host and port speed. Fixed-delay
calibration above is only needed to drive the *original* open-loop device or an
original-faithful reimplementation.

**Fail-safe / timeout.** Bound every probe with a timeout, exactly as `DGSETUP`
does (it aborts if its sound/communication test runs past a time limit). If the echo
never passes at any delay — or the port does not respond at register level at all,
as with a USB→parallel adapter that does not expose real SPP registers — report
the port as **unusable** and move on, rather than hanging or emitting garbage.

**When to run / caching.** Historically this was re-run on any CPU-speed (turbo)
change. On a modern host, once per session at startup is enough; cache the result
keyed by the port address.

**Output.** Either the decision "use the closed-loop handshake," or a concrete set
of per-phase delays (Δ1..Δ3, read delay) that the streaming path (§8, §14.2) will
use. This directly fixes your maximum sustainable sample rate: if it falls below
your target Sound Blaster rate, **resample down in the mixer** (§14.3) rather than
overrunning the device.

### 14.5 Recommended shape of the effort

- Treat the **PCM output backend** as a small, well-specified module: `detect()`,
  `set_format(rate, channels, bits)`, `write_block(pcm)`, `on_irq()/poll()`,
  `close()`.
- Validate it first with the §5 echo test and a §8 tone playback before wiring it
  under an emulator core.
- Then integrate as a new device target in an SBEMU/VSBHDA-style project; the
  emulator core already produces the mixed PCM you need.
- If you are *also* building compatible hardware, implement §13's EPP/ECP + FIFO +
  optional real OPL so the *same* device serves both the legacy drivers and the
  modern emulator optimally.

---

## 15. Quick-start checklist

- [ ] Resolve LPT base (BIOS Data Area `0040:0008`) and set DATA/STATUS/CONTROL.
- [ ] Implement **write-word** (§3.1) and **nibble-read** (§3.2) with adjustable Δ.
- [ ] Run the **echo-test detection** (§5.2); confirm `0xAAAA/0x5555/0x0F0F/0xF0F0`.
- [ ] Calibrate Δ (largest safe transfer rate).
- [ ] Send a **play command** (§6) with a chosen format code (§6.1).
- [ ] Stream a test tone; refill on **IRQ** (§8).
- [ ] (Optional) Recording via nibble-read (§10).
- [ ] (Emulator) Wrap the above as a PCM output backend (§14).
- [ ] (Hardware) Add FIFO + on-device mix + EPP/ECP (§13).

---

## 16. Evidence appendix (annotated)

All offsets are into the **load image** (post-MZ-header) of the named binary.
Disassembly is 16-bit real mode unless noted. These are the load-bearing
excerpts; the reasoning in the body is derived from them.

### 16.1 Port variables and the write-word primitive — `DS301.SYS`

Port setup **[@0x545c]**: `DATA/STATUS/CONTROL` are `BASE`, `BASE+1`, `BASE+2`:

```
mov ax,[bp+4]         ; BASE (validated candidate)
mov [0x352],ax        ; DATA
mov [0x354],ax
inc ax
mov [0x356],ax        ; STATUS = BASE+1
mov ax,[0x352]; add ax,2
mov [0x358],ax        ; CONTROL = BASE+2
```

Write-word **[@0x3e9a]** — the canonical strobe sequence (low byte, control
0x0E, raise strobe to 0x0F, high byte, drop strobe):

```
out DATA, al                 ; low byte
mov al,[0x35a]; add al,0x0e  ; control base = 0x0E
out CONTROL, al
loop Δ1 ; loop Δ1
or al,1 ; out CONTROL,al      ; 0x0F -> latch low byte (STROBE up)
... ; delay
xchg ah,al ; out DATA,al      ; high byte
... ; delay
mov al,ah ; xor al,1 ; out CONTROL,al  ; 0x0E -> latch high byte (STROBE down)
```

The Windows VxD (`VDS301.386`, 32-bit) contains a byte-identical routine
**[@0x175c]** (`add al,0x0e` / `or al,1` / `xor al,1`, delays from `[0x83c4/
0x83cc/0x83d0]`), and `DS301.DRV` (NE) the same at **[@0x21d0]** — the
cross-check that fixes the sequence.

### 16.2 Block streaming and the IRQ refill — `DS301.SYS`

Block writer **[@0x3ede]**: set control stream-nibble once, then a tight
`lodsw` / `out DATA` loop with delays — contiguous sample words. Streaming ISR
**[@0x4cc6]** computes consumed vs. written position and refills; PIC-mask helper
**[@0x6154]** enables the device IRQ (`in 0x21/0xA1`, set/clear the IRQ bit);
ISR EOIs to `0x20/0xA0`.

### 16.3 Nibble-read and the decode tables — `DS301.SYS`

Read primitive **[@0x40c0 / @0x416c]**: `write DATA=nibble_index`, delay,
`in STATUS`, `shr al,3`, `xlatb` through a 32-entry table; four nibbles per word.
The two tables (low-nibble at image `[0x2f4]`, high-nibble at `[0x314]`):

```
LOW  (index = (status>>3)&0x1f):
 01 09 05 0d 03 0b 07 0f 01 09 05 0d 03 0b 07 0f
 00 08 04 0c 02 0a 06 0e 00 08 04 0c 02 0a 06 0e
HIGH (= LOW << 4):
 10 90 50 d0 30 b0 70 f0 10 90 50 d0 30 b0 70 f0
 00 80 40 c0 20 a0 60 e0 00 80 40 c0 20 a0 60 e0
```

These tables define exactly which status line carries which returned data bit; a
compatible device must drive its nibble so that this decode yields the intended
value.

### 16.4 Detection echo test — `DS301.SYS`

**[@0x439c / @0x54c6]**: knock/wake writes of `0xF0F0`, `0x0F0F`, rolling
values (each looped up to 0x80), then echo probes `0xAAAA`, `0x5555`, `0x0F0F`,
`0xF0F0` via write-word, each read back via nibble-read and compared for
equality. The routine's diagnostic messages — reporting that it is probing for the
adapter, that no adapter was found, or that one was located on a given LPT and IRQ
— confirm the purpose.

### 16.5 Format classifier and command block — `DS301.SYS`

Classifier **[@0x1e74]** maps (channels, bits, rate) → format code
(`0x00/0x03` mono 8/16-bit; `0x48/0x49/0x4A` stereo). Command builder
**[@0x1c40]** assembles the play message (format, buffer base, rate, block size
`0x1000`) sent with the command control-nibble variant.

### 16.6 Code/coefficient download — `DS301.SYS`

**[@0x4526]**: iterates `{target address, length ≤ 0x79, data}` records with a
`0xCE01` loadable marker, writing into addressable device memory — the mechanism
by which speech engines and other DSP images are installed.

### 16.7 SB/AdLib emulation — `BMASTER.EXE` (32-bit VCPI)

Trap install: builds an I/O-permission bitmap with `bts` for ports `0x388/0x389`
and the SB range; a per-port handler table at `[0x400 + port*4]` routes
`0x388→0x141c`, `0x389→0x142c`. The OPL handlers store the register index/data
into a host shadow block near `[0x1670]` (they do **not** bit-bang each write to
the LPT). An enable/disable-trapping routine also traps PIC ports `0x20/0x21` to
virtualize the SB IRQ. Synthesis-style tables are present (16-bit sine peaking at
`0x7FFF`; exponential `2^(-n/8)` antilog). The final consumer of the OPL shadow
was not traced to a definitive endpoint (§11.4).

### 16.8 Windows path — `DS301.DRV` (NE) + `VDS301.386` (LE)

`DS301.DRV` declares Wave and MIDI capability for the Port·Able Sound device,
contains the same write-word/nibble-read primitives, and includes control-panel
labels for enabling AdLib and Sound Blaster emulation. `VDS301.386` traps
`0x388/0x389`
(via VMM `Install_IO_Handler`), latches the OPL register, manages LPT-port
trapping, and carries the byte-identical LPT send routine — confirming the same
protocol under Windows.

---

## 17. Open questions (honest limits of this analysis)

- **[Open] The DOS `BMASTER` FM division of labor** (§11.4). The manual establishes
  that the *device* performs the FM synthesis, but how much OPL state `BMASTER`
  processes host-side before handing off — and the on-wire FM register/command
  encoding — is unresolved. Does not affect the guidance; emulator authors pre-mix
  on the host and ignore on-device FM entirely (§14).
- **[Open] Exact device-side meaning of the command "buffer base" words** and the
  precise onboard buffer depth. The IRQ-flow-control model is clear; the buffer
  size is inferred (block size `0x1000`) rather than read from silicon.
- **[Open] DSP image/ISA format** of the downloaded engines (§9) — the transport
  is decoded; the payload instruction set is not.
- **[Open] Full format-code bitfield semantics** (§6.1) beyond the observed
  mono/stereo/width mapping.
- **[Hypothesis — must be tested] Flawless simultaneous FM+PCM with full original
  compatibility** (§13). Well-reasoned but unproven; the binding unknown is
  whether the original drivers emit both streams concurrently or serialize them.

### 17.1 Validation / test plan

These findings are from static analysis plus corroboration by independent public
hardware demonstrations. Treat the list above as a test plan. In rough priority:

1. **Original-hardware bus capture (best).** Put a logic analyzer on the LPT lines
   and record three sessions: (a) detection, (b) a plain PCM tone, (c) an
   FM-only case, and (d) a game that attempts FM music + digitized effects. This
   single experiment confirms the calibrated timing and buffer/flow-control depth,
   settles the §11.4 DOS division (FM-only showing *sparse OPL register writes* ⇒
   `BMASTER` drives the device's own FM synth; a *continuous PCM stream* ⇒ it
   synthesizes host-side), and reveals whether `BMASTER` serializes FM and PCM or
   interleaves them — which is exactly the fact the §13 simultaneity claim hinges
   on.
2. **Iterative bring-up (if no original hardware).** Implement the SPP protocol on
   the target device; verify **detection** against the original drivers, then
   **plain PCM playback** against real software, *before* attempting mixing. Only
   then add on-device FM + PCM mixing and test it under (a) the original driver
   stack and (b) a purpose-written driver, separately — so you can tell a device
   limitation apart from a host-driver limitation.
3. **Confirm the remaining Open items** (FM locus, buffer semantics, download image
   format, format-code bitfields) as they become observable during bring-up.

Document what the tests reveal; expect this static analysis to be *correct on the
mechanics but incomplete on the device-internal and forward-looking details.*

---

## 18. Cross-check against the manufacturer manual

The reverse-engineered findings were checked against *A Guide to Using Digispeech
Plus* (DSP Solutions, ©1994). Summary: **the RE mechanics hold up; the manual
confirms the feature set, pins down exact numbers the binaries only implied, and
corrected one over-strong conclusion (the FM+PCM "cannot mix" claim).**

**Confirmed by the manual:**

- **Transport / resources.** Standard parallel port only; the resource listing
  records that **no hardware DMA channel and no memory address space** are used.
  The manual lists I/O at `278–27Bh`, `378–37Bh`, or `3BC–3BEh` and interrupt
  **IRQ5 or IRQ7** — but these are **host-side facts, not device settings** (see box
  below). Matches §2/§5/§7 (SPP-only, IRQ-driven, no host DMA).

  > **The port address and IRQ belong to the host, not the device.** The device
  > has no notion of "its" I/O address — it simply responds to strobes and drives
  > the status/handshake lines on whatever LPT port it is physically plugged into.
  > Likewise it does not "use" an IRQ number; it asserts the ACK/status line, and
  > the *host's* parallel-port hardware converts that into whatever interrupt that
  > port is wired to (conventionally LPT1 → IRQ7, LPT2 → IRQ5). The `278/378/3BC`
  > and `IRQ5/IRQ7` menu is therefore a **driver/host resource choice**, possibly
  > limited by the software, and imposes **no requirement on the device beyond
  > being SPP-compatible with a functioning interrupt line on that port.** A
  > compatible reimplementation inherits whatever LPT it is attached to and should
  > make no assumption about the base address or IRQ number — it discovers the base
  > (BIOS Data Area, §5.1) and services whatever interrupt the port raises.
- **PCM playback.** *Stereo:* 8/16-bit linear or 8-bit µ-law at **11.025 / 22.05 /
  44.1 kHz** only. *Mono:* 8-bit linear/µ-law/A-law or 16-bit linear, **4 kHz–44.1
  kHz continuous.** Confirms §6.1's 8/16-bit mono/stereo and rate range; *new
  detail:* stereo is restricted to three rates.
- **ADPCM playback (game-relevant, §11.6).** Mono DVI(IMA) 4-bit, OKI 4-bit, and
  Sound Blaster ADPCM at 4 / 2.6 / 2 bits per sample (Creative's 2:1 / 3:1 / 4:1
  ratios), 4 kHz–44.1 kHz. Confirms the SB-ADPCM priority.
- **Music synthesis.** Described as functionally equivalent to a two-operator,
  ~11-voice OPL2 and as accepting Sound Blaster/AdLib-style FM register
  programming. Supports the §11.4 conclusion: OPL2-*functional* (DSP firmware),
  **no discrete OPL chip** (the stated ~11-voice count is not a real OPL2's).
- **Recording is secondary/limited** (as prioritized here): **mono only**, 8 kHz &
  11.025 kHz, 8/16-bit linear/µ-law/A-law and DVI/OKI/SB ADPCM. Confirms §10.
- **Codec suite** (§11.6): A-law, µ-law, IMA/DVI ADPCM, SB ADPCM, OKI ADPCM, CVSD;
  voice coders **LPC & CELP = playback-only**, **RELP = record + playback**.
- **SB emulation defaults** (setup screen): **I/O 220h, IRQ 7, DMA 1** — the
  *emulated* SB resources BMASTER virtualizes (the device itself uses no DMA).

**Corrected by the manual (important):**

- **FM + PCM *can* be mixed — in mono.** The mixer offers *Stereo Digital + Line-In*
  **or** *Mono Synth + Mono Digital + Line-In*. My earlier "cannot mix at all" was
  wrong; the real limit is **no stereo-digital-plus-synth** mode. §11.3 is rewritten
  accordingly, and it explains why mono games (Wolfenstein 3D) mixed fine while
  stereo/other titles did not.
- **FM synthesis is a device (DSP) capability**, not purely host software — §11.4
  updated. (The vendor attributes synthesis to the device and lists "Synthesized
  Music" as an output-mix *source*.)

**Blind spots the manual revealed (now noted in the guide):**

- **An output mixer with defined modes**, plus always-available **stereo Line-In**
  passthrough into the output mix; **master volume 0–94.5 dB**; **AGC** on the mic
  input. (Previously unmodeled.)
- **Power management is part of the protocol:** the host puts the device in a
  **power-down/"hold"** state when no sound plays (~300 mW saved) and issues a
  **power-up command** to resume; the device restores internal state and avoids
  power-on popping. ⇒ a compatible device/driver should implement **power-down and
  power-up commands**. *(Command encodings [Open] — recover via §17.1.)*
- **Native file formats** carry an **internal header (not the extension)**: `.LIN`
  PCM, `.U` µ-law, `.A` A-law, `.DVI`, `.OKI`, `.CVS`, `.RLP` (RELP), `.PAC`
  (Digispeech std), `.FIX` (Digispeech fixed), plus `.WAV`/`.VOC`; `DigiPlay` also
  takes **ASCII text** (via the First Byte TTS engine) and raw stereo PCM.

**Net:** nothing in the manual contradicts the recovered SPP protocol mechanics
(§3–§10). The corrections are about *device capabilities above the wire* (a
mono mixer and on-device FM), which strengthen rather than undermine the
"better Digispeech" case (§13): the enhancement is to lift the **mono-only**
mixing to **stereo synth+digital**, not to add mixing from nothing.

### 18.1 Cross-check against the v4.00 / Windows 95 software (`DS3XX`)

A later release (**v4.00**, "Parallel Audio v4.05") was also examined
(`DS3XX.SYS`/`.DRV`, `VDS3XX.386`, updated `BMASTER`, `PDIGI`, more `PDRV*`
overlays, and `311ADD.DOC`). Findings:

- **The protocol is unchanged.** `DS3XX.DRV` and `VDS3XX.386` carry the *same*
  write-word strobe and nibble-read signatures as the v2.0 binaries. The single
  `DS3XX` ("DS-3-anything") driver family spans DS301/DS311 and identical wire
  behavior — strong evidence the SPP protocol here is stable across the product
  line and across versions.
- **Still OPL2 / SB-class — no OPL3, no SB16.** The Windows driver declares Wave,
  MIDI, Mixer, and Aux capabilities with an AdLib-class synth; nothing referencing
  OPL3 or SB16 appears anywhere. This confirms the §13.4 "SB16 parity" mode is a
  genuine *superset*, not something latent in the originals.
- **New:** the v4.00 Windows driver explicitly exposes a **mixer** and an **aux
  (line-in)** input to the OS, with controls for synth volume, MIDI-out volume and
  mute, and a master volume — matching the manual's audio-mixer spec (§18), so the
  mixer is real and OS-visible.
- **A *second, distinct* simultaneous-stream limit:** the v4.00 documentation notes
  that obtaining full-duplex sound under Windows requires the wave/synth (MIDI)
  mixing option to be turned off. Here **full duplex = simultaneous playback *and
  recording***, so this is about play-vs-record, **not** the same thing as the
  §11.3 output-mix rule.
  Read together, the two constraints show the device has a **limited number of
  simultaneous audio paths**: it can do *(a)* stereo digital playback, or *(b)*
  mono-synth + mono-digital mixed playback (§11.3), or *(c)* full-duplex
  play+record — but it cannot stack these arbitrarily (e.g. no synth-mix *and*
  record at once). A superset device with more DSP/mixer resources (§13.4) would
  lift all of these.
- **Adds Windows 95 support** (same driver model) and generalizes the DOS `PDIGI`
  educational-audio path (LPC/CVSD/etc.); no change to the game-relevant PCM/SB/FM
  behavior this guide focuses on.

---

*Provenance and licensing posture: the facts in this document were derived by
reverse-engineering and analysis of the original DOS/Windows 3.x/Windows 95 driver
and utility binaries (`DS301.SYS`/`DS3XX.SYS`, `SOUND301.EXE`, `PDIGI.EXE`,
`BMASTER.EXE`, `DGSETUP.EXE`, `DS301.DRV`/`DS3XX.DRV`, `VDS301.386`/`VDS3XX.386`)
and cross-checked against the manufacturer's user manual. It reproduces **no source
or binary code** from the original product and **no verbatim passages** from the
manual or the software's text; capabilities, specifications, numbers, and behaviors
are stated as facts in the author's own words (facts and interface details are not
themselves copyrightable). The guide is written so that a **free, open-source,
royalty-free** compatible device and driver can be implemented from it: every
algorithm it recommends is royalty-free or long patent-expired, and it explicitly
disallows introducing any patent-encumbered method (§13.4.4/§13.4.6). Product,
company, and trademark names are used only for identification and interoperability.
Implementers should perform their own patent/trademark diligence for their
jurisdiction and product; nothing here is legal advice.*
