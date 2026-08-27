from __future__ import annotations


class KosinskiError(ValueError):
    pass


def decompress(data: bytes, offset: int = 0) -> tuple[bytes, int]:
    """Decompress a Sega Kosinski stream.

    Returns ``(decompressed_bytes, compressed_bytes_consumed)``.
    Descriptor bits are consumed LSB-first, matching the Mega Drive decoder
    used by Streets of Rage and Sonic-era Sega code.
    """

    pos = offset
    out = bytearray()

    def read_byte() -> int:
        nonlocal pos
        if pos >= len(data):
            raise KosinskiError("unexpected end of compressed stream")
        value = data[pos]
        pos += 1
        return value

    descriptor = read_byte() | (read_byte() << 8)
    bits_left = 16

    def pop_descriptor() -> int:
        nonlocal descriptor, bits_left
        result = descriptor & 1
        descriptor >>= 1
        bits_left -= 1
        if bits_left == 0:
            descriptor = read_byte() | (read_byte() << 8)
            bits_left = 16
        return result

    while True:
        if pop_descriptor():
            out.append(read_byte())
            continue

        if pop_descriptor():
            low = read_byte()
            high = read_byte()
            distance = ((high & 0xF8) << 5) | low
            distance = (distance ^ 0x1FFF) + 1
            count = high & 7
            if count:
                count += 2
            else:
                count = read_byte() + 1
                if count == 1:
                    break
                if count == 2:  # 0xA000 boundary marker
                    continue
        else:
            count = 2
            if pop_descriptor():
                count += 2
            if pop_descriptor():
                count += 1
            distance = (read_byte() ^ 0xFF) + 1

        if distance <= 0 or distance > len(out):
            raise KosinskiError(f"invalid back-reference distance {distance}")
        for _ in range(count):
            out.append(out[-distance])

    return bytes(out), pos - offset
