"""Launcher hub: game library, home carousel and system checks; opens a game's module."""
import glob
import logging
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, art, catalog as cat_mod, chrome, game, shell, theme
from . import wasd as wasd_mod

BRAND = "SecretGear"
BRAND_SUB = "Игровой лаунчер"
ART_DIR = os.path.join(game.CACHE_DIR, "art")

# Games shown in the library. "ready" games open their module, "soon" ones are placeholders.
GAMES = [
    {"id": "mcd", "title": "Minecraft Dungeons", "status": "ready", "badge": "NEW", "hue": (24, 52, 120),
     "text": "Редактор сохранений, все предметы игры с иконками и ходьба на WASD — прямо поверх игры.",
     "tag": "Модуль готов"},
    {"id": "rv", "title": "RV There Yet?", "status": "soon", "hue": (120, 66, 24),
     "text": "Модуль для этой игры пока в разработке.", "tag": "Скоро"},
]

NEWS = [
    ("ⓘ", "31 окт 2026", "Новый лаунчер", "Библиотека игр, экран загрузки и проверка системы."),
    ("✓", "31 окт 2026", "Minecraft Dungeons", "Все предметы с иконками, редактор персонажа и ходьба на WASD."),
    ("ⓘ", "31 окт 2026", "RV There Yet?", "Модуль появится в библиотеке позже."),
]


def cached_item_icons(limit=12):
    """Icons already extracted by the Minecraft Dungeons module (used for card art)."""
    paths = sorted(glob.glob(os.path.join(game.CACHE_DIR, "catalog", "icons", "*.png")))
    return paths[:limit]


