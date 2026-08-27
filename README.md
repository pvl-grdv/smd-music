# smd-music

Tools for reconstructing **editable Sega Mega Drive / Genesis music projects**
from the best source available: MUCOM88 MML/MUB, game ROM sequence data, or
VGM/VGZ hardware logs.

The goal is deliberately **more than MIDI**.

A useful DAW reconstruction needs:

- editable note/event data;
- original YM2612 FM patches;
- PSG provenance;
- PCM/DAC assets;
- loop/modulation/pan information;
- a manifest connecting those assets to DAW tracks.

MIDI is one export, not the internal source of truth. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Current state (v0.1)

Working now:

- inspect Mega Drive ROM headers;
- recognize the known Streets of Rage 1 World/JUE rev-00 ROM;
- extract its Kosinski-compressed Z80 sound-driver image;
- inspect Genesis VGM/VGZ streams;
- capture/deduplicate YM2612 four-operator patch states at key-on;
- export native RYM2612 `.rym2612` presets directly, plus `.dmp` and `.tfi`;
- parse MUCOM88 32-byte `voice.dat` banks and export their original FM voices directly to RYM2612;
- extract VGM PCM data bank;
- reconstruct an exact 44.1 kHz unsigned-8-bit YM2612 DAC register timeline;
- parse MUCOM88 MUC metadata (`#voice`, `#pcm`, title, composer, ...);
- compile `.muc -> .mub` through either an installed Open MUCOM88 CLI or optional `mucom88-js` Node backend;
- initial clean-room decoder for compiled MUCOM88 sequence data to Type-1 MIDI;
- puts global tempo changes in MIDI track 0 and preserves native MUCOM patch IDs as markers instead of pretending they are General MIDI programs.

In progress:

- decode SoR1's **ROM-native song sequence format** after the Z80 driver loads;
- normalize MUCOM/ROM events into a common Song IR;
- validate generated native RYM2612 presets in current AU builds and add richer Furnace/VGI interchange;
- per-track GarageBand manifests and optional AU setup guidance;
- Sonic/SMPS adapter after the Streets of Rage path is solid.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Examples

### Inspect the Streets of Rage ROM

```bash
smd-music rom-info "Streets of Rage.gen"
```

Known SoR1 rev-00 MD5:

```text
569cfec15813294a8f0cf88cccc8c151
```

### Extract its Z80 sound driver

```bash
smd-music sor1-driver "Streets of Rage.gen" -o work/sor1-z80.bin
```

Use `--full` to keep the complete `0x1F00` decompressed block rather than only
the `0x1EC7` bytes copied into Z80 RAM by the game.

### Make a VGM/VGZ DAW asset pack

```bash
smd-music vgm-assets "01 - The Street of Rage.vgz" -o out/street
```

This currently writes:

```text
out/street/
├── manifest.json
├── ym2612_patches.json
├── fm_patches/             # .rym2612 + .dmp + .tfi per unique YM2612 patch
├── pcm_bank_00.bin          # when present
└── dac_timeline_u8.wav      # when DAC stream is present
```

The WAV is the digital YM2612 DAC byte timeline, **not** an analog-emulated
Mega Drive recording. DMP patches preserve FMS/AMS/per-operator AM and are a
better interchange format than plain MIDI for YM2612-aware tools; TFI is also
exported for broad compatibility. Native `.rym2612` JUCE-state presets are generated
directly, so **RYMCast is not required**.

### Best path for Koshiro's published MUCOM88 source tracks

For a source-faithful note sequence, compile the MUC to MUB and decode the actual
MUCOM sequence commands:

```bash
smd-music muc-midi stk023.muc -o out/The_Street_of_Rage_source.mid --keep-mub work/stk023.mub
```

The compiler backend is selected automatically. Native Open MUCOM88 is preferred.
As a cross-platform fallback in a checkout of this repo:

```bash
npm install --no-save mucom88-js
smd-music muc-midi stk023.muc -o out/The_Street_of_Rage_source.mid
```

For the **original MUCOM FM voice bank**, no compiler is needed:

```bash
smd-music voice-rym2612 stkvoice.dat -o out/rym2612
# or only programs referenced by a track:
smd-music voice-rym2612 stkvoice.dat -o out/rym2612 --program 58 --program 106 --program 192
```

By default this keeps Sega/MUCOM total levels literal and sets MIDI velocity
sensitivity to zero. `--playable-velocity` reproduces the long-standing
`mucom88torym2612` convention of adding velocity response to carrier operators.

`stk023` is the published MUCOM88 sample for **The Street of Rage**. This path
is preferred over VGM note reconstruction because the compiled sequence still
contains explicit note lengths, loops and instrument events.

The Koshiro sample MML/voice/PCM files are **not redistributed by this repo**;
use the upstream Open MUCOM88/88play sources according to their licenses.

## GarageBand / real Mega Drive sound

A Standard MIDI file cannot carry a native YM2612 four-operator patch. For a
close-to-hardware editable GarageBand project, use the exported MIDI for notes
and load the extracted FM patches into a compatible Audio Unit such as
**Plogue chipsynth MD** or **Inphonik RYM2612**. For RYM2612, `smd-music` now
generates the native XML preset format itself; the separate RYMCast application
is not part of the required workflow. PCM/DAC material can go to
GarageBand Sampler/drum tracks.

The long-term `daw-pack` output will describe this mapping explicitly so one
song can be reconstructed as a set of editable DAW tracks rather than a flat
General MIDI approximation.

## Data / legal note

This repository contains tooling only. Do not commit commercial ROMs, ripped
VGM packs, extracted game samples, or third-party MML unless you have the
rights and the applicable license permits redistribution. See
[`docs/SOURCES.md`](docs/SOURCES.md).
