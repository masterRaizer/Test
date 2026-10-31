"""Window chrome: app icon, dark Windows title bar, splash screen and small animations."""
import os
import sys
import time
import tkinter as tk

from . import theme


def asset_path(name):
    base = getattr(sys, "_MEIPASS", None)
    if base:
        bundled = os.path.join(base, "mcd_loader", "assets", name)
        if os.path.exists(bundled):
            return bundled
    return os.path.join(os.path.dirname(__file__), "assets", name)


def load_logo(master, size):
    try:
        from PIL import Image, ImageTk
        with Image.open(asset_path("logo.png")) as img:
            return ImageTk.PhotoImage(img.convert("RGBA").resize((size, size), Image.LANCZOS), master=master)
    except Exception:
        return None


def set_window_icon(win):
    if os.name == "nt":
        try:
            win.iconbitmap(default=asset_path("launcher.ico"))
        except tk.TclError:
            pass
    logo = load_logo(win, 64)
    if logo:
        win.iconphoto(True, logo)
        win._icon_ref = logo


def _hwnd(win):
    import ctypes
    win.update_idletasks()
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def _colorref(hex_color):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return b << 16 | g << 8 | r


def style_titlebar(win, caption=theme.WINDOW, text=theme.FG, border=theme.BORDER, rounded=True):
    """Windows 10/11: dark title bar in the app's colours and rounded corners (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        hwnd = _hwnd(win)

        def attr(code, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, code, ctypes.byref(v), ctypes.sizeof(v))
        attr(20, 1)                       # DWMWA_USE_IMMERSIVE_DARK_MODE
        attr(35, _colorref(caption))      # DWMWA_CAPTION_COLOR (Windows 11)
        attr(36, _colorref(text))         # DWMWA_TEXT_COLOR
        attr(34, _colorref(border))       # DWMWA_BORDER_COLOR
        if rounded:
            attr(33, 2)                   # DWMWA_WINDOW_CORNER_PREFERENCE = round
    except Exception:
        pass


def ease_out(t):
    return 1 - (1 - t) ** 3


class Animator:
    """Runs one tween per key; starting a new one cancels the previous."""

    def __init__(self, widget):
        self.widget = widget
        self._jobs = {}

    def run(self, key, start, end, ms, apply, done=None):
        token = object()
        self._jobs[key] = token
        t0 = time.perf_counter()

        def frame():
            if self._jobs.get(key) is not token:
                return
            t = min(1.0, (time.perf_counter() - t0) * 1000 / max(1, ms))
            try:
                apply(start + (end - start) * ease_out(t))
            except tk.TclError:
                return
            if t < 1.0:
                self.widget.after(12, frame)
            elif done:
                done()
        frame()


def fade(animator, win, start, end, ms=180, done=None, key="fade"):
    def apply(alpha):
        win.attributes("-alpha", max(0.0, min(1.0, alpha)))
    animator.run(key, start, end, ms, apply, done)


class Splash(tk.Toplevel):
    """Startup screen: logo, title, animated progress bar and status line."""

    W, H = 520, 330
    BAR_W = 360

    def __init__(self, root, version=""):
        super().__init__(root, bg=theme.BORDER)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        sx = (self.winfo_screenwidth() - self.W) // 2
        sy = (self.winfo_screenheight() - self.H) // 2
        self.geometry(f"{self.W}x{self.H}+{sx}+{sy}")
        self.animator = Animator(self)
        self.started = time.perf_counter()
        self.progress = 0.0
        self.target = 0.0
        self._phase = 0.0
        self._dots = 0

        body = tk.Canvas(self, bg=theme.WINDOW, highlightthickness=0, bd=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        self.canvas = body
        w = self.W - 2
        # soft accent glow at the top
        for i in range(18):
            shade = _mix(theme.WINDOW, theme.ACCENT, 0.16 * (1 - i / 18))
            body.create_oval(w / 2 - 170 + i * 6, -150 + i * 4, w / 2 + 170 - i * 6, 150 - i * 4, fill=shade, outline="")
        self.logo = load_logo(self, 92)
        if self.logo:
            body.create_image(w / 2, 92, image=self.logo)
        body.create_text(w / 2, 168, text="MCD LOADER", fill=theme.FG, font=("Segoe UI", 22, "bold"))
        body.create_text(w / 2, 198, text=f"Minecraft Dungeons  ·  {version}".strip(" ·"), fill=theme.MUTED,
                         font=("Segoe UI", 10))
        x0, y0 = (w - self.BAR_W) / 2, 250
        self.bar = (x0, y0, x0 + self.BAR_W, y0 + 6)
        _round_rect(body, *self.bar, 3, fill=theme.INPUT, outline="")
        self.fill = _round_rect(body, x0, y0, x0 + 6, y0 + 6, 3, fill=theme.ACCENT, outline="")
        self.shine = body.create_rectangle(x0, y0, x0, y0 + 6, fill=theme.ACCENT_HOVER, outline="")
        self.status = body.create_text(w / 2, 282, text="Запуск", fill=theme.MUTED, font=("Segoe UI", 10))
        self.status_text = "Запуск"
        self.update_idletasks()
        style_titlebar(self)
        fade(self.animator, self, 0.0, 1.0, 260)
        self._tick()

    def step(self, text, progress):
        self.status_text = text
        self.target = max(self.target, min(1.0, progress))
        self.update()

    def _tick(self):
        if not self.winfo_exists():
            return
        self.progress += (self.target - self.progress) * 0.18
        x0, y0, x1, y1 = self.bar
        right = x0 + max(6, (x1 - x0) * self.progress)
        self.canvas.coords(self.fill, *_round_rect_points(x0, y0, right, y1, 3))
        self._phase = (self._phase + 0.025) % 1.3
        sx = x0 + (right - x0) * min(1.0, self._phase)
        self.canvas.coords(self.shine, max(x0, sx - 40), y0 + 1, min(right, sx), y1 - 1)
        self._dots = (self._dots + 1) % 48
        self.canvas.itemconfigure(self.status, text=self.status_text + "." * (self._dots // 12))
        self.after(16, self._tick)

    def finish(self, on_done, min_seconds=1.4):
        """Fill the bar, wait for the minimum show time, fade out, then call on_done."""
        self.step("Готово", 1.0)
        wait = max(0, int((min_seconds - (time.perf_counter() - self.started)) * 1000))

        def close():
            fade(self.animator, self, 1.0, 0.0, 220, done=lambda: (self.destroy(), on_done()))
        self.after(wait + 250, close)


def _mix(a, b, t):
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def _round_rect_points(x0, y0, x1, y1, r):
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def _round_rect(canvas, x0, y0, x1, y1, r, **kw):
    return canvas.create_polygon(_round_rect_points(x0, y0, x1, y1, r), smooth=True, **kw)


class SlidingIndicator:
    """Accent bar that glides to the active sidebar button."""

    def __init__(self, parent, animator):
        self.bar = tk.Frame(parent, bg=theme.ACCENT, width=3)
        self.animator = animator
        self.y = None

    def move_to(self, widget):
        widget.update_idletasks()
        y, h = widget.winfo_y() + 6, max(10, widget.winfo_height() - 12)
        if self.y is None:
            self.y = y
            self.bar.place(x=0, y=y, width=3, height=h)
            return

        def apply(v):
            self.y = v
            self.bar.place_configure(y=int(v), height=h)
        self.animator.run("nav", self.y, y, 180, apply)
