"""Game integration: config, locating and launching Minecraft Dungeons, hotkeys."""
import json
import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
GAME_PROCESSES = ("Dungeons.exe", "Dungeons-Win64-Shipping.exe")
STEAM_URI = "steam://rungameid/1672970"

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~/.config"), "MCDLoader")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
BACKUP_DIR = os.path.join(APP_DIR, "backups")
CACHE_DIR = os.path.join(APP_DIR, "cache")

DEFAULT_CONFIG = {
    "hotkey": "F8",
    "game_path": "",
    "launch_game": False,
    "backup_on_apply": True,
    "overlay_alpha": 0.95,
    "extra_save_dirs": [],
    "last_save": "",
    "paks_dir": "",
    "pak_key": "",
    "language": "ru-RU",
    "wasd_enabled": False,
    "wasd_arrows": True,
}

# Virtual-key codes for the hotkeys offered in settings.
VK_CODES = {f"F{i}": 0x6F + i for i in range(1, 13)}
VK_CODES.update({"Insert": 0x2D, "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22})


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def candidate_game_paths():
    paths = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(os.path.join(local, "Mojang", "products", "dungeons", "dungeons", "Dungeons.exe"))
    for pf in filter(None, (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"))):
        paths.append(os.path.join(pf, "Steam", "steamapps", "common", "MinecraftDungeons", "Dungeons.exe"))
    paths.append(os.path.join("C:\\", "XboxGames", "Minecraft Dungeons", "Content", "Dungeons.exe"))
    return paths


def find_game(cfg):
    if cfg.get("game_path") and os.path.isfile(cfg["game_path"]):
        return cfg["game_path"]
    return next((p for p in candidate_game_paths() if os.path.isfile(p)), None)


def launch_game(cfg):
    """Start the game. Returns a human readable description of what was started."""
    exe = find_game(cfg)
    if exe:
        subprocess.Popen([exe], cwd=os.path.dirname(exe))
        return exe
    if IS_WINDOWS:
        os.startfile(STEAM_URI)  # noqa: S606 - opens through Steam if installed
        return STEAM_URI
    raise FileNotFoundError("Не найден Dungeons.exe — укажите путь в настройках")


def is_game_running():
    if not IS_WINDOWS:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=5,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return any(f'"{name.lower()}"' in out for name in GAME_PROCESSES)


class HotkeyPoller:
    """Edge-triggered global key check (works while the game has focus)."""

    def __init__(self, key_name):
        self.vk = VK_CODES.get(key_name, VK_CODES["F8"])
        self._down = False
        self._user32 = None
        if IS_WINDOWS:
            import ctypes
            self._user32 = ctypes.windll.user32

    @property
    def available(self):
        return self._user32 is not None

    def pressed(self):
        if not self._user32:
            return False
        down = bool(self._user32.GetAsyncKeyState(self.vk) & 0x8000)
        fired = down and not self._down
        self._down = down
        return fired
