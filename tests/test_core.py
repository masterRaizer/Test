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


class EnchantmentPointsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Characters", "hero.dat")
        os.makedirs(os.path.dirname(self.path))
        shutil.copy(BLANK, self.path)
        self.save = SaveFile(self.path)
        self.save.level = 50
        self.sword = self.save.new_item("Sword", slot="MeleeGear")
        set_enchantment(self.sword, 0, "Sharpness", 3)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_free_points_via_level(self):
        self.save.set_free_points_via_level(1000)
        self.assertEqual(self.save.enchantment_points_left(), 1000)
        self.assertEqual(self.save.level, 1000 + 6 + 1)

    def test_bonus_points_roundtrip_and_survive_edits(self):
        from mcd_loader.savefile import recompute_invested_points
        item = self.save.set_bonus_points(950)
        self.assertIs(item, self.sword)
        self.assertEqual(self.save.bonus_points(), 950)
        recompute_invested_points(self.sword)
        set_enchantment(self.sword, 1, "Looting", 0)
        set_enchantment(self.sword, 3, "Echo", 2)
        self.assertEqual(self.save.bonus_points(), 950)
        self.save.write()
        again = SaveFile(self.path)
        self.assertEqual(again.bonus_points(), 950)
        self.assertEqual(again.level, 50)
        again.set_bonus_points(0)
        self.assertEqual(again.bonus_points(), 0)

    def test_bonus_needs_enchantable_item(self):
        self.save.remove_item(self.sword)
        with self.assertRaises(ValueError):
            self.save.set_bonus_points(10)


class PortalTests(unittest.TestCase):
    def test_unlock_portal(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "hero.dat")
            shutil.copy(BLANK, path)
            s = SaveFile(path)
            self.assertIsNone(s.portal_unlocked())
            s.profile["strongholdProgress"] = {"FirstUnlocked": True, "SecondUnlocked": False, "Seen": False}
            self.assertFalse(s.portal_unlocked())
            self.assertTrue(s.unlock_portal())
            self.assertTrue(s.portal_unlocked())
            self.assertFalse(s.profile["strongholdProgress"]["Seen"])
            self.assertFalse(s.unlock_portal())
        finally:
            shutil.rmtree(d)


class EnchantmentRegressionTests(unittest.TestCase):
    """The game stores three offered options per slot; only level > 0 marks the chosen one."""

    def offered(self):
        return {"type": "Sword", "power": 2.0, "rarity": "Common", "enchantments": [
            {"id": "Sharpness", "level": 0}, {"id": "Looting", "level": 2}, {"id": "Echo", "level": 0}]}

    def test_max_out_keeps_unchosen_options(self):
        from mcd_loader.savefile import max_out_enchantments
        item = self.offered()
        item["enchantments"][1]["level"] = 0
        self.assertFalse(max_out_enchantments(item))
        self.assertEqual([e["level"] for e in item["enchantments"]], [0, 0, 0])
        item["enchantments"][1]["level"] = 2
        self.assertTrue(max_out_enchantments(item))
        self.assertEqual([e["level"] for e in item["enchantments"]], [0, 3, 0])

    def test_set_enchantment_on_short_list_does_not_pad_or_crash(self):
        item = self.offered()
        set_enchantment(item, 0, "Sharpness", 3)
        self.assertEqual(len(item["enchantments"]), 3)
        self.assertEqual([e["level"] for e in item["enchantments"]], [3, 0, 0])

    def test_clear_enchantments(self):
        from mcd_loader.savefile import clear_enchantments
        item = self.offered()
        self.assertTrue(clear_enchantments(item))
        self.assertEqual([e["level"] for e in item["enchantments"]], [0, 0, 0])
        self.assertEqual([e["id"] for e in item["enchantments"]], ["Sharpness", "Looting", "Echo"])


