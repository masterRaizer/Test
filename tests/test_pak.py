"""Round-trip tests for the pak/locres/texture readers using synthetic archives."""
import os
import shutil
import struct
import tempfile
import unittest
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from mcd_loader import catalog, ue4pak

KEY = ue4pak.parse_key(ue4pak.KNOWN_PAK_KEYS[0][1])


def fstring(text):
    try:
        raw = text.encode("ascii") + b"\x00"
        return struct.pack("<i", len(raw)) + raw
    except UnicodeEncodeError:
        raw = text.encode("utf-16-le") + b"\x00\x00"
        return struct.pack("<i", -(len(raw) // 2)) + raw


def encrypt(data):
    data += b"\x00" * (-len(data) % 16)
    enc = Cipher(algorithms.AES(KEY), modes.ECB()).encryptor()
    return enc.update(data) + enc.finalize()


def build_pak(path, files, compress=(), encrypt_files=()):
    """Write a version 8 pak (4 compression names, byte method index, encrypted index)."""
    body = bytearray()
    index = bytearray()
    for name, data in files.items():
        offset = len(body)
        method = 1 if name in compress else 0
        enc = name in encrypt_files

        def header(blocks):
            h = struct.pack("<qqqB", offset, stored_size, len(data), method) + b"\x00" * 20
            if method:
                h += struct.pack("<i", len(blocks)) + b"".join(struct.pack("<qq", s, e) for s, e in blocks)
            return h + struct.pack("<BI", 1 if enc else 0, 0x10000 if method else 0)

        if method:
            chunks = [zlib.compress(data[i:i + 64]) for i in range(0, len(data), 64)]
            stored_size = sum(len(c) for c in chunks)
            head_len = len(header([(0, 0)] * len(chunks)))
            blocks, payload, pos = [], b"", head_len
            for c in chunks:
                stored = encrypt(c) if enc else c
                blocks.append((pos, pos + len(c)))
                payload += stored
                pos += len(stored)
        else:
            stored_size = len(data)
            payload = encrypt(data) if enc else data
            blocks = []
        h = header(blocks)
        body += h + payload
        index += fstring(name) + h
    index = fstring("../../../") + struct.pack("<i", len(files)) + index
    enc_index = encrypt(bytes(index))
    index_offset = len(body)
    names = b"Zlib".ljust(32, b"\x00") + b"\x00" * 96
    footer = b"\x00" * 16 + b"\x01" + struct.pack("<IIqq", ue4pak.PAK_MAGIC, 8, index_offset, len(enc_index)) \
        + b"\x00" * 20 + names
    with open(path, "wb") as f:
        f.write(bytes(body) + enc_index + footer)


def build_locres(tables):
    strings = []
    ns_part = b""
    for ns, entries in tables.items():
        ns_part += struct.pack("<I", 0) + fstring(ns) + struct.pack("<I", len(entries))
        for key, text in entries.items():
            strings.append(text)
            ns_part += struct.pack("<I", 0) + fstring(key) + struct.pack("<Ii", 0, len(strings) - 1)
    head_len = 16 + 1 + 8
    body = struct.pack("<I", sum(len(e) for e in tables.values())) + struct.pack("<I", len(tables)) + ns_part
    array = struct.pack("<i", len(strings)) + b"".join(fstring(s) + struct.pack("<i", 1) for s in strings)
    return ue4pak.LOCRES_MAGIC + bytes([2]) + struct.pack("<q", head_len + len(body)) + body + array


def build_texture(fmt, mips, prefix=b"\x00" * 37):
    """mips: list of (w, h, data, in_ubulk). Returns (uasset, uexp, ubulk)."""
    uasset = b"\xc1\x83\x2a\x9e" + b"\x00" * 60
    ubulk = b""
    out = prefix + struct.pack("<iii", mips[0][0], mips[0][1], 1) + fstring(fmt) + struct.pack("<ii", 0, len(mips))
    for w, h, data, in_ubulk in mips:
        if in_ubulk:
            out += struct.pack("<iIiiq", 1, 0x100 | 0x1, len(data), len(data), len(ubulk))
            ubulk += data
        else:
            out += struct.pack("<iIiiq", 1, 0x40, len(data), len(data), 0) + data
        out += struct.pack("<iii", w, h, 1)
    return uasset, out + b"\x00" * 8 + b"\xc1\x83\x2a\x9e", ubulk


RED_DXT1_BLOCK = struct.pack("<HHI", 0xF800, 0x0000, 0)  # every texel = color0 (red)


class TextureTests(unittest.TestCase):
    def test_dxt1_inline(self):
        uasset, uexp, _ = build_texture("PF_DXT1", [(8, 8, RED_DXT1_BLOCK * 4, False)])
        img = ue4pak.decode_texture(uasset, uexp)
        self.assertEqual(img.size, (8, 8))
        self.assertEqual(img.getpixel((3, 3))[:3], (255, 0, 0))

    def test_bgra_mip_from_ubulk(self):
        big = bytes([255, 0, 0, 255]) * 16  # blue in BGRA
        small = bytes([0, 255, 0, 255]) * 4
        uasset, uexp, ubulk = build_texture("PF_B8G8R8A8", [(4, 4, big, True), (2, 2, small, False)])
        img = ue4pak.decode_texture(uasset, uexp, ubulk)
        self.assertEqual(img.size, (4, 4))
        self.assertEqual(img.getpixel((0, 0)), (0, 0, 255, 255))

    def test_falls_back_to_inline_mip_without_ubulk(self):
        big = bytes([255, 0, 0, 255]) * 16
        small = bytes([0, 255, 0, 255]) * 4
        uasset, uexp, _ = build_texture("PF_B8G8R8A8", [(4, 4, big, True), (2, 2, small, False)])
        self.assertEqual(ue4pak.decode_texture(uasset, uexp, None).size, (2, 2))


class LocResTests(unittest.TestCase):
    def test_parse_v2_with_unicode(self):
        data = build_locres({"ItemType": {"Sword": "Меч", "Flavour_Sword": "Надёжный клинок."},
                             "Enchantment": {"Sharpness": "Острота"}})
        tables = ue4pak.parse_locres(data)
        self.assertEqual(tables["ItemType"]["Sword"], "Меч")
        self.assertEqual(tables["Enchantment"]["Sharpness"], "Острота")


class PakAndCatalogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.paks = os.path.join(self.dir, "Paks")
        os.makedirs(self.paks)
        root = "Dungeons/Content/"
        tex = build_texture("PF_DXT1", [(8, 8, RED_DXT1_BLOCK * 4, False)])
        self.files = {}

        def add_texture(asset):
            self.files[root + asset + ".uasset"], self.files[root + asset + ".uexp"], _ = tex

        add_texture("Actors/Items/Equipment/MeleeWeapons/Sword_Steel/T_Sword_Icon_inventory")
        add_texture("Actors/Items/Equipment/RangedWeapons/LongBow/T_LongBow_Icon_inventory")
        add_texture("Actors/Items/Equipment/Armor/ArchersStrappings/T_ArchersStrappings_Icon_inventory")
        add_texture("Actors/Items/Items/FireworksArrowItem/T_FireworksArrow_Icon_inventory")
        add_texture("Actors/Items/Items/EyeOfEnder/T_EyeOfEnder_Icon_inventory")
        add_texture("UI/Enchantments/Sharpness/T_Sharpness_Icon")
        add_texture("UI/Enchantments/SharpnessShine/T_SharpnessShine_Icon")
        self.files[root + "Actors/ArmorProperties/AllyDamageBoost/BP_AllyDamageBoost.uasset"] = b"x"
        self.files[root + "Localization/Game/ru-RU/Game.locres"] = build_locres({
            "ItemType": {"Sword": "Меч", "Longbow": "Длинный лук", "Flavour_Sword": "Надёжный клинок."},
            "Enchantment": {"Sharpness": "Острота", "Sharpness_desc": "Больше урона."},
            "ArmorProperties": {"AllyDamageBoost": "Урон союзников +"},
        })
        self.files[root + "big.bin"] = bytes(range(256)) * 5
        names = sorted(self.files)
        half = len(names) // 2
        build_pak(os.path.join(self.paks, "pakchunk0-WindowsNoEditor.pak"), {n: self.files[n] for n in names[:half]},
                  compress={root + "big.bin"}, encrypt_files={root + "big.bin"})
        build_pak(os.path.join(self.paks, "pakchunk1-WindowsNoEditor.pak"), {n: self.files[n] for n in names[half:]},
                  compress=set(names[half:half + 3]))

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_index_and_read(self):
        index = ue4pak.PakIndex(self.paks)
        self.assertEqual(index.version_label, ue4pak.KNOWN_PAK_KEYS[0][0])
        for name, data in self.files.items():
            self.assertEqual(index.read("/" + name), data, name)

    def test_wrong_key_rejected(self):
        saved = ue4pak.KNOWN_PAK_KEYS[:]
        try:
            ue4pak.KNOWN_PAK_KEYS[:] = saved[1:]
            with self.assertRaises(ue4pak.PakError):
                ue4pak.PakIndex(self.paks)
            index = ue4pak.PakIndex(self.paks, user_keys=["0x" + saved[0][1]])
            self.assertEqual(index.version_label, "пользовательский")
        finally:
            ue4pak.KNOWN_PAK_KEYS[:] = saved

    def test_catalog(self):
        cache = os.path.join(self.dir, "cache")
        cat = catalog.GameCatalog.load(self.paks, cache)
        self.assertEqual(cat.items["Sword"]["category"], "melee")
        self.assertEqual(cat.items["Longbow"]["category"], "ranged")
        self.assertEqual(cat.items["ArchersStrappings"]["category"], "armor")
        self.assertEqual(cat.items["FireworksArrowItem"]["category"], "artifact")
        self.assertNotIn("EyeOfEnder", cat.items)
        self.assertEqual(set(cat.enchantments), {"Sharpness"})
        self.assertEqual(cat.armor_properties, {"AllyDamageBoost"})
        self.assertEqual(cat.language, "ru-RU")
        self.assertEqual(cat.item_name("Sword"), "Меч")
        self.assertEqual(cat.item_name("Longbow"), "Длинный лук")
        self.assertEqual(cat.enchantment_name("Sharpness"), "Острота")
        self.assertEqual(cat.enchantment_description("Sharpness"), "Больше урона.")
        icon = cat.icon_file("item", "Sword")
        self.assertTrue(icon and os.path.isfile(icon))
        self.assertTrue(cat.icon_file("enchantment", "Sharpness"))

        cached = catalog.GameCatalog.load(self.paks, cache)
        self.assertIsNone(cached._index)  # served from catalog.json without opening paks
        self.assertEqual(cached.items, cat.items)
        self.assertEqual(cached.icon_file("item", "Sword"), icon)


if __name__ == "__main__":
    unittest.main()
