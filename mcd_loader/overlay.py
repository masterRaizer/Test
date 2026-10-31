"""In-game overlay: a topmost editor window toggled by a hotkey over the running game."""
import json
import logging
import os
import queue
import shutil
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import catalog as cat_mod, chrome, game, gamedata as gd, shell, theme
from .pickers import RARITY_COLORS, EnchantmentPicker, IconCache, ItemPicker, ItemTypePicker
from . import wasd as wasd_mod
from .wasd import WasdMovement, WasdUnavailable
from .savefile import (SaveFile, clear_enchantments, find_saves, item_level, max_out_enchantments,
                       read_profile, set_enchantment, set_item_level)

BG, PANEL, FG, MUTED, ACCENT, WARN = theme.PAGE, theme.INPUT, theme.FG, theme.MUTED, theme.ACCENT, theme.WARN
NO_SLOT = "(не надет)"
LOCATIONS = {"inventory": "Инвентарь", "chest": "Сундук"}
SLOT_NAMES = {"MeleeGear": "Ближнее", "RangedGear": "Дальнее", "ArmorGear": "Броня",
              "HotbarSlot1": "Артефакт 1", "HotbarSlot2": "Артефакт 2", "HotbarSlot3": "Артефакт 3"}
FILTERS = ["Все", "Надетые", "Инвентарь", "Сундук"]


def _int(var, default=0):
    try:
        return int(float(str(var.get()).replace(" ", "")))
    except (ValueError, tk.TclError):
        return default


