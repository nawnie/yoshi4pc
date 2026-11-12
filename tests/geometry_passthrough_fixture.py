"""Original Maxwell passthrough inputs; no captured shader or SDK bytes."""
import struct

import geometry_shader_fixture as geometry


def skip_words(locations):
    # Hardware attribute components: Position is 28..31, user locations start at 32.
    words = [0x0fffffff] + [0xffffffff] * 7
    for location in locations:
        assert 0 <= location < 32
        words[1 + location // 8] &= ~(15 << (4 * (location % 8)))
    return words


def program(store=False, extra=()):
    header = bytearray(geometry.geometry_header('triangle_strip', 1, 1))
    word = struct.unpack_from('<I', header)[0] | (1 << 24) | (int(store) << 16)
    struct.pack_into('<I', header, 0, word)
    instructions = []
    if store:
        instructions += [geometry.movi(8, 0x1234abcd), geometry.movc(10, 3, 0), geometry.movc(11, 3, 1),
                         0xeed8000000000000 | (4 << 48) | (1 << 45) | (10 << 8) | geometry.PT | 8]
    return bytes(header) + geometry.framed(instructions + list(extra) + [geometry.EXIT])
