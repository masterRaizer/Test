"""Icon cache and searchable pickers (items / enchantments) for the overlay."""
import tkinter as tk
from tkinter import ttk

from . import catalog as cat_mod, gamedata as gd, theme

BG, PANEL, FG, MUTED = theme.PAGE, theme.INPUT, theme.FG, theme.MUTED
RARITY_COLORS = {"Common": "#e8e8e8", "Rare": "#4fc3f7", "Unique": "#ffb74d"}
ALL = "Все"


class IconCache:
    """PhotoImages for item/enchantment icons; icons not yet extracted show a placeholder."""

    def __init__(self, root):
        self.root = root
        self.catalog = None
        self._images = {}
        self._placeholders = {}

    def set_catalog(self, catalog):
        self.catalog = catalog
        self._images.clear()

    def placeholder(self, size):
        if size not in self._placeholders:
            img = tk.PhotoImage(master=self.root, width=size, height=size)
            img.put(theme.INPUT, to=(2, 2, size - 2, size - 2))
            self._placeholders[size] = img
        return self._placeholders[size]

    def get(self, kind, ident, size=24):
        key = (kind, ident, size)
        if key in self._images:
            return self._images[key]
        path = self.catalog.icon_file(kind, ident, extract=False) if self.catalog and ident else None
        if not path:
            return self.placeholder(size)
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as img:
                img = img.convert("RGBA")
                img.thumbnail((size, size), Image.LANCZOS)
                canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
                photo = ImageTk.PhotoImage(canvas, master=self.root)
        except Exception:
            return self.placeholder(size)
        self._images[key] = photo
        return photo


def item_rows(catalog, extra_ids):
    """Picker rows for every catalog item plus IDs only known from the save."""
    rows, seen = [], set()
    if catalog and catalog.loaded:
        for ident, info in catalog.items.items():
            label = cat_mod.CATEGORIES.get(info["category"], "Прочее")
            rows.append((ident, catalog.item_name(ident), label, label, "item", catalog.item_description(ident)))
            seen.add(ident)
    for ident in extra_ids:
        if ident and ident not in seen:
            name = catalog.item_name(ident) if catalog else ident
            rows.append((ident, name, "Прочее", "Прочее", "item", "Найден в сохранении"))
    order = {v: i for i, v in enumerate(list(cat_mod.CATEGORIES.values()) + ["Прочее"])}
    rows.sort(key=lambda r: (order[r[3]], r[1].lower()))
    return rows


class _Picker(tk.Toplevel):
    """Base: search box + filter + icon list + details pane."""

    def __init__(self, parent, title, filters, icons, on_pick, keep_open=False, width=760, height=560):
        super().__init__(parent, bg=BG, padx=10, pady=10)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.attributes("-topmost", True)
        self.transient(parent)
        parent.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 40}+{parent.winfo_rooty() + 40}")
        self.configure(padx=14, pady=12)
        self.icons = icons
        self.on_pick = on_pick
        self.keep_open = keep_open
        self.rows = []
        self.by_iid = {}

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text=title, style="Section.TLabel").pack(side="left", padx=(0, 16))
        ttk.Label(top, text="⌕").pack(side="left")
        self.search = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.search, width=30)
        entry.pack(side="left", padx=6)
        entry.focus_set()
        self.filter = tk.StringVar(value=filters[0])
        box = ttk.Combobox(top, textvariable=self.filter, values=filters, state="readonly", width=16)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.search.trace_add("write", lambda *_: self.refresh())
        self.count_var = tk.StringVar()
        ttk.Label(top, textvariable=self.count_var, style="Muted.TLabel").pack(side="right")

        self.bottom = ttk.Frame(self)
        self.bottom.pack(side="bottom", fill="x", pady=(8, 0))
        self.details = ttk.Label(self, style="Muted.TLabel", wraplength=width - 40, justify="left")
        self.details.pack(side="bottom", fill="x", pady=(6, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(8, 0))
        style = ttk.Style(self)
        style.configure("Picker.Treeview", rowheight=36)
        self.tree = ttk.Treeview(body, columns=("id", "kind"), show="tree headings", style="Picker.Treeview",
                                 selectmode="browse")
        self.tree.heading("#0", text="Название")
        self.tree.heading("id", text="ID")
        self.tree.heading("kind", text="Тип")
        self.tree.column("#0", width=300)
        self.tree.column("id", width=220)
        self.tree.column("kind", width=120, stretch=False)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_details())
        self.tree.bind("<Double-1>", lambda e: self.pick())
        self.bind("<Return>", lambda e: self.pick())
        self.bind("<Escape>", lambda e: self.destroy())

    # rows: (ident, name, kind_label, filter_key, icon_kind, description)
    def set_rows(self, rows):
        self.rows = rows
        self.refresh()

    def refresh(self):
        needle = self.search.get().strip().lower()
        flt = self.filter.get()
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        shown = 0
        for row in self.rows:
            ident, name, kind_label, filter_key, icon_kind, _desc = row
            if not self.matches_filter(flt, filter_key):
                continue
            if needle and needle not in name.lower() and needle not in ident.lower():
                continue
            iid = self.tree.insert("", "end", text="  " + name, values=(ident, kind_label),
                                   image=self.icons.get(icon_kind, ident, 32))
            self.by_iid[iid] = row
            shown += 1
        self.count_var.set(f"{shown} из {len(self.rows)}")
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])

    def matches_filter(self, flt, key):
        return flt == ALL or flt == key

    def selected(self):
        sel = self.tree.selection()
        return self.by_iid.get(sel[0]) if sel else None

    def _show_details(self):
        row = self.selected()
        self.details.configure(text=(f"{row[1]}  [{row[0]}]\n{row[5]}" if row else ""))

    def pick(self):
        row = self.selected()
        if not row:
            return
        self.on_pick(row[0], self)
        if not self.keep_open:
            self.destroy()


