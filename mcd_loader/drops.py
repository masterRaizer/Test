"""Where Minecraft Dungeons items can be found.

DROPS maps a save-file item ID to a short Russian description of where it drops
(missions, chests, merchants). It is filled from the community wikis; items that
are not listed show "no data" in the pickers.
"""

DROPS = {}

ENCHANTMENT_SOURCE = ("Зачарования не выпадают отдельно: они появляются в ячейках выпавших предметов, "
                      "и в игре их открывают очками зачарований. Здесь можно поставить любое.")


def where(item_id):
    return DROPS.get(item_id, "")
