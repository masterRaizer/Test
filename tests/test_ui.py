"""Behaviour tests for the Minecraft Dungeons module window (skipped without a display)."""
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from mcd_loader import crypto
from mcd_loader.savefile import SaveFile

BLANK = os.path.join(os.path.dirname(__file__), "data", "Blank.dat")


def make_save(path, items):
    with open(BLANK, "rb") as f:
        profile = json.loads(crypto.decrypt(f.read()))
    profile["items"] = items
    profile["name"] = os.path.basename(path)
    with open(path, "wb") as f:
        f.write(crypto.encrypt(json.dumps(profile).encode()))


SWORD = {"type": "Sword", "power": 2.0, "rarity": "Common", "equipmentSlot": "MeleeGear", "enchantments": [
    {"id": "Sharpness", "level": 0}, {"id": "Looting", "level": 0}, {"id": "Echo", "level": 0}]}
ARTIFACT = {"type": "FireworksArrowItem", "power": 2.0, "rarity": "Common", "equipmentSlot": "HotbarSlot1"}


class ModuleUiTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
            self.root = tk.Tk()
        except Exception as e:  # no display (e.g. headless Linux)
            self.skipTest(f"no display: {e}")
        self.root.withdraw()
        self.dir = tempfile.mkdtemp()
        from mcd_loader import catalog, game, overlay
        self.patches = [
            mock.patch.object(game, "APP_DIR", self.dir),
            mock.patch.object(game, "CONFIG_PATH", os.path.join(self.dir, "config.json")),
            mock.patch.object(game, "BACKUP_DIR", os.path.join(self.dir, "backups")),
            mock.patch.object(game, "CACHE_DIR", os.path.join(self.dir, "cache")),
            mock.patch.object(game, "is_game_running", lambda: False),
            mock.patch.object(catalog, "find_paks_dir", lambda *a, **k: None),
            mock.patch.object(overlay, "find_saves", lambda extra=(): list(self.saves)),
        ]
        for p in self.patches:
            p.start()
        self.saves = []
        for name in ("a.dat", "b.dat"):
            path = os.path.join(self.dir, name)
            make_save(path, [json.loads(json.dumps(SWORD)), json.loads(json.dumps(ARTIFACT))])
            self.saves.append(path)
        self.overlay = overlay
        self.app = overlay.LoaderApp(self.root, game.load_config(), initial_save=self.saves[0])
        self.pump()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.shutdown()
            self.root.destroy()
            for p in self.patches:
                p.stop()
            shutil.rmtree(self.dir, ignore_errors=True)

    def pump(self, seconds=0.2):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def select(self, item_type):
        iid, item = next((i, it) for i, it in self.app.items_by_iid.items() if it["type"] == item_type)
        self.app.tree.selection_set(iid)
        self.pump()
        self.assertIs(self.app.current_item, item)
        return item

    def test_viewing_and_editing_does_not_add_enchantments(self):
        sword = self.select("Sword")
        self.app.it_level.set("50")
        self.app.commit_item()
        self.assertEqual(len(sword["enchantments"]), 3)
        self.assertEqual([e["level"] for e in sword["enchantments"]], [0, 0, 0])
        self.app.max_all_enchantments()
        self.assertEqual([e["level"] for e in sword["enchantments"]], [0, 0, 0])

    def test_choosing_an_enchantment_in_the_editor(self):
        sword = self.select("Sword")
        self.app.ench_vars[1][1].set("2")
        self.app.commit_item()
        self.assertEqual([e["level"] for e in sword["enchantments"]], [0, 2, 0])
        self.assertEqual(len(sword["enchantments"]), 3)

    def test_artifacts_get_no_enchantments(self):
        artifact = self.select("FireworksArrowItem")
        self.app.ench_vars[0][0].set("Sharpness")
        self.app.ench_vars[0][1].set("3")
        self.app.gild_on.set(True)
        self.app.gild_id.set("Looting")
        self.app.commit_item()
        self.assertNotIn("enchantments", artifact)
        self.assertNotIn("netheriteEnchant", artifact)

    def test_cancelled_switch_keeps_current_save_selected(self):
        self.app.level_var.set("30")
        self.app.commit_character()
        self.assertTrue(self.app.save.dirty)
        with mock.patch.object(self.overlay.messagebox, "askyesno", return_value=False):
            self.app.save_box.current(self.app.saves.index(self.saves[1]))
            self.app.open_selected_save()
        self.assertEqual(self.app.save.path, self.saves[0])
        self.assertEqual(self.app.saves[self.app.save_box.current()], self.saves[0])

    def test_apply_writes_and_backs_up(self):
        self.app.level_var.set("40")
        self.app.apply_to_game()
        self.assertEqual(SaveFile(self.saves[0]).level, 40)
        self.assertTrue(os.listdir(os.path.join(self.dir, "backups")))

    def test_unapplied_json_is_offered_when_leaving_the_page(self):
        self.app.notebook.select(2)
        self.pump()
        data = json.loads(self.app.json_text.get("1.0", "end"))
        data["xp"] = 123456
        self.app.json_text.delete("1.0", "end")
        self.app.json_text.insert("1.0", json.dumps(data))
        with mock.patch.object(self.overlay.messagebox, "askyesno", return_value=True):
            self.app.notebook.select(0)
            self.pump()
        self.assertEqual(self.app.save.xp, 123456)


if __name__ == "__main__":
    unittest.main()