class Hub:
    PAGES = [("⌂", "Главная"), ("▤", "Библиотека"), ("⚙", "Система")]
    HOME, LIBRARY, SYSTEM = 0, 1, 2

    def __init__(self, root, cfg, border=None, initial_save=None):
        self.root, self.cfg, self.border = root, cfg, border
        self.initial_save = initial_save
        self.module = None
        self._opening = False  # a module is being opened (ignore repeated clicks)
        self._queue = queue.Queue()
        self.art = {g["id"]: art.cached_game_art(g["id"], ART_DIR) for g in GAMES}
        self.animator = chrome.Animator(root)
        self.alpha = float(cfg.get("overlay_alpha", 0.95))
        self._logo_small = chrome.load_logo(root, 40)
        self._logo_slide = chrome.load_logo(root, 50)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.frame = tk.Frame(root, bg=theme.WINDOW)
        self.frame.pack(fill="both", expand=True)
        self.module_host = tk.Frame(root, bg=theme.WINDOW)
        self._build_sidebar()
        right = tk.Frame(self.frame, bg=theme.WINDOW)
        right.pack(side="left", fill="both", expand=True)
        self._build_header(right)
        panel = theme.RoundedBox(right, bg=theme.PAGE, outline=theme.BORDER, radius=14, pad=6, fill_height=True,
                                 frame_style="Page.TFrame", parent_bg=theme.WINDOW)
        panel.pack(fill="both", expand=True, padx=(0, 8), pady=(0, 8))
        content = ttk.Frame(panel.inner, style="Page.TFrame", padding=(16, 4, 16, 6))
        content.pack(fill="both", expand=True)
        self.progress = shell.TopProgress(content)
        self.progress.pack(fill="x", pady=(0, 10))
        self.notebook = ttk.Notebook(content, style="Hidden.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.cover = tk.Frame(content, bg=theme.PAGE)
        if border:
            border.resize_grip(panel.inner).place(relx=1.0, rely=1.0, anchor="se")
        self._build_home()
        self._build_library()
        self._build_system()
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._highlight())
        self._highlight()
        self.root.after(200, self.run_checks)
        self.root.after(100, self._drain)
        threading.Thread(target=self._download_art, daemon=True, name="art").start()

    def _drain(self):
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._drain)

    def _download_art(self):
        for g in GAMES:
            try:
                found = art.fetch_game_art(g["id"], ART_DIR)
            except Exception:
                logging.exception("art download failed for %s", g["id"])
                continue
            if found != self.art.get(g["id"]):
                self._queue.put(lambda gid=g["id"], f=found: self._on_art(gid, f))

    def _on_art(self, gid, found):
        self.art[gid] = found
        self.carousel.slides = self._slides()
        self.carousel._images.clear()
        self.carousel.show(self.carousel.index, animate=False)
        self._fill_library()
        self._fill_home_games()

    # -------------------------------------------------------------- chrome
    def _build_sidebar(self):
        side = tk.Frame(self.frame, bg=theme.WINDOW, width=212)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=theme.WINDOW)
        brand.pack(fill="x", padx=16, pady=(14, 14))
        self._mark = None
        try:
            from PIL import Image, ImageTk
            with Image.open(chrome.asset_path("mark.png")) as im:
                self._mark = ImageTk.PhotoImage(im.convert("RGBA").resize((30, 30), Image.LANCZOS), master=side)
        except Exception:
            pass
        logo = tk.Label(brand, image=self._mark, bg=theme.WINDOW)
        logo.pack(side="left")
        names = tk.Frame(brand, bg=theme.WINDOW)
        names.pack(side="left", padx=(10, 0))
        tk.Label(names, text=BRAND, bg=theme.WINDOW, fg=theme.FG, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(names, text=BRAND_SUB, bg=theme.WINDOW, fg=theme.DIM, font=("Segoe UI", 9)).pack(anchor="w")
        if self.border:
            for w in (brand, logo, names):
                self.border.drag_handle(w)
        nav = tk.Frame(side, bg=theme.WINDOW)
        nav.pack(fill="x", padx=12)
        self.nav = {}
        for i, (icon, title) in enumerate(self.PAGES):
            item = shell.NavItem(nav, icon, title, lambda i=i: self.show_page(i))
            item.pack(fill="x", pady=1)
            self.nav[i] = item
        tk.Frame(side, bg=theme.BORDER, height=1).pack(fill="x", padx=16, pady=12)
        tk.Label(side, text="Быстрый запуск", bg=theme.WINDOW, fg=theme.DIM, font=("Segoe UI", 9)).pack(
            anchor="w", padx=24, pady=(0, 4))
        quick = tk.Frame(side, bg=theme.WINDOW)
        quick.pack(fill="x", padx=12)
        for g in GAMES:
            if g["status"] == "ready":
                shell.NavItem(quick, "▶", g["title"], lambda gid=g["id"]: self.open_game(gid),
                              bold=True).pack(fill="x", pady=1)
        tk.Label(side, text=f"v{__version__}", bg=theme.WINDOW, fg=theme.DIM, font=("Segoe UI", 8)).pack(
            side="bottom", anchor="w", padx=24, pady=12)

    def _build_header(self, parent):
        bar = tk.Frame(parent, bg=theme.WINDOW)
        bar.pack(fill="x")
        self.title = tk.Label(bar, text="", bg=theme.WINDOW, fg=theme.FG, font=("Segoe UI Semibold", 16))
        self.title.pack(side="left", padx=(14, 18), pady=(14, 12))
        if self.border:
            shell.WindowButtons(bar, self.border.minimize, self.border.toggle_maximize, self.on_close).pack(
                side="right", anchor="n", padx=(8, 6), pady=(6, 0))
            self.border.drag_handle(bar)
            self.border.drag_handle(self.title)

    def _page(self, title):
        tab = ttk.Frame(self.notebook, style="Page.TFrame", padding=(0, 6, 0, 0))
        self.notebook.add(tab, text=title)
        return tab

    def show_page(self, index):
        if self.notebook.index("current") == index:
            return
        self.cover.place(in_=self.notebook, relx=0, rely=0, relwidth=1, relheight=1)
        self.cover.lift()
        self.notebook.select(index)
        self.progress.sweep(280, done=self.cover.place_forget)
        if index == self.SYSTEM:
            self.run_checks()

    def _highlight(self):
        current = self.notebook.index("current")
        for i, item in self.nav.items():
            item.set_active(i == current)
        self.title.configure(text=self.PAGES[current][1])

    # ---------------------------------------------------------------- home
    def _slides(self):
        icons = cached_item_icons()
        slides = []
        for g in GAMES:
            ready = g["status"] == "ready"
            fallback = shell.banner_art(icons if g["id"] == "mcd" else [], g["hue"])
            hero = self.art.get(g["id"], {}).get("hero")
            slides.append({
                "art": shell.image_art(hero, fallback) if hero else fallback,
                "logo": self._logo_slide if g["id"] == "mcd" and not hero else None,
                "title": g["title"], "badge": g.get("badge"), "text": g["text"], "tag": g["tag"],
                "button": ("▶  Открыть" if ready else "Скоро", lambda gid=g["id"]: self.open_game(gid)),
                "note": "Модуль загружен" if ready else "",
            })
        return slides

    def _build_home(self):
        tab = self._page("Главная")
        right = ttk.Frame(tab, style="Page.TFrame", width=270)
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)
        left = ttk.Frame(tab, style="Page.TFrame")
        left.pack(side="left", fill="both", expand=True)
        self.carousel = shell.Carousel(left, self._slides(), width=560, height=300)
        self.carousel.pack(fill="x")
        self.carousel.show(0, animate=False)

        head = ttk.Frame(left, style="Page.TFrame")
        head.pack(fill="x", pady=(14, 8))
        ready = [g for g in GAMES if g["status"] == "ready"]
        tk.Label(head, text="Мои игры", bg=theme.PAGE, fg=theme.FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        shell.pill(head, str(len(ready)), theme.MUTED, "#1d1e25").pack(side="left", padx=8)
        link = tk.Label(head, text="Вся библиотека  ›", bg=theme.PAGE, fg=theme.ACCENT_HOVER, cursor="hand2",
                        font=("Segoe UI", 9, "bold"))
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: self.show_page(self.LIBRARY))
        self.home_games = ttk.Frame(left, style="Page.TFrame")
        self.home_games.pack(fill="x")
        self._fill_home_games()

        news = theme.RoundedBox(right, bg=theme.PAGE, outline=theme.BORDER, radius=12, pad=6, fill_height=True,
                                frame_style="Page.TFrame")
        news.pack(fill="both", expand=True)
        top = ttk.Frame(news.inner, style="Page.TFrame", padding=(10, 8, 10, 6))
        top.pack(fill="x")
        tk.Label(top, text="Новости", bg=theme.PAGE, fg=theme.FG, font=("Segoe UI", 11, "bold")).pack(side="left")
        shell.pill(top, str(len(NEWS)), theme.MUTED, "#1d1e25").pack(side="left", padx=8)
        box = theme.RoundedBox(news.inner, bg=theme.CARD, outline=theme.BORDER, radius=10, pad=4)
        box.pack(fill="x", padx=8, pady=(4, 8))
        for k, (icon, date, title, text) in enumerate(NEWS):
            if k:
                tk.Frame(box.inner, bg=theme.BORDER, height=1).pack(fill="x", padx=6)
            e = ttk.Frame(box.inner, style="Card.TFrame", padding=(10, 8))
            e.pack(fill="x")
            r = ttk.Frame(e, style="Card.TFrame")
            r.pack(fill="x")
            tk.Label(r, text=icon, bg=theme.CARD, fg=theme.GREEN if icon == "✓" else theme.ACCENT_HOVER,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Label(r, text=date, bg=theme.CARD, fg=theme.DIM, font=("Segoe UI", 8)).pack(side="right")
            tk.Label(e, text=title, bg=theme.CARD, fg=theme.FG, font=("Segoe UI", 10, "bold"), wraplength=200,
                     justify="left").pack(anchor="w", pady=(2, 0))
            tk.Label(e, text=text, bg=theme.CARD, fg=theme.MUTED, font=("Segoe UI", 9), wraplength=200,
                     justify="left").pack(anchor="w")

    def _fill_home_games(self):
        for w in self.home_games.winfo_children():
            w.destroy()
        for k, g in enumerate([g for g in GAMES if g["status"] == "ready"]):
            self._game_card(self.home_games, g, small=True).grid(row=0, column=k, sticky="w", padx=(0, 12))

    # ------------------------------------------------------------- library
    def _card_art(self, g, w, h):
        from PIL import Image, ImageDraw, ImageTk
        fallback = shell.banner_art(cached_item_icons() if g["id"] == "mcd" else [], g["hue"])
        card = self.art.get(g["id"], {}).get("card") or self.art.get(g["id"], {}).get("hero")
        art = (shell.image_art(card, fallback, shade=0) if card else fallback)(w, h)
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=10, fill=255)
        base = Image.new("RGB", (w, h), shell._rgb(theme.CARD))
        base.paste(art.convert("RGB"), (0, 0), mask)
        if g["status"] != "ready":
            base = Image.blend(base, Image.new("RGB", (w, h), shell._rgb(theme.CARD)), 0.35)
        return ImageTk.PhotoImage(base, master=self.root)

    def _game_card(self, parent, g, small=False):
        w, h = (250, 120) if small else (290, 150)
        box = theme.RoundedBox(parent, bg=theme.PAGE, outline=theme.PAGE, radius=10, pad=0, frame_style="Page.TFrame")
        canvas = tk.Canvas(box.inner, width=w, height=h, bg=theme.PAGE, highlightthickness=0, bd=0, cursor="hand2")
        canvas.pack()
        photo = self._card_art(g, w, h)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        has_art = bool(self.art.get(g["id"]))
        if has_art:
            pass  # the official capsule already carries the game's logo
        elif g["id"] == "mcd" and self._logo_small:
            canvas.create_image(12, 12, image=self._logo_small, anchor="nw")
        else:
            theme.rounded_rect(canvas, 12, 12, 52, 52, 9, fill="#2b1d10", outline="")
            canvas.create_text(32, 32, text="".join(p[0] for p in g["title"].split()[:2]).upper(), fill=theme.WARN,
                               font=("Segoe UI", 12, "bold"))
        badge = g.get("badge") if g["status"] == "ready" else "СКОРО"
        if badge:
            bw = 8 * len(badge) + 14
            theme.rounded_rect(canvas, w - bw - 10, 10, w - 10, 30, 6,
                               fill=theme.WARN if g["status"] == "ready" else "#2a2c34", outline="")
            canvas.create_text(w - bw / 2 - 10, 20, text=badge, fill="#ffffff", font=("Segoe UI", 8, "bold"))
        info = ttk.Frame(box.inner, style="Page.TFrame", padding=(2, 8, 2, 4))
        info.pack(fill="x")
        texts = ttk.Frame(info, style="Page.TFrame")
        texts.pack(side="left", fill="x", expand=True)
        tk.Label(texts, text=g["title"], bg=theme.PAGE, fg=theme.FG, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ready = g["status"] == "ready"
        tk.Label(texts, text="Доступно — открыть модуль" if ready else "Модуль в разработке", bg=theme.PAGE,
                 fg=theme.ACCENT_HOVER if ready else theme.DIM, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(info, text="▶" if ready else "⏳", bg=theme.PAGE, fg=theme.MUTED, font=("Segoe UI", 11)).pack(
            side="right", padx=4)
        for wdg in (canvas, info, texts, *texts.winfo_children(), *info.winfo_children()):
            wdg.bind("<Button-1>", lambda e, gid=g["id"]: self.open_game(gid))
        return box

    def _build_library(self):
        tab = self._page("Библиотека")
        self.library = ttk.Frame(tab, style="Page.TFrame")
        self.library.pack(fill="x")
        self._fill_library()

    def _fill_library(self):
        for w in self.library.winfo_children():
            w.destroy()
        for k, g in enumerate(GAMES):
            self._game_card(self.library, g).grid(row=k // 3, column=k % 3, sticky="nw", padx=(0, 16), pady=(0, 16))

    # -------------------------------------------------------------- system
    def _build_system(self):
        tab = self._page("Система")
        summary = theme.RoundedBox(tab, bg=theme.CARD, outline=theme.BORDER, radius=12, pad=6)
        summary.pack(fill="x")
        inner = ttk.Frame(summary.inner, style="Card.TFrame", padding=(10, 8))
        inner.pack(fill="x")
        self.sys_icon = tk.Label(inner, text="✓", width=3, font=("Segoe UI", 14, "bold"), bg="#12301f",
                                 fg=theme.GREEN, pady=6)
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

    def checks(self):
        out = []
        paks = cat_mod.find_paks_dir(self.cfg.get("paks_dir", ""), self.cfg.get("game_path", ""))
        out.append(("Minecraft Dungeons", bool(paks), paks or "Игра не найдена — укажите папку в модуле игры",
                    "Открыть модуль" if not paks else "", lambda: self.open_game("mcd")))
        if game.IS_WINDOWS:
            drv = wasd_mod.driver_installed()
            out.append(("Драйвер геймпада", drv, "ViGEmBus установлен" if drv else "Нужен для ходьбы на WASD",
                        "" if drv else "Установить драйвер", self._install_driver))
        out.append(("Горячая клавиша", game.IS_WINDOWS, f"{self.cfg.get('hotkey', 'F8')} — окно поверх игры"
                    if game.IS_WINDOWS else "Работает только в Windows", "", None))
        try:
            os.makedirs(game.APP_DIR, exist_ok=True)
            writable = os.access(game.APP_DIR, os.W_OK)
        except OSError:
            writable = False
        out.append(("Папка настроек", writable, game.APP_DIR, "", None))
        out.append(("Версия лаунчера", None, f"v{__version__}", "", None))
        out.append(("Игра запущена", None, "Minecraft Dungeons запущена" if game.is_game_running()
                    else "Сейчас ни одна игра не запущена", "", None))
        return out

    def run_checks(self):
        checks = self.checks()
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
        self.sys_good.configure(text=f"{sum(1 for c in checks if c[1])} пройдено")
        self.sys_bad.configure(text=f"  ·  {len(issues)} проблем(ы)" if issues else "")
        if issues:
            self.sys_icon.configure(text="✕", bg="#2a1416", fg=theme.RED)
            self.sys_title.configure(text="Найдены проблемы")
            self.sys_sub.configure(text=f"{len(issues)} проблем(ы) требуют внимания.")
        else:
            self.sys_icon.configure(text="✓", bg="#12301f", fg=theme.GREEN)
            self.sys_title.configure(text="Всё в порядке")
            self.sys_sub.configure(text="Лаунчер готов к работе.")
        self.sys_fix.enabled = any(c[4] for c in issues)
        self.sys_fix.draw()
        self.nav[self.SYSTEM].set_badge("⚠" if issues else None)

    def fix_all(self):
        for _t, ok, _d, _h, fix in getattr(self, "_checks", []):
            if ok is False and fix:
                fix()
                break  # one fix at a time: some open dialogs or switch to a module
        self.root.after(600, self.run_checks)

    def _install_driver(self):
        installer = wasd_mod.driver_installer()
        if installer and messagebox.askyesno("Драйвер геймпада", "Установить драйвер ViGEmBus для ходьбы на WASD?\n"
                                             "Windows попросит права администратора.", parent=self.root):
            os.startfile(installer)  # noqa: S606 - bundled msi
        elif not installer:
            messagebox.showinfo("Драйвер геймпада", "Установщик ViGEmBus не найден в сборке.", parent=self.root)

    # -------------------------------------------------------------- modules
    def open_game(self, gid):
        g = next((x for x in GAMES if x["id"] == gid), None)
        if not g:
            return
        if g["status"] != "ready":
            messagebox.showinfo(g["title"], "Модуль для этой игры пока в разработке.", parent=self.root)
            return
        if self._opening or self.module_host.winfo_ismapped():
            return
        self._opening = True
        view = shell.LoadingView(self.root, title=g["title"].upper(), status="Загрузка модуля")
        view.place(relx=0, rely=0, relwidth=1, relheight=1)
        view.raise_view()
        started = time.perf_counter()

        def build():
            if self.module is None:
                from .overlay import LoaderApp
                try:
                    self.module = LoaderApp(self.root, self.cfg, initial_save=self.initial_save, loading=view,
                                            border=self.border, host=self.module_host, on_back=self.back_to_hub)
                except Exception as e:
                    logging.exception("module %s failed", gid)
                    self._opening = False
                    view.stop()
                    view.destroy()
                    messagebox.showerror(g["title"], f"Не удалось загрузить модуль: {e}", parent=self.root)
                    return
            view.set_status("Готово")
            view.raise_view()
            wait = max(0, int((2.2 - (time.perf_counter() - started)) * 1000))
            self.root.after(wait, swap)

        def swap():
            def flip():
                self.frame.pack_forget()
                self.module_host.pack(fill="both", expand=True)
                view.stop()
                view.destroy()
                self._opening = False
                self.root.protocol("WM_DELETE_WINDOW", self.on_close)
                chrome.fade(self.animator, self.root, 0.0, self.alpha, 240)
            chrome.fade(self.animator, self.root, float(self.root.attributes("-alpha")), 0.0, 150, done=flip)
        self.root.after(700, build)

    def back_to_hub(self):
        def flip():
            self.module_host.pack_forget()
            self.frame.pack(fill="both", expand=True)
            self.carousel.slides = self._slides()
            self.carousel._images.clear()
            self.carousel.show(self.carousel.index, animate=False)
            self.run_checks()
            chrome.fade(self.animator, self.root, 0.0, self.alpha, 220)
        chrome.fade(self.animator, self.root, float(self.root.attributes("-alpha")), 0.0, 140, done=flip)

    def on_close(self):
        if self.module:
            self.module.on_close()  # asks about unapplied edits, then destroys the window
        else:
            self.root.destroy()


def run(initial_save=None, launch=None):
    game.setup_logging()
    cfg = game.load_config()
    root = tk.Tk()
    root.configure(bg=theme.WINDOW)
    root.title(BRAND)
    chrome.set_window_icon(root)
    theme.apply_theme(root)
    root.attributes("-topmost", True)
    w, h = min(1280, root.winfo_screenwidth() - 40), min(800, root.winfo_screenheight() - 60)
    root.geometry(f"{w}x{h}+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 2}")
    border = shell.Borderless(root)
    loading = shell.LoadingView(root, title=BRAND, status="Запуск")
    loading.place(relx=0, rely=0, relwidth=1, relheight=1)
    root.update()
    started = time.perf_counter()
    hub = Hub(root, cfg, border=border, initial_save=initial_save)
    loading.raise_view()
    loading.set_status("Готово")

    def reveal():
        def swap():
            loading.stop()
            loading.destroy()
            chrome.fade(hub.animator, root, 0.0, hub.alpha, 260)
            if initial_save or launch:
                hub.open_game("mcd")
                if launch:
                    root.after(3500, lambda: hub.module and hub.module.launch_with_animation())
        chrome.fade(hub.animator, root, 1.0, 0.0, 160, done=swap)
    root.after(max(0, int((2.6 - (time.perf_counter() - started)) * 1000)), reveal)
    root.mainloop()
