"""Minimal reader for Minecraft Dungeons' Unreal Engine 4 .pak archives.

Covers what the loader needs and nothing more: pak index (optionally AES
encrypted), file extraction (stored / zlib / gzip blocks), LocRes string
tables and cooked Texture2D icons. Layouts follow PakReader (used by
MCDSaveEdit) and UE4 sources.
"""
import gzip
import io
import os
import struct
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PAK_MAGIC = 0x5A6F12E1
PAK_INFO_SIZE = 4 * 2 + 8 * 2 + 20 + 1 + 16  # without compression method names
COMPRESSION_NAME_LEN = 32
VERSION_RELATIVE_CHUNK_OFFSETS = 5
VERSION_FNAME_COMPRESSION = 8
VERSION_PATH_HASH_INDEX = 10

# Community-published AES keys for the game's paks, newest first.
KNOWN_PAK_KEYS = [
    ("1.17.0.0", "7D5F892ECEBFA53CC22001DF48B871D51C0DF7C54CE41933BFB285219829B3A8"),
    ("1.9.1.0", "0A01138AC7553ECEA7E9E257B5A45FA6665679D360B270278AE5D5367B172E40"),
    ("1.8.8.0", "8F80D8A467F135AC43BB1324861EF5D91316AD954A09D4B3499A8CCA8AE70AB7"),
    ("1.8.6.0", "A031D8DC72D498FF3856CF3B6E7FCA0DF09D59E6C75DCA8A9FBE152C7982C4A2"),
    ("1.8.0.0", "0634AF9A409BA6D24FC17B6872124A91F3DBC4C3986F639A5E29C1BB10B2A099"),
    ("<1.8.0.0", "90F270A4EA6DE0E3BABDC4C8BDC04F46FA5B9087BE8FE76AA859C93C17D04661"),
]


class PakError(Exception):
    pass


def parse_key(text):
    text = text.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    key = bytes.fromhex(text)
    if len(key) != 32:
        raise PakError("AES-ключ должен быть 32 байта (64 hex-символа)")
    return key


def aes_decrypt(data, key):
    if len(data) % 16:
        data += b"\x00" * (-len(data) % 16)
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(data) + dec.finalize()


