"""Game catalog built from the installed game's .pak files.

Provides the complete list of item / enchantment / armor property IDs,
their localized names and icons (cached as PNG), the same way MCDSaveEdit
discovers them.
"""
import hashlib
import json
import os
import posixpath
import threading

from . import ue4pak

CATEGORIES = {"melee": "Ближний бой", "ranged": "Дальний бой", "armor": "Броня", "artifact": "Артефакты"}
CATEGORY_SLOT = {"melee": "MeleeGear", "ranged": "RangedGear", "armor": "ArmorGear", "artifact": "HotbarSlot1"}

# Icon folder name -> ID used in save files.
FOLDER_FIXES = {
    "TrickBow": "Trickbow", "TrickBow_Unique1": "Trickbow_Unique1", "TrickBow_Unique2": "Trickbow_Unique2",
    "TrickBow_Year1": "Trickbow_Year1", "LongBow": "Longbow", "LongBow_Unique1": "Longbow_Unique1",
    "LongBow_Unique2": "Longbow_Unique2", "PowerBow": "Powerbow", "PowerBow_Unique1": "Powerbow_Unique1",
    "PowerBow_Unique2": "Powerbow_Unique2", "Slowbow_Unique1": "SlowBow_Unique1", "ShortBow": "Shortbow",
    "ShortBow_Unique1": "Shortbow_Unique1", "ShortBow_Unique2": "Shortbow_Unique2",
    "ShortBow_Unique3": "Shortbow_Unique3", "Huntingbow_Unique1": "HuntingBow_Unique1",
    "TwistingVineBow_UNique1": "TwistingVineBow_Unique1", "Battlerobe_unique1": "BattleRobe_Unique1",
    "Sword_Steel": "Sword", "Pickaxe_Steel": "Pickaxe", "Pickaxe_Unique1_Steel": "Pickaxe_Unique1",
    "Daggers_unique2": "Daggers_Unique2", "Beenest": "BeeNest", "SatchelofNourishment": "SatchelOfNourishment",
    "SatchelofNeed": "SatchelOfNeed", "Firetrail": "FireTrail",
}
# Items that exist as icons but break the game when added.
BLOCKED_ITEMS = ("MysteryBox", "Potions", "Food", "Elytra", "EyeOfEnder", "TNTBox", "Trident", "HighlanderLongSword")

