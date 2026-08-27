from __future__ import annotations

import hashlib
from collections import OrderedDict

from .ir import FmOperator, FmPatch


# OPN register slot ordering is 1, 3, 2, 4.
_SLOT_TO_LOGICAL_OPERATOR = {0: 1, 1: 3, 2: 2, 3: 4}


def _channel_location(channel: int) -> tuple[int, int]:
    if not 0 <= channel < 6:
        raise ValueError(channel)
    return (0, channel) if channel < 3 else (1, channel - 3)


class Ym2612State:
    """Track enough YM2612 register state to snapshot four-operator patches."""

    def __init__(self) -> None:
        self.reg = [[0] * 256 for _ in range(2)]
        self.patches: "OrderedDict[str, FmPatch]" = OrderedDict()

    def write(self, port: int, register: int, value: int, sample: int) -> None:
        self.reg[port][register] = value
        if port == 0 and register == 0x28 and (value & 0xF0):
            code = value & 0x07
            mapping = {0: 0, 1: 1, 2: 2, 4: 3, 5: 4, 6: 5}
            if code in mapping:
                self._record_patch(mapping[code], sample)

    def _operator_value(self, port: int, local_ch: int, base: int, slot: int) -> int:
        return self.reg[port][base + (slot * 4) + local_ch]

    def snapshot(self, channel: int, sample: int | None = None) -> FmPatch:
        port, local = _channel_location(channel)
        b0 = self.reg[port][0xB0 + local]
        b4 = self.reg[port][0xB4 + local]
        operators: list[FmOperator] = []
        raw_signature: list[int] = [b0, b4]
        for slot in range(4):
            r30 = self._operator_value(port, local, 0x30, slot)
            r40 = self._operator_value(port, local, 0x40, slot)
            r50 = self._operator_value(port, local, 0x50, slot)
            r60 = self._operator_value(port, local, 0x60, slot)
            r70 = self._operator_value(port, local, 0x70, slot)
            r80 = self._operator_value(port, local, 0x80, slot)
            r90 = self._operator_value(port, local, 0x90, slot)
            raw_signature += [r30, r40, r50, r60, r70, r80, r90]
            operators.append(
                FmOperator(
                    logical_operator=_SLOT_TO_LOGICAL_OPERATOR[slot],
                    detune=(r30 >> 4) & 0x07,
                    multiple=r30 & 0x0F,
                    total_level=r40 & 0x7F,
                    rate_scale=(r50 >> 6) & 0x03,
                    attack_rate=r50 & 0x1F,
                    am_enable=(r60 >> 7) & 0x01,
                    decay_rate=r60 & 0x1F,
                    sustain_rate=r70 & 0x1F,
                    sustain_level=(r80 >> 4) & 0x0F,
                    release_rate=r80 & 0x0F,
                    ssg_eg=r90 & 0x0F,
                )
            )
        digest = hashlib.sha1(bytes(raw_signature)).hexdigest()[:12]
        return FmPatch(
            id=f"ym2612-{digest}",
            algorithm=b0 & 0x07,
            feedback=(b0 >> 3) & 0x07,
            ams=(b4 >> 4) & 0x03,
            fms=b4 & 0x07,
            pan_left=bool(b4 & 0x80),
            pan_right=bool(b4 & 0x40),
            operators=operators,
            first_seen_sample=sample,
            use_count=0,
            source_channels=[channel],
        )

    def _record_patch(self, channel: int, sample: int) -> None:
        patch = self.snapshot(channel, sample)
        existing = self.patches.get(patch.id)
        if existing is None:
            patch.use_count = 1
            self.patches[patch.id] = patch
        else:
            existing.use_count += 1
            if channel not in existing.source_channels:
                existing.source_channels.append(channel)


_YM_DT_TO_TFI = {0: 3, 1: 4, 2: 5, 3: 6, 4: 3, 5: 2, 6: 1, 7: 0}


def patch_to_tfi(patch: FmPatch) -> bytes:
    """Serialize a YM2612 patch as a 42-byte TFI instrument.

    TFI stores operators in OPN register-slot order S1,S3,S2,S4. It does not
    preserve per-operator AM enable, FMS/AMS or stereo pan.
    """
    out = bytearray([patch.algorithm & 7, patch.feedback & 7])
    # patch.operators is already captured in YM register-slot order.
    for op in patch.operators:
        out.extend([
            op.multiple & 0x0F,
            _YM_DT_TO_TFI[op.detune & 7],
            op.total_level & 0x7F,
            op.rate_scale & 3,
            op.attack_rate & 0x1F,
            op.decay_rate & 0x1F,
            op.sustain_rate & 0x1F,
            op.release_rate & 0x0F,
            op.sustain_level & 0x0F,
            op.ssg_eg & 0x0F,
        ])
    if len(out) != 42:
        raise AssertionError(len(out))
    return bytes(out)


def patch_to_dmp(patch: FmPatch) -> bytes:
    """Serialize a YM2612 patch as DefleMask DMP v10 FM preset.

    DMP preserves FMS, AMS and per-operator AM in addition to the core FM
    envelope parameters. Stereo pan is not part of the DMP FM preset format.
    """
    out = bytearray([
        0x0A,  # DMP file version
        0x01,  # FM instrument
        patch.fms & 7,
        patch.feedback & 7,
        patch.algorithm & 7,
        patch.ams & 3,
    ])
    # DMP operator lists are logical operator 1..4.
    for op in sorted(patch.operators, key=lambda item: item.logical_operator):
        out.extend([
            op.multiple & 0x0F,
            op.total_level & 0x7F,
            op.attack_rate & 0x1F,
            op.decay_rate & 0x1F,
            op.sustain_level & 0x0F,
            op.release_rate & 0x0F,
            op.am_enable & 1,
            op.rate_scale & 3,
            op.detune & 7,
            op.sustain_rate & 0x1F,
            op.ssg_eg & 0x0F,
        ])
    return bytes(out)


