"""Visual theme: dark navy palette, cards, sidebar navigation and toggle switches."""
import tkinter as tk
from tkinter import ttk

WINDOW = "#0a0a0d"      # window frame + sidebar
PAGE = "#0e0f13"        # content panel
CARD = "#131419"        # cards
CARD_HEAD = "#16171d"   # card title strip
BORDER = "#1e2027"
INPUT = "#1a1b22"
FG = "#f1f2f5"
MUTED = "#8a8d97"
DIM = "#5d606b"
ACCENT = "#2d64f0"
ACCENT_HOVER = "#4479ff"
WARN = "#f59e0b"
GREEN = "#3ec46d"
RED = "#e5484d"
SELECT = "#1d2a4d"
NAV_ACTIVE = "#1a1b21"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI Semibold", 17)
FONT_SECTION = ("Segoe UI", 11, "bold")


def apply_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=WINDOW)
    root.option_add("*Font", FONT)
    style.configure(".", background=PAGE, foreground=FG, fieldbackground=INPUT, bordercolor=BORDER,
                    lightcolor=PAGE, darkcolor=PAGE, troughcolor=INPUT, arrowcolor=FG, insertcolor=FG,
                    selectbackground=SELECT, selectforeground=FG, font=FONT, focuscolor=ACCENT)
    # Pages are driven by the sidebar, so notebook tabs are hidden.
    style.layout("Hidden.TNotebook.Tab", [])
    style.configure("Hidden.TNotebook", background=PAGE, borderwidth=0, tabmargins=0, bordercolor=PAGE,
                    lightcolor=PAGE, darkcolor=PAGE)
    style.configure("Window.TFrame", background=WINDOW)
    style.configure("Card.TFrame", background=CARD)
    style.configure("CardHead.TFrame", background=CARD_HEAD)

    style.configure("TButton", background=INPUT, foreground=FG, borderwidth=0, padding=(12, 5), relief="flat")
    style.map("TButton", background=[("active", "#353950"), ("pressed", "#353950")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=FONT_BOLD)
    style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])
    style.configure("Icon.TButton", background=WINDOW, foreground=MUTED, padding=(4, 4), font=("Segoe UI Symbol", 13),
                    anchor="center")
    style.map("Icon.TButton", background=[("active", CARD)], foreground=[("active", FG)])
    style.configure("Nav.TButton", background=WINDOW, foreground=MUTED, anchor="w", padding=(16, 10), font=("Segoe UI", 11))
    style.map("Nav.TButton", background=[("active", "#1c1e2b")], foreground=[("active", FG)])
    style.configure("NavActive.TButton", background="#232640", foreground=ACCENT, anchor="w", padding=(16, 10),
                    font=("Segoe UI", 11, "bold"))
    style.map("NavActive.TButton", background=[("active", "#262a46")])
    style.configure("Ench.TButton", anchor="w", padding=(6, 2), background=INPUT)

    style.configure("TLabelframe", background=CARD, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=CARD, foreground=ACCENT, font=FONT_BOLD)
    style.configure("TLabel", background=PAGE, foreground=FG)
    style.configure("Window.TLabel", background=WINDOW, foreground=FG)
    style.configure("Title.TLabel", background=WINDOW, foreground=FG, font=FONT_TITLE)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("WindowMuted.TLabel", background=WINDOW, foreground=MUTED)
    style.configure("Warn.TLabel", foreground=WARN)
    style.configure("Big.TLabel", font=("Segoe UI", 13, "bold"))
    style.configure("Section.TLabel", foreground=FG, font=("Segoe UI", 11, "bold"))
    style.configure("Card.TLabel", background=CARD, foreground=FG)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    style.configure("CardHead.TLabel", background=CARD, foreground=FG, font=FONT_BOLD)
    style.configure("Page.TFrame", background=PAGE)
    style.configure("PageTitle.TLabel", background=PAGE, foreground=FG, font=("Segoe UI Semibold", 16))
    style.configure("Green.TLabel", background=CARD, foreground=GREEN, font=FONT_BOLD)
    style.configure("Red.TLabel", background=CARD, foreground=RED, font=FONT_BOLD)

    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=PAGE, foreground=FG, indicatorbackground=INPUT, indicatorforeground="#ffffff",
                        indicatorrelief="flat", indicatormargin=(0, 0, 8, 0), focuscolor=PAGE)
        style.map(name, indicatorbackground=[("selected", ACCENT), ("active", "#353950")],
                  background=[("active", PAGE)])
    for name in ("Card.TCheckbutton", "Card.TRadiobutton"):
        style.configure(name, background=CARD, focuscolor=CARD)
        style.map(name, background=[("active", CARD)])

    style.configure("TEntry", fieldbackground=INPUT, bordercolor=INPUT, lightcolor=INPUT, darkcolor=INPUT, padding=4)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    style.configure("TSpinbox", fieldbackground=INPUT, bordercolor=INPUT, lightcolor=INPUT, darkcolor=INPUT,
                    arrowsize=11, padding=3)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=INPUT, background=INPUT, bordercolor=INPUT, lightcolor=INPUT,
                    darkcolor=INPUT, padding=3)
    style.map("TCombobox", fieldbackground=[("readonly", INPUT)], foreground=[("readonly", FG)],
              bordercolor=[("focus", ACCENT)], background=[("active", INPUT)])
    root.option_add("*TCombobox*Listbox.background", INPUT)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    style.configure("Horizontal.TScale", troughcolor=INPUT, background=ACCENT, bordercolor=PAGE,
                    lightcolor=ACCENT, darkcolor=ACCENT, sliderthickness=14, gripcount=0)
    style.configure("Vertical.TScrollbar", background=INPUT, troughcolor=PAGE, bordercolor=PAGE, arrowcolor=MUTED,
                    lightcolor=INPUT, darkcolor=INPUT, gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", "#3a3e57")])

    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=FG, rowheight=30,
                    bordercolor=BORDER, borderwidth=0)
    style.configure("Treeview.Heading", background=CARD_HEAD, foreground=MUTED, relief="flat", font=FONT_BOLD,
                    bordercolor=BORDER)
    style.map("Treeview.Heading", background=[("active", CARD_HEAD)])
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", "#ffffff")])
    return style