# Save-file ID -> localization key, where they differ (from MCDSaveEdit).
STRING_KEY_FIXES = {
    "Unset_desc": "Unset",
    "Accelerating": "Accelerate", "AnimaConduitMelee": "Anima", "AnimaConduitMelee_desc": "Anima_desc",
    "AnimaConduitRanged": "Anima", "AnimaConduitRanged_desc": "AnimaRanged_desc", "Celerity": "Cool Down",
    "ChainReaction_desc": "Chain_desc", "CriticalHit": "Critical", "CriticalHit_desc": "Critical_desc",
    "Deflecting": "Deflect", "EnigmaResonatorMelee": "EnigmaMelee", "EnigmaResonatorRanged": "EnigmaRanged",
    "FireAspect": "Fire", "FireAspect_desc": "Fire_desc", "Firetrail": "FireTrail",
    "Firetrail_desc": "FireTrail_desc", "Gravity": "GravityMelee", "Gravity_desc": "GravityMelee_desc",
    "JunglePoisonRanged": "JunglePoison", "MultiShot": "Multi", "MultiShot_desc": "Multi_desc",
    "PoisonedMelee": "Poisoned", "PoisonedRanged": "Poisoned", "PoisonedMelee_desc": "Poisoned_desc",
    "PoisonedRanged_desc": "Poisoned_desc", "Shockwave": "Shock", "Shockwave_desc": "Shock_desc",
    "SoulSiphon": "Soul", "TempoTheft": "Tempo", "TempoTheft_desc": "Tempo_desc",
    "JunglePoisonMelee_desc": "JunglePoisonMelee", "JunglePoisonRanged_desc": "JunglePoison",
    "EnigmaResonatorMelee_desc": "Enigma_desc", "EnigmaResonatorRanged_desc": "EnigmaRanged_desc",
    "SoulSiphon_desc": "Soul_desc", "EmeraldDivination_desc": "EmeraldDivination_effect_desc",
    "DeathBarter_desc": "DeathBarter_effect_desc", "VoidTouchedMelee": "VoidStrikeMelee",
    "VoidTouchedMelee_desc": "VoidStrikeMelee_desc", "VoidTouchedRanged": "VoidStrikeRanged",
    "VoidTouchedRanged_desc": "VoidStrikeRanged_desc", "Powerbow": "PowerBow",
    "Powerbow_Unique1": "PowerBow_Unique1", "Powerbow_Unique2": "PowerBow_Unique2",
    "Flavour_Sword": "Desc_Sword", "Flavour_Sword_Steel": "Desc_Sword",
    "Flavour_Sword_Spooky1": "Desc_Sword_Spooky1", "Flavour_ShortBow_Unique3": "Flavour_Shortbow_Unique3",
    "CorruptedSeeds": "CorruptedSeeds_Unique1", "Flavour_CorruptedSeeds": "Flavour_CorruptedSeeds_Unique1",
    "Beenest": "BeeNest", "Flavour_Beenest": "Flavour_BeeNest", "Daggers_unique2": "Daggers_Unique2",
    "Flavour_Daggers_unique2": "Flavour_Daggers_Unique2", "HighlanderLongSword": "Sword",
    "Flavour_HighlanderLongSword": "Desc_Sword", "LongBow": "Longbow", "Flavour_LongBow": "Flavour_Longbow",
    "LongBow_Unique1": "Longbow_Unique1", "LongBow_Unique2": "Longbow_Unique2",
    "TwistingVineBow_UNique1": "TwistingVineBow_Unique1",
    "Flavour_TwistingVineBow_UNique1": "Flavour_TwistingVineBow_Unique1", "OakWoodBrew": "OakwoodBrew",
    "Pickaxe_Steel": "Pickaxe", "Flavour_Pickaxe_Steel": "Flavour_Pickaxe",
    "Pickaxe_Unique1_Steel": "Pickaxe_Unique1", "Flavour_Pickaxe_Unique1_Steel": "Flavour_Pickaxe_Unique1",
    "ShortBow_Unique1": "Shortbow_Unique1", "ShortBow_Unique2": "Shortbow_Unique1",
    "ShortBow_Unique3": "Shortbow_Unique1", "Slowbow_Unique1": "SlowBow_Unique1", "Sword_Steel": "Sword",
    "Flavour_Sword_Unique2": "Desc_Sword_Unique2", "Flavour_Sword_Unique1": "Desc_Sword_Unique1",
    "TrickBow": "Trickbow", "TrickBow_Unique1": "Trickbow_Unique1", "TrickBow_Unique2": "Trickbow_Unique2",
    "TrickBow_Year1": "Trickbow_Year1", "Flavour_TrickBow_Year1": "Flavour_Trickbow_Year1",
    "Flavour_LongBow_Unique1": "Flavour_Longbow_Unique1",
    "Flavour_LongBow_Unique2": "Flavour_Longbow_Unique2", "Flavour_PowerBow": "Flavour_Powerbow",
    "Flavour_PowerBow_Unique1": "Flavour_Powerbow_Unique1",
    "Flavour_PowerBow_Unique2": "Flavour_Powerbow_Unique2",
    "Flavour_ShortBow_Unique1": "Flavour_Shortbow_Unique1",
    "Flavour_ShortBow_Unique2": "Flavour_Shortbow_Unique2",
    "Flavour_Slowbow_Unique1": "Flavour_SlowBow_Unique1", "Flavour_TrickBow": "Flavour_Trickbow",
    "Flavour_TrickBow_Unique1": "Flavour_Trickbow_Unique1",
    "Flavour_TrickBow_Unique2": "Flavour_Trickbow_Unique2",
    "Flavour_BackstabbersBrew": "Desc_BackstabbersBrew", "Flavour_HealthPotion": "Desc_HealthPotion",
    "Flavour_OakWoodBrew": "OakwoodBrew", "Flavour_StrengthPotion": "Desc_StrengthPotion",
    "Flavour_SwiftnessPotion": "Desc_SwiftnessPotion", "Flavour_TNTBox": "Desc_TNTBox",
    "EmeraldArmor_Unique1": "Emerald_Armor_Unique1", "EmeraldArmor_Unique2": "Emerald_Armor_Unique2",
    "Flavour_ClimbingGear_Unique1": "Flavour_ClimbingGearSolid",
    "Flavour_ThunderingQuiver": "Flavour_ThunderQuiver", "Flavour_Anchor": "Flavour_Anchor_Unique1",
    "Flavour_CoralBlade": "Flavour_CoralBlade_Unique1",
    "Flavour_HarpoonCrossbow": "Flavour_HarpoonCrossbow_Unique1",
    "Flavour_WaterBreathingPotion": "Desc_WaterBreathingPotion", "SatchelofNeed": "SatchelOfNeed",
    "Flavour_SatchelofNeed": "Flavour_SatchelOfNeed", "SatchelofNourishment": "Desc_SatchelOfNourishment",
    "Flavour_SatchelofNourishment": "Flavour_SatchelOfNourishment",
    "Flavour_Backstabber_Unique1": "Desc_Backstabber_Unique1", "Flavour_Backstabber": "Desc_Backstabber",
    "Flavour_Trident": "Desc_Trident", "Flavour_LostEvocation": "Flavor_LostEvocation",
    "Flavour_Elytra": "Desc_Elytra", "Flavour_EyeOfEnder": "Desc_EyeOfEnder",
    "Flavour_GhostArmor_Spooky2": "Flavour_GhostArmor_Unique1", "Spear_Spooky2": "Spear_spooky2",
    "Flavour_Spear_Spooky2": "Flavour_Spear_spooky2", "ReviveChance": "Unset",
    "ReviveChance_description": "Unset", "ItemCooldownDecrease": "ArtifactCooldownDecrease",
    "ItemCooldownDecrease_description": "ArtifactCooldownDecrease_description",
    "ItemDamageBoost": "ArtifactDamageBoost",
    "ItemDamageBoost_description": "ArtifactDamageBoost_description", "SlowResistance": "FreezingResistance",
    "SlowResistance_description": "FreezingResistance_description",
    "FallResistance": "EnviromentalProtection",
    "FallResistance_description": "EnviromentalProtection_description", "Reckless_desc": "ShardArmor_desc",
    "Flee_desc": "Flee_effect_desc", "ReliableRicochet_desc": "Ricochet_desc",
}