class LoaderApp:
    PAGES = [("◉", "Персонаж"), ("▦", "Инвентарь"), ("{ }", "JSON"), ("☰", "Настройки"), ("✦", "Моды"),
             ("⌂", "Главная"), ("⚙", "Система")]
    HOME, SYSTEM = 5, 6
    NAV_MAIN = [5, 0, 1, 4, 6]
    NAV_QUICK = [2, 3]

    def __init__(self, root, cfg, initial_save=None, loading=None, border=None, host=None, on_back=None):
        step = loading.set_status if loading else (lambda *a: None)
        self.root = root
        self.cfg = cfg
        self.border = border
        self.on_back = on_back
        self.frame = tk.Frame(host or root, bg=theme.WINDOW)
        self.frame.pack(fill="both", expand=True)
        self.loading = loading
        self.save = None
        self.saves = []
        self.save_infos = []
        self.items_by_iid = {}
        self.current_item = None
        self.armor_props = []
        self.hotkey = game.HotkeyPoller(cfg.get("hotkey", "F8"))
        self._suspend_traces = False
        self.catalog = None
        self.paks_dir = None
        self.catalog_error = None
        self.icons = IconCache(root)
        self.wasd = WasdMovement(arrows=cfg.get("wasd_arrows", True), shift_walk=cfg.get("wasd_shift", True))
        self._icon_thread_stop = threading.Event()
        self._ui_queue = queue.Queue()  # callables from worker threads, run on the Tk thread
        self._catalog_gen = 0           # ignores results of an older catalog load
        self._jobs = {}                 # periodic after() callbacks, cancelled on shutdown
        self._last_running = False
        self._last_tab = None

        root.title("SecretGear — Minecraft Dungeons")
        root.attributes("-topmost", True)
        self.alpha = float(cfg.get("overlay_alpha", 0.95))
        self.animator = chrome.Animator(root)
        chrome.set_window_icon(root)
        theme.apply_theme(root)
        step("Подготовка интерфейса")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda e: self.apply_to_game() if self.frame.winfo_ismapped() else None)

        self._build_sidebar(self.frame)
        right = tk.Frame(self.frame, bg=theme.WINDOW)
        right.pack(side="left", fill="both", expand=True)
        self._build_header(right)
        panel = theme.RoundedBox(right, bg=theme.PAGE, outline=theme.BORDER, radius=14, pad=6, fill_height=True,
                                 frame_style="Page.TFrame", parent_bg=theme.WINDOW)
        panel.pack(fill="both", expand=True, padx=(0, 8), pady=(0, 8))
        content = ttk.Frame(panel.inner, style="Page.TFrame", padding=(16, 4, 16, 6))
        content.pack(fill="both", expand=True)
        self.top_progress = shell.TopProgress(content)
        self.top_progress.pack(fill="x", pady=(0, 6))
        self.status_var = tk.StringVar(value="Выберите персонажа")
        self.status = ttk.Label(content, textvariable=self.status_var, style="Muted.TLabel")
        self.status.pack(fill="x", pady=(0, 8))
        self.banner = tk.Frame(content, bg="#211b0e", highlightbackground="#5a4312", highlightthickness=1)
        self.banner_text = tk.StringVar()
        tk.Label(self.banner, textvariable=self.banner_text, bg="#211b0e", fg=theme.WARN, font=theme.FONT,
                 justify="left", anchor="w", wraplength=700).pack(side="left", fill="x", expand=True, padx=12, pady=8)
        shell.CanvasButton(self.banner, "Указать папку игры…", self.choose_game_folder,
                           bg="#211b0e").pack(side="right", padx=10, pady=6)
        self.notebook = ttk.Notebook(content, style="Hidden.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.page_cover = tk.Frame(content, bg=theme.PAGE)
        grip = self.border.resize_grip(panel.inner) if self.border else None
        if grip:
            grip.place(relx=1.0, rely=1.0, anchor="se")
        self._build_character_tab()
        step("Инвентарь и зачарования")
        self._build_inventory_tab()
        self._build_json_tab()
        self._build_settings_tab()
        self._build_mods_tab()
        self._build_home_tab()
        self._build_system_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        step("Поиск сохранений")
        self.refresh_save_list(select=initial_save or cfg.get("last_save"))
        step("Файлы игры")
        self.notebook.select(self.HOME)
        self._every("hotkey", 50, self._poll_hotkey)
        self._every("disk", 2000, self._watch_disk)
        self._every("queue", 100, self._drain_ui_queue)
        self.load_catalog()
        if cfg.get("wasd_enabled"):
            self.root.after(500, lambda: self.set_wasd(True))
        self.root.after(80, self._highlight_nav)
        self.root.after(300, self.run_checks)

    # ------------------------------------------------------------------ UI
    def _build_header(self, parent):
        bar = tk.Frame(parent, bg=theme.WINDOW)
        bar.pack(fill="x")
        self.page_title = tk.Label(bar, text="", bg=theme.WINDOW, fg=theme.FG, font=("Segoe UI Semibold", 16))
        self.page_title.pack(side="left", padx=(14, 18), pady=(14, 12))
        if self.border:
            shell.WindowButtons(bar, self.border.minimize, self.border.toggle_maximize, self.on_close).pack(
                side="right", anchor="n", padx=(8, 6), pady=(6, 0))
            self.border.drag_handle(bar)
            self.border.drag_handle(self.page_title)
        shell.CanvasButton(bar, "Применить в игре", self.apply_to_game, icon="✔", bg=theme.WINDOW).pack(
            side="right", pady=(12, 10))
        self.save_var = tk.StringVar()
        ttk.Button(bar, text="…", style="Icon.TButton", width=3, command=self.browse_save).pack(side="right", padx=(2, 10))
        ttk.Button(bar, text="⟳", style="Icon.TButton", width=3, command=self.reload_save).pack(side="right")
        self.save_box = ttk.Combobox(bar, textvariable=self.save_var, state="readonly", width=36)
        self.save_box.pack(side="right", padx=(0, 4))
        self.save_box.bind("<<ComboboxSelected>>", lambda e: self.open_selected_save())

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=theme.WINDOW, width=212)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=theme.WINDOW)
        brand.pack(fill="x", padx=16, pady=(14, 14))
        self._brand_logo = None
        try:
            from PIL import Image, ImageTk
            with Image.open(chrome.asset_path("mark.png")) as im:
                self._brand_logo = ImageTk.PhotoImage(im.convert("RGBA").resize((30, 30), Image.LANCZOS), master=side)
        except Exception:
            pass
        logo = tk.Label(brand, image=self._brand_logo, bg=theme.WINDOW)
        logo.pack(side="left")
        names = tk.Frame(brand, bg=theme.WINDOW)
        names.pack(side="left", padx=(10, 0))
        tk.Label(names, text="Minecraft Dungeons", bg=theme.WINDOW, fg=theme.FG, font=("Segoe UI", 10, "bold")).pack(
            anchor="w")
        tk.Label(names, text="Модуль SecretGear", bg=theme.WINDOW, fg=theme.DIM, font=("Segoe UI", 9)).pack(anchor="w")
        if self.border:
            for w in (brand, logo, names):
                self.border.drag_handle(w)
        self.nav_items = {}
        nav = tk.Frame(side, bg=theme.WINDOW)
        nav.pack(fill="x", padx=12)
        if self.on_back:
            shell.NavItem(nav, "←", "Библиотека", self.go_back).pack(fill="x", pady=(0, 6))
        for index in self.NAV_MAIN:
            icon, title = self.PAGES[index]
            item = shell.NavItem(nav, icon, title, lambda i=index: self.show_page(i))
            item.pack(fill="x", pady=1)
            self.nav_items[index] = item
        tk.Frame(side, bg=theme.BORDER, height=1).pack(fill="x", padx=16, pady=12)
        tk.Label(side, text="Быстрый запуск", bg=theme.WINDOW, fg=theme.DIM, font=("Segoe UI", 9)).pack(
            anchor="w", padx=24, pady=(0, 4))
        quick = tk.Frame(side, bg=theme.WINDOW)
        quick.pack(fill="x", padx=12)
        shell.NavItem(quick, "▶", "Запустить игру", self.launch_with_animation, chevron=True, bold=True).pack(
            fill="x", pady=1)
        for index in self.NAV_QUICK:
            icon, title = self.PAGES[index]
            item = shell.NavItem(quick, icon, title, lambda i=index: self.show_page(i))
            item.pack(fill="x", pady=1)
            self.nav_items[index] = item
        from . import __version__
        hint = f"{self.cfg.get('hotkey', 'F8')} — показать / скрыть" if self.hotkey.available else ""
        tk.Label(side, text=f"v{__version__}   {hint}", bg=theme.WINDOW, fg=theme.DIM, font=("Segoe UI", 8)).pack(
            side="bottom", anchor="w", padx=24, pady=12)

    def go_back(self):
        self.commit_forms()
        if self.on_back:
            self.on_back()

    def show_page(self, index):
        if self.notebook.index("current") == index:
            return
        self.page_cover.place(in_=self.notebook, relx=0, rely=0, relwidth=1, relheight=1)
        self.page_cover.lift()
        self.notebook.select(index)
        self.top_progress.sweep(280, done=self.page_cover.place_forget)

    def _highlight_nav(self):
        current = self.notebook.index("current")
        for index, item in self.nav_items.items():
            item.set_active(index == current)
        self.page_title.configure(text=self.PAGES[current][1])

    def _labeled(self, parent, row, text, widget):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=row, column=1, sticky="we", pady=4)
        return widget

    def _page(self, title):
        tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=(0, 6, 0, 0))
        self.notebook.add(tab, text=title)
        return tab
    # ------------------------------------------------------------ home page
    def _build_home_tab(self):
        tab = self._page("Главная")
        right = ttk.Frame(tab, style="Page.TFrame", width=270)
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)
        left = ttk.Frame(tab, style="Page.TFrame")
        left.pack(side="left", fill="both", expand=True)

        self._slide_logo = chrome.load_logo(self.root, 50)
        self.carousel = shell.Carousel(left, self._home_slides(), width=560, height=300)
        self.carousel.pack(fill="x")
        self.carousel.show(0, animate=False)

        head = ttk.Frame(left, style="Page.TFrame")
        head.pack(fill="x", pady=(14, 8))
        tk.Label(head, text="Мои персонажи", bg=theme.PAGE, fg=theme.FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.chars_count = shell.pill(head, "0", theme.MUTED, "#1d1e25")
        self.chars_count.pack(side="left", padx=8)
        link = tk.Label(head, text="Открыть .dat  ›", bg=theme.PAGE, fg=theme.ACCENT_HOVER, cursor="hand2",
                        font=("Segoe UI", 9, "bold"))
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: self.browse_save())
        self.chars_grid = ttk.Frame(left, style="Page.TFrame")
        self.chars_grid.pack(fill="both", expand=True)

        news = theme.RoundedBox(right, bg=theme.PAGE, outline=theme.BORDER, radius=12, pad=6, fill_height=True,
                                frame_style="Page.TFrame")
        news.pack(fill="both", expand=True)
        top = ttk.Frame(news.inner, style="Page.TFrame", padding=(10, 8, 10, 6))
        top.pack(fill="x")
        tk.Label(top, text="Новости", bg=theme.PAGE, fg=theme.FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        entries = [
            ("ⓘ", theme.ACCENT_HOVER, "31 окт 2026", "Новый лаунчер",
             "Окно без рамки, экран загрузки, главная страница и проверка системы."),
            ("✓", theme.GREEN, "31 окт 2026", "Все предметы с иконками",
             "Каталог берётся из файлов игры: предметы, зачарования и русские названия."),
            ("✓", theme.GREEN, "31 окт 2026", "Мод: ходьба на WASD",
             "W/A/S/D двигают персонажа через виртуальный геймпад — и в мире друга тоже."),
        ]
        shell.pill(top, str(len(entries)), theme.MUTED, "#1d1e25").pack(side="left", padx=8)
        box = theme.RoundedBox(news.inner, bg=theme.CARD, outline=theme.BORDER, radius=10, pad=4)
        box.pack(fill="x", padx=8, pady=(4, 8))
        for k, (icon, color, date, title, text) in enumerate(entries):
            if k:
                tk.Frame(box.inner, bg=theme.BORDER, height=1).pack(fill="x", padx=6)
            e = ttk.Frame(box.inner, style="Card.TFrame", padding=(10, 8))
            e.pack(fill="x")
            row = ttk.Frame(e, style="Card.TFrame")
            row.pack(fill="x")
            tk.Label(row, text=icon, bg=theme.CARD, fg=color, font=("Segoe UI", 10)).pack(side="left")
            tk.Label(row, text=date, bg=theme.CARD, fg=theme.DIM, font=("Segoe UI", 8)).pack(side="right")
            tk.Label(e, text=title, bg=theme.CARD, fg=theme.FG, font=("Segoe UI", 10, "bold"), justify="left",
                     wraplength=200).pack(anchor="w", pady=(2, 0))
            tk.Label(e, text=text, bg=theme.CARD, fg=theme.MUTED, font=("Segoe UI", 9), justify="left",
                     wraplength=200).pack(anchor="w")

    def _home_slides(self):
        icon_paths = self._showcase_icons()
        from . import art
        hero = art.cached_game_art("mcd", os.path.join(game.CACHE_DIR, "art")).get("hero")
        first = shell.banner_art(icon_paths, (24, 52, 120))
        if hero:
            first = shell.image_art(hero, first)
        return [
            {"art": first, "logo": None if hero else self._slide_logo, "title": "Minecraft Dungeons",
             "badge": "MOD", "text": "Редактор сохранений, все предметы игры и ходьба на WASD — прямо поверх игры.",
             "tag": f"{self.cfg.get('hotkey', 'F8')} — открыть поверх игры",
             "button": ("▶  Играть", self.launch_with_animation), "note": "Запуск через лаунчер"},
            {"art": shell.banner_art(icon_paths[3:], (70, 40, 120)), "title": "Все предметы игры", "badge": "NEW",
             "text": "Каталог оружия, брони, артефактов и зачарований с иконками. Добавляйте в инвентарь в один клик.",
             "tag": "Каталог из файлов игры", "button": ("＋  Добавить предмет", self._home_add_item)},
            {"art": shell.banner_art(icon_paths[6:], (20, 90, 90)), "title": "Редактор персонажа",
             "text": "Уровень, изумруды, золото, сложность и угрозы. Изменения — кнопкой «Применить в игре».",
             "tag": "Бэкап перед каждым применением", "button": ("Открыть", lambda: self.show_page(0))},
            {"art": shell.banner_art(icon_paths[1:], (40, 70, 140)), "title": "Ходьба на WASD",
             "text": "W/A/S/D и стрелки двигают персонажа, Shift — шагом. Работает и в мире друга.",
             "tag": "Виртуальный геймпад", "button": ("Настроить", lambda: self.show_page(4))},
        ]

    def _home_add_item(self):
        self.show_page(1)
        self.root.after(320, self.add_item)

    def _showcase_icons(self):
        if not self.catalog or not self.catalog.loaded:
            return []
        ids = sorted((i for i in self.catalog.items if "_Unique" in i), key=lambda i: hash(i) % 997)
        paths = []
        for ident in ids + list(self.catalog.items):
            p = self.catalog.icon_file("item", ident, extract=False)
            if p and p not in paths:
                paths.append(p)
            if len(paths) >= 12:
                break
        return paths

    def _refresh_home_art(self):
        self.carousel.slides = self._home_slides()
        self.carousel._images.clear()
        self.carousel.show(self.carousel.index, animate=False)

    def _refresh_home_chars(self):
        if not hasattr(self, "chars_grid"):
            return
        for w in self.chars_grid.winfo_children():
            w.destroy()
        self.chars_count.configure(text=f" {len(self.save_infos)} ")
        if not self.save_infos:
            tk.Label(self.chars_grid, text="Сохранения не найдены — нажмите «Открыть .dat».", bg=theme.PAGE,
                     fg=theme.MUTED).pack(anchor="w")
            return
        for k, info in enumerate(self.save_infos[:6]):
            box = theme.RoundedBox(self.chars_grid, bg=theme.CARD, outline=theme.BORDER, radius=10, pad=4)
            box.grid(row=k // 3, column=k % 3, sticky="we", padx=(0, 10), pady=(0, 10))
            self.chars_grid.columnconfigure(k % 3, weight=1, uniform="chars")
            inner = ttk.Frame(box.inner, style="Card.TFrame", padding=(10, 8))
            inner.pack(fill="x")
            widgets = [box, inner,
                       tk.Label(inner, text=info["name"], bg=theme.CARD, fg=theme.FG, font=("Segoe UI", 10, "bold")),
                       tk.Label(inner, text=f"Уровень {info['level']}", bg=theme.CARD, fg=theme.ACCENT_HOVER,
                                font=("Segoe UI", 9)),
                       tk.Label(inner, text=info["when"], bg=theme.CARD, fg=theme.DIM, font=("Segoe UI", 8))]
            for w in widgets[2:]:
                w.pack(anchor="w")
            for w in widgets:
                w.configure(cursor="hand2")
                w.bind("<Button-1>", lambda e, p=info["path"]: self._open_character(p))

    def _open_character(self, path):
        if path in self.saves:
            self.save_box.current(self.saves.index(path))
            self.open_selected_save()
        if self.save and self.save.path == path:
            self.show_page(0)

    # ---------------------------------------------------------- system page
    def _build_system_tab(self):
        tab = self._page("Система")
        summary = theme.RoundedBox(tab, bg=theme.CARD, outline=theme.BORDER, radius=12, pad=6)
        summary.pack(fill="x")
        inner = ttk.Frame(summary.inner, style="Card.TFrame", padding=(10, 8))
        inner.pack(fill="x")
        self.sys_icon = tk.Label(inner, text="✓", width=3, height=1, font=("Segoe UI", 14, "bold"),
                                 bg="#12301f", fg=theme.GREEN, pady=6)
        self.sys_icon.pack(side="left")
        texts = ttk.Frame(inner, style="Card.TFrame")
        texts.pack(side="left", padx=14)
        self.sys_title = tk.Label(texts, text="", bg=theme.CARD, fg=theme.FG, font=("Segoe UI", 12, "bold"))
        self.sys_title.pack(anchor="w")
        self.sys_sub = tk.Label(texts, text="", bg=theme.CARD, fg=theme.MUTED, font=("Segoe UI", 9))
        self.sys_sub.pack(anchor="w")
        self.sys_fix = shell.CanvasButton(inner, "Исправить всё", self.fix_all, icon="🔧", bg=theme.CARD)
        self.sys_fix.pack(side="right")
        shell.CanvasButton(inner, "Обновить", self.run_checks, primary=False, icon="⟳", bg=theme.CARD).pack(
            side="right", padx=8)

        head = ttk.Frame(tab, style="Page.TFrame")
        head.pack(fill="x", pady=(16, 8))
        tk.Label(head, text="Проверки", bg=theme.PAGE, fg=theme.FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.sys_bad = tk.Label(head, text="", bg=theme.PAGE, fg=theme.RED, font=("Segoe UI", 9, "bold"))
        self.sys_bad.pack(side="right")
        self.sys_good = tk.Label(head, text="", bg=theme.PAGE, fg=theme.GREEN, font=("Segoe UI", 9, "bold"))
        self.sys_good.pack(side="right")
        self.sys_box = theme.RoundedBox(tab, bg=theme.CARD, outline=theme.BORDER, radius=12, pad=4)
        self.sys_box.pack(fill="x")

    def system_checks(self):
        """(title, ok, description, hint, fix) — ok None means informational."""
        checks = []
        paks = self.paks_dir
        checks.append(("Игра установлена", bool(paks), paks or "Папка с файлами игры не найдена",
                       "" if paks else "Укажите папку игры", self.choose_game_folder))
        cat = self.catalog if self.catalog and self.catalog.loaded else None
        checks.append(("Файлы игры прочитаны", bool(cat),
                       f"Ключ {cat.version}, предметов: {len(cat.items)}" if cat else (self.catalog_error or "Не загружены"),
                       "" if cat else "Перечитать файлы игры", lambda: self.load_catalog(force=True)))
        ok_icons, failed_icons, _ = cat.icon_stats() if cat else (0, 0, "")
        checks.append(("Иконки предметов", bool(ok_icons), f"Извлечено: {ok_icons}" +
                       (f", не удалось: {failed_icons}" if failed_icons else ""),
                       "" if ok_icons else "Повторить извлечение", lambda: self.load_catalog(force=True)))
        checks.append(("Сохранения персонажей", bool(self.saves), f"Найдено: {len(self.saves)}",
                       "" if self.saves else "Открыть .dat вручную", self.browse_save))
        if game.IS_WINDOWS:
            drv = wasd_mod.driver_installed()
            checks.append(("Драйвер геймпада (WASD)", drv, "ViGEmBus установлен" if drv else "Нужен для ходьбы на WASD",
                           "" if drv else "Установить драйвер", self._install_driver))
        checks.append(("Горячая клавиша", self.hotkey.available,
                       f"{self.cfg.get('hotkey', 'F8')} показывает окно поверх игры" if self.hotkey.available
                       else "Работает только в Windows", "", None))
        checks.append(("Резервные копии", bool(self.cfg.get("backup_on_apply", True)),
                       "Бэкап перед каждым применением", "" if self.cfg.get("backup_on_apply", True) else "Включить",
                       self._enable_backups))
        if self.notebook.index("current") == self.SYSTEM:
            self._last_running = game.is_game_running()
        running = self._last_running
        checks.append(("Игра запущена", None, "Minecraft Dungeons запущена" if running else "Игра сейчас не запущена",
                       "", None))
        return checks

    def run_checks(self):
        checks = self.system_checks()
        self._checks = checks
        for w in self.sys_box.inner.winfo_children():
            w.destroy()
        grid = ttk.Frame(self.sys_box.inner, style="Card.TFrame")
        grid.pack(fill="x")
        for k, (title, ok, desc, hint, _fix) in enumerate(checks):
            cell = ttk.Frame(grid, style="Card.TFrame", padding=(12, 9))
            cell.grid(row=k // 2, column=k % 2, sticky="nsew")
            grid.columnconfigure(k % 2, weight=1, uniform="checks")
            mark, color = ("✓", theme.GREEN) if ok or ok is None else ("✕", theme.RED)
            tk.Label(cell, text=mark, bg=theme.CARD, fg=color if ok is not None else theme.DIM,
                     font=("Segoe UI", 11, "bold")).pack(side="left", anchor="n", padx=(0, 10))
            texts = ttk.Frame(cell, style="Card.TFrame")
            texts.pack(side="left", fill="x", expand=True)
            tk.Label(texts, text=title, bg=theme.CARD, fg=theme.FG, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(texts, text=desc, bg=theme.CARD, fg=theme.MUTED, font=("Segoe UI", 9), wraplength=300,
                     justify="left").pack(anchor="w")
            if hint and not ok:
                tk.Label(texts, text=hint, bg=theme.CARD, fg=theme.DIM, font=("Segoe UI", 8)).pack(anchor="w")
            if ok is None:
                badge = shell.pill(cell, "—", theme.DIM, "#1d1e25")
            elif ok:
                badge = shell.pill(cell, "OK", theme.MUTED, "#1d1e25")
            else:
                badge = shell.pill(cell, "Проблема", theme.RED, "#2a1416")
            badge.pack(side="right", anchor="n")
        issues = [c for c in checks if c[1] is False]
        passed = sum(1 for c in checks if c[1])
        self.sys_good.configure(text=f"{passed} пройдено")
        self.sys_bad.configure(text=f"  ·  {len(issues)} проблем(ы)" if issues else "")
        if issues:
            self.sys_icon.configure(text="✕", bg="#2a1416", fg=theme.RED)
            self.sys_title.configure(text="Найдены проблемы")
            self.sys_sub.configure(text=f"{len(issues)} проблем(ы) требуют внимания.")
        else:
            self.sys_icon.configure(text="✓", bg="#12301f", fg=theme.GREEN)
            self.sys_title.configure(text="Всё в порядке")
            self.sys_sub.configure(text="Загрузчик готов к работе.")
        self.sys_fix.enabled = bool([c for c in issues if c[4]])
        self.sys_fix.draw()
        if self.SYSTEM in self.nav_items:
            self.nav_items[self.SYSTEM].set_badge("⚠" if issues else None)

    def fix_all(self):
        for _title, ok, _desc, _hint, fix in getattr(self, "_checks", []):
            if ok is False and fix:
                fix()  # one at a time: fixes open dialogs or reload game files
                break
        self.root.after(600, self.run_checks)

    def _install_driver(self):
        installer = wasd_mod.driver_installer()
        if installer and messagebox.askyesno("Драйвер геймпада", "Установить драйвер ViGEmBus для ходьбы на WASD?\n"
                                             "Windows попросит права администратора.", parent=self.root):
            os.startfile(installer)  # noqa: S606 - bundled msi
        elif not installer:
            messagebox.showinfo("Драйвер геймпада", "Установщик ViGEmBus не найден в сборке. Скачайте его с "
                                "github.com/nefarius/ViGEmBus/releases.", parent=self.root)

    def _enable_backups(self):
        self.cfg["backup_on_apply"] = True
        self.set_backup.set(True)
        game.save_config(self.cfg)

    # ------------------------------------------------------------ launching
    def launch_with_animation(self):
        """Launcher-style start: loading screen with the logo until the game process appears."""
        view = shell.LoadingView(self.root, status="Запуск Minecraft Dungeons…")
        view.place(relx=0, rely=0, relwidth=1, relheight=1)
        view.raise_view()
        try:
            started = game.launch_game(self.cfg)
            logging.info("launch: %s", started)
        except Exception as e:
            view.stop()
            view.destroy()
            messagebox.showerror("Запуск игры", str(e), parent=self.root)
            return
        deadline = time.time() + 90
        view.set_status("Запуск Minecraft Dungeons…  Не закрывайте это окно")

        def wait():
            if game.is_game_running() or not game.IS_WINDOWS:
                view.set_status(f"Игра запущена. {self.cfg.get('hotkey', 'F8')} — открыть SecretGear поверх игры")
                self.root.after(1800, finish)
            elif time.time() > deadline:
                view.set_status("Игра не появилась за 90 секунд")
                self.root.after(2500, finish)
            else:
                self.root.after(1000, wait)

        def finish():
            view.stop()
            view.destroy()
            if self.hotkey.available and game.is_game_running():
                self.hide()
        self.root.after(1500, wait)


    def _build_character_tab(self):
        tab = self._page("Персонаж")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y", anchor="n", padx=(0, 14))
        right = ttk.Frame(tab)
        right.pack(side="left", fill="y", anchor="n")

        self.name_var = tk.StringVar()
        self.level_var = tk.StringVar()
        self.xp_var = tk.StringVar()
        self.currency_vars = {k: tk.StringVar() for k in gd.CURRENCIES}
        self.difficulty_var = tk.StringVar()
        self.threat_var = tk.StringVar()

        theme.section(left, "◉", "Персонаж")
        body = theme.card(left, "Характеристики", pack={"fill": "x", "pady": (0, 10), "ipadx": 0})
        ttk.Label(body, textvariable=self.name_var, style="Card.TLabel", font=("Segoe UI", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        theme.card_row(body, 1, "Уровень", ttk.Spinbox(body, from_=1, to=10000, textvariable=self.level_var, width=16))
        theme.card_row(body, 2, "Опыт (XP)", ttk.Entry(body, textvariable=self.xp_var, width=18))
        body = theme.card(left, "Валюта")
        for row, (key, title) in enumerate(gd.CURRENCIES.items()):
            theme.card_row(body, row, title, ttk.Entry(body, textvariable=self.currency_vars[key], width=18))
        self.portal_var = tk.StringVar()
        portal = ttk.Frame(body, style="Card.TFrame")
        portal.grid(row=len(gd.CURRENCIES), column=0, columnspan=2, sticky="we", pady=(6, 0))
        ttk.Label(portal, textvariable=self.portal_var, style="CardMuted.TLabel").pack(side="left")
        self.portal_button = shell.CanvasButton(portal, "Открыть портал", self._unlock_portal, primary=False,
                                                bg=theme.CARD, icon="◈")
        self.portal_button.pack(side="right")
        body = theme.card(left, "Прогресс")
        theme.card_row(body, 0, "Открытая сложность",
                       ttk.Combobox(body, textvariable=self.difficulty_var, state="readonly", width=24,
                                    values=[f"{d} — {gd.DIFFICULTY_NAMES[d]}" for d in gd.DIFFICULTIES]))
        theme.card_row(body, 1, "Уровень угрозы", ttk.Combobox(body, textvariable=self.threat_var,
                                                               values=gd.THREAT_LEVELS, state="readonly", width=24))
        self.level_var.trace_add("write", self._on_level_changed)
        self.xp_var.trace_add("write", self._on_xp_changed)

        theme.section(right, "★", "Сводка")
        info = theme.card(right, "Персонаж сейчас", pack={"fill": "x", "pady": (0, 10)})
        self.power_var = tk.StringVar()
        self.points_var = tk.StringVar()
        self.items_count_var = tk.StringVar()
        for var in (self.power_var, self.points_var, self.items_count_var):
            ttk.Label(info, textvariable=var, style="Card.TLabel").pack(anchor="w", pady=3)

        pts = theme.card(right, "Очки зачарований", pack={"fill": "x", "pady": (0, 10)})
        self.points_target = tk.StringVar(value="1000")
        self.points_info = tk.StringVar()
        ttk.Label(pts, textvariable=self.points_info, style="CardMuted.TLabel", wraplength=360,
                  justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
        theme.card_row(pts, 1, "Нужно свободных очков", ttk.Spinbox(pts, from_=0, to=1000000, width=10,
                                                                    textvariable=self.points_target))
        row = ttk.Frame(pts, style="Card.TFrame")
        row.grid(row=2, column=0, columnspan=2, sticky="we", pady=(6, 0))
        shell.CanvasButton(row, "Через уровень", self._points_via_level, bg=theme.CARD).pack(side="left")
        shell.CanvasButton(row, "Бонус без уровня", self._points_bonus, primary=False, bg=theme.CARD).pack(
            side="left", padx=6)
        shell.CanvasButton(row, "Убрать бонус", self._points_clear_bonus, primary=False, bg=theme.CARD).pack(
            side="left")
        quick = theme.card(right, "Быстрые действия")
        for k, (text, cmd) in enumerate((("Изумруды и золото 999 999", self._quick_rich),
                                         ("Открыть всё", self._quick_unlock),
                                         ("Уровень = 100", self._quick_level_100),
                                         ("Уровень предметов…", self.set_all_levels),
                                         ("Выбранные чары до 3", self.max_all_enchantments))):
            ttk.Button(quick, text=text, command=cmd).grid(row=k // 2, column=k % 2, sticky="we", padx=3, pady=3)
            quick.columnconfigure(k % 2, weight=1)

    def _build_inventory_tab(self):
        tab = self._page("Инвентарь")
        self._build_item_editor(tab)
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, padx=(0, 14))
        actions = ttk.Frame(left)
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        for i, (text, cmd, style) in enumerate((("＋  Добавить", self.add_item, "Accent.TButton"),
                                                ("⧉  Копия", self.duplicate_item, "TButton"),
                                                ("✕  Удалить", self.delete_item, "TButton"),
                                                ("⇄  Переложить", self.move_item, "TButton"))):
            ttk.Button(actions, text=text, command=cmd, style=style).grid(row=i // 2, column=i % 2, sticky="we",
                                                                          padx=3, pady=3)
            actions.columnconfigure(i % 2, weight=1)

        top = ttk.Frame(left)
        top.pack(fill="x", pady=(0, 8))
        theme.section(top, "▦", "Инвентарь и сундук", side="left")
        self.filter_var = tk.StringVar(value=FILTERS[0])
        flt = ttk.Combobox(top, textvariable=self.filter_var, values=FILTERS, state="readonly", width=12)
        flt.pack(side="right")
        flt.bind("<<ComboboxSelected>>", lambda e: self.refresh_items())

        frame = tk.Frame(left, bg=theme.BORDER, padx=1, pady=1)
        frame.pack(fill="both", expand=True)
        cols = ("slot", "lvl", "ench")
        self.tree = ttk.Treeview(frame, columns=cols, show="tree headings", selectmode="browse",
                                 displaycolumns=("slot", "lvl"))
        self.tree.heading("#0", text="Предмет")
        self.tree.column("#0", width=210)
        for col, title, width in zip(cols, ("Где", "Ур.", "Зачарования"), (100, 44, 170)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col == "ench")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_item_selected)

    def _build_item_editor(self, parent):
        ed = ttk.Frame(parent)
        ed.pack(side="right", fill="y")
        self.editor = theme.section(ed, "⚔", "Предмет")
        cols = ttk.Frame(ed)
        cols.pack(fill="both", expand=True)
        col_a = theme.card(cols, "Основное", pack={"side": "left", "fill": "y", "anchor": "n"})
        col_b_outer = ttk.Frame(cols)
        col_b_outer.pack(side="left", fill="y", anchor="n", padx=(10, 0))
        self.it_type = tk.StringVar()
        self.it_level = tk.StringVar()
        self.it_rarity = tk.StringVar()
        self.it_slot = tk.StringVar()
        self.it_upgraded = tk.BooleanVar()
        self.it_gifted = tk.BooleanVar()
        self.it_new = tk.BooleanVar()

        head = ttk.Frame(col_a, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 8))
        self.item_icon = ttk.Label(head, image=self.icons.placeholder(64), style="Card.TLabel")
        self.item_icon.pack(side="left")
        self.item_title = ttk.Label(head, text="—", style="Card.TLabel", font=("Segoe UI", 13, "bold"), wraplength=210)
        self.item_title.pack(side="left", padx=10)
        grid = ttk.Frame(col_a, style="Card.TFrame")
        grid.pack(fill="x")
        type_row = ttk.Frame(grid, style="Card.TFrame")
        self.type_box = ttk.Combobox(type_row, textvariable=self.it_type, width=14)
        self.type_box.pack(side="left")
        ttk.Button(type_row, text="…", width=2, command=self._pick_type).pack(side="left", padx=(3, 0))
        theme.card_row(grid, 0, "Тип (ID)", type_row, muted=True)
        self.it_type.trace_add("write", lambda *_: self._update_item_header())
        theme.card_row(grid, 1, "Уровень силы", ttk.Spinbox(grid, from_=0, to=10000, textvariable=self.it_level,
                                                             width=15), muted=True)
        theme.card_row(grid, 2, "Редкость", ttk.Combobox(grid, textvariable=self.it_rarity, values=gd.RARITIES,
                                                         state="readonly", width=15), muted=True)
        theme.card_row(grid, 3, "Слот", ttk.Combobox(grid, textvariable=self.it_slot, state="readonly", width=15,
                                                     values=[NO_SLOT] + gd.EQUIPMENT_SLOTS), muted=True)
        for row, (text, var) in enumerate((("Улучшен (алмаз)", self.it_upgraded), ("Подарок", self.it_gifted),
                                           ("Отмечен как новый", self.it_new)), start=4):
            theme.card_row(grid, row, text, theme.Toggle(grid, var), muted=True)

        gild = ttk.Frame(col_a, style="Card.TFrame")
        gild.pack(fill="x", pady=(10, 0))
        self.gild_on = tk.BooleanVar()
        self.gild_id = tk.StringVar()
        self.gild_lvl = tk.StringVar(value="1")
        ttk.Label(gild, text="Позолоченное (незерит)", style="CardMuted.TLabel").pack(side="left")
        theme.Toggle(gild, self.gild_on).pack(side="right")
        gild_row = ttk.Frame(col_a, style="Card.TFrame")
        gild_row.pack(fill="x", pady=(4, 0))
        self.gild_box = ttk.Button(gild_row, style="Ench.TButton", compound="left", width=18,
                                   command=lambda: self._pick_enchantment(None))
        self.gild_box.pack(side="left")
        self.gild_id.trace_add("write", lambda *_: self._update_ench_button(self.gild_box, self.gild_id))
        self._update_ench_button(self.gild_box, self.gild_id)
        ttk.Spinbox(gild_row, from_=0, to=3, textvariable=self.gild_lvl, width=3).pack(side="left", padx=4)

        ttk.Label(col_a, text="Свойства брони", style="CardMuted.TLabel").pack(anchor="w", pady=(10, 2))
        self.props_list = tk.Listbox(col_a, height=3, bg=theme.INPUT, fg=FG, highlightthickness=0, bd=0,
                                     selectbackground=theme.ACCENT, activestyle="none")
        self.props_list.pack(fill="x")
        row = ttk.Frame(col_a, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 0))
        self.prop_id = tk.StringVar(value=gd.DEFAULT_ARMOR_PROPERTY)
        self.prop_rarity = tk.StringVar(value="Common")
        self.prop_box = ttk.Combobox(row, textvariable=self.prop_id, width=13)
        self.prop_box.pack(side="left")
        ttk.Combobox(row, textvariable=self.prop_rarity, values=gd.RARITIES, state="readonly",
                     width=8).pack(side="left", padx=3)
        ttk.Button(row, text="+", width=2, command=self._add_prop).pack(side="left")
        ttk.Button(row, text="−", width=2, command=self._remove_prop).pack(side="left", padx=(3, 0))

        self.ench_vars = []
        self.ench_boxes = []
        for s in range(3):
            body = theme.card(col_b_outer, f"Зачарования · слот {s + 1}", pack={"fill": "x", "pady": (0, 8)})
            for k in range(3):
                index = s * 3 + k
                id_var, lvl_var = tk.StringVar(value=gd.UNSET_ENCHANTMENT), tk.StringVar(value="0")
                button = ttk.Button(body, style="Ench.TButton", compound="left", width=18,
                                    command=lambda i=index: self._pick_enchantment(i))
                button.grid(row=k, column=0, pady=2, sticky="we")
                ttk.Spinbox(body, from_=0, to=3, textvariable=lvl_var, width=3).grid(row=k, column=1, padx=(6, 0))
                id_var.trace_add("write", lambda *_, b=button, v=id_var: self._update_ench_button(b, v))
                self._update_ench_button(button, id_var)
                self.ench_vars.append((id_var, lvl_var))
                self.ench_boxes.append(button)
        ttk.Button(col_b_outer, text="Снять все чары с предмета", command=self.clear_item_enchantments).pack(
            fill="x", pady=(0, 6))
        ttk.Button(col_b_outer, text="Сохранить предмет", style="Accent.TButton",
                   command=self.commit_item).pack(fill="x", pady=(2, 0))

    def _build_json_tab(self):
        tab = self._page("JSON")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 8))
        theme.section(bar, "{ }", "JSON сохранения", side="left")
        ttk.Button(bar, text="Принять JSON", style="Accent.TButton", command=self.apply_json_text).pack(side="right")
        ttk.Button(bar, text="Сбросить текст", command=self.refresh_json).pack(side="right", padx=6)
        ttk.Label(tab, text="Полный доступ к данным. После правки нажмите «Принять JSON», затем «Применить в игре».",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        frame = tk.Frame(tab, bg=theme.BORDER, padx=1, pady=1)
        frame.pack(fill="both", expand=True)
        self.json_text = tk.Text(frame, bg=theme.CARD, fg=FG, insertbackground=FG, wrap="none", undo=True,
                                 font=("Consolas", 10), relief="flat", bd=8, selectbackground=theme.SELECT)
        self.json_text.pack(fill="both", expand=True)

    def _build_settings_tab(self):
        tab = self._page("Настройки")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, anchor="n", padx=(0, 14))
        right = ttk.Frame(tab)
        right.pack(side="left", fill="both", expand=True, anchor="n")
        self.set_hotkey = tk.StringVar(value=self.cfg.get("hotkey", "F8"))
        self.set_game = tk.StringVar(value=self.cfg.get("game_path", ""))
        self.set_launch = tk.BooleanVar(value=self.cfg.get("launch_game", False))
        self.set_backup = tk.BooleanVar(value=self.cfg.get("backup_on_apply", True))
        self.set_alpha = tk.DoubleVar(value=self.cfg.get("overlay_alpha", 0.95))
        self.set_paks = tk.StringVar(value=self.cfg.get("paks_dir", ""))
        self.set_pak_key = tk.StringVar(value=self.cfg.get("pak_key", ""))
        self.set_lang = tk.StringVar(value=self.cfg.get("language", "ru-RU"))

        theme.section(left, "⚙", "Оверлей")
        body = theme.card(left, "Окно поверх игры")
        theme.card_row(body, 0, "Горячая клавиша", ttk.Combobox(body, textvariable=self.set_hotkey,
                                                                values=list(game.VK_CODES), state="readonly", width=10),
                       muted=True)
        alpha_row = ttk.Frame(body, style="Card.TFrame")
        ttk.Scale(alpha_row, from_=0.5, to=1.0, variable=self.set_alpha, length=150,
                  command=self._preview_alpha).pack(side="left")
        self.alpha_label = ttk.Label(alpha_row, width=5, anchor="center", style="Card.TLabel",
                                     background=theme.INPUT, padding=(6, 3))
        self.alpha_label.pack(side="left", padx=(10, 0))
        self._preview_alpha()
        theme.card_row(body, 1, "Прозрачность", alpha_row, muted=True)
        body = theme.card(left, "Сохранения")
        theme.card_row(body, 0, "Бэкап перед каждым применением", theme.Toggle(body, self.set_backup), muted=True)
        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="Восстановить из бэкапа…", command=self.restore_backup).pack(side="left")
        ttk.Button(buttons, text="Экспорт JSON…", command=self.export_json).pack(side="left", padx=6)
        ttk.Button(buttons, text="Импорт JSON…", command=self.import_json).pack(side="left")
        ttk.Label(body, text=f"Бэкапы: {game.BACKUP_DIR}", style="CardMuted.TLabel", wraplength=480).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        body = theme.card(left, "Как применить изменения в игре")
        ttk.Label(body, style="CardMuted.TLabel", justify="left", wraplength=500, text=(
            "1. Выйдите из миссии в главное меню — игра сохранит персонажа.\n"
            "2. Нажмите горячую клавишу, отредактируйте и нажмите «Применить в игре».\n"
            "3. Выберите персонажа заново — загрузится изменённое сохранение.\n"
            "Окно видно поверх игры в режиме «В окне» или «Полноэкранный в окне».")).pack(anchor="w")

        theme.section(right, "▣", "Игра")
        body = theme.card(right, "Файлы игры")
        path_row = ttk.Frame(body, style="Card.TFrame")
        ttk.Entry(path_row, textvariable=self.set_game, width=26).pack(side="left")
        ttk.Button(path_row, text="…", width=2, command=self._browse_game).pack(side="left", padx=(3, 0))
        theme.card_row(body, 0, "Dungeons.exe", path_row, muted=True)
        paks_row = ttk.Frame(body, style="Card.TFrame")
        ttk.Entry(paks_row, textvariable=self.set_paks, width=26).pack(side="left")
        ttk.Button(paks_row, text="…", width=2, command=self._browse_paks).pack(side="left", padx=(3, 0))
        theme.card_row(body, 1, "Папка Paks", paks_row, muted=True)
        theme.card_row(body, 2, "AES-ключ (если нужен)", ttk.Entry(body, textvariable=self.set_pak_key, width=30),
                       muted=True)
        theme.card_row(body, 3, "Язык названий", ttk.Combobox(body, textvariable=self.set_lang, width=10,
                                                              values=["ru-RU", "en", "de-DE", "fr-FR", "es-ES", "uk-UA"]),
                       muted=True)
        theme.card_row(body, 4, "Автозапуск игры", theme.Toggle(body, self.set_launch), muted=True)
        self.catalog_status = tk.StringVar(value="Файлы игры: загрузка…")
        ttk.Label(body, textvariable=self.catalog_status, style="CardMuted.TLabel", wraplength=480,
                  justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(body, text="Перечитать файлы игры", command=lambda: self.load_catalog(force=True)).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(right, text="Сохранить настройки", style="Accent.TButton",
                   command=self.save_settings).pack(anchor="e", pady=(4, 0))

    def _build_mods_tab(self):
        tab = self._page("Моды")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y", anchor="n")
        theme.section(left, "✦", "Моды управления")
        self.set_wasd_on = tk.BooleanVar(value=False)
        self.set_wasd_arrows = tk.BooleanVar(value=self.cfg.get("wasd_arrows", True))
        self.set_wasd_shift = tk.BooleanVar(value=self.cfg.get("wasd_shift", True))
        body = theme.card(left, "Ходьба на WASD", toggle_var=self.set_wasd_on,
                          toggle_command=lambda: self.set_wasd(self.set_wasd_on.get()))
        theme.card_row(body, 0, "Стрелки тоже двигают персонажа",
                       theme.Toggle(body, self.set_wasd_arrows, self._wasd_options_changed), muted=True)
        theme.card_row(body, 1, "Shift — идти шагом",
                       theme.Toggle(body, self.set_wasd_shift, self._wasd_options_changed), muted=True)
        self.wasd_status = tk.StringVar(value="Выключено")
        ttk.Label(body, textvariable=self.wasd_status, style="CardMuted.TLabel", wraplength=470,
                  justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        info = theme.card(left, "Как это работает")
        ttk.Label(info, style="CardMuted.TLabel", justify="left", wraplength=470, text=(
            "Игра на ПК ходит только мышью или геймпадом, поэтому мод создаёт виртуальный геймпад Xbox, "
            "и W/A/S/D двигают его левый стик. Клавиши работают, только когда активно окно игры.\n\n"
            "Мод работает в любом мире, в том числе когда вы заходите к другу: управление обрабатывается "
            "на вашем ПК. Чтобы друг тоже ходил на WASD, ему нужно включить мод в загрузчике у себя.\n\n"
            "Нужен драйвер ViGEmBus — ставится вместе с пакетом vgamepad.")).pack(anchor="w")

    # ---------------------------------------------------------- save files
    def refresh_save_list(self, select=None, confirmed=False):
        self.saves = find_saves(self.cfg.get("extra_save_dirs", []))
        if select and os.path.isfile(select) and select not in self.saves:
            self.saves.insert(0, select)
        labels = []
        self.save_infos = []
        for path in self.saves:
            try:
                profile = read_profile(path)
                level = gd.level_for_xp(int(profile.get("xp") or 0))
                name = profile.get("name") or os.path.splitext(os.path.basename(path))[0]
                labels.append(f"{name} — ур. {level} — …{path[-40:]}")
                when = time.strftime("Изменён %d.%m.%Y %H:%M", time.localtime(os.path.getmtime(path)))
                self.save_infos.append({"path": path, "name": name, "level": level, "when": when})
            except Exception as e:  # unreadable file: still list it so the error is visible on open
                labels.append(f"[ошибка: {e}] {path}")
        self.save_box["values"] = labels
        self._refresh_home_chars()
        if not self.saves:
            self.status_var.set("Сохранения не найдены. Нажмите «Открыть .dat…» и укажите файл из папки Characters.")
            return
        if self.save and select is None and self.save.path in self.saves:
            select = self.save.path  # keep the open character selected after a rescan
        index = self.saves.index(select) if select in self.saves else 0
        self.save_box.current(index)
        self.open_selected_save(confirmed=confirmed)

    def open_selected_save(self, confirmed=False):
        index = self.save_box.current()
        if index < 0:
            return
        path = self.saves[index]
        if self.save and self.save.path == path:
            return
        if not confirmed and not self._confirm_discard():
            self._show_current_save_in_box()
            return
        self.load(path)

    def _show_current_save_in_box(self):
        if self.save and self.save.path in self.saves:
            self.save_box.current(self.saves.index(self.save.path))

    def browse_save(self):
        path = filedialog.askopenfilename(title="Сохранение персонажа", filetypes=[("Minecraft Dungeons", "*.dat"),
                                                                                  ("Все", "*.*")])
        if path and self._confirm_discard():
            self.refresh_save_list(select=os.path.normpath(path), confirmed=True)

    def load(self, path):
        try:
            self.save = SaveFile(path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать сохранение:\n{e}", parent=self.root)
            self._show_current_save_in_box()
            return
        self.cfg["last_save"] = path
        game.save_config(self.cfg)
        self.current_item = None
        self.refresh_all()
        self.status_var.set(f"Загружено: {path}")

    def reload_save(self):
        if self.save and self._confirm_discard():
            self.save.reload()
            self.current_item = None
            self.refresh_all()
            self.status_var.set("Сохранение перечитано с диска")

    def _confirm_discard(self):
        self.commit_forms()
        if self.save and self.save.dirty:
            return messagebox.askyesno("Несохранённые изменения", "Есть непримененные изменения. Отбросить их?", parent=self.root)
        return True

    def apply_to_game(self):
        if not self.save:
            return
        self.commit_forms()
        if self.save.changed_on_disk() and not messagebox.askyesno(
                "Сохранение изменено игрой",
                "Игра записала файл после того, как он был открыт в загрузчике.\n"
                "Перезаписать его вашей версией? («Нет» — отменить, затем «Обновить»).", parent=self.root):
            return
        try:
            backup = self.save.write(game.BACKUP_DIR if self.cfg.get("backup_on_apply", True) else None)
        except Exception as e:
            messagebox.showerror("Ошибка записи", str(e), parent=self.root)
            return
        msg = "Применено. В игре: главное меню → выберите персонажа заново."
        if backup:
            msg += f"  Бэкап: {os.path.basename(backup)}"
        self.status_var.set(msg)
        self.status.configure(style="Muted.TLabel")
        self.refresh_save_list(select=self.save.path)

    # ------------------------------------------------------------ refresh
    def refresh_all(self):
        self.refresh_character()
        self.refresh_items()
        self.refresh_json()
        self._refresh_value_lists()

    def refresh_character(self):
        s = self.save
        self._suspend_traces = True
        try:
            self.name_var.set(s.name)
            self.xp_var.set(str(s.xp))
            self.level_var.set(str(s.level))
            for key, var in self.currency_vars.items():
                var.set(str(s.get_currency(key)))
            diff = s.get_difficulty()
            self.difficulty_var.set(f"{diff} — {gd.DIFFICULTY_NAMES.get(diff, '')}")
            self.threat_var.set(s.get_threat())
        finally:
            self._suspend_traces = False
        self.refresh_summary()

    def _unlock_portal(self):
        if self.save and self.save.unlock_portal():
            self.refresh_summary()
            self.status_var.set("Портал в Край открыт. Нажмите «Применить в игре».")

    def refresh_summary(self):
        s = self.save
        portal = s.portal_unlocked()
        self.portal_var.set({None: "Портал Края: ещё не найден в сохранении", True: "Портал Края: открыт",
                             False: "Портал Края: закрыт"}[portal])
        self.portal_button.enabled = portal is False
        self.portal_button.draw()
        self.power_var.set(f"Сила персонажа: {s.character_power()}")
        left = s.enchantment_points_left()
        bonus = s.bonus_points()
        self.points_var.set(f"Свободные очки зачарований: {left}" + (f" (+{bonus} бонус)" if bonus else "")
                            + ("  ⚠ меньше нуля" if left < 0 else ""))
        self.points_info.set(
            f"Уровень {s.level}, потрачено {s.enchantment_points_spent()}, свободно {left}"
            + (f", бонус {bonus} (эксперимент)" if bonus else "") + ".\n"
            "«Через уровень» — надёжно, игра покажет новый уровень. «Бонус без уровня» — экспериментально, "
            "проверьте в игре.")
        self.items_count_var.set(f"Предметов: {len(s.inventory)} в инвентаре, {len(s.chest)} в сундуке")

    def refresh_items(self):
        self.tree.delete(*self.tree.get_children())
        self.items_by_iid.clear()
        if not self.save:
            return
        flt = self.filter_var.get()
        rows = [(it, "inventory") for it in self.save.inventory] + [(it, "chest") for it in self.save.chest]
        slot_order = {s: i for i, s in enumerate(gd.EQUIPMENT_SLOTS)}
        rows.sort(key=lambda r: (r[1] == "chest", r[0].get("equipmentSlot") is None,
                                 slot_order.get(r[0].get("equipmentSlot"), 0), r[0].get("inventoryIndex") or 0))
        selected_iid = None
        for item, loc in rows:
            equipped = bool(item.get("equipmentSlot"))
            if (flt == "Надетые" and not equipped) or (flt == "Инвентарь" and (loc != "inventory" or equipped)) \
                    or (flt == "Сундук" and loc != "chest"):
                continue
            if item.get("equipmentSlot"):
                slot = "★ " + SLOT_NAMES.get(item["equipmentSlot"], item["equipmentSlot"])
            else:
                slot = f"{LOCATIONS[loc]} #{item.get('inventoryIndex', '')}"
            item_type = item.get("type", "?")
            iid = self.tree.insert("", "end", text=" " + self._item_name(item_type),
                                   image=self.icons.get("item", item_type, 26),
                                   values=(slot, item_level(item), self._describe_enchants(item)),
                                   tags=(item.get("rarity", "Common"),))
            self.items_by_iid[iid] = item
            if item is self.current_item:
                selected_iid = iid
        for rarity, color in RARITY_COLORS.items():
            self.tree.tag_configure(rarity, foreground=color)
        if selected_iid:
            self.tree.selection_set(selected_iid)
            self.tree.see(selected_iid)
        if self.save:
            self.refresh_summary()

    def refresh_json(self):
        if not self.save:
            return
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", json.dumps(self.save.profile, ensure_ascii=False, indent=2))
        self.json_text.edit_reset()
        self.json_text.edit_modified(False)

    # ---------------------------------------------------- character edits
    def _on_level_changed(self, *_):
        if self._suspend_traces or not self.save:
            return
        level = _int(self.level_var, 0)
        if level >= 1:
            self._suspend_traces = True
            self.xp_var.set(str(gd.xp_for_level(level)))
            self._suspend_traces = False

    def _on_xp_changed(self, *_):
        if self._suspend_traces or not self.save:
            return
        self._suspend_traces = True
        self.level_var.set(str(gd.level_for_xp(_int(self.xp_var, 0))))
        self._suspend_traces = False

    def commit_character(self):
        s = self.save
        if not s:
            return
        xp = _int(self.xp_var, s.xp)
        if xp != s.xp:
            s.xp = xp
        for key, var in self.currency_vars.items():
            value = _int(var, s.get_currency(key))
            if value != s.get_currency(key):
                s.set_currency(key, value)
        diff = self.difficulty_var.get().split(" ")[0]
        if diff and diff != s.get_difficulty():
            s.set_difficulty(diff)
        threat = self.threat_var.get()
        if threat and threat != s.get_threat():
            s.set_threat(threat)
        self.refresh_summary()

    def _points_target_value(self):
        try:
            return max(0, int(float(self.points_target.get())))
        except ValueError:
            messagebox.showerror("Очки зачарований", "Введите число", parent=self.root)
            return None

    def _points_via_level(self):
        if not self.save:
            return
        target = self._points_target_value()
        if target is None:
            return
        self.commit_forms()
        self.save.set_bonus_points(0)  # the two ways would add up otherwise
        level = self.save.set_free_points_via_level(target)
        self.refresh_character()
        self.status_var.set(f"Уровень {level}: свободных очков {self.save.enchantment_points_left()}. "
                            "Нажмите «Применить в игре».")

    def _points_bonus(self):
        if not self.save:
            return
        target = self._points_target_value()
        if target is None:
            return
        self.commit_forms()
        extra = max(0, target - self.save.enchantment_points_left())
        try:
            item = self.save.set_bonus_points(extra)
        except ValueError as e:
            messagebox.showerror("Очки зачарований", str(e), parent=self.root)
            return
        self.refresh_summary()
        where = self._item_name(item.get("type")) if item else "—"
        self.status_var.set(f"Бонус {extra} очков записан в пустую ячейку зачарования предмета «{where}». "
                            "Это экспериментально: примените и проверьте в игре.")

    def _points_clear_bonus(self):
        if self.save:
            self.save.set_bonus_points(0)
            self.refresh_summary()
            self.status_var.set("Бонусные очки убраны. Нажмите «Применить в игре».")

    def _quick_level_100(self):
        self.level_var.set("100")
        self.commit_character()

    def _quick_rich(self):
        for key in ("Emerald", "Gold"):
            self.currency_vars[key].set("999999")
        self.commit_character()

    def _quick_unlock(self):
        self.difficulty_var.set(f"{gd.DIFFICULTIES[-1]} — {gd.DIFFICULTY_NAMES[gd.DIFFICULTIES[-1]]}")
        self.threat_var.set(gd.THREAT_LEVELS[-1])
        self.commit_character()

    # --------------------------------------------------------- item edits
    def _on_item_selected(self, _event=None):
        sel = self.tree.selection()
        item = self.items_by_iid.get(sel[0]) if sel else None
        if item is self.current_item:
            return
        self.commit_item(refresh=False)
        self.current_item = item
        self.load_item_form(item)
        self.refresh_items()

    def load_item_form(self, item):
        item = item or {}
        self.it_type.set(item.get("type", ""))
        self.it_level.set(str(item_level(item)) if item else "")
        self.it_rarity.set(item.get("rarity", "Common"))
        self.it_slot.set(item.get("equipmentSlot") or NO_SLOT)
        self.it_upgraded.set(bool(item.get("upgraded")))
        self.it_gifted.set(bool(item.get("gifted")))
        self.it_new.set(bool(item.get("markedNew")))
        enchants = item.get("enchantments") or []
        for i, (id_var, lvl_var) in enumerate(self.ench_vars):
            e = enchants[i] if i < len(enchants) else {}  # rows past the item's slots stay empty
            id_var.set(e.get("id", gd.UNSET_ENCHANTMENT))
            lvl_var.set(str(e.get("level", 0)))
        gilded = item.get("netheriteEnchant")
        self.gild_on.set(gilded is not None)
        self.gild_id.set((gilded or {}).get("id", ""))
        self.gild_lvl.set(str((gilded or {}).get("level", 1)))
        self.armor_props = [dict(p) for p in item.get("armorproperties") or []]
        self._refresh_props()
        self.editor.configure(text="Предмет")
        self._update_item_header()

    def _refresh_props(self):
        self.props_list.delete(0, "end")
        for p in self.armor_props:
            name = self.catalog.armor_property_name(p.get("id")) if self.catalog else p.get("id")
            self.props_list.insert("end", f"{name}  [{p.get('id')}]  ({p.get('rarity', 'Common')})")

    def _add_prop(self):
        if self.current_item is None or not self.prop_id.get().strip():
            return
        if self._item_kind() != "armor" and not self.current_item.get("armorproperties"):
            messagebox.showinfo("Свойства брони", "Свойства брони бывают только у брони.", parent=self.root)
            return
        self.armor_props.append({"id": self.prop_id.get().strip(), "rarity": self.prop_rarity.get() or "Common"})
        self._refresh_props()

    def _remove_prop(self):
        sel = self.props_list.curselection()
        if sel:
            del self.armor_props[sel[0]]
            self._refresh_props()

    def commit_item(self, refresh=True):
        item, s = self.current_item, self.save
        if item is None or s is None or not any(it is item for it in s.all_items()):
            return
        before = json.dumps(item, sort_keys=True)

        new_type = self.it_type.get().strip()
        if new_type and new_type != item.get("type"):
            item["type"] = new_type
            found = s.profile.get("itemsFound")
            if isinstance(found, list) and new_type not in found:
                found.append(new_type)
        level = _int(self.it_level, item_level(item))
        if level != item_level(item):
            set_item_level(item, level)
        if self.it_rarity.get():
            item["rarity"] = self.it_rarity.get()
        for key, var in (("upgraded", self.it_upgraded), ("gifted", self.it_gifted), ("markedNew", self.it_new)):
            if key in item or var.get():
                item[key] = bool(var.get())

        artifact = self._item_kind(item) == "artifact"
        if self.gild_on.get() and self.gild_id.get().strip() and not (artifact and "netheriteEnchant" not in item):
            gilded = item.get("netheriteEnchant") or {}
            gilded["id"] = self.gild_id.get().strip()
            gilded["level"] = max(0, min(3, _int(self.gild_lvl, 1)))
            item["netheriteEnchant"] = gilded
        else:
            item.pop("netheriteEnchant", None)

        form = [(v[0].get().strip() or gd.UNSET_ENCHANTMENT, _int(v[1], 0)) for v in self.ench_vars]
        existing = item.get("enchantments") or []
        # Only the item's own slots are compared/written; rows past them count only if the user filled them.
        used = max(len(existing), max((i + 1 for i, (eid, lvl) in enumerate(form)
                                       if eid != gd.UNSET_ENCHANTMENT or lvl), default=0))
        if artifact and not existing:
            used = 0  # artifacts have no enchantment slots
        if used:
            used = min(gd.ENCHANTMENTS_PER_ITEM, -(-used // 3) * 3)  # whole slots of three options
            current = [(e.get("id"), int(e.get("level") or 0)) for e in existing]
            current += [(gd.UNSET_ENCHANTMENT, 0)] * (used - len(current))
            if current[:used] != form[:used]:
                for i, (eid, lvl) in enumerate(form[:used]):
                    if lvl == 0 and (i >= len(existing) or current[i] != (eid, lvl)):
                        set_enchantment(item, i, eid, 0)
                for i, (eid, lvl) in enumerate(form[:used]):
                    if lvl > 0 and (i >= len(existing) or current[i] != (eid, lvl)):
                        set_enchantment(item, i, eid, lvl)

        if self.armor_props or "armorproperties" in item:
            item["armorproperties"] = [dict(p) for p in self.armor_props]

        slot = self.it_slot.get()
        slot = None if slot in ("", NO_SLOT) else slot
        if slot != item.get("equipmentSlot"):
            s.equip(item, slot)

        if json.dumps(item, sort_keys=True) != before:
            s.dirty = True
            self.status_var.set("Есть непримененные изменения — нажмите «Применить в игре»")
        if refresh:
            self.load_item_form(item)
            self.refresh_items()

    def commit_forms(self):
        if self.save:
            self.commit_character()
            self.commit_item(refresh=False)

    def _select(self, item):
        self.current_item = item
        self.load_item_form(item)
        self.filter_var.set(FILTERS[0])
        self.refresh_items()

    def add_item(self):
        if not self.save:
            return
        self.commit_item(refresh=False)
        if not (self.catalog and self.catalog.loaded):
            self.status_var.set("Файлы игры не загружены — в списке только предметы из сохранения. "
                                "Укажите папку Paks в «Настройках», чтобы видеть все предметы с иконками.")
        ItemPicker(self.root, self.icons, self.catalog, sorted(self.save.known_item_types()), self._add_from_picker)

    def _add_from_picker(self, ident, category=None, in_chest=False, level=1, count=1, equip=False, rarity="Common"):
        slot = cat_mod.CATEGORY_SLOT.get(category) if equip and not in_chest else None
        if slot == "HotbarSlot1":
            used = {i.get("equipmentSlot") for i in self.save.inventory}
            slot = next((s for s in gd.EQUIPMENT_SLOTS[3:] if s not in used), "HotbarSlot1")
        item = None
        for n in range(count):
            item = self.save.new_item(ident, slot=slot if n == 0 else None, in_chest=in_chest,
                                      artifact=category == "artifact", rarity=rarity, level=level)
        self._select(item)
        self.status_var.set(f"Добавлено: {self._item_name(ident)} × {count}. Нажмите «Применить в игре».")

    def duplicate_item(self):
        if self.save and self.current_item is not None:
            self.commit_item(refresh=False)
            self._select(self.save.duplicate_item(self.current_item))

    def delete_item(self):
        if self.save and self.current_item is not None:
            if messagebox.askyesno("Удалить", f"Удалить {self.current_item.get('type')}?", parent=self.root):
                self.save.remove_item(self.current_item)
                self.current_item = None
                self.load_item_form(None)
                self.refresh_items()

    def move_item(self):
        if self.save and self.current_item is not None:
            self.commit_item(refresh=False)
            to_chest = self.save.location(self.current_item) == "inventory"
            self.save.move_item(self.current_item, to_chest)
            self._select(self.current_item)

    def set_all_levels(self):
        if not self.save:
            return
        self.commit_item(refresh=False)
        win = tk.Toplevel(self.root, bg=BG, padx=16, pady=16)
        win.title("Уровень всех предметов")
        win.attributes("-topmost", True)
        var = tk.StringVar(value="100")
        ttk.Label(win, text="Уровень силы для всех предметов:").pack(anchor="w")
        ttk.Spinbox(win, from_=1, to=10000, textvariable=var, width=10).pack(anchor="w", pady=6)

        def ok():
            for it in self.save.all_items():
                set_item_level(it, _int(var, 100))
            self.save.dirty = True
            win.destroy()
            self.load_item_form(self.current_item)
            self.refresh_items()
        ttk.Button(win, text="OK", style="Accent.TButton", command=ok).pack(anchor="e")

    def max_all_enchantments(self):
        if not self.save:
            return
        self.commit_item(refresh=False)
        changed = sum(1 for it in self.save.all_items() if max_out_enchantments(it))
        if changed:
            self.save.dirty = True
        self.load_item_form(self.current_item)
        self.refresh_items()
        self.status_var.set(f"Выбранные зачарования подняты до 3 на {changed} предмет(ах). "
                            "Невыбранные варианты не тронуты.")

    def clear_item_enchantments(self):
        if not self.save or self.current_item is None:
            return
        self.commit_item(refresh=False)
        if clear_enchantments(self.current_item):
            self.save.dirty = True
            self.status_var.set("Все зачарования предмета сняты. Нажмите «Применить в игре».")
        self.load_item_form(self.current_item)
        self.refresh_items()

    # ------------------------------------------------------------- JSON
    def apply_json_text(self):
        if not self.save:
            return
        try:
            data = json.loads(self.json_text.get("1.0", "end"))
            if not isinstance(data, dict):
                raise ValueError("ожидался JSON-объект")
        except ValueError as e:
            messagebox.showerror("Ошибка JSON", str(e), parent=self.root)
            return
        self.save.profile = data
        self.save.dirty = True
        self.current_item = None
        self.load_item_form(None)
        self.refresh_all()
        self.json_text.edit_modified(False)
        self.status_var.set("JSON принят — нажмите «Применить в игре», чтобы записать сохранение")

    def _on_tab_changed(self, _event=None):
        self._highlight_nav()
        current = self.notebook.index("current")
        left_json = self._last_tab == 2 and current != 2
        self._last_tab = current
        if not self.save:
            return
        if left_json and self.json_text.edit_modified():
            if messagebox.askyesno("JSON", "Текст JSON изменён, но не принят. Принять изменения?", parent=self.root):
                self.apply_json_text()
            self.json_text.edit_modified(False)
        self.commit_forms()
        if self.notebook.index("current") == 2:
            self.refresh_json()
        elif self.notebook.index("current") == 0:
            self.refresh_character()

    # --------------------------------------------------------- settings
    def _browse_game(self):
        path = filedialog.askopenfilename(title="Dungeons.exe", filetypes=[("Программа", "*.exe")])
        if path:
            self.set_game.set(path)

    def _preview_alpha(self, _value=None):
        self.alpha_label.configure(text=f"{float(self.set_alpha.get()):.2f}")
        self.alpha = float(self.set_alpha.get())
        try:
            self.root.attributes("-alpha", float(self.set_alpha.get()))
        except tk.TclError:
            pass

    def save_settings(self):
        catalog_changed = (self.set_paks.get().strip(), self.set_pak_key.get().strip(), self.set_lang.get()) != \
            (self.cfg.get("paks_dir", ""), self.cfg.get("pak_key", ""), self.cfg.get("language", "ru-RU"))
        self.cfg.update(hotkey=self.set_hotkey.get(), game_path=self.set_game.get().strip(),
                        launch_game=self.set_launch.get(), backup_on_apply=self.set_backup.get(),
                        overlay_alpha=round(float(self.set_alpha.get()), 2), paks_dir=self.set_paks.get().strip(),
                        pak_key=self.set_pak_key.get().strip(), language=self.set_lang.get() or "ru-RU",
                        wasd_arrows=self.set_wasd_arrows.get(), wasd_shift=self.set_wasd_shift.get())
        game.save_config(self.cfg)
        if catalog_changed:
            self.load_catalog(force=True)
        self.hotkey = game.HotkeyPoller(self.cfg["hotkey"])
        self.status_var.set(f"Настройки сохранены ({game.CONFIG_PATH})")

    def restore_backup(self):
        if not self.save:
            return
        path = filedialog.askopenfilename(title="Бэкап", initialdir=game.BACKUP_DIR, filetypes=[("Сохранение", "*.dat")])
        if path and messagebox.askyesno("Восстановить", f"Заменить {self.save.path}\nфайлом {path}?", parent=self.root):
            self.save.backup(game.BACKUP_DIR)
            shutil.copy2(path, self.save.path)
            self.save.reload()
            self.refresh_all()
            self.status_var.set("Восстановлено из бэкапа. В игре выберите персонажа заново.")

    def export_json(self):
        if not self.save:
            return
        self.commit_forms()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialfile=os.path.splitext(os.path.basename(self.save.path))[0] + ".json")
        if path:
            self.save.export_json(path)
            self.status_var.set(f"Экспортировано: {path}")

    def import_json(self):
        if not self.save:
            return
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("Сохранение", "*.dat")])
        if path:
            try:
                self.save.profile = read_profile(path)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e), parent=self.root)
                return
            self.save.dirty = True
            self.current_item = None
            self.load_item_form(None)
            self.refresh_all()
            self.status_var.set("Импортировано — нажмите «Применить в игре»")

    # ----------------------------------------------------- game / overlay
    def start_game(self):
        try:
            started = game.launch_game(self.cfg)
            self.status_var.set(f"Игра запускается: {started}. Нажмите {self.cfg.get('hotkey', 'F8')} в игре.")
            if self.hotkey.available:
                self.root.after(1500, self.hide)
        except Exception as e:
            messagebox.showerror("Запуск игры", str(e), parent=self.root)

    def show(self):
        self._hiding = False
        self.root.attributes("-alpha", 0.0)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        chrome.fade(self.animator, self.root, 0.0, self.alpha, 200)
        self._highlight_nav()
        self._sync_with_disk()

    def hide(self):
        self.commit_forms()
        self._hiding = True

        def done():
            if self._hiding:
                self.root.withdraw()
        chrome.fade(self.animator, self.root, float(self.root.attributes("-alpha")), 0.0, 150, done=done)

    def toggle(self):
        if self.root.state() == "withdrawn" or getattr(self, "_hiding", False):
            self.show()
        else:
            self.hide()

    def _every(self, key, ms, fn):
        """Run fn every ms milliseconds until shutdown()."""
        def tick():
            try:
                fn()
            except Exception:
                logging.exception("periodic task %s failed", key)
            if key in self._jobs:
                self._jobs[key] = self.root.after(ms, tick)
        self._jobs[key] = self.root.after(ms, tick)

    def _poll_hotkey(self):
        if self.hotkey.pressed():
            self.toggle()

    def _sync_with_disk(self):
        if not self.save or not self.save.changed_on_disk():
            return
        self.commit_forms()
        if self.save.dirty:
            self.status_var.set("⚠ Игра перезаписала сохранение. Ваши правки ещё не применены — "
                                "«Применить в игре» перезапишет файл, «Обновить» загрузит версию игры.")
            self.status.configure(style="Warn.TLabel")
        else:
            try:
                self.save.reload()
            except Exception:
                return  # the game may still be writing; retry on next tick
            self.refresh_all()
            self.status_var.set("Игра обновила сохранение — данные перезагружены")
            self.status.configure(style="Muted.TLabel")

    def _watch_disk(self):
        if self.root.state() != "withdrawn":
            self._sync_with_disk()

    def on_close(self):
        self.commit_forms()
        if self.save and self.save.dirty and not messagebox.askyesno(
                "Выход", "Есть непримененные изменения. Выйти без применения?", parent=self.root):
            return
        self.shutdown()
        self.root.destroy()

    def shutdown(self):
        self._icon_thread_stop.set()
        self.wasd.stop()
        for job in self._jobs.values():
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()

    # ------------------------------------------------- game catalog/icons
    def load_catalog(self, force=False):
        """Read the game's paks in the background: full item list, names and icons."""
        paks_dir = cat_mod.find_paks_dir(self.cfg.get("paks_dir", ""), self.cfg.get("game_path", ""))
        logging.info("paks dir: %s", paks_dir)
        self.paks_dir = paks_dir
        if not paks_dir:
            self.catalog_status.set("Файлы игры не найдены — укажите папку игры")
            self.show_banner("Файлы игры не найдены, поэтому нет иконок и полного списка предметов. "
                             "Укажите папку, куда установлена Minecraft Dungeons (или запустите игру и "
                             "нажмите «Перечитать файлы игры» в настройках).")
            return
        self.hide_banner()
        self._icon_thread_stop.set()
        self._icon_thread_stop = threading.Event()
        stop = self._icon_thread_stop
        self._catalog_gen += 1
        gen = self._catalog_gen

        def post(fn):
            self._ui_queue.put(lambda: fn() if gen == self._catalog_gen else None)
        cache_dir = os.path.join(game.CACHE_DIR, "catalog")
        self.catalog_error = None
        if force:
            try:
                os.remove(os.path.join(cache_dir, "catalog.json"))
            except OSError:
                pass
            icons_dir = os.path.join(cache_dir, "icons")
            for name in os.listdir(icons_dir) if os.path.isdir(icons_dir) else []:
                if name.endswith(".failed"):
                    os.remove(os.path.join(icons_dir, name))
        self.catalog_status.set(f"Файлы игры: чтение {paks_dir}…")

        def work():
            try:
                catalog = cat_mod.GameCatalog.load(paks_dir, cache_dir, [self.cfg.get("pak_key", "")],
                                                   self.cfg.get("language", "ru-RU"))
            except Exception as e:
                logging.exception("catalog load failed for %s", paks_dir)
                message = f"Не удалось прочитать файлы игры: {e}"
                error = str(e)

                def failed():
                    self.catalog_error = error
                    self.catalog_status.set(message)
                    self.show_banner(f"{message}. Подробности — в файле {game.LOG_PATH}")
                    self.run_checks()
                post(failed)
                return
            logging.info("catalog: %s items, %s enchantments, version %s, language %s", len(catalog.items),
                         len(catalog.enchantments), catalog.version, catalog.language)
            post(lambda: self._on_catalog(catalog))
            catalog.extract_all_icons(stop=stop.is_set)
            ok, failed, sample = catalog.icon_stats()
            logging.info("icons: %s ok, %s failed; e.g. %s", ok, failed, sample)
            if not stop.is_set():
                post(self._on_icons_ready)

        threading.Thread(target=work, daemon=True, name="catalog").start()

    def _drain_ui_queue(self):
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass

    def _on_catalog(self, catalog):
        self.catalog = catalog
        self.icons.set_catalog(catalog)
        self.catalog_status.set(
            f"Файлы игры: версия {catalog.version or '?'}, предметов {len(catalog.items)}, "
            f"зачарований {len(catalog.enchantments)}, свойств брони {len(catalog.armor_properties)}, "
            f"язык {catalog.language or '—'}. Иконки извлекаются…")
        self._refresh_after_catalog()
        self.run_checks()

    def show_banner(self, text):
        self.banner_text.set(text)
        if not self.banner.winfo_ismapped():
            self.banner.pack(fill="x", pady=(0, 10), before=self.notebook)

    def hide_banner(self):
        self.banner.pack_forget()

    def choose_game_folder(self):
        path = filedialog.askdirectory(title="Папка с установленной Minecraft Dungeons", parent=self.root)
        if not path:
            return
        self.show_banner(f"Ищу файлы игры в {path}…")

        def work():
            found = cat_mod.paks_from_install(path) or cat_mod.search_paks(path)
            logging.info("user folder %s -> %s", path, found)
            self._ui_queue.put(lambda: self._on_game_folder(path, found))
        threading.Thread(target=work, daemon=True, name="find-paks").start()

    def _on_game_folder(self, path, found):
        if not found:
            self.show_banner(f"В папке {path} не нашлось файлов игры (pakchunk0-….pak). "
                             "Выберите папку, куда установлена Minecraft Dungeons.")
            return
        self.cfg["paks_dir"] = found
        game.save_config(self.cfg)
        self.set_paks.set(found)
        self.load_catalog(force=True)

    def _on_icons_ready(self):
        ok, failed, _sample = self.catalog.icon_stats()
        if failed and not ok:
            self.show_banner(f"Список предметов загружен, но иконки извлечь не удалось ({failed} шт.). "
                             f"Пришлите файл {game.LOG_PATH} — по нему видно причину.")
        self.icons.set_catalog(self.catalog)
        self.catalog_status.set(self.catalog_status.get().replace("Иконки извлекаются…", "Иконки готовы."))
        self._refresh_home_art()
        self.run_checks()
        self._refresh_after_catalog()

    def _refresh_after_catalog(self):
        if self.save:
            self._refresh_value_lists()
            self.refresh_items()
            self._update_item_header()
            for button, (id_var, _) in zip(self.ench_boxes, self.ench_vars):
                self._update_ench_button(button, id_var)
            self._update_ench_button(self.gild_box, self.gild_id)
            self._refresh_props()

    def _refresh_value_lists(self):
        types = set(self.save.known_item_types())
        props = set(self.save.known_armor_properties())
        if self.catalog:
            types.update(self.catalog.items)
            props.update(self.catalog.armor_properties)
        self.type_box["values"] = sorted(types, key=str.lower)
        self.prop_box["values"] = sorted(props, key=str.lower)

    def _item_name(self, item_type):
        return self.catalog.item_name(item_type) if self.catalog else item_type

    def _ench_name(self, ench_id):
        if not ench_id or ench_id == gd.UNSET_ENCHANTMENT:
            return "— пусто —"
        return self.catalog.enchantment_name(ench_id) if self.catalog else ench_id

    def _describe_enchants(self, item):
        parts = [f"{self._ench_name(e['id'])} {e['level']}" for e in item.get("enchantments") or []
                 if e.get("level") and e.get("id") != gd.UNSET_ENCHANTMENT]
        gilded = item.get("netheriteEnchant")
        if gilded:
            parts.append(f"★{self._ench_name(gilded.get('id'))} {gilded.get('level', 0)}")
        return ", ".join(parts)

    def _update_item_header(self):
        item_type = self.it_type.get().strip()
        self.item_icon.configure(image=self.icons.get("item", item_type, 64) if item_type else self.icons.placeholder(64))
        self.item_title.configure(text=self._item_name(item_type) if item_type else "—")

    def _update_ench_button(self, button, var):
        ench_id = var.get().strip() or gd.UNSET_ENCHANTMENT
        image = self.icons.get("enchantment", ench_id, 22) if ench_id != gd.UNSET_ENCHANTMENT \
            else self.icons.placeholder(22)
        button.configure(text=" " + self._ench_name(ench_id), image=image)
        button.image = image

    def _pick_type(self):
        if not self.save or self.current_item is None:
            return
        ItemTypePicker(self.root, self.icons, self.catalog, sorted(self.save.known_item_types()),
                       lambda ident: self.it_type.set(ident))

    def _item_kind(self, item=None):
        """'artifact', 'armor', 'melee', 'ranged' or None for the edited item."""
        item = item if item is not None else self.current_item or {}
        slot = item.get("equipmentSlot") or ""
        if slot.startswith("Hotbar"):
            return "artifact"
        if slot in cat_mod.CATEGORY_SLOT.values():
            return {v: k for k, v in cat_mod.CATEGORY_SLOT.items()}[slot]
        return self.catalog.category(item.get("type", "")) if self.catalog else None

    def _pick_enchantment(self, index):
        if not self.save or self.current_item is None:
            return
        if self._item_kind() == "artifact" and not self.current_item.get("enchantments"):
            messagebox.showinfo("Зачарования", "У артефактов нет зачарований.", parent=self.root)
            return
        slot = self.it_slot.get()
        category = self.catalog.category(self.it_type.get().strip()) if self.catalog else None
        if slot not in gd.GEAR_SLOTS and category in ("melee", "ranged", "armor"):
            slot = cat_mod.CATEGORY_SLOT[category]
        target = self.gild_id if index is None else self.ench_vars[index][0]

        def chosen(ident):
            target.set(ident)
            if index is None:
                self.gild_on.set(ident != gd.UNSET_ENCHANTMENT)
            elif ident == gd.UNSET_ENCHANTMENT:
                self.ench_vars[index][1].set("0")
            elif _int(self.ench_vars[index][1], 0) == 0:
                self.ench_vars[index][1].set("3")
                base = index - index % 3
                for j in range(base, base + 3):
                    if j != index:
                        self.ench_vars[j][1].set("0")
        EnchantmentPicker(self.root, self.icons, self.catalog, self.save.known_enchantments(), slot, chosen,
                          allow_unset=index is not None)

    def _browse_paks(self):
        path = filedialog.askdirectory(title="Папка Dungeons\\Content\\Paks")
        if path:
            self.set_paks.set(os.path.normpath(path))

    # ------------------------------------------------------------- WASD
    def set_wasd(self, enabled):
        if enabled:
            try:
                self.wasd.arrows = self.set_wasd_arrows.get()
                self.wasd.start()
            except WasdUnavailable as e:
                self.set_wasd_on.set(False)
                self.wasd_status.set(f"Не включено: {e}")
                if e.installer and messagebox.askyesno(
                        "Драйвер геймпада",
                        "Для ходьбы на WASD нужен драйвер ViGEmBus (виртуальный геймпад).\n"
                        "Установить его сейчас? Windows попросит права администратора.\n\n"
                        "После установки снова включите «Ходьба на WASD».", parent=self.root):
                    os.startfile(e.installer)  # noqa: S606 - runs the bundled msi via msiexec
                    self.wasd_status.set("Идёт установка драйвера ViGEmBus. После неё включите мод снова.")
                return
            self.wasd_status.set("Включено. В окне игры W/A/S/D двигают персонажа (через виртуальный геймпад). "
                                 "Мышь по-прежнему атакует и целится.")
        else:
            self.wasd.stop()
            self.wasd_status.set("Выключено")
        self.set_wasd_on.set(enabled)
        self.cfg["wasd_enabled"] = enabled
        game.save_config(self.cfg)

    def _wasd_options_changed(self):
        self.wasd.arrows = self.set_wasd_arrows.get()
        self.wasd.shift_walk = self.set_wasd_shift.get()
        self.cfg["wasd_arrows"] = self.wasd.arrows
        self.cfg["wasd_shift"] = self.wasd.shift_walk
        game.save_config(self.cfg)


def run(initial_save=None, launch=None):
    from . import hub
    hub.run(initial_save=initial_save, launch=launch)