class ConfigTests(unittest.TestCase):
    def test_bad_values_fall_back_to_defaults(self):
        from unittest import mock
        from mcd_loader import game
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "config.json")
            with open(path, "w") as f:
                json.dump({"overlay_alpha": "x", "hotkey": "Q", "backup_on_apply": False, "paks_dir": 5,
                           "custom": 1}, f)
            with mock.patch.object(game, "CONFIG_PATH", path):
                cfg = game.load_config()
            self.assertEqual(cfg["overlay_alpha"], game.DEFAULT_CONFIG["overlay_alpha"])
            self.assertEqual(cfg["hotkey"], "F8")
            self.assertFalse(cfg["backup_on_apply"])
            self.assertEqual(cfg["paks_dir"], "")
            self.assertEqual(cfg["custom"], 1)
        finally:
            shutil.rmtree(d)


class CopyPasteAndBonusTests(unittest.TestCase):
    def test_copy_paste_enchantments(self):
        from mcd_loader.savefile import copy_enchantments, paste_enchantments
        dagger = {"type": "Daggers", "enchantments": [
            {"id": "Sharpness", "level": 3, "investedPoints": 6}, {"id": "Looting", "level": 0},
            {"id": "Echo", "level": 0}, {"id": "Unset", "level": 0, "investedPoints": -500}],
            "netheriteEnchant": {"id": "Leeching", "level": 2}}
        sword = {"type": "Sword", "enchantments": [{"id": "Chains", "level": 1}]}
        payload = copy_enchantments(dagger)
        paste_enchantments(sword, json.loads(json.dumps(payload)))
        self.assertEqual([(e["id"], e["level"]) for e in sword["enchantments"]],
                         [("Sharpness", 3), ("Looting", 0), ("Echo", 0), ("Unset", 0)])
        self.assertEqual(sword["netheriteEnchant"], {"id": "Leeching", "level": 2})
        self.assertFalse(any(int(e.get("investedPoints") or 0) < 0 for e in sword["enchantments"]))
        self.assertEqual(sword["enchantments"][0]["investedPoints"], 9)  # gilded cost
        sword["enchantments"][0]["level"] = 1  # editing the copy leaves the source alone
        self.assertEqual(dagger["enchantments"][0]["level"], 3)

    def test_bonus_found_and_removed_wherever_it_moved(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "hero.dat")
            shutil.copy(BLANK, path)
            s = SaveFile(path)
            sword = s.new_item("Sword")
            set_enchantment(sword, 0, "Sharpness", 2)
            sword["enchantments"][0]["investedPoints"] = -400  # the game moved the bonus here
            sword["netheriteEnchant"] = {"id": "Looting", "level": 1, "investedPoints": -100}
            self.assertEqual(s.bonus_points(), 500)
            s.set_bonus_points(0)
            self.assertEqual(s.bonus_points(), 0)
            self.assertEqual(sword["enchantments"][0]["investedPoints"], 5)  # level 2: 1+2, gilded +2
            self.assertEqual(sword["netheriteEnchant"]["investedPoints"], 1)
        finally:
            shutil.rmtree(d)


class BonusOnRealItemsTests(unittest.TestCase):
    def test_bonus_uses_unchosen_option_and_survives_choosing_it(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "hero.dat")
            shutil.copy(BLANK, path)
            s = SaveFile(path)
            sword = {"type": "Sword", "power": 2.0, "rarity": "Common", "equipmentSlot": "MeleeGear",
                     "enchantments": [{"id": "Sharpness", "level": 0}, {"id": "Looting", "level": 0},
                                      {"id": "Echo", "level": 1}]}
            s.inventory.append(sword)
            s.set_bonus_points(300)  # game items have no Unset entries
            self.assertEqual(s.bonus_points(), 300)
            carrier = next(i for i, e in enumerate(sword["enchantments"]) if int(e.get("investedPoints") or 0) < 0)
            set_enchantment(sword, carrier, sword["enchantments"][carrier]["id"], 2)
            self.assertEqual(s.bonus_points(), 300)
            self.assertEqual(len(sword["enchantments"]), 3)
            s.set_bonus_points(0)
            self.assertEqual(s.bonus_points(), 0)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
