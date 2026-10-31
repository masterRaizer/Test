"""In-game overlay: a topmost editor window toggled by a hotkey over the running game."""
import json
import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import game, gamedata as gd
from .savefile import (SaveFile, describe_item, find_saves, item_level, max_out_enchantments,
                       read_profile, recompute_invested_points, set_enchantment, set_item_level)

BG, PANEL, FG, MUTED, ACCENT, WARN = "#1e1f24", "#2a2c33", "#e8e8e8", "#9aa0a6", "#3fa66b", "#d9a441"
NO_SLOT = "(не надет)"
LOCATIONS = {"inventory": "Инвентарь", "chest": "Сундук"}
FILTERS = ["Все", "Надетые", "Инвентарь", "Сундук"]


def _int(var, default=0):
    try:
        return int(float(str(var.get()).replace(" ", "")))
    except (ValueError, tk.TclError):
        return default


def apply_dark_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=BG)
    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, bordercolor="#3a3d45",
                    lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, arrowcolor=FG, insertcolor=FG)
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 6))
    style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
    style.configure("TButton", background=PANEL, padding=(10, 4))
    style.map("TButton", background=[("active", "#353842")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", "#4cbb7c")])
    style.configure("TLabelframe", background=BG)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Warn.TLabel", foreground=WARN)
    style.configure("Big.TLabel", font=("Segoe UI", 13, "bold"))
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=24)
    style.configure("Treeview.Heading", background="#33363e", foreground=FG)
    style.map("Treeview", background=[("selected", "#3d5a80")])
    style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", FG)


class LoaderApp:
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

        root.title("MCD Loader — Minecraft Dungeons")
        root.geometry("1280x760")
        root.minsize(1100, 640)
        root.attributes("-topmost", True)
        try:
            root.attributes("-alpha", float(cfg.get("overlay_alpha", 0.95)))
        except tk.TclError:
            pass
        apply_dark_theme(root)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<Control-s>", lambda e: self.apply_to_game())
        root.bind("<Escape>", lambda e: self.hide() if self.hotkey.available else None)

        self._build_topbar()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._build_character_tab()
        self._build_inventory_tab()
        self._build_json_tab()
        self._build_settings_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.refresh_save_list(select=initial_save or cfg.get("last_save"))
        self.root.after(50, self._poll_hotkey)
        self.root.after(2000, self._watch_disk)

    # ------------------------------------------------------------------ UI
    def _build_topbar(self):
        bar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="Персонаж:").pack(side="left")
        self.save_var = tk.StringVar()
        self.save_box = ttk.Combobox(bar, textvariable=self.save_var, state="readonly", width=48)
        self.save_box.pack(side="left", padx=6)
        self.save_box.bind("<<ComboboxSelected>>", lambda e: self.open_selected_save())
        ttk.Button(bar, text="⟳ Обновить", command=self.reload_save).pack(side="left", padx=2)
        ttk.Button(bar, text="Открыть .dat…", command=self.browse_save).pack(side="left", padx=2)
        ttk.Button(bar, text="✔ Применить в игре  (Ctrl+S)", style="Accent.TButton",
                   command=self.apply_to_game).pack(side="left", padx=8)
        ttk.Button(bar, text="▶ Запустить игру", command=self.start_game).pack(side="right")
        hint = f"{self.cfg.get('hotkey', 'F8')} — показать/скрыть" if self.hotkey.available else ""
        ttk.Label(bar, text=hint, style="Muted.TLabel").pack(side="right", padx=10)

        self.status_var = tk.StringVar(value="Выберите персонажа")
        self.status = ttk.Label(self.root, textvariable=self.status_var, style="Muted.TLabel", padding=(10, 0, 10, 6))
        self.status.pack(fill="x")

    def _labeled(self, parent, row, text, widget):
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
        widget.grid(row=row, column=1, sticky="we", pady=4)
        return widget

    def _build_character_tab(self):
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Персонаж")
        form = ttk.Frame(tab)
        form.pack(side="left", anchor="n")

        self.name_var = tk.StringVar()
        self.level_var = tk.StringVar()
        self.xp_var = tk.StringVar()
        self.currency_vars = {k: tk.StringVar() for k in gd.CURRENCIES}
        self.difficulty_var = tk.StringVar()
        self.threat_var = tk.StringVar()

        ttk.Label(form, textvariable=self.name_var, style="Big.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self._labeled(form, 1, "Уровень", ttk.Spinbox(form, from_=1, to=10000, textvariable=self.level_var, width=18))
        self._labeled(form, 2, "Опыт (XP)", ttk.Entry(form, textvariable=self.xp_var, width=20))
        for row, (key, title) in enumerate(gd.CURRENCIES.items(), start=3):
            self._labeled(form, row, title, ttk.Entry(form, textvariable=self.currency_vars[key], width=20))
        self._labeled(form, 6, "Открытая сложность",
                      ttk.Combobox(form, textvariable=self.difficulty_var, state="readonly", width=18,
                                   values=[f"{d} — {gd.DIFFICULTY_NAMES[d]}" for d in gd.DIFFICULTIES]))
        self._labeled(form, 7, "Уровень угрозы", ttk.Combobox(form, textvariable=self.threat_var, values=gd.THREAT_LEVELS,
                                                              state="readonly", width=18))
        self.level_var.trace_add("write", self._on_level_changed)
        self.xp_var.trace_add("write", self._on_xp_changed)

        info = ttk.LabelFrame(tab, text="Сводка", padding=12)
        info.pack(side="left", anchor="n", padx=24)
        self.power_var = tk.StringVar()
        self.points_var = tk.StringVar()
        self.items_count_var = tk.StringVar()
        for var in (self.power_var, self.points_var, self.items_count_var):
            ttk.Label(info, textvariable=var).pack(anchor="w", pady=3)

        quick = ttk.LabelFrame(tab, text="Быстрые действия", padding=12)
        quick.pack(side="left", anchor="n")
        ttk.Button(quick, text="Изумруды / золото = 999 999", command=self._quick_rich).pack(fill="x", pady=2)
        ttk.Button(quick, text="Открыть все сложности и угрозы", command=self._quick_unlock).pack(fill="x", pady=2)
        ttk.Button(quick, text="Уровень персонажа = 100", command=lambda: self.level_var.set("100")).pack(fill="x", pady=2)

    def _build_inventory_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="Инвентарь")
        self._build_item_editor(tab)
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        actions = ttk.Frame(left)
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        for i, (text, cmd) in enumerate((("＋ Новый", self.add_item), ("⧉ Дублировать", self.duplicate_item),
                                         ("✕ Удалить", self.delete_item), ("⇄ Сундук/инвентарь", self.move_item),
                                         ("Все: уровень…", self.set_all_levels),
                                         ("Все: зачар. ур. 3", self.max_all_enchantments))):
            ttk.Button(actions, text=text, command=cmd).grid(row=i // 3, column=i % 3, sticky="we", padx=2, pady=2)
            actions.columnconfigure(i % 3, weight=1)

        top = ttk.Frame(left)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Показать:").pack(side="left")
        self.filter_var = tk.StringVar(value=FILTERS[0])
        flt = ttk.Combobox(top, textvariable=self.filter_var, values=FILTERS, state="readonly", width=12)
        flt.pack(side="left", padx=6)
        flt.bind("<<ComboboxSelected>>", lambda e: self.refresh_items())

        cols = ("loc", "slot", "type", "lvl", "rarity", "ench")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for col, title, width in zip(cols, ("Где", "Слот/индекс", "Тип", "Ур.", "Редкость", "Зачарования"),
                                     (85, 95, 150, 40, 70, 200)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col in ("type", "ench"))
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_item_selected)

    def _build_item_editor(self, parent):
        ed = ttk.LabelFrame(parent, text="Предмет", padding=10)
        ed.pack(side="right", fill="y")
        self.editor = ed
        col_a = ttk.Frame(ed)
        col_a.pack(side="left", fill="y", anchor="n")
        col_b = ttk.Frame(ed)
        col_b.pack(side="left", fill="y", anchor="n", padx=(10, 0))
        self.it_type = tk.StringVar()
        self.it_level = tk.StringVar()
        self.it_rarity = tk.StringVar()
        self.it_slot = tk.StringVar()
        self.it_upgraded = tk.BooleanVar()
        self.it_gifted = tk.BooleanVar()
        self.it_new = tk.BooleanVar()

        grid = ttk.Frame(col_a)
        grid.pack(fill="x")
        self.type_box = self._labeled(grid, 0, "Тип (ID)", ttk.Combobox(grid, textvariable=self.it_type, width=22))
        self._labeled(grid, 1, "Уровень силы", ttk.Spinbox(grid, from_=0, to=10000, textvariable=self.it_level, width=10))
        self._labeled(grid, 2, "Редкость", ttk.Combobox(grid, textvariable=self.it_rarity, values=gd.RARITIES, state="readonly", width=12))
        self._labeled(grid, 3, "Слот", ttk.Combobox(grid, textvariable=self.it_slot, values=[NO_SLOT] + gd.EQUIPMENT_SLOTS,
                                                    state="readonly", width=14))
        flags = ttk.Frame(col_a)
        flags.pack(fill="x", pady=4)
        for text, var in (("Улучшен (алмаз)", self.it_upgraded), ("Подарок", self.it_gifted), ("Новый", self.it_new)):
            ttk.Checkbutton(flags, text=text, variable=var).pack(anchor="w")

        ench = ttk.Frame(col_b)
        ench.pack(fill="x")
        self.ench_vars = []
        self.ench_boxes = []
        for s in range(3):
            frame = ttk.LabelFrame(ench, text=f"Зачарования, слот {s + 1}", padding=4)
            frame.grid(row=s, column=0, sticky="we", pady=2)
            for k in range(3):
                id_var, lvl_var = tk.StringVar(), tk.StringVar(value="0")
                box = ttk.Combobox(frame, textvariable=id_var, width=20)
                box.grid(row=k, column=0, padx=2, pady=1)
                ttk.Spinbox(frame, from_=0, to=3, textvariable=lvl_var, width=4).grid(row=k, column=1, padx=2)
                self.ench_vars.append((id_var, lvl_var))
                self.ench_boxes.append(box)

        gild = ttk.LabelFrame(col_a, text="Позолоченное (незерит)", padding=4)
        gild.pack(fill="x", pady=4)
        self.gild_on = tk.BooleanVar()
        self.gild_id = tk.StringVar()
        self.gild_lvl = tk.StringVar(value="1")
        ttk.Checkbutton(gild, variable=self.gild_on).pack(side="left")
        self.gild_box = ttk.Combobox(gild, textvariable=self.gild_id, width=18)
        self.gild_box.pack(side="left", padx=2)
        ttk.Spinbox(gild, from_=0, to=3, textvariable=self.gild_lvl, width=4).pack(side="left")

        props = ttk.LabelFrame(col_a, text="Свойства брони", padding=4)
        props.pack(fill="x", pady=4)
        self.props_list = tk.Listbox(props, height=3, bg=PANEL, fg=FG, highlightthickness=0, selectbackground="#3d5a80")
        self.props_list.pack(fill="x")
        row = ttk.Frame(props)
        row.pack(fill="x", pady=2)
        self.prop_id = tk.StringVar(value=gd.DEFAULT_ARMOR_PROPERTY)
        self.prop_rarity = tk.StringVar(value="Common")
        self.prop_box = ttk.Combobox(row, textvariable=self.prop_id, width=15)
        self.prop_box.pack(side="left")
        ttk.Combobox(row, textvariable=self.prop_rarity, values=gd.RARITIES, state="readonly", width=8).pack(side="left", padx=2)
        ttk.Button(row, text="+", width=2, command=self._add_prop).pack(side="left")
        ttk.Button(row, text="−", width=2, command=self._remove_prop).pack(side="left")

        ttk.Button(col_b, text="Сохранить предмет", style="Accent.TButton",
                   command=self.commit_item).pack(fill="x", pady=(8, 0))

    def _build_json_tab(self):
        tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(tab, text="JSON")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Принять JSON в редактор", command=self.apply_json_text).pack(side="left")
        ttk.Button(bar, text="Сбросить текст", command=self.refresh_json).pack(side="left", padx=6)
        ttk.Label(bar, text="Полный доступ к данным сохранения. После правки нажмите «Принять», затем «Применить в игре».",
                  style="Muted.TLabel").pack(side="left", padx=10)
        self.json_text = tk.Text(tab, bg=PANEL, fg=FG, insertbackground=FG, wrap="none", undo=True,
                                 font=("Consolas", 10), relief="flat")
        self.json_text.pack(fill="both", expand=True)

    def _build_settings_tab(self):
        tab = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(tab, text="Настройки")
        self.set_hotkey = tk.StringVar(value=self.cfg.get("hotkey", "F8"))
        self.set_game = tk.StringVar(value=self.cfg.get("game_path", ""))
        self.set_launch = tk.BooleanVar(value=self.cfg.get("launch_game", False))
        self.set_backup = tk.BooleanVar(value=self.cfg.get("backup_on_apply", True))
        self.set_alpha = tk.DoubleVar(value=self.cfg.get("overlay_alpha", 0.95))
        self._labeled(tab, 0, "Горячая клавиша", ttk.Combobox(tab, textvariable=self.set_hotkey, values=list(game.VK_CODES),
                                                              state="readonly", width=12))
        path_row = ttk.Frame(tab)
        ttk.Entry(path_row, textvariable=self.set_game, width=60).pack(side="left")
        ttk.Button(path_row, text="…", width=3, command=self._browse_game).pack(side="left", padx=4)
        self._labeled(tab, 1, "Путь к Dungeons.exe", path_row)
        self._labeled(tab, 2, "", ttk.Checkbutton(tab, text="Запускать игру вместе с загрузчиком", variable=self.set_launch))
        self._labeled(tab, 3, "", ttk.Checkbutton(tab, text="Резервная копия перед каждым применением", variable=self.set_backup))
        self._labeled(tab, 4, "Прозрачность окна", ttk.Scale(tab, from_=0.5, to=1.0, variable=self.set_alpha,
                                                              command=self._preview_alpha))
        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=2, sticky="w", pady=(16, 0))
        ttk.Button(buttons, text="Сохранить настройки", style="Accent.TButton", command=self.save_settings).pack(side="left")
        ttk.Button(buttons, text="Восстановить из бэкапа…", command=self.restore_backup).pack(side="left", padx=6)
        ttk.Button(buttons, text="Экспорт JSON…", command=self.export_json).pack(side="left")
        ttk.Button(buttons, text="Импорт JSON…", command=self.import_json).pack(side="left", padx=6)
        ttk.Label(tab, text=f"Бэкапы: {game.BACKUP_DIR}", style="Muted.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=12)
        ttk.Label(tab, style="Muted.TLabel", justify="left", text=(
            "Как применить изменения в игре:\n"
            "  1. Выйдите из миссии в главное меню (игра сохранит персонажа).\n"
            "  2. Нажмите горячую клавишу, отредактируйте и нажмите «Применить в игре».\n"
            "  3. Выберите персонажа заново — игра загрузит изменённое сохранение.\n"
            "Для работы поверх игры включите в настройках игры режим «В окне» или «Полноэкранный в окне»."
        )).grid(row=7, column=0, columnspan=2, sticky="w")

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
        types = sorted(self.save.known_item_types(), key=str.lower)
        self.type_box["values"] = types
        enchants = [gd.UNSET_ENCHANTMENT] + sorted(self.save.known_enchantments(), key=str.lower)
        for box in self.ench_boxes:
            box["values"] = enchants
        self.gild_box["values"] = enchants[1:]
        self.prop_box["values"] = sorted(self.save.known_armor_properties(), key=str.lower)

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
            slot = item.get("equipmentSlot") or f"#{item.get('inventoryIndex', '')}"
            iid = self.tree.insert("", "end", values=(LOCATIONS[loc], slot, item.get("type", "?"), item_level(item),
                                                      item.get("rarity", ""), describe_item(item)))
            self.items_by_iid[iid] = item
            if item is self.current_item:
                selected_iid = iid
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
        self.editor.configure(text=f"Предмет: {item.get('type', '—')}")

    def _refresh_props(self):
        self.props_list.delete(0, "end")
        for p in self.armor_props:
            self.props_list.insert("end", f"{p.get('id')}  ({p.get('rarity', 'Common')})")

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
        self._select(self.save.new_item(gd.DEFAULT_ITEM_FOR_SLOT["MeleeGear"]))
        self.type_box.focus_set()

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
        try:
            self.root.attributes("-alpha", float(self.set_alpha.get()))
        except tk.TclError:
            pass

    def save_settings(self):
        self.cfg.update(hotkey=self.set_hotkey.get(), game_path=self.set_game.get().strip(),
                        launch_game=self.set_launch.get(), backup_on_apply=self.set_backup.get(),
                        overlay_alpha=round(float(self.set_alpha.get()), 2))
        game.save_config(self.cfg)
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
        self.root.destroy()


def run(initial_save=None, launch=None):
    cfg = game.load_config()
    root = tk.Tk()
    app = LoaderApp(root, cfg, initial_save=initial_save)
    if launch if launch is not None else cfg.get("launch_game"):
        app.start_game()
    root.mainloop()
