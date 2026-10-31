"""Encryption of Minecraft Dungeons character saves (*.dat).

Format (same as DungeonTools / MCDSaveEdit):
    b"D001" + 4 zero bytes, then AES-256-ECB ciphertext of UTF-8 JSON,
    zero-padded to a 16 byte boundary.
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"D001\x00\x00\x00\x00"
KEY = bytes([
    0x5C, 0xEB, 0x9D, 0x0A, 0xEB, 0xB9, 0x5A, 0xC0, 0x27, 0x0B, 0x0A, 0xF6, 0x75, 0x3D, 0xFC, 0x0E,
    0xE3, 0xE6, 0x8B, 0xB6, 0x94, 0x79, 0x02, 0x0F, 0x24, 0x30, 0xE2, 0xEA, 0x00, 0x2B, 0xD4, 0xC9,
])
BLOCK = 16


class SaveFormatError(ValueError):
    pass


def _cipher() -> Cipher:
    return Cipher(algorithms.AES(KEY), modes.ECB())


def is_encrypted(data: bytes) -> bool:
    return data[:len(MAGIC)] == MAGIC


def decrypt(data: bytes) -> bytes:
    """Return the plain JSON bytes of an encrypted save."""
    if not is_encrypted(data):
        raise SaveFormatError("файл не похож на сохранение Minecraft Dungeons (нет сигнатуры D001)")
    body = data[len(MAGIC):]
    if len(body) % BLOCK:
        raise SaveFormatError("повреждённое сохранение: длина не кратна 16 байтам")
    dec = _cipher().decryptor()
    plain = dec.update(body) + dec.finalize()
    # Zero padding: the JSON text ends at the first NUL byte.
    end = plain.find(b"\x00")
    return plain if end < 0 else plain[:end]


def encrypt(plain: bytes) -> bytes:
    """Encrypt plain JSON bytes into the game's save format."""
    pad = -len(plain) % BLOCK
    enc = _cipher().encryptor()
    return MAGIC + enc.update(plain + b"\x00" * pad) + enc.finalize()
