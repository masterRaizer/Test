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
    else:
        from . import overlay
        overlay.run(getattr(args, "save", None), True if getattr(args, "launch", False) else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
