# Architecture

`smd-music` deliberately does **not** use MIDI as its internal truth.

The target is a loss-aware pipeline:

```text
MUC/MUB ─┐
ROM ─────┼──> source adapters ──> Song IR ──┬─> DAW MIDI
VGM/VGZ ─┘                                  ├─> YM2612 patch bank
                                            ├─> PCM/DAC assets
                                            ├─> DAW manifest
                                            └─> future Furnace export
```

## Source priority

For reconstruction quality, prefer the highest-level source available:

1. **Author/source MML (MUCOM88)** — explicit notes, lengths, loops, instruments.
2. **ROM sequence data** — game driver's native command stream.
3. **VGM/VGZ** — sample-accurate hardware register log; excellent for validation,
   exact chip patch state and PCM/DAC, but note intent must be reconstructed.
4. **Audio transcription** — last resort.

This is why VGM remains valuable even when MML exists: it tells us what the
actual Mega Drive hardware received after the game's conversion/driver path.

## Why not just MIDI?

Standard MIDI cannot represent a native YM2612 patch. It has no fields for
four-operator algorithm, feedback, detune/multiple, TL, AR/DR/SR/RR, SSG-EG,
or the Mega Drive DAC data bank. General MIDI Program Change is only a hint to
a DAW's own instrument library.

For GarageBand the useful reconstruction package is therefore:

- clean Type-1 MIDI for editing notes/regions;
- YM2612 patch definitions for an AU such as chipsynth MD / RYM2612;
- PCM/DAC WAV or raw data for Sampler/drum tracks;
- a manifest mapping source channels/patches/assets to DAW tracks.

## Streets of Rage 1

The known World/JUE rev-00 ROM (`MD5 569cfec15813294a8f0cf88cccc8c151`)
contains a Kosinski-compressed Z80 sound driver at ROM offset `0x795A2`.
The stream expands to `0x1F00` bytes; the 68000 loader copies `0x1EC7` bytes
into Z80 RAM. The extractor validates those sizes.

The next ROM milestone is decoding the driver's banked sequence format so the
remaining SoR1 tracks can be exported without reverse-inferring notes from VGM.

## MUCOM88 path

Open MUCOM88's CLI can compile `.muc` to `.mub`:

```bash
mucom88 -c -g -o song.mub song.muc
```

`smd-music muc-compile` wraps that command and supplies `#voice`/`#pcm`
companions when present. `smd-music mub-midi` then decodes the compiled MUCOM88
sequence into editable MIDI.

The original Koshiro sample sources are *not* vendored in this repository.
