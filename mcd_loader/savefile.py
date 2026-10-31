"""Character save model: load, edit and write back Minecraft Dungeons *.dat files."""
import copy
import glob
import json
import os
import shutil
import time

from . import crypto, gamedata as gd


def default_save_roots():
    roots = []
    home = os.path.expanduser("~")
    roots.append(os.path.join(home, "Saved Games", "Mojang Studios", "Dungeons"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        # Microsoft Store / Game Pass build
        roots.append(os.path.join(local, "Packages", "Microsoft.Lovika_8wekyb3d8bbwe", "LocalCache", "Local", "Dungeons"))
    return roots


def find_saves(extra_roots=()):
    """All character files under the known save folders, newest first."""
    found = set()
    for root in list(default_save_roots()) + list(extra_roots):
        if not root or not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "*.dat"), recursive=True):
            if os.path.basename(os.path.dirname(path)).lower() == "characters":
                found.add(os.path.normpath(path))
    return sorted(found, key=os.path.getmtime, reverse=True)


def read_profile(path):
    with open(path, "rb") as f:
        raw = f.read()
    plain = crypto.decrypt(raw) if crypto.is_encrypted(raw) else raw.rstrip(b"\x00")
    return json.loads(plain.decode("utf-8"))


def dump_profile(profile):
    return json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SaveFile:
    def __init__(self, path):
        self.path = path
        self.profile = {}
        self.mtime = 0.0
        self.dirty = False
        self.reload()

    # --- file I/O -------------------------------------------------------
    def reload(self):
        self.profile = read_profile(self.path)
        self.mtime = os.path.getmtime(self.path)
        self.dirty = False

    def changed_on_disk(self):
        try:
            return os.path.getmtime(self.path) != self.mtime
        except OSError:
            return False

    def backup(self, backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name, ext = os.path.splitext(os.path.basename(self.path))
        target = os.path.join(backup_dir, f"{name}_{stamp}{ext}")
        shutil.copy2(self.path, target)
        return target

    def write(self, backup_dir=None):
        backup = self.backup(backup_dir) if backup_dir and os.path.exists(self.path) else None
        data = crypto.encrypt(dump_profile(self.profile))
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self.path)
        self.mtime = os.path.getmtime(self.path)
        self.dirty = False
        return backup

    def export_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, ensure_ascii=False, indent=2)

    # --- character ------------------------------------------------------
    @property
    def name(self):
        return self.profile.get("name") or os.path.splitext(os.path.basename(self.path))[0]

    @property
    def xp(self):
        return int(self.profile.get("xp") or 0)

    @xp.setter
    def xp(self, value):
        self.profile["xp"] = max(0, int(value))
        self.dirty = True

    @property
    def level(self):
        return gd.level_for_xp(self.xp)

    @level.setter
    def level(self, value):
        self.xp = gd.xp_for_level(value)

    def get_currency(self, kind):
        for c in self.profile.get("currency") or []:
            if c.get("type") == kind:
                return int(c.get("count") or 0)
        return 0

    def set_currency(self, kind, count):
        currencies = self.profile.setdefault("currency", [])
        if currencies is None:
            currencies = self.profile["currency"] = []
        count = max(0, int(count))
        for c in currencies:
            if c.get("type") == kind:
                c["count"] = count
                break
        else:
            currencies.append({"count": count, "type": kind})
        found = self.profile.get("currenciesFound")
        if isinstance(found, list) and kind not in found:
            found.append(kind)
        self.dirty = True

    def get_difficulty(self):
        return (self.profile.get("difficulties") or {}).get("unlocked") or gd.DIFFICULTIES[0]

    def set_difficulty(self, value):
        diff = self.profile.get("difficulties") or {}
        diff["unlocked"] = value
        self.profile["difficulties"] = diff
        self.dirty = True

    def get_threat(self):
        return (self.profile.get("threatLevels") or {}).get("unlocked") or gd.THREAT_LEVELS[0]

    def set_threat(self, value):
        threats = self.profile.get("threatLevels") or {}
        threats["unlocked"] = value
        self.profile["threatLevels"] = threats
        self.dirty = True

    # --- items ----------------------------------------------------------
    @property
    def inventory(self):
        if self.profile.get("items") is None:
            self.profile["items"] = []
        return self.profile["items"]

    @property
    def chest(self):
        if self.profile.get("storageChestItems") is None:
            self.profile["storageChestItems"] = []
        return self.profile["storageChestItems"]

    def all_items(self):
        return list(self.inventory) + list(self.chest)

    def equipped(self, slot):
        return next((i for i in self.inventory if i.get("equipmentSlot") == slot), None)

    def character_power(self):
        powers = [(self.equipped(s) or {}).get("power", 0) for s in gd.EQUIPMENT_SLOTS]
        return gd.character_power(*powers)

    def enchantment_points_spent(self):
        total = 0
        for item in self.all_items():
            gilded = item.get("netheriteEnchant") is not None
            for ench in item.get("enchantments") or []:
                total += gd.enchantment_cost(ench.get("id"), ench.get("level"), gilded)
        return total

    def enchantment_points_left(self):
        # Matches MCDSaveEdit: one point is consumed by level 1.
        return self.level - 1 - self.enchantment_points_spent()

    @staticmethod
    def _next_index(collection):
        indexes = [i.get("inventoryIndex") for i in collection if i.get("inventoryIndex") is not None]
        return (max(indexes) + 1) if indexes else 0

    def new_item(self, item_type, slot=None, in_chest=False):
        item = {
            "enchantments": [{"id": gd.UNSET_ENCHANTMENT, "level": 0} for _ in range(gd.ENCHANTMENTS_PER_ITEM)],
            "markedNew": True,
            "power": gd.power_from_level(1),
            "rarity": "Common",
            "type": item_type,
            "upgraded": False,
        }
        if slot and slot.startswith("Hotbar"):
            item.pop("enchantments")
        self.add_item(item, slot=slot, in_chest=in_chest)
        return item

    def add_item(self, item, slot=None, in_chest=False):
        if in_chest:
            item.pop("equipmentSlot", None)
            item["inventoryIndex"] = self._next_index(self.chest)
            self.chest.append(item)
        else:
            self._place_in_inventory(item, slot)
            self.inventory.append(item)
        found = self.profile.get("itemsFound")
        if isinstance(found, list) and item.get("type") and item["type"] not in found:
            found.append(item["type"])
        self.dirty = True
        return item

    def _place_in_inventory(self, item, slot):
        item.pop("equipmentSlot", None)
        item.pop("inventoryIndex", None)
        if slot:
            current = self.equipped(slot)
            if current is not None and current is not item:
                current.pop("equipmentSlot", None)
                current["inventoryIndex"] = self._next_index(self.inventory)
            item["equipmentSlot"] = slot
        else:
            item["inventoryIndex"] = self._next_index(self.inventory)

    def duplicate_item(self, item):
        clone = copy.deepcopy(item)
        clone.pop("equipmentSlot", None)
        return self.add_item(clone, in_chest=self.location(item) == "chest")

    def remove_item(self, item):
        for coll in (self.inventory, self.chest):
            for i, it in enumerate(coll):
                if it is item:
                    del coll[i]
                    self.dirty = True
                    return True
        return False

    def location(self, item):
        if any(it is item for it in self.chest):
            return "chest"
        return "inventory"

    def move_item(self, item, to_chest):
        self.remove_item(item)
        self.add_item(item, in_chest=to_chest)

    def equip(self, item, slot):
        """Equip an inventory item into slot (or unequip when slot is None)."""
        if self.location(item) == "chest":
            self.remove_item(item)
            self._place_in_inventory(item, slot)
            self.inventory.append(item)
        else:
            self._place_in_inventory(item, slot)
        self.dirty = True

    def known_item_types(self):
        types = set(gd.DEFAULT_ITEM_FOR_SLOT.values())
        types.update(self.profile.get("itemsFound") or [])
        types.update(i.get("type") for i in self.all_items() if i.get("type"))
        return types

    def known_enchantments(self):
        ids = set(gd.KNOWN_ENCHANTMENTS)
        for item in self.all_items():
            for e in (item.get("enchantments") or []) + [item.get("netheriteEnchant") or {}]:
                if e.get("id"):
                    ids.add(e["id"])
        ids.discard(gd.UNSET_ENCHANTMENT)
        return ids

    def known_armor_properties(self):
        ids = {gd.DEFAULT_ARMOR_PROPERTY}
        for item in self.all_items():
            ids.update(p.get("id") for p in item.get("armorproperties") or [] if p.get("id"))
        return ids


