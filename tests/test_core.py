import json
import os
import shutil
import tempfile
import unittest

from mcd_loader import crypto, gamedata as gd
from mcd_loader.savefile import SaveFile, item_level, max_out_enchantments, set_enchantment, set_item_level

BLANK = os.path.join(os.path.dirname(__file__), "data", "Blank.dat")


class CryptoTests(unittest.TestCase):
    def test_decrypt_real_save(self):
        with open(BLANK, "rb") as f:
            raw = f.read()
        profile = json.loads(crypto.decrypt(raw))
        self.assertEqual(profile["playerId"], "C2BC12F8-4800-51B5-D9E3-6F9E2865F96D")
        self.assertEqual(profile["skin"], "steve")

    def test_roundtrip_is_byte_identical(self):
        with open(BLANK, "rb") as f:
            raw = f.read()
        self.assertEqual(crypto.encrypt(crypto.decrypt(raw)), raw)

    def test_rejects_non_save(self):
        with self.assertRaises(crypto.SaveFormatError):
            crypto.decrypt(b"{}")


class FormulaTests(unittest.TestCase):
    def test_xp_level_inverse(self):
        for level in (1, 2, 50, 100, 1000):
            self.assertEqual(gd.level_for_xp(gd.xp_for_level(level)), level)

    def test_power_level_inverse(self):
        for level in (1, 100, 266):
            self.assertEqual(gd.level_from_power(gd.power_from_level(level)), level)

    def test_enchantment_costs(self):
        self.assertEqual(gd.enchantment_cost("Sharpness", 3), 6)
        self.assertEqual(gd.enchantment_cost("CriticalHit", 3), 9)
        self.assertEqual(gd.enchantment_cost("Sharpness", 3, gilded=True), 9)
        self.assertEqual(gd.enchantment_cost("CriticalHit", 3, gilded=True), 12)


class SaveFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Characters", "hero.dat")
        os.makedirs(os.path.dirname(self.path))
        shutil.copy(BLANK, self.path)
        self.save = SaveFile(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_edit_write_reload(self):
        s = self.save
        s.level = 80
        s.set_currency("Emerald", 12345)
        s.set_difficulty("Difficulty_3")
        sword = s.new_item("Sword", slot="MeleeGear")
        set_item_level(sword, 150)
        set_enchantment(sword, 0, "Sharpness", 3)
        s.new_item("FireworksArrowItem", slot="HotbarSlot1")
        s.new_item("Bow", in_chest=True)
        backup = s.write(os.path.join(self.dir, "backups"))
        self.assertTrue(os.path.isfile(backup))

        again = SaveFile(self.path)
        self.assertEqual(again.level, 80)
        self.assertEqual(again.get_currency("Emerald"), 12345)
        self.assertEqual(again.get_difficulty(), "Difficulty_3")
        self.assertEqual(len(again.inventory), 2)
        self.assertEqual(len(again.chest), 1)
        melee = again.equipped("MeleeGear")
        self.assertEqual(item_level(melee), 150)
        self.assertEqual(melee["enchantments"][0], {"id": "Sharpness", "level": 3, "investedPoints": 6})
        self.assertNotIn("enchantments", again.equipped("HotbarSlot1"))
        self.assertIn("Sword", again.profile["itemsFound"])

    def test_one_active_enchantment_per_slot(self):
        item = self.save.new_item("Sword")
        set_enchantment(item, 0, "Sharpness", 2)
        set_enchantment(item, 1, "Looting", 3)
        self.assertEqual(item["enchantments"][0]["level"], 0)
        self.assertEqual(item["enchantments"][1]["level"], 3)

    def test_equip_swaps_previous_item(self):
        first = self.save.new_item("Sword", slot="MeleeGear")
        second = self.save.new_item("Axe", in_chest=True)
        self.save.equip(second, "MeleeGear")
        self.assertIs(self.save.equipped("MeleeGear"), second)
        self.assertNotIn("equipmentSlot", first)
        self.assertIn("inventoryIndex", first)
        self.assertEqual(self.save.location(second), "inventory")

    def test_move_and_duplicate(self):
        item = self.save.new_item("Sword")
        self.save.move_item(item, to_chest=True)
        self.assertEqual(self.save.location(item), "chest")
        clone = self.save.duplicate_item(item)
        self.assertIsNot(clone, item)
        self.assertEqual(self.save.location(clone), "chest")
        self.assertNotEqual(clone["inventoryIndex"], item["inventoryIndex"])

    def test_max_out_enchantments(self):
        item = self.save.new_item("Sword")
        set_enchantment(item, 3, "Looting", 0)
        set_enchantment(item, 4, "Echo", 1)
        max_out_enchantments(item)
        self.assertEqual(item["enchantments"][4]["level"], 3)
        self.assertEqual(item["enchantments"][3]["level"], 0)

    def test_enchantment_points(self):
        self.save.level = 10
        item = self.save.new_item("Sword")
        set_enchantment(item, 0, "Sharpness", 3)
        self.assertEqual(self.save.enchantment_points_left(), 10 - 1 - 6)

    def test_detects_external_change(self):
        self.assertFalse(self.save.changed_on_disk())
        os.utime(self.path, (1, 1))
        self.assertTrue(self.save.changed_on_disk())


class WasdTests(unittest.TestCase):
    def test_stick_directions(self):
        from mcd_loader.wasd import stick_from_keys
        self.assertEqual(stick_from_keys(False, False, False, False), (0.0, 0.0))
        self.assertEqual(stick_from_keys(True, False, False, False), (0.0, 1.0))
        self.assertEqual(stick_from_keys(False, True, False, False), (-1.0, 0.0))
        self.assertEqual(stick_from_keys(True, True, True, True), (0.0, 0.0))
        x, y = stick_from_keys(True, False, False, True)
        self.assertAlmostEqual(x * x + y * y, 1.0)
        self.assertEqual(stick_from_keys(False, False, True, False, slow=True), (0.0, -0.5))


if __name__ == "__main__":
    unittest.main()
