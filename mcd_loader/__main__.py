"""Entry point: `python -m mcd_loader` starts the overlay; subcommands give CLI access."""
import argparse
import sys

from . import crypto, game
from .savefile import find_saves, read_profile


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mcd_loader", description="Загрузчик/редактор Minecraft Dungeons")
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="запустить оверлей (по умолчанию)")
    run.add_argument("save", nargs="?", help="путь к .dat персонажа")
    run.add_argument("--launch", action="store_true", help="сразу запустить игру")
    dec = sub.add_parser("decrypt", help=".dat → .json")
    dec.add_argument("src")
    dec.add_argument("dst")
    enc = sub.add_parser("encrypt", help=".json → .dat")
    enc.add_argument("src")
    enc.add_argument("dst")
    sub.add_parser("list", help="показать найденные сохранения")
    items = sub.add_parser("items", help="прочитать файлы игры: все предметы/зачарования и проверка иконок")
    items.add_argument("paks", nargs="?", help="папка Dungeons\\Content\\Paks (по умолчанию — найти)")
    items.add_argument("--icons", action="store_true", help="извлечь все иконки в кэш")
    args = parser.parse_args(argv)

    if args.cmd == "decrypt":
        with open(args.src, "rb") as f:
            plain = crypto.decrypt(f.read())
        with open(args.dst, "wb") as f:
            f.write(plain)
    elif args.cmd == "encrypt":
        with open(args.src, "rb") as f:
            plain = f.read().strip()
        with open(args.dst, "wb") as f:
            f.write(crypto.encrypt(plain))
    elif args.cmd == "list":
        for path in find_saves(game.load_config().get("extra_save_dirs", [])):
            profile = read_profile(path)
            print(f"{profile.get('name') or '-':20} xp={profile.get('xp', 0):<10} {path}")
    elif args.cmd == "items":
        return _items(args)
    else:
        from . import overlay
        overlay.run(getattr(args, "save", None), True if getattr(args, "launch", False) else None)
    return 0


def _items(args):
    import os
    from . import catalog
    cfg = game.load_config()
    paks = args.paks or catalog.find_paks_dir(cfg.get("paks_dir", ""), cfg.get("game_path", ""))
    if not paks:
        print("Папка Paks не найдена — передайте путь: python -m mcd_loader items <папка Paks>")
        return 1
    cat = catalog.GameCatalog.load(paks, os.path.join(game.CACHE_DIR, "catalog"), [cfg.get("pak_key", "")],
                                   cfg.get("language", "ru-RU"))
    print(f"Версия ключа: {cat.version}, язык: {cat.language}")
    for key, title in catalog.CATEGORIES.items():
        ids = sorted(i for i, info in cat.items.items() if info["category"] == key)
        print(f"\n== {title}: {len(ids)}")
        for ident in ids:
            print(f"  {ident:40} {cat.item_name(ident)}")
    print(f"\n== Зачарования: {len(cat.enchantments)}")
    for ident in sorted(cat.enchantments):
        print(f"  {ident:40} {cat.enchantment_name(ident)}")
    print(f"\n== Свойства брони: {len(cat.armor_properties)}")
    print("  " + ", ".join(sorted(cat.armor_properties)))
    if args.icons:
        ok = failed = 0
        for kind, ids in (("item", cat.items), ("enchantment", cat.enchantments)):
            for ident in ids:
                if cat.icon_file(kind, ident):
                    ok += 1
                else:
                    failed += 1
        print(f"\nИконки: {ok} извлечено, {failed} не удалось (кэш: {cat.cache_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