class Reader:
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise PakError("неожиданный конец данных")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def _unpack(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def u8(self):
        return self._unpack("<B")

    def i32(self):
        return self._unpack("<i")

    def u32(self):
        return self._unpack("<I")

    def i64(self):
        return self._unpack("<q")

    def fstring(self):
        length = self.i32()
        if length == 0:
            return ""
        if length > 0:
            if length > 4096:
                raise PakError("слишком длинная строка")
            return self.take(length)[:-1].decode("latin-1")
        if -length > 4096:
            raise PakError("слишком длинная строка")
        return self.take(-length * 2)[:-2].decode("utf-16-le")


class PakEntry:
    __slots__ = ("name", "offset", "size", "uncompressed", "method", "blocks", "encrypted", "block_size", "struct_size")


class PakFile:
    def __init__(self, path):
        self.path = path
        self.entries = {}
        self.mount_point = ""
        self.compression = []
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            self.file_size = f.tell()
            tail_len = min(self.file_size, PAK_INFO_SIZE + COMPRESSION_NAME_LEN * 8)
            f.seek(self.file_size - tail_len)
            tail = f.read()
        self._read_info(tail)

    def _read_info(self, tail):
        # The compression-name table length varies between engine versions:
        # try 0..8 names and keep the layout whose magic matches.
        for names in range(0, 9):
            start = len(tail) - PAK_INFO_SIZE - names * COMPRESSION_NAME_LEN
            if start < 0:
                break
            r = Reader(tail, start + 16)  # skip encryption key GUID
            encrypted_index = r.u8() != 0
            if r.u32() != PAK_MAGIC:
                continue
            self.version = r.i32()
            self.index_offset = r.i64()
            self.index_size = r.i64()
            r.take(20)
            self.encrypted_index = encrypted_index
            self.method_is_byte = self.version == VERSION_FNAME_COMPRESSION and names == 4
            if self.version < VERSION_FNAME_COMPRESSION:
                self.compression = ["Zlib", "Gzip", "Oodle"]
            else:
                for _ in range(names):
                    name = r.take(COMPRESSION_NAME_LEN).rstrip(b"\x00").decode("ascii", "replace")
                    if name:
                        self.compression.append(name)
            return
        raise PakError(f"{os.path.basename(self.path)}: не похоже на UE4 pak")

    def read_index(self, keys):
        """Read the file table. Returns the key that worked (or None if unencrypted)."""
        if self.version >= VERSION_PATH_HASH_INDEX:
            raise PakError(f"версия pak {self.version} не поддерживается")
        with open(self.path, "rb") as f:
            f.seek(self.index_offset)
            raw = f.read(self.index_size)
        candidates = keys if self.encrypted_index else [None]
        for key in candidates:
            data = aes_decrypt(raw, key) if key else raw
            try:
                self._parse_index(data)
                return key
            except (PakError, struct.error, UnicodeDecodeError):
                continue
        raise PakError(f"{os.path.basename(self.path)}: ни один AES-ключ не подошёл")

    def _parse_index(self, data):
        r = Reader(data)
        mount = r.fstring()
        if not mount.startswith("../"):
            raise PakError("неверная точка монтирования")
        count = r.i32()
        if count < 0 or count > 2_000_000:
            raise PakError("неверное число файлов")
        entries = {}
        mount = mount.replace("../../../", "/")
        for _ in range(count):
            e = PakEntry()
            e.name = mount + r.fstring()
            start = r.pos
            e.offset, e.size, e.uncompressed = r.i64(), r.i64(), r.i64()
            if self.version < VERSION_FNAME_COMPRESSION:
                legacy = r.i32()
                e.method = 0 if legacy == 0 else 1 if legacy & 1 else 2 if legacy & 2 else 3
            else:
                e.method = r.u8() if self.method_is_byte else r.u32()
            if self.version <= 1:
                r.i64()
            r.take(20)
            e.blocks = []
            e.encrypted = False
            e.block_size = 0
            if self.version >= 3:
                if e.method:
                    for _ in range(r.i32()):
                        e.blocks.append((r.i64(), r.i64()))
                e.encrypted = bool(r.u8() & 1)
                e.block_size = r.u32()
            e.struct_size = r.pos - start
            entries[e.name] = e
        self.entries = entries
        self.mount_point = mount

    def read(self, entry, key):
        with open(self.path, "rb") as f:
            if entry.method == 0:
                f.seek(entry.offset + entry.struct_size)
                size = entry.size + (-entry.size % 16 if entry.encrypted else 0)
                data = f.read(size)
                if entry.encrypted:
                    data = aes_decrypt(data, key)
                return data[:entry.uncompressed]
            method = self.compression[entry.method - 1] if entry.method - 1 < len(self.compression) else "?"
            out = bytearray()
            base = entry.offset if self.version >= VERSION_RELATIVE_CHUNK_OFFSETS else 0
            for start, end in entry.blocks:
                f.seek(base + start)
                size = end - start
                block = f.read(size + (-size % 16 if entry.encrypted else 0))
                if entry.encrypted:
                    block = aes_decrypt(block, key)[:size]
                if method.lower() == "zlib":
                    out += zlib.decompressobj().decompress(block)
                elif method.lower() == "gzip":
                    out += gzip.decompress(block)
                else:
                    raise PakError(f"сжатие {method} не поддерживается")
            return bytes(out[:entry.uncompressed])


class PakIndex:
    """All paks of a game install; later (patch) paks override earlier files."""

    def __init__(self, paks_dir, user_keys=()):
        self.paks = []
        self.files = {}
        self.version_label = None
        keys = []
        for text in user_keys:
            try:
                keys.append(("пользовательский", parse_key(text)))
            except (ValueError, PakError):
                pass
        keys += [(label, parse_key(k)) for label, k in KNOWN_PAK_KEYS]
        key_bytes = [k for _, k in keys]
        names = sorted(n for n in os.listdir(paks_dir) if n.lower().endswith(".pak"))
        if not names:
            raise PakError(f"в папке нет .pak файлов: {paks_dir}")
        errors = []
        for name in sorted(names, key=lambda n: ("_p." in n.lower(), n.lower())):
            try:
                pak = PakFile(os.path.join(paks_dir, name))
                used = pak.read_index(key_bytes)
            except (OSError, PakError) as e:
                errors.append(str(e))
                continue
            if used is not None:
                pak.key = used
                key_bytes = [used] + [k for k in key_bytes if k != used]
                self.version_label = next(label for label, k in keys if k == used)
            else:
                pak.key = None
            self.paks.append(pak)
            for path, entry in pak.entries.items():
                self.files[path.lower()] = (pak, entry)
        if not self.files:
            raise PakError("; ".join(errors) or "файлы игры не прочитаны")

    def paths(self):
        return (entry.name for _, entry in self.files.values())

    def exists(self, path):
        return path.lower() in self.files

    def read(self, path):
        pak, entry = self.files[path.lower()]
        return pak.read(entry, pak.key)


# --------------------------------------------------------------- LocRes
LOCRES_MAGIC = bytes.fromhex("0E147475674A03FC4A15909DC3377F1B")


def parse_locres(data):
    """Return {namespace: {key: text}} from a UE4 .locres file."""
    r = Reader(data)
    version = 0
    if data[:16] == LOCRES_MAGIC:
        r.take(16)
        version = r.u8()
    strings = []
    if version >= 1:
        array_offset = r.i64()
        if array_offset != -1:
            here = r.pos
            r.pos = array_offset
            for _ in range(r.i32()):
                text = r.fstring()
                if version >= 2:
                    r.i32()  # ref count
                strings.append(text)
            r.pos = here
    if version >= 2:
        r.u32()  # total entries
    result = {}
    for _ in range(r.u32()):
        if version >= 2:
            r.u32()
        namespace = r.fstring()
        table = result.setdefault(namespace, {})
        for _ in range(r.u32()):
            if version >= 2:
                r.u32()
            key = r.fstring()
            r.u32()  # source string hash
            if version >= 1:
                index = r.i32()
                table[key] = strings[index] if 0 <= index < len(strings) else ""
            else:
                table[key] = r.fstring()
    return result


# ------------------------------------------------------------- Texture2D
BULK_INLINE = 0x40
BULK_SEPARATE_FILE = 0x100
BULK_UNUSED = 0x20
BULK_SIZE64 = 0x2000
BULK_COMPRESSED_ZLIB = 0x2

PIXEL_FORMATS = {
    # name: (bytes per 4x4 block or None, PIL decoder args)
    "PF_DXT1": (8, ("bcn", 1, "RGBA")),
    "PF_DXT3": (16, ("bcn", 2, "RGBA")),
    "PF_DXT5": (16, ("bcn", 3, "RGBA")),
    "PF_BC4": (8, ("bcn", 4, "L")),
    "PF_BC5": (16, ("bcn", 5, "RGB")),
    "PF_BC7": (16, ("bcn", 7, "RGBA")),
    "PF_B8G8R8A8": (None, ("raw", "BGRA", "RGBA", 4)),
    "PF_R8G8B8A8": (None, ("raw", "RGBA", "RGBA", 4)),
    "PF_G8": (None, ("raw", "L", "L", 1)),
}


def _expected_size(fmt, w, h):
    block, args = PIXEL_FORMATS[fmt]
    if block:
        return ((w + 3) // 4) * ((h + 3) // 4) * block
    return w * h * args[3]


def _decode_pixels(fmt, w, h, data):
    from PIL import Image
    block, args = PIXEL_FORMATS[fmt]
    if block:
        _, n, mode = args
        img = Image.frombytes(mode, (w, h), data, "bcn", n)
    else:
        _, rawmode, mode, _ = args
        img = Image.frombytes(mode, (w, h), data, "raw", rawmode)
    return img.convert("RGBA")


def _find_platform_data(uexp):
    """Locate the cooked FTexturePlatformData by its pixel-format FString."""
    pos = 0
    while True:
        pos = uexp.find(b"PF_", pos)
        if pos < 0:
            return None
        if pos >= 16:
            length = struct.unpack_from("<i", uexp, pos - 4)[0]
            end = pos + length - 1
            if 4 < length < 32 and end < len(uexp) and uexp[end] == 0:
                fmt = uexp[pos:end].decode("ascii", "replace")
                if fmt in PIXEL_FORMATS:
                    return pos - 16, fmt, end + 1
        pos += 3


def decode_texture(uasset, uexp, ubulk=None):
    """Return the largest decodable mip of a cooked Texture2D as a PIL image."""
    found = _find_platform_data(uexp)
    if not found:
        raise PakError("в текстуре не найден формат пикселей")
    header_pos, fmt, after = found
    size_x, size_y, packed = struct.unpack_from("<iii", uexp, header_pos)
    r = Reader(uexp, after)
    if packed & (1 << 30):  # optional data: ExtData + NumMipsInTail
        r.take(8)
    r.i32()  # first mip to serialize
    mip_count = r.i32()
    if not 0 < mip_count < 20:
        raise PakError("неверное число мипов")
    bulk_base = len(uasset) + len(uexp) - 4
    errors = []
    for _ in range(mip_count):
        r.i32()  # bCooked
        flags = r.u32()
        if flags & BULK_SIZE64:
            count = r.i64()
            r.i64()  # size on disk
        else:
            count = r.i32()
            r.i32()  # size on disk
        offset = r.i64()
        data = None
        if flags & BULK_INLINE and not flags & BULK_UNUSED:
            data = r.take(count)
        w, h = r.i32(), r.i32()
        r.i32()  # depth
        if data is None and flags & BULK_SEPARATE_FILE and ubulk:
            for start in (offset, offset - bulk_base, offset + bulk_base):
                if 0 <= start and start + count <= len(ubulk):
                    data = ubulk[start:start + count]
                    break
        if data is None or flags & BULK_COMPRESSED_ZLIB:
            continue
        if len(data) != _expected_size(fmt, w, h):
            errors.append(f"{w}x{h}: размер {len(data)}")
            continue
        try:
            return _decode_pixels(fmt, w, h, data)
        except (ValueError, OSError) as e:
            errors.append(str(e))
    raise PakError(f"не удалось декодировать {fmt} {size_x}x{size_y}: {'; '.join(errors) or 'нет данных'}")


def read_texture(index, path_without_ext):
    uasset = index.read(path_without_ext + ".uasset")
    uexp = index.read(path_without_ext + ".uexp")
    ubulk_path = path_without_ext + ".ubulk"
    ubulk = index.read(ubulk_path) if index.exists(ubulk_path) else None
    return decode_texture(uasset, uexp, ubulk)


def read_bytes(data):
    return io.BytesIO(data)
