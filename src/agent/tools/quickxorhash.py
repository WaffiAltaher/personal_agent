# src/agent/tools/quickxorhash.py
"""
OneDrive's `quickXorHash` (the only content hash OneDrive for Business guarantees, ADR-020),
from Microsoft's published algorithm: byte i is XORed into a 160-bit block rotated left by
11·i bits, the block is written out little-endian, the input's length (8 bytes, little-endian)
is XORed into its last 8 bytes, and the 20 bytes are base64-encoded.

Rotations repeat every 160 bytes (160·11 is a multiple of 160), so the bytes at the same position
modulo 160 are XORed together first, as 160-byte little-endian integers, and rotated once each.
"""

import base64

WIDTH = 160  # bits in the block
SHIFT = 11
_MASK = (1 << WIDTH) - 1
_ROW = WIDTH  # bytes after which the rotations repeat


def quick_xor_hash(data: bytes) -> str:
    """The base64 `quickXorHash` OneDrive reports for a file holding `data`."""
    rows = 0
    for offset in range(0, len(data), _ROW):
        rows ^= int.from_bytes(data[offset:offset + _ROW], "little")
    block = 0
    for position, byte in enumerate(rows.to_bytes(_ROW, "little")):
        if byte:
            shift = (position * SHIFT) % WIDTH
            rotated = byte << shift
            block ^= (rotated & _MASK) | (rotated >> WIDTH)
    digest = bytearray(block.to_bytes(WIDTH // 8, "little"))
    for i, length_byte in enumerate(len(data).to_bytes(8, "little")):
        digest[WIDTH // 8 - 8 + i] ^= length_byte
    return base64.b64encode(bytes(digest)).decode("ascii")
