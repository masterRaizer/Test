"""Visual theme: dark navy palette, cards, sidebar navigation and toggle switches."""
import tkinter as tk
from tkinter import ttk

WINDOW = "#14151d"     # header + sidebar
PAGE = "#1b1c27"       # page background
CARD = "#212332"       # card body
CARD_HEAD = "#262839"  # card title strip
BORDER = "#2f3246"
INPUT = "#2b2e42"
FG = "#e6e8ef"
MUTED = "#8b8fa3"
ACCENT = "#3d6df2"
ACCENT_HOVER = "#5a83f5"
WARN = "#e0a84a"
SELECT = "#2f4a8f"
FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
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
    style.configure("Section.TLabel", foreground=ACCENT, font=FONT_SECTION)
    style.configure("Card.TLabel", background=CARD, foreground=FG)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    style.configure("CardHead.TLabel", background=CARD_HEAD, foreground=FG, font=FONT_BOLD)

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
    label = ttk.Label(parent, text=f"{icon}  {text}", style="Section.TLabel")
    label.pack(anchor="w", **(pack or {"pady": (0, 8)}))
    return label


def card(parent, title, toggle_var=None, toggle_command=None, pack=None):
    """Card with a title strip (optional toggle). Returns the body frame."""
    outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
    outer.pack(**(pack or {"fill": "x", "pady": (0, 10)}))
    head = ttk.Frame(outer, style="CardHead.TFrame", padding=(14, 10))
    head.pack(fill="x")
    ttk.Label(head, text=title, style="CardHead.TLabel").pack(side="left")
    if toggle_var is not None:
        Toggle(head, toggle_var, toggle_command, bg=CARD_HEAD).pack(side="right")
    body = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10))
    body.pack(fill="both", expand=True)
    return body


def card_row(body, row, text, widget, muted=False):
    ttk.Label(body, text=text, style="CardMuted.TLabel" if muted else "Card.TLabel").grid(
        row=row, column=0, sticky="w", pady=5, padx=(0, 16))
    widget.grid(row=row, column=1, sticky="e", pady=5)
    body.columnconfigure(0, weight=1)
    return widget
