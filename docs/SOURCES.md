# Technical references and upstream projects

These are references/upstreams, not vendored dependencies unless explicitly stated.

- Open MUCOM88 — https://github.com/onitama/mucom88
  - MML compiler/player; macOS/Xcode support exists upstream.
  - Upstream software license: CC BY-NC-SA 4.0 plus component-specific terms.
- 88play — https://github.com/digital-sound-antiques/88play
  - Public sample catalog identifies Koshiro `BARE1_MML` and `BARE2_MML` tracks.
  - In particular `BARE1_MML/stk023.muc` is **The Street of Rage**.
- ValleyBell/MidiConverters — https://github.com/ValleyBell/MidiConverters
  - `Mucom88_Format.txt` is a useful description of compiled MUCOM88 sequence data.
  - `mucom2mid.c` is an independent GPLv2 implementation used as a behavioral
    cross-check; its source is not copied into this MIT project.
- gsaurus/sor-disassemblies — https://github.com/gsaurus/sor-disassemblies
  - IDA-derived disassembly for Streets of Rage titles; confirms the SoR1
    `SoundDriverLoad` Kosinski block and loader addresses.
- Clownacy/accurate-kosinski — https://github.com/Clownacy/accurate-kosinski
  - Reference implementation for Kosinski semantics.
- VGM specification — https://vgmrips.net/wiki/VGM_Specification
- Plogue chipsynth MD — https://www.plogue.com/products/chipsynth-md.html
- Inphonik RYM2612 — https://www.inphonik.com/products/rym2612-iconic-fm-synthesizer/

## Copyrighted inputs

ROMs, commercial game music, VGM packs, extracted PCM, and original MML are
not committed here. The toolkit operates on user-supplied/local files.