class Toggle(tk.Canvas):
    """Pill-shaped on/off switch bound to a BooleanVar."""

    W, H = 38, 20

    def __init__(self, parent, variable, command=None, bg=CARD):
        super().__init__(parent, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.variable = variable
        self.command = command
        self.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _click(self, _event=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        on = bool(self.variable.get())
        r = self.H // 2
        track = ACCENT if on else "#3a3d52"
        self.create_oval(0, 0, self.H, self.H, fill=track, outline=track)
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=track, outline=track)
        self.create_rectangle(r, 0, self.W - r, self.H, fill=track, outline=track)
        x = self.W - r if on else r
        self.create_oval(x - r + 3, 3, x + r - 3, self.H - 3, fill="#ffffff" if on else "#c9ccd8", outline="")


def section(parent, icon, text, **pack):
    """Blue section heading like "⚔ Battle Modifiers"."""
    label = ttk.Label(parent, text=text, style="Section.TLabel")
    label.pack(anchor="w", **(pack or {"pady": (0, 8)}))
    return label


def rounded_rect(canvas, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, **kw)


class RoundedBox(tk.Canvas):
    """Canvas that draws a rounded, bordered box and hosts a frame inside it.

    The inner frame decides the height (unless fill_height); the canvas width follows its layout.
    """

    def __init__(self, parent, bg=CARD, outline=BORDER, radius=12, pad=8, parent_bg=None, fill_height=False,
                 frame_style="Card.TFrame", fixed_width=None):
        parent_bg = parent_bg or _bg_of(parent)
        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0, height=40, width=40)
        self.fill_color, self.outline, self.radius, self.pad = bg, outline, radius, pad
        self.fill_height = fill_height
        self.fixed_width = fixed_width
        if fixed_width:
            self.configure(width=fixed_width)
        self.inner = ttk.Frame(self, style=frame_style)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.inner)
        self.inner.bind("<Configure>", self._inner_changed)
        self.bind("<Configure>", self._redraw)

    def _inner_changed(self, _e=None):
        want_w = self.fixed_width or self.inner.winfo_reqwidth() + 2 * self.pad
        if int(self.cget("width")) != want_w:
            self.configure(width=want_w)
        if not self.fill_height:
            want = self.inner.winfo_reqheight() + 2 * self.pad
            if int(self.cget("height")) != want:
                self.configure(height=want)

    def _redraw(self, _e=None):
        w, h = self.winfo_width(), self.winfo_height()
        self.delete("box")
        item = rounded_rect(self, 1, 1, w - 2, h - 2, self.radius, fill=self.fill_color, outline=self.outline,
                            tags="box")
        self.tag_lower(item)
        self.itemconfigure(self._win, width=max(1, w - 2 * self.pad))
        if self.fill_height:
            self.itemconfigure(self._win, height=max(1, h - 2 * self.pad))


def _bg_of(widget):
    try:
        return widget.cget("background")
    except tk.TclError:
        try:
            return ttk.Style(widget).lookup(widget.cget("style") or widget.winfo_class(), "background") or PAGE
        except tk.TclError:
            return PAGE


def card(parent, title, toggle_var=None, toggle_command=None, pack=None):
    """Rounded card with a title row (optional toggle). Returns the body frame."""
    box = RoundedBox(parent, pad=6)
    box.pack(**(pack or {"fill": "x", "pady": (0, 12)}))
    head = ttk.Frame(box.inner, style="Card.TFrame", padding=(10, 6, 10, 4))
    head.pack(fill="x")
    ttk.Label(head, text=title, style="CardHead.TLabel").pack(side="left")
    if toggle_var is not None:
        Toggle(head, toggle_var, toggle_command, bg=CARD).pack(side="right")
    tk.Frame(box.inner, bg=BORDER, height=1).pack(fill="x", padx=4, pady=(4, 0))
    body = ttk.Frame(box.inner, style="Card.TFrame", padding=(10, 8, 10, 6))
    body.pack(fill="both", expand=True)
    return body


def card_row(body, row, text, widget, muted=False):
    ttk.Label(body, text=text, style="CardMuted.TLabel" if muted else "Card.TLabel").grid(
        row=row, column=0, sticky="w", pady=5, padx=(0, 16))
    widget.grid(row=row, column=1, sticky="e", pady=5)
    body.columnconfigure(0, weight=1)
    return widget
