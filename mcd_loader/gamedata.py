"""Game constants and formulas (ported from MCDSaveEdit's GameCalculator/Constants)."""
import math

CURRENCIES = {"Emerald": "Изумруды", "Gold": "Золото", "EyeOfEnder": "Око Эндера"}

RARITIES = ["Common", "Rare", "Unique"]
EQUIPMENT_SLOTS = ["MeleeGear", "ArmorGear", "RangedGear", "HotbarSlot1", "HotbarSlot2", "HotbarSlot3"]
GEAR_SLOTS = EQUIPMENT_SLOTS[:3]
DIFFICULTIES = ["Difficulty_1", "Difficulty_2", "Difficulty_3"]
DIFFICULTY_NAMES = {"Difficulty_1": "По умолчанию", "Difficulty_2": "Приключение", "Difficulty_3": "Апокалипсис"}
THREAT_LEVELS = [f"Threat_{i}" for i in range(1, 8)]

UNSET_ENCHANTMENT = "Unset"
ENCHANTMENTS_PER_ITEM = 9  # three slots of three options
DEFAULT_ARMOR_PROPERTY = "AllyDamageBoost"

DEFAULT_ITEM_FOR_SLOT = {
    "MeleeGear": "Sword",
    "ArmorGear": "ArchersStrappings",
    "RangedGear": "Bow",
    "HotbarSlot1": "FireworksArrowItem",
    "HotbarSlot2": "FireworksArrowItem",
    "HotbarSlot3": "FireworksArrowItem",
}

POWERFUL_ENCHANTMENTS = {
    "Backstabber", "FinalShout", "Chilling", "Protection", "PotionThirstMelee", "PotionThirstRanged",
    "GravityPulse", "CriticalHit", "Exploding", "RadianceMelee", "GravityMelee", "Shockwave", "Swirling",
    "Gravity", "TempoTheft", "ChainReaction", "RadianceRanged", "ShockWeb", "VoidTouchedMelee",
    "VoidTouchedRanged", "MultiCharge", "DeathBarter", "FireFocus", "LightningFocus", "MultiDodge",
    "PoisonFocus", "SoulFocus",
}
ARMOR_ENCHANTMENTS = {
    "Swiftfooted", "PotionFortification", "Snowing", "SurpriseGift", "Burning", "Cowardice", "Deflecting",
    "Electrified", "Thorns", "Explorer", "Frenzied", "Celerity", "Recycler", "FoodReserves", "FireTrail",
    "HealthSynergy", "SpeedSynergy", "SpiritSpeed", "FinalShout", "Chilling", "Protection", "GravityPulse",
}
MELEE_ENCHANTMENTS = {
    "Weakening", "FireAspect", "Looting", "Chains", "Echo", "Stunning", "Rampaging", "Freezing", "Committed",
    "PoisonedMelee", "Prospector", "EnigmaResonatorMelee", "SoulSiphon", "Thundering", "Sharpness", "Leeching",
    "CriticalHit", "Exploding", "RadianceMelee", "GravityMelee", "Shockwave", "Swirling",
}
RANGED_ENCHANTMENTS = {
    "Accelerating", "Growing", "AnimaConduitRanged", "RapidFire", "Infinity", "Unchanting", "Piercing", "Power",
    "WildRage", "Punch", "Ricochet", "Supercharge", "FuseShot", "BonusShot", "FireAspect", "MultiShot",
    "Gravity", "TempoTheft", "ChainReaction", "RadianceRanged",
}
KNOWN_ENCHANTMENTS = POWERFUL_ENCHANTMENTS | ARMOR_ENCHANTMENTS | MELEE_ENCHANTMENTS | RANGED_ENCHANTMENTS


def enchantments_for_slot(slot):
    if slot == "MeleeGear":
        return MELEE_ENCHANTMENTS
    if slot == "ArmorGear":
        return ARMOR_ENCHANTMENTS
    if slot == "RangedGear":
        return RANGED_ENCHANTMENTS
    return KNOWN_ENCHANTMENTS


def enchantment_cost(enchantment_id, level, gilded=False):
    """Enchantment points spent on an enchantment at the given level."""
    level = int(level or 0)
    if level <= 0:
        return 0
    if enchantment_id in POWERFUL_ENCHANTMENTS:
        cost = level * (level + 3) // 2
    else:
        cost = level * (level + 1) // 2
    return cost + level if gilded else cost


def level_from_power(power):
    if not power or power <= 0:
        return 0
    return int(math.floor((max(1.0, power) - 1 + 0.00001) * 10)) + 1


def power_from_level(level):
    if level <= 0:
        return 0.0
    return (max(1, level) - 1) / 10.0 + 1 + 0.00001


def level_for_xp(xp):
    return int(math.floor((math.sqrt(3 * max(0, xp) + 100.0) + 20) / 30.0))


def xp_for_level(level):
    level = max(1, int(level))
    return 100 * (level - 1) * (3 * level - 1)


def character_power(melee, armor, ranged, slot1, slot2, slot3):
    """Displayed character power from equipped item powers."""
    weighted = (melee + armor + ranged) / 4 + (slot1 + slot2 + slot3) / 12
    return level_from_power(weighted)