class ItemPicker(_Picker):
    """Every item of the game, with options for where and how to add it."""

    def __init__(self, parent, icons, catalog, extra_ids, on_add):
        filters = [ALL] + list(cat_mod.CATEGORIES.values()) + ["Прочее"]
        super().__init__(parent, "Добавить предмет", filters, icons, self._add, keep_open=True, width=820, height=640)
        self.on_add = on_add
        self.catalog = catalog
        self.dest = tk.StringVar(value="inventory")
        self.level = tk.StringVar(value="100")
        self.count = tk.StringVar(value="1")
        self.equip = tk.BooleanVar(value=False)
        self.max_rarity = tk.BooleanVar(value=True)
        b = self.bottom
        ttk.Button(b, text="Добавить", style="Accent.TButton", command=self.pick).pack(side="right", fill="y")
        row1, row2 = ttk.Frame(b), ttk.Frame(b)
        row1.pack(fill="x")
        row2.pack(fill="x", pady=(4, 0))
        ttk.Radiobutton(row1, text="В инвентарь", variable=self.dest, value="inventory").pack(side="left")
        ttk.Radiobutton(row1, text="В сундук", variable=self.dest, value="chest").pack(side="left", padx=(6, 12))
        ttk.Checkbutton(row1, text="Сразу надеть", variable=self.equip).pack(side="left")
        ttk.Label(row2, text="Уровень:").pack(side="left")
        ttk.Spinbox(row2, from_=1, to=10000, textvariable=self.level, width=6).pack(side="left", padx=4)
        ttk.Label(row2, text="Кол-во:").pack(side="left")
        ttk.Spinbox(row2, from_=1, to=100, textvariable=self.count, width=4).pack(side="left", padx=4)
        ttk.Checkbutton(row2, text="Уникальным — редкость Unique", variable=self.max_rarity).pack(side="left", padx=6)

        self.set_rows(item_rows(catalog, extra_ids))

    def _add(self, ident, _picker):
        try:
            level = max(1, int(self.level.get()))
            count = max(1, min(100, int(self.count.get())))
        except ValueError:
            level, count = 1, 1
        category = self.catalog.category(ident) if self.catalog else None
        rarity = "Unique" if self.max_rarity.get() and "_unique" in ident.lower() else "Common"
        self.on_add(ident, category=category, in_chest=self.dest.get() == "chest", level=level, count=count,
                    equip=self.equip.get(), rarity=rarity)
        self.details.configure(text=f"Добавлено: {self.catalog.item_name(ident) if self.catalog else ident} × {count}")


class ItemTypePicker(_Picker):
    """Pick an item ID to change the type of an existing item."""

    def __init__(self, parent, icons, catalog, extra_ids, on_pick):
        filters = [ALL] + list(cat_mod.CATEGORIES.values()) + ["Прочее"]
        super().__init__(parent, "Тип предмета", filters, icons, lambda i, p: on_pick(i), width=760, height=600)
        ttk.Button(self.bottom, text="Выбрать", style="Accent.TButton", command=self.pick).pack(side="right")
        self.set_rows(item_rows(catalog, extra_ids))


class EnchantmentPicker(_Picker):
    def __init__(self, parent, icons, catalog, known_ids, slot, on_pick, allow_unset=True):
        suitable = "Подходящие"
        super().__init__(parent, "Выбор зачарования", [suitable, ALL], icons, lambda i, p: on_pick(i),
                         width=700, height=560)
        self.suitable = gd.enchantments_for_slot(slot) if slot in gd.GEAR_SLOTS else None
        ids = set(known_ids)
        if catalog and catalog.loaded:
            ids.update(catalog.enchantments)
        rows = []
        if allow_unset:
            rows.append((gd.UNSET_ENCHANTMENT, "— пусто —", "", "", "enchantment", "Убрать зачарование из этой ячейки"))
        in_game = set(catalog.enchantments) if catalog and catalog.loaded else set()
        for ident in sorted(ids, key=lambda i: (i not in in_game,
                                                (catalog.enchantment_name(i) if catalog else i).lower())):
            if ident == gd.UNSET_ENCHANTMENT:
                continue
            name = catalog.enchantment_name(ident) if catalog else ident
            kind = "Мощное" if ident in gd.POWERFUL_ENCHANTMENTS else ""
            desc = catalog.enchantment_description(ident) if catalog else ""
            rows.append((ident, name, kind, "", "enchantment", desc))
        if not self.suitable:
            self.filter.set(ALL)
        ttk.Button(self.bottom, text="Выбрать", style="Accent.TButton", command=self.pick).pack(side="right")
        self.set_rows(rows)

    def matches_filter(self, flt, key):
        return True

    def refresh(self):
        # "Подходящие" keeps enchantments known to fit the item's slot (unknown ones stay visible in "Все").
        flt = self.filter.get()
        if flt != ALL and getattr(self, "suitable", None):
            rows, self.rows = self.rows, [r for r in self.rows if r[0] in self.suitable or r[0] == gd.UNSET_ENCHANTMENT]
            try:
                super().refresh()
            finally:
                self.rows = rows
        else:
            super().refresh()