PAK_MARKER = "pakchunk0"


def _is_paks_dir(path):
    try:
        return os.path.isdir(path) and any(n.lower().startswith(PAK_MARKER) and n.lower().endswith(".pak")
                                           for n in os.listdir(path))
    except OSError:
        return False


def paks_from_install(path):
    """Paks folder for anything inside a game install: Dungeons.exe, the shipping exe or a folder."""
    if not path:
        return None
    path = os.path.normpath(path)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    probe = path
    for _ in range(6):  # walk up: ...\Dungeons\Binaries\Win64 -> install root
        for sub in (("Paks",), ("Content", "Paks"), ("Dungeons", "Content", "Paks"),
                    ("Content", "Dungeons", "Content", "Paks")):
            cand = os.path.join(probe, *sub)
            if _is_paks_dir(cand):
                return cand
        if _is_paks_dir(probe):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return None


def search_paks(root, max_depth=7):
    """Look for the game's Paks folder anywhere below root (depth-limited)."""
    root = os.path.normpath(root)
    base_depth = root.count(os.sep)
    for current, dirs, files in os.walk(root):
        if any(f.lower().startswith(PAK_MARKER) and f.lower().endswith(".pak") for f in files):
            return current
        if current.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not d.startswith(("$", ".")) and d.lower() not in ("windows", "saved")]
    return None