# --- item helpers (operate on raw item dicts) ---------------------------
def item_level(item):
    return gd.level_from_power(float(item.get("power") or 0))


def set_item_level(item, level):
    item["power"] = gd.power_from_level(int(level))


def set_enchantment(item, index, enchantment_id, level):
    enchants = item.setdefault("enchantments", [])
    while len(enchants) < gd.ENCHANTMENTS_PER_ITEM:
        enchants.append({"id": gd.UNSET_ENCHANTMENT, "level": 0})
    level = max(0, min(3, int(level)))
    ench = enchants[index]
    ench["id"] = enchantment_id or gd.UNSET_ENCHANTMENT
    ench["level"] = level if ench["id"] != gd.UNSET_ENCHANTMENT else 0
    gilded = item.get("netheriteEnchant") is not None
    ench["investedPoints"] = gd.enchantment_cost(ench["id"], ench["level"], gilded)
    # Only one enchantment per slot may be active.
    if ench["level"] > 0:
        base = index - index % 3
        for j in range(base, base + 3):
            if j != index:
                enchants[j]["level"] = 0
                enchants[j]["investedPoints"] = 0


def recompute_invested_points(item):
    gilded = item.get("netheriteEnchant") is not None
    for e in item.get("enchantments") or []:
        e["investedPoints"] = gd.enchantment_cost(e.get("id"), e.get("level"), gilded)


def max_out_enchantments(item):
    """Set the first real enchantment of each slot to level 3."""
    enchants = item.get("enchantments") or []
    for base in range(0, len(enchants), 3):
        group = enchants[base:base + 3]
        active = next((k for k, e in enumerate(group) if e.get("level") and e.get("id") != gd.UNSET_ENCHANTMENT), None)
        if active is None:
            active = next((k for k, e in enumerate(group) if e.get("id") != gd.UNSET_ENCHANTMENT), None)
        if active is not None:
            set_enchantment(item, base + active, group[active]["id"], 3)


def describe_item(item):
    parts = []
    for e in item.get("enchantments") or []:
        if e.get("level") and e.get("id") != gd.UNSET_ENCHANTMENT:
            parts.append(f"{e['id']} {e['level']}")
    gilded = item.get("netheriteEnchant")
    if gilded:
        parts.append(f"★{gilded.get('id')} {gilded.get('level', 0)}")
    return ", ".join(parts)