_RYM_DT_FROM_YM = {0: 0, 1: 1, 2: 2, 3: 3, 4: 0, 5: -1, 6: -2, 7: -3}
# RYM2612 stores MUL on a quasi-frequency scale, not as the raw OPN nibble.
# Values match the long-standing mucom88torym2612 converter.
_RYM_MULS = [
    0, 1054, 1581, 2635, 3689, 4743, 5797, 6851,
    7905, 8959, 10013, 10540, 11594, 12648, 14229, 15000,
]
# YM2612 carrier operators for algorithms 0..7, logical OP1..OP4.
_RYM_CARRIERS = [
    (False, False, False, True),
    (False, False, False, True),
    (False, False, False, True),
    (False, False, False, True),
    (False, True, False, True),
    (False, True, True, True),
    (False, True, True, True),
    (True, True, True, True),
]


def patch_to_rym2612(
    patch: FmPatch,
    *,
    name: str | None = None,
    category: str = "Video Games",
    carrier_velocity: bool = False,
) -> bytes:
    """Serialize an FM patch as a native RYM2612 ``.rym2612`` preset.

    RYM2612 presets are JUCE XML state files. The parameter names/layout here
    follow the MIT-licensed ``but80/mucom88torym2612`` converter and are also
    compatible with the parser in ``ulalume/ym2612_format``.

    ``carrier_velocity=False`` is deliberate for extracted game patches: Sega
    hardware has no MIDI velocity, so the exact YM2612 TL is kept in OPxTL and
    OPxVel is zero. Set it to true to mimic the historical MUCOM->RYM2612
    converter, which moves half of each carrier's output level into velocity
    sensitivity for a more playable preset.
    """
    from xml.sax.saxutils import escape, quoteattr

    patch_name = name or patch.id
    attrs = (
        f"patchName={quoteattr(patch_name)} "
        f"category={quoteattr(category)} rating=\"3\" type=\"User\""
    )
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '', f"<RYM2612Params {attrs}>"]

    by_logical = {op.logical_operator: op for op in patch.operators}
    op_lines: dict[int, list[str]] = {}
    for logical in range(1, 5):
        op = by_logical[logical]
        output_level = 127 - (op.total_level & 0x7F)
        vel = 0
        if carrier_velocity and _RYM_CARRIERS[patch.algorithm & 7][logical - 1]:
            vel = output_level // 2
            output_level -= vel
        ssgeg = ((op.ssg_eg & 7) + 1) if (op.ssg_eg & 8) else 0
        values = [
            (f"OP{logical}Vel", float(vel)),
            (f"OP{logical}TL", float(output_level)),
            (f"OP{logical}SSGEG", float(ssgeg)),
            (f"OP{logical}RS", float(op.rate_scale & 3)),
            (f"OP{logical}RR", float(op.release_rate & 0x0F)),
            (f"OP{logical}MW", 0.0),
            (f"OP{logical}MUL", float(_RYM_MULS[op.multiple & 0x0F])),
            (f"OP{logical}Fixed", 0.0),
            (f"OP{logical}DT", float(_RYM_DT_FROM_YM[op.detune & 7])),
            (f"OP{logical}D2R", float(op.sustain_rate & 0x1F)),
            (f"OP{logical}D2L", float(15 - (op.sustain_level & 0x0F))),
            (f"OP{logical}D1R", float(op.decay_rate & 0x1F)),
            (f"OP{logical}AR", float(op.attack_rate & 0x1F)),
            (f"OP{logical}AM", float(op.am_enable & 1)),
        ]
        op_lines[logical] = [
            f'  <PARAM id="{escape(param)}" value="{value:.1f}"/>'
            for param, value in values
        ]

    # Native presets interleave OP4..OP1 parameter-by-parameter. Lookup is by
    # id, but preserving that ordering makes generated files diff-friendly.
    for row in range(len(op_lines[1])):
        for logical in (4, 3, 2, 1):
            lines.append(op_lines[logical][row])

    lines.extend([
        '  <PARAM id="volume" value="0.4483062326908112"/>',
        '  <PARAM id="Ladder_Effect" value="0.0"/>',
        '  <PARAM id="Output_Filtering" value="0.0"/>',
        '  <PARAM id="Polyphony" value="8.0"/>',
        '  <PARAM id="TimerA" value="0.2000000029802322"/>',
        '  <PARAM id="Spec_Mode" value="2.0"/>',
        '  <PARAM id="Pitchbend_Range" value="2.0"/>',
        '  <PARAM id="Legato_Retrig" value="0.0"/>',
        '  <PARAM id="LFO_Speed" value="2.0"/>',
        # FMS/AMS sensitivity does not prove global YM2612 LFO register 0x22
        # was enabled for the whole song, so default to disabled.
        '  <PARAM id="LFO_Enable" value="0.0"/>',
        f'  <PARAM id="Feedback" value="{float(patch.feedback & 7):.1f}"/>',
        '  <PARAM id="FMSMW" value="100.0"/>',
        f'  <PARAM id="FMS" value="{float(patch.fms & 7):.1f}"/>',
        '  <PARAM id="DAC_Prescaler" value="1.0"/>',
        f'  <PARAM id="Algorithm" value="{float((patch.algorithm & 7) + 1):.1f}"/>',
        f'  <PARAM id="AMS" value="{float(patch.ams & 3):.1f}"/>',
        '  <PARAM id="masterTune"/>',
        '</RYM2612Params>',
        '',
    ])
    return "\n".join(lines).encode("utf-8")