def running_game_exes():
    """Full paths of running Minecraft Dungeons processes (Windows only)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    found = []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() in ("dungeons.exe", "dungeons-win64-shipping.exe"):
                handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(len(buf))
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        found.append(buf.value)
                    kernel32.CloseHandle(handle)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return found


def steam_libraries():
    roots = []
    for pf in filter(None, (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"))):
        steam = os.path.join(pf, "Steam")
        roots.append(steam)
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.strip().split('"')
                    if len(parts) >= 4 and parts[1].lower() == "path":
                        roots.append(parts[3].replace("\\\\", "\\"))
        except OSError:
            pass
    return roots


def _drives():
    if os.name != "nt":
        return []
    return [f"{c}:\\" for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]


def default_paks_dirs(game_path=""):
    dirs = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Mojang", "products", "dungeons", "dungeons", "Dungeons", "Content", "Paks"))
    for lib in steam_libraries():
        dirs.append(os.path.join(lib, "steamapps", "common", "MinecraftDungeons", "Dungeons", "Content", "Paks"))
    for drive in _drives():
        dirs.append(os.path.join(drive, "XboxGames", "Minecraft Dungeons", "Content", "Dungeons", "Content", "Paks"))
        dirs.append(os.path.join(drive, "Program Files", "Minecraft Dungeons", "Dungeons", "Content", "Paks"))
    return dirs


def find_paks_dir(configured="", game_path=""):
    """Best guess of the Paks folder: settings, the running game, then the usual install places."""
    for hint in (configured, game_path, *running_game_exes()):
        found = paks_from_install(hint) if hint else None
        if found:
            return found
    for d in default_paks_dirs(game_path):
        if _is_paks_dir(d):
            return d
    return None


def _fingerprint(paks_dir):
    parts = []
    for name in sorted(os.listdir(paks_dir)):
        if name.lower().endswith(".pak"):
            st = os.stat(os.path.join(paks_dir, name))
            parts.append(f"{name}:{st.st_size}:{int(st.st_mtime)}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def scan_paths(paths):
    """Classify pak paths into items, enchantments, armor properties and locres files."""
    items, enchantments, props, locres = {}, {}, set(), {}
    for path in paths:
        lower = path.lower()
        if lower.endswith(".locres") and "/localization/game/" in lower:
            locres[posixpath.basename(posixpath.dirname(path))] = path
            continue
        if not lower.endswith(".uasset"):
            continue
        asset = path[:-len(".uasset")]
        folder = posixpath.basename(posixpath.dirname(asset))
        filename = posixpath.basename(asset)
        if "ArmorProperties" in path and "Cues" not in path:
            if folder not in ("ArmorProperties", "ReviveChance"):
                props.add(folder)
            continue
        low_asset = asset.lower()
        if not filename.startswith("T") or "_icon" not in low_asset:
            continue
        if "Enchantments" in asset and low_asset.endswith("_icon"):
            if not folder.endswith("Shine"):
                enchantments.setdefault(FOLDER_FIXES.get(folder, folder), asset)
            continue
        if low_asset.endswith("_icon_inventory"):
            folders = posixpath.dirname(asset)
            if any(b in folders for b in BLOCKED_ITEMS) or filename.startswith("T_Arrow_Icon"):
                continue
            if "Equipment" in asset and "MeleeWeapons" in asset:
                category = "melee"
            elif "Equipment" in asset and "RangedWeapons" in asset:
                category = "ranged"
            elif "Equipment" in asset and "Armor" in asset:
                category = "armor"
            elif "Items" in asset:
                category = "artifact"
            else:
                continue
            items.setdefault(FOLDER_FIXES.get(folder, folder), {"category": category, "icon": asset})
    return items, enchantments, props, locres


class GameCatalog:
    def __init__(self):
        self.items = {}          # id -> {"category", "icon"}
        self.enchantments = {}   # id -> icon asset path
        self.armor_properties = set()
        self.strings = {}        # namespace -> {key: text}
        self.language = None
        self.version = None
        self.paks_dir = None
        self.cache_dir = None
        self._index = None
        self._keys = ()
        self._lock = threading.Lock()

    @property
    def loaded(self):
        return bool(self.items)

    # --------------------------------------------------------- loading
    @classmethod
    def load(cls, paks_dir, cache_dir, user_keys=(), language="ru-RU"):
        cat = cls()
        cat.paks_dir, cat.cache_dir, cat._keys = paks_dir, cache_dir, tuple(k for k in user_keys if k)
        os.makedirs(os.path.join(cache_dir, "icons"), exist_ok=True)
        cache_file = os.path.join(cache_dir, "catalog.json")
        fingerprint = _fingerprint(paks_dir)
        try:
            with open(cache_file, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fingerprint") == fingerprint and cached.get("language") == language:
                cat._from_dict(cached)
                return cat
        except (OSError, ValueError):
            pass
        index = cat.index()
        items, enchantments, props, locres = scan_paths(index.paths())
        cat.items, cat.enchantments, cat.armor_properties = items, enchantments, props
        cat.version = index.version_label
        cat.language, cat.strings = cat._load_strings(index, locres, language)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(dict(cat._to_dict(), fingerprint=fingerprint), f, ensure_ascii=False)
        return cat

    def _load_strings(self, index, locres, language):
        wanted = [language, language.split("-")[0], "en", "en-US"]
        lang = next((l for l in wanted if l in locres), None)
        if not lang:
            return None, {}
        try:
            tables = ue4pak.parse_locres(index.read(locres[lang]))
        except (ue4pak.PakError, KeyError):
            return None, {}
        keep = ("ItemType", "Enchantment", "ArmorProperties", "ItemTag")
        return lang, {ns: tables[ns] for ns in keep if ns in tables}

    def _to_dict(self):
        return {"items": self.items, "enchantments": self.enchantments,
                "armor_properties": sorted(self.armor_properties), "strings": self.strings,
                "language": self.language, "version": self.version}

    def _from_dict(self, d):
        self.items = d.get("items", {})
        self.enchantments = d.get("enchantments", {})
        self.armor_properties = set(d.get("armor_properties", []))
        self.strings = d.get("strings", {})
        self.language = d.get("language")
        self.version = d.get("version")

    def index(self):
        with self._lock:
            if self._index is None:
                self._index = ue4pak.PakIndex(self.paks_dir, self._keys)
            return self._index

    # ----------------------------------------------------------- names
    def _text(self, namespace, key):
        table = self.strings.get(namespace, {})
        return table.get(STRING_KEY_FIXES.get(key, key)) or table.get(key)

    def item_name(self, item_id):
        return self._text("ItemType", item_id) or item_id

    def item_description(self, item_id):
        return self._text("ItemType", "Flavour_" + item_id) or self._text("ItemType", "Desc_" + item_id) or ""

    def enchantment_name(self, ench_id):
        return self._text("Enchantment", ench_id) or ench_id

    def enchantment_description(self, ench_id):
        return self._text("Enchantment", ench_id + "_desc") or ""

    def armor_property_name(self, prop_id):
        return self._text("ArmorProperties", prop_id) or prop_id

    def armor_property_description(self, prop_id):
        return self._text("ArmorProperties", prop_id + "_description") or ""

    def category(self, item_id):
        return (self.items.get(item_id) or {}).get("category")

    # ----------------------------------------------------------- icons
    def _icon_asset(self, kind, ident):
        if kind == "item":
            return (self.items.get(ident) or {}).get("icon")
        if kind == "enchantment":
            return self.enchantments.get(ident)
        return None

    def icon_file(self, kind, ident, extract=True):
        """Path of the cached PNG icon; extracts it from the paks when allowed (None if unavailable)."""
        asset = self._icon_asset(kind, ident)
        if not asset or not self.cache_dir:
            return None
        name = hashlib.sha1(asset.lower().encode()).hexdigest() + ".png"
        target = os.path.join(self.cache_dir, "icons", name)
        if os.path.exists(target):
            return target
        failed = target + ".failed"
        if not extract or os.path.exists(failed):
            return None
        try:
            image = ue4pak.read_texture(self.index(), asset)
            tmp = target + ".tmp"
            image.save(tmp, "PNG")
            os.replace(tmp, target)
            return target
        except Exception as e:  # keep going: a missing icon must not break the editor
            with open(failed, "w", encoding="utf-8") as f:
                f.write(str(e))
            return None

    def icon_stats(self):
        """(extracted, failed, first failure message) for the icons of this catalog."""
        ok = failed = 0
        sample = ""
        for kind, ids in (("item", self.items), ("enchantment", self.enchantments)):
            for ident in ids:
                asset = self._icon_asset(kind, ident)
                if not asset:
                    continue
                target = os.path.join(self.cache_dir, "icons", hashlib.sha1(asset.lower().encode()).hexdigest() + ".png")
                if os.path.exists(target):
                    ok += 1
                elif os.path.exists(target + ".failed"):
                    failed += 1
                    if not sample:
                        with open(target + ".failed", encoding="utf-8") as f:
                            sample = f"{asset}: {f.read()}"
        return ok, failed, sample

    def extract_all_icons(self, stop=lambda: False):
        for kind, ids in (("enchantment", list(self.enchantments)), ("item", list(self.items))):
            for ident in ids:
                if stop():
                    return
                self.icon_file(kind, ident)
