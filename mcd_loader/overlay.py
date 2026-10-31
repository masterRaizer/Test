"""In-game overlay: a topmost editor window toggled by a hotkey over the running game."""
import json
import os
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import catalog as cat_mod, game, gamedata as gd, theme
from .pickers import RARITY_COLORS, EnchantmentPicker, IconCache, ItemPicker, ItemTypePicker
from .wasd import WasdMovement, WasdUnavailable
from .savefile import (SaveFile, find_saves, item_level, max_out_enchantments,
                       read_profile, recompute_invested_points, set_enchantment, set_item_level)

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
    PAGES = [("◉", "Персонаж"), ("▦", "Инвентарь"), ("{ }", "JSON"), ("⚙", "Настройки"), ("✦", "Моды")]
    NAV_ORDER = [0, 1, 4, 2, 3]  # sidebar order: character, inventory, mods, JSON, settings

    def __init__(self, root, cfg, initial_save=None):
        self.root = root
        self.cfg = cfg
        self.save = None
        self.saves = []
        self.items_by_iid = {}
        self.current_item = None
        self.armor_props = []
        self.hotkey = game.HotkeyPoller(cfg.get("hotkey", "F8"))
        self._suspend_traces = False
        self.catalog = None
        self.icons = IconCache(root)
        self.wasd = WasdMovement(arrows=cfg.get("wasd_arrows", True), shift_walk=cfg.get("wasd_shift", True))
        self._icon_thread_stop = threading.Event()
        self._ui_queue = queue.Queue()  # callables from worker threads, run on the Tk thread

        root.title("MCD Loader — Minecraft Dungeons")
        root.geometry("1320x800")
        root.minsize(1180, 680)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", float(cfg.get("overlay_alpha", 0.95)))
        except tk.TclError:
            pass
        theme.apply_theme(root)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda e: self.apply_to_game())
        root.bind("<Escape>", lambda e: self.hide() if self.hotkey.available else None)

        self._build_header()
        body = ttk.Frame(root, style="Window.TFrame")
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        content = ttk.Frame(body, padding=(14, 10, 14, 12))
        content.pack(side="left", fill="both", expand=True)
        self.status_var = tk.StringVar(value="Выберите персонажа")
        self.status = ttk.Label(content, textvariable=self.status_var, style="Muted.TLabel")
        self.status.pack(fill="x", pady=(0, 8))
        self.notebook = ttk.Notebook(content, style="Hidden.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self._build_character_tab()
        self._build_inventory_tab()
        self._build_json_tab()
        self._build_settings_tab()
        self._build_mods_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.refresh_save_list(select=initial_save or cfg.get("last_save"))
        self.root.after(50, self._poll_hotkey)
        self.root.after(2000, self._watch_disk)
        self.root.after(100, self._drain_ui_queue)
        self.load_catalog()
        if cfg.get("wasd_enabled"):
            self.root.after(500, lambda: self.set_wasd(True))

    # ------------------------------------------------------------------ UI
    def _build_header(self):
        bar = ttk.Frame(self.root, style="Window.TFrame", padding=(22, 12, 14, 12))
        bar.pack(fill="x")
        ttk.Label(bar, text="MCD LOADER", style="Title.TLabel").pack(side="left", padx=(0, 28))
        self.save_var = tk.StringVar()
        self.save_box = ttk.Combobox(bar, textvariable=self.save_var, state="readonly", width=40)
        self.save_box.pack(side="left")
        self.save_box.bind("<<ComboboxSelected>>", lambda e: self.open_selected_save())
        ttk.Button(bar, text="⟳", style="Icon.TButton", width=3, command=self.reload_save).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="…", style="Icon.TButton", width=3, command=self.browse_save).pack(side="left")
        ttk.Button(bar, text="⌕", style="Icon.TButton", width=3, command=self.add_item).pack(side="right")
        ttk.Button(bar, text="⚙", style="Icon.TButton", width=3, command=lambda: self.show_page(3)).pack(side="right")
        ttk.Button(bar, text="▶  Игра", command=self.start_game).pack(side="right", padx=(0, 10))
        ttk.Button(bar, text="✔  Применить в игре", style="Accent.TButton",
                   command=self.apply_to_game).pack(side="right", padx=(0, 8))
        hint = f"{self.cfg.get('hotkey', 'F8')} — показать / скрыть" if self.hotkey.available else ""
        ttk.Label(bar, text=hint, style="WindowMuted.TLabel").pack(side="right", padx=12)
        tk.Frame(self.root, bg=theme.BORDER, height=1).pack(fill="x")

    def _build_sidebar(self, parent):
        side = ttk.Frame(parent, style="Window.TFrame", padding=(10, 14, 10, 10))
        side.pack(side="left", fill="y")
        self.nav_buttons = {}
        for index in self.NAV_ORDER:
            icon, title = self.PAGES[index]
            button = ttk.Button(side, text=f"{icon:<3}  {title}", style="Nav.TButton", width=16,
                                command=lambda i=index: self.show_page(i))
            button.pack(fill="x", pady=2)
            self.nav_buttons[index] = button
        tk.Frame(parent, bg=theme.BORDER, width=1).pack(side="left", fill="y")

    def show_page(self, index):
        self.notebook.select(index)

    def _highlight_nav(self):
        current = self.notebook.index("current")
        for index, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if index == current else "Nav.TButton")

    def _labeled(self, parent, row, text, widget):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=row, column=1, sticky="we", pady=4)
        return widget

    def _page(self, title):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text=title)
        return tab

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
        quick = theme.card(right, "Быстрые действия")
        for text, cmd in (("Изумруды и золото = 999 999", self._quick_rich),
                          ("Открыть все сложности и угрозы", self._quick_unlock),
                          ("Уровень персонажа = 100", lambda: self.level_var.set("100")),
                          ("Все предметы: уровень…", self.set_all_levels),
                          ("Все зачарования на уровень 3", self.max_all_enchantments)):
            ttk.Button(quick, text=text, command=cmd, width=34).pack(fill="x", pady=3)

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
        self.type_box = ttk.Combobox(type_row, textvariable=self.it_type, width=17)
        self.type_box.pack(side="left")
        ttk.Button(type_row, text="…", width=2, command=self._pick_type).pack(side="left", padx=(3, 0))
        theme.card_row(grid, 0, "Тип (ID)", type_row, muted=True)
        self.it_type.trace_add("write", lambda *_: self._update_item_header())
        theme.card_row(grid, 1, "Уровень силы", ttk.Spinbox(grid, from_=0, to=10000, textvariable=self.it_level,
                                                             width=19), muted=True)
        theme.card_row(grid, 2, "Редкость", ttk.Combobox(grid, textvariable=self.it_rarity, values=gd.RARITIES,
                                                         state="readonly", width=19), muted=True)
        theme.card_row(grid, 3, "Слот", ttk.Combobox(grid, textvariable=self.it_slot, state="readonly", width=19,
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
        self.gild_box = ttk.Button(gild_row, style="Ench.TButton", compound="left", width=22,
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
        self.prop_box = ttk.Combobox(row, textvariable=self.prop_id, width=16)
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
                button = ttk.Button(body, style="Ench.TButton", compound="left", width=22,
                                    command=lambda i=index: self._pick_enchantment(i))
                button.grid(row=k, column=0, pady=2, sticky="we")
                ttk.Spinbox(body, from_=0, to=3, textvariable=lvl_var, width=3).grid(row=k, column=1, padx=(6, 0))
                id_var.trace_add("write", lambda *_, b=button, v=id_var: self._update_ench_button(b, v))
                self._update_ench_button(button, id_var)
                self.ench_vars.append((id_var, lvl_var))
                self.ench_boxes.append(button)
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
    def refresh_save_list(self, select=None):
        self.saves = find_saves(self.cfg.get("extra_save_dirs", []))
        if select and os.path.isfile(select) and select not in self.saves:
            self.saves.insert(0, select)
        labels = []
        for path in self.saves:
            try:
                profile = read_profile(path)
                level = gd.level_for_xp(int(profile.get("xp") or 0))
                name = profile.get("name") or os.path.splitext(os.path.basename(path))[0]
                labels.append(f"{name} — ур. {level} — …{path[-40:]}")
            except Exception as e:  # unreadable file: still list it so the error is visible on open
                labels.append(f"[ошибка: {e}] {path}")
        self.save_box["values"] = labels
        if not self.saves:
            self.status_var.set("Сохранения не найдены. Нажмите «Открыть .dat…» и укажите файл из папки Characters.")
            return
        index = self.saves.index(select) if select in self.saves else 0
        self.save_box.current(index)
        self.open_selected_save()

    def open_selected_save(self):
        index = self.save_box.current()
        if index < 0:
            return
        path = self.saves[index]
        if self.save and self.save.path == path:
            return
        if not self._confirm_discard():
            return
        self.load(path)

    def browse_save(self):
        path = filedialog.askopenfilename(title="Сохранение персонажа", filetypes=[("Minecraft Dungeons", "*.dat"), ("Все", "*.*")])
        if path:
            if self._confirm_discard():
                self.refresh_save_list(select=os.path.normpath(path))

    def load(self, path):
        try:
            self.save = SaveFile(path)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать сохранение:\n{e}", parent=self.root)
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

    def refresh_summary(self):
        s = self.save
        self.power_var.set(f"Сила персонажа: {s.character_power()}")
        left = s.enchantment_points_left()
        self.points_var.set(f"Свободные очки зачарований: {left}" + ("  ⚠ меньше нуля" if left < 0 else ""))
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
            e = enchants[i] if i < len(enchants) else {}
            id_var.set(e.get("id", gd.UNSET_ENCHANTMENT))
            lvl_var.set(str(e.get("level", 0)))
        gilded = item.get("netheriteEnchant")
        self.gild_on.set(gilded is not None)
        self.gild_id.set((gilded or {}).get("id", ""))
        self.gild_lvl.set(str((gilded or {}).get("level", 1)))
        self.armor_props = [dict(p) for p in item.get("armorproperties") or []]
        self._refresh_props()
        self.editor.configure(text="⚔  Предмет")
        self._update_item_header()

    def _refresh_props(self):
        self.props_list.delete(0, "end")
        for p in self.armor_props:
            name = self.catalog.armor_property_name(p.get("id")) if self.catalog else p.get("id")
            self.props_list.insert("end", f"{name}  [{p.get('id')}]  ({p.get('rarity', 'Common')})")

    def _add_prop(self):
        if self.current_item is None or not self.prop_id.get().strip():
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

        if self.gild_on.get() and self.gild_id.get().strip():
            gilded = item.get("netheriteEnchant") or {}
            gilded["id"] = self.gild_id.get().strip()
            gilded["level"] = max(0, min(3, _int(self.gild_lvl, 1)))
            item["netheriteEnchant"] = gilded
        else:
            item.pop("netheriteEnchant", None)

        form = [(v[0].get().strip() or gd.UNSET_ENCHANTMENT, _int(v[1], 0)) for v in self.ench_vars]
        has_enchants = "enchantments" in item or any(eid != gd.UNSET_ENCHANTMENT for eid, _ in form)
        if has_enchants:
            current = [(e.get("id"), int(e.get("level") or 0)) for e in item.get("enchantments") or []]
            if current != form:
                for i, (eid, lvl) in enumerate(form):
                    if lvl == 0:
                        set_enchantment(item, i, eid, 0)
                for i, (eid, lvl) in enumerate(form):
                    if lvl > 0:
                        set_enchantment(item, i, eid, lvl)
            recompute_invested_points(item)

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
        for it in self.save.all_items():
            max_out_enchantments(it)
        self.save.dirty = True
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
        self.status_var.set("JSON принят — нажмите «Применить в игре», чтобы записать сохранение")

    def _on_tab_changed(self, _event=None):
        self._highlight_nav()
        if not self.save:
            return
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
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self._sync_with_disk()

    def hide(self):
        self.commit_forms()
        self.root.withdraw()

    def toggle(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def _poll_hotkey(self):
        try:
            if self.hotkey.pressed():
                self.toggle()
        finally:
            self.root.after(50, self._poll_hotkey)

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
        try:
            if self.root.state() != "withdrawn":
                self._sync_with_disk()
        finally:
            self.root.after(2000, self._watch_disk)

    def on_close(self):
        self.commit_forms()
        if self.save and self.save.dirty and not messagebox.askyesno(
                "Выход", "Есть непримененные изменения. Выйти без применения?", parent=self.root):
            return
        self._icon_thread_stop.set()
        self.wasd.stop()
        self.root.destroy()

    # ------------------------------------------------- game catalog/icons
    def load_catalog(self, force=False):
        """Read the game's paks in the background: full item list, names and icons."""
        paks_dir = cat_mod.find_paks_dir(self.cfg.get("paks_dir", ""), self.cfg.get("game_path", ""))
        if not paks_dir:
            self.catalog_status.set("Файлы игры не найдены — укажите папку …\\Dungeons\\Content\\Paks")
            return
        self._icon_thread_stop.set()
        self._icon_thread_stop = threading.Event()
        stop = self._icon_thread_stop
        cache_dir = os.path.join(game.CACHE_DIR, "catalog")
        if force:
            try:
                os.remove(os.path.join(cache_dir, "catalog.json"))
            except OSError:
                pass
        self.catalog_status.set(f"Файлы игры: чтение {paks_dir}…")

        def work():
            try:
                catalog = cat_mod.GameCatalog.load(paks_dir, cache_dir, [self.cfg.get("pak_key", "")],
                                                   self.cfg.get("language", "ru-RU"))
            except Exception as e:
                message = f"Не удалось прочитать файлы игры: {e}"
                self._ui_queue.put(lambda: self.catalog_status.set(message))
                return
            self._ui_queue.put(lambda: self._on_catalog(catalog))
            catalog.extract_all_icons(stop=stop.is_set)
            if not stop.is_set():
                self._ui_queue.put(self._on_icons_ready)

        threading.Thread(target=work, daemon=True, name="catalog").start()

    def _drain_ui_queue(self):
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._drain_ui_queue)

    def _on_catalog(self, catalog):
        self.catalog = catalog
        self.icons.set_catalog(catalog)
        self.catalog_status.set(
            f"Файлы игры: версия {catalog.version or '?'}, предметов {len(catalog.items)}, "
            f"зачарований {len(catalog.enchantments)}, свойств брони {len(catalog.armor_properties)}, "
            f"язык {catalog.language or '—'}. Иконки извлекаются…")
        self._refresh_after_catalog()

    def _on_icons_ready(self):
        self.icons.set_catalog(self.catalog)
        self.catalog_status.set(self.catalog_status.get().replace("Иконки извлекаются…", "Иконки готовы."))
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

    def _pick_enchantment(self, index):
        if not self.save or self.current_item is None:
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
            elif ident != gd.UNSET_ENCHANTMENT and _int(self.ench_vars[index][1], 0) == 0:
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
    cfg = game.load_config()
    root = tk.Tk()
    app = LoaderApp(root, cfg, initial_save=initial_save)
    if launch if launch is not None else cfg.get("launch_game"):
        app.start_game()
    root.mainloop()
