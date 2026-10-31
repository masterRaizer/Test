"""Launcher shell widgets: borderless window, sidebar items, loading screen, carousel, badges."""
import math
import os
import time
import tkinter as tk

from . import chrome, theme

SANS = "Segoe UI"


# ---------------------------------------------------------------- window
class Borderless:
    """Frameless main window that still shows in the taskbar, can be dragged, minimized and maximized."""

    def __init__(self, root):
        self.root = root
        self._drag = None
        self._normal_geometry = None
        self.maximized = False
        self._restoring = False
        root.overrideredirect(True)
        root.after(10, self._as_app_window)
        root.bind("<Map>", self._on_map, add="+")

    def _as_app_window(self):
        if os.name != "nt":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            style = (style & ~0x00000080) | 0x00040000  # -WS_EX_TOOLWINDOW, +WS_EX_APPWINDOW
            user32.SetWindowLongW(hwnd, -20, style)
            chrome.style_titlebar(self.root)
            self._round_corners(hwnd)
            if self.root.state() != "withdrawn":
                self.root.withdraw()
                self.root.after(10, self.root.deiconify)
        except Exception:
            pass

    def _round_corners(self, hwnd):
        import ctypes
        import sys
        if sys.getwindowsversion().build >= 22000:
            return  # Windows 11 rounds via DWM (style_titlebar)
        w, h = self.root.winfo_width(), self.root.winfo_height()
        region = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 16, 16)
        ctypes.windll.user32.SetWindowRgn(hwnd, region, True)

    def _on_map(self, event=None):
        # <Map> bound on the root also fires for every child widget: react to the window itself, once.
        if event is not None and event.widget is not self.root:
            return
        if not self.root.overrideredirect() and not self._restoring:
            self._restoring = True

            def restore():
                self.root.overrideredirect(True)
                self._as_app_window()
                self._restoring = False
            self.root.after(10, restore)

    def minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()

    def toggle_maximize(self):
        if self.maximized:
            self.root.geometry(self._normal_geometry)
        else:
            self._normal_geometry = self.root.geometry()
            x, y, w, h = _work_area(self.root)
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.maximized = not self.maximized

    def drag_handle(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag, add="+")
        widget.bind("<B1-Motion>", self._do_drag, add="+")
        widget.bind("<Double-Button-1>", lambda e: self.toggle_maximize(), add="+")

    def _start_drag(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _do_drag(self, event):
        if self._drag and not self.maximized:
            self.root.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def resize_grip(self, parent):
        grip = tk.Label(parent, text="◢", bg=theme.PAGE, fg=theme.DIM, cursor="size_nw_se" if os.name == "nt" else "bottom_right_corner", font=(SANS, 8))
        start = {}

        def press(e):
            start.update(x=e.x_root, y=e.y_root, w=self.root.winfo_width(), h=self.root.winfo_height())

        def motion(e):
            w = max(self.root.winfo_reqwidth() // 2, start["w"] + e.x_root - start["x"], 980)
            h = max(620, start["h"] + e.y_root - start["y"])
            self.root.geometry(f"{w}x{h}")
        grip.bind("<ButtonPress-1>", press)
        grip.bind("<B1-Motion>", motion)
        return grip


def _work_area(root):
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class WindowButtons(tk.Frame):
    def __init__(self, parent, on_min, on_max, on_close, bg=theme.WINDOW):
        super().__init__(parent, bg=bg)
        for text, cmd, hover in (("—", on_min, "#1d1e24"), ("▢", on_max, "#1d1e24"), ("✕", on_close, "#c42b1c")):
            b = tk.Label(self, text=text, bg=bg, fg=theme.MUTED, font=(SANS, 10), width=4, pady=6, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b, h=hover: w.configure(bg=h, fg="#ffffff"))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=bg, fg=theme.MUTED))


# --------------------------------------------------------------- sidebar
class NavItem(tk.Canvas):
    """Sidebar entry: rounded highlight, accent bar when active, icon, label, optional badge/chevron."""

    H = 38

    def __init__(self, parent, icon, text, command, width=184, chevron=False, bold=False):
        super().__init__(parent, width=width, height=self.H, bg=theme.WINDOW, highlightthickness=0, bd=0,
                         cursor="hand2")
        self.icon, self.text, self.command = icon, text, command
        self.chevron, self.bold = chevron, bold
        self.active = self.hover = False
        self.badge = None
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Configure>", lambda e: self.draw())

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def set_active(self, active):
        self._set(active=active)

    def set_badge(self, badge):
        self._set(badge=badge)

    def draw(self):
        self.delete("all")
        w, h = int(self.winfo_width() or self.cget("width")), self.H
        if self.active or self.hover:
            theme.rounded_rect(self, 0, 2, w - 1, h - 2, 9, fill=theme.NAV_ACTIVE if self.active else "#131418",
                               outline="")
        if self.active:
            self.create_rectangle(4, 11, 6, h - 11, fill=theme.ACCENT, outline="")
        color = theme.ACCENT if self.active else theme.MUTED
        self.create_text(22, h / 2, text=self.icon, fill=color, font=(SANS, 11))
        self.create_text(42, h / 2, text=self.text, anchor="w", font=(SANS, 10, "bold" if self.active or self.bold else ""),
                         fill=theme.FG if self.active or self.hover else "#c9cbd1")
        if self.badge:
            self.create_text(w - 16, h / 2, text=self.badge, fill=theme.WARN, font=(SANS, 10))
        elif self.chevron:
            self.create_text(w - 14, h / 2, text="›", fill=theme.DIM, font=(SANS, 12))


# ------------------------------------------------------------- controls
class CanvasButton(tk.Canvas):
    """Rounded button drawn on a canvas (primary blue or dark)."""

    def __init__(self, parent, text, command, primary=True, width=None, height=34, bg=None, icon=""):
        self.text = f"{icon}  {text}" if icon else text
        font = (SANS, 10, "bold")
        width = width or int(len(self.text) * 7.6 + 34)
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, cursor="hand2",
                         bg=bg or theme._bg_of(parent))
        self.primary, self.command, self.font = primary, command, font
        self.enabled = True
        self.hover = False
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<Button-1>", lambda e: self.enabled and self.command())
        self.draw()

    def _hover(self, on):
        self.hover = on
        self.draw()

    def set_text(self, text):
        self.text = text
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = int(self.cget("width")), int(self.cget("height"))
        if self.primary:
            fill = theme.ACCENT_HOVER if self.hover else theme.ACCENT
            fg = "#ffffff"
        else:
            fill = "#22232b" if self.hover else "#1a1b21"
            fg = theme.FG
        if not self.enabled:
            fill, fg = "#1a1b21", theme.DIM
        theme.rounded_rect(self, 0, 0, w - 1, h - 1, 8, fill=fill, outline="" if self.primary else theme.BORDER)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)


def pill(parent, text, fg, bg, font=(SANS, 8, "bold")):
    return tk.Label(parent, text=f" {text} ", fg=fg, bg=bg, font=font, padx=4, pady=1)


class TopProgress(tk.Canvas):
    """Thin accent line that sweeps across the top of the content panel on page changes."""

    def __init__(self, parent):
        super().__init__(parent, height=2, bg=theme.PAGE, highlightthickness=0, bd=0)
        self.line = self.create_line(0, 1, 0, 1, fill=theme.ACCENT, width=2)
        self.anim = chrome.Animator(self)

    def sweep(self, ms=260, done=None):
        w = self.winfo_width() or 800

        def apply(v):
            self.coords(self.line, 0, 1, v, 1)

        def finish():
            self.coords(self.line, 0, 1, 0, 1)
            if done:
                done()
        self.anim.run("sweep", 0, w, ms, apply, finish)


# ---------------------------------------------------------- loading view
def liquid_frames(size=96, intro=12, cycle=72):
    """PIL RGBA frames: logo pops in, then drains and refills with a tilted liquid surface."""
    from PIL import Image, ImageDraw, ImageEnhance
    with Image.open(chrome.asset_path("mark.png")) as src:
        mark = src.convert("RGBA").resize((size, size), Image.LANCZOS)
    alpha = mark.getchannel("A")
    dim = ImageEnhance.Brightness(mark).enhance(0.28)
    frames = []
    for i in range(intro):  # scale-in with overshoot
        t = (i + 1) / intro
        scale = 0.6 + 0.5 * math.sin(t * math.pi * 0.75) / math.sin(math.pi * 0.75)
        s = max(4, int(size * scale))
        img = Image.new("RGBA", (int(size * 1.2), int(size * 1.2)), (0, 0, 0, 0))
        m = mark.resize((s, s), Image.LANCZOS)
        a = m.getchannel("A").point(lambda v, t=t: int(v * min(1.0, t * 1.6)))
        m.putalpha(a)
        img.alpha_composite(m, ((img.width - s) // 2, (img.height - s) // 2))
        frames.append(img)

    def level_at(k):
        p = k / cycle
        if p < 0.15:
            return 1.0
        if p < 0.48:
            q = (p - 0.15) / 0.33
            return 1 - (1 - math.cos(q * math.pi)) / 2
        if p < 0.58:
            return 0.0
        if p < 0.92:
            q = (p - 0.58) / 0.34
            return (1 - math.cos(q * math.pi)) / 2
        return 1.0

    box = alpha.getbbox() or (0, 0, size, size)
    top, bottom = box[1], box[3]
    for k in range(cycle):
        level = level_at(k)
        tilt = math.sin(k / cycle * math.pi * 4) * size * 0.05
        surface = bottom - (bottom - top) * level
        mask = Image.new("L", (size, size), 0)
        d = ImageDraw.Draw(mask)
        d.polygon([(0, surface - tilt), (size, surface + tilt), (size, size), (0, size)], fill=255)
        fill = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        fill.paste(mark, (0, 0), Image.composite(alpha, Image.new("L", (size, size), 0), mask))
        img = Image.new("RGBA", (int(size * 1.2), int(size * 1.2)), (0, 0, 0, 0))
        off = ((img.width - size) // 2, (img.height - size) // 2)
        img.alpha_composite(dim, off)
        img.alpha_composite(fill, off)
        if 0.02 < level < 0.98:  # bright line on the liquid surface, clipped to the logo
            line = Image.new("L", (size, size), 0)
            ImageDraw.Draw(line).line([(0, surface - tilt), (size, surface + tilt)], fill=255, width=max(2, size // 40))
            hl = Image.new("RGBA", (size, size), (150, 185, 255, 255))
            hl.putalpha(Image.composite(alpha, Image.new("L", (size, size), 0), line))
            img.alpha_composite(hl, off)
        frames.append(img)
    return frames, intro


class LoadingView(tk.Canvas):
    """Full-window loading screen: dark backdrop, liquid logo, spaced title, status line."""

    def __init__(self, parent, title="MCD LOADER", status=""):
        super().__init__(parent, bg=theme.WINDOW, highlightthickness=0, bd=0)
        self.title, self.status = title, status
        self._frames = []
        self._intro = 0
        self._index = 0
        self._job = None
        self._bg = None
        self.started = time.perf_counter()
        try:
            from PIL import ImageTk
            frames, self._intro = liquid_frames()
            self._frames = [ImageTk.PhotoImage(f, master=self) for f in frames]
        except Exception:
            self._frames = []
        self.bind("<Configure>", lambda e: self._layout())

    def _backdrop(self, w, h):
        try:
            from PIL import Image, ImageDraw, ImageFilter, ImageTk
            img = Image.new("RGB", (max(1, w // 4), max(1, h // 4)), (8, 8, 11))
            d = ImageDraw.Draw(img)
            cw, ch = img.size
            d.ellipse([cw * 0.55, -ch * 0.2, cw * 1.25, ch * 0.9], fill=(20, 32, 70))
            d.ellipse([-cw * 0.2, ch * 0.5, cw * 0.4, ch * 1.3], fill=(16, 20, 40))
            img = img.filter(ImageFilter.GaussianBlur(cw * 0.08)).resize((w, h), Image.BICUBIC)
            return ImageTk.PhotoImage(img, master=self)
        except Exception:
            return None

    def _layout(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return
        self.delete("all")
        self._bg = self._backdrop(w, h)
        if self._bg:
            self.create_image(0, 0, image=self._bg, anchor="nw")
        self.logo = self.create_image(w / 2, h / 2 - 24, image=self._frames[0] if self._frames else "")
        self.create_text(w / 2, h / 2 + 46, text=" ".join(self.title.upper()), fill="#6c6f7a", font=(SANS, 10, "bold"))
        self.status_item = self.create_text(w / 2, h / 2 + 76, text=self.status, fill=theme.DIM, font=(SANS, 9))
        if self._job is None:
            self._tick()

    def raise_view(self):
        self.tk.call("raise", self._w)  # Canvas.lift() raises canvas items, not the widget

    def set_status(self, text):
        self.status = text
        try:
            self.itemconfigure(self.status_item, text=text)
        except (AttributeError, tk.TclError):
            pass

    def restart(self):
        self._index = 0
        self.started = time.perf_counter()

    def _tick(self):
        if not self.winfo_exists():
            return
        if self._frames:
            frame = self._frames[self._index]
            try:
                self.itemconfigure(self.logo, image=frame)
            except (AttributeError, tk.TclError):
                pass
            self._index += 1
            if self._index >= len(self._frames):
                self._index = self._intro
        self._job = self.after(33, self._tick)

    def stop(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None


# --------------------------------------------------------------- carousel
class Carousel(tk.Frame):
    """Hero banner with slides (background image + title, badge, text, button) and dot indicators."""

    def __init__(self, parent, slides, width=560, height=270, interval_ms=6000):
        super().__init__(parent, bg=theme.PAGE)
        self.slides, self.w, self.h = slides, width, height
        self.index = 0
        self.interval = interval_ms
        self.canvas = tk.Canvas(self, width=width, height=height, bg=theme.PAGE, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x")
        self.dots = tk.Canvas(self, height=18, bg=theme.PAGE, highlightthickness=0, bd=0)
        self.dots.pack(fill="x", pady=(8, 0))
        self.dots.bind("<Button-1>", self._dot_click)
        self.dots.bind("<Configure>", lambda e: self._draw_dots())
        self.canvas.bind("<Configure>", self._resized)
        self._images = {}
        self._button = None
        self._job = None
        self._fade_job = None

    def _resized(self, event):
        if abs(event.width - self.w) > 2:
            self.w = event.width
            self._images.clear()
            self.show(self.index, animate=False)

    def _render(self, i):
        key = (i, self.w, self.h)
        if key not in self._images:
            from PIL import Image, ImageDraw
            art = self.slides[i]["art"](self.w, self.h)
            mask = Image.new("L", (self.w, self.h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, self.w - 1, self.h - 1], radius=14, fill=255)
            base = Image.new("RGB", (self.w, self.h), _rgb(theme.PAGE))
            base.paste(art.convert("RGB"), (0, 0), mask)
            self._images[key] = base
        return self._images[key]

    def show(self, i, animate=True):
        from PIL import Image, ImageTk
        prev = self._render(self.index)
        self.index = i % len(self.slides)
        cur = self._render(self.index)
        if self._fade_job:
            self.after_cancel(self._fade_job)
        steps = 8 if animate and prev is not cur else 1

        def step(k=1):
            img = Image.blend(prev, cur, k / steps) if steps > 1 else cur
            self._photo = ImageTk.PhotoImage(img, master=self)
            self.canvas.delete("bg")
            self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="bg")
            self.canvas.tag_lower("bg")
            if k < steps:
                self._fade_job = self.after(22, lambda: step(k + 1))
            else:
                self._fade_job = None
                self._draw_text()
        self.canvas.delete("text")
        if self._button:
            self._button.destroy()
            self._button = None
        step()
        self._draw_dots()
        self._schedule()

    def _draw_text(self):
        s = self.slides[self.index]
        c = self.canvas
        c.delete("text")
        x, y = 26, 26
        if s.get("logo"):
            c.create_image(x, y, image=s["logo"], anchor="nw", tags="text")
            y += 62
        title = c.create_text(x, y, text=s["title"], anchor="nw", fill="#ffffff", font=(SANS, 17, "bold"), tags="text")
        if s.get("badge"):
            bx = c.bbox(title)[2] + 10
            theme.rounded_rect(c, bx, y + 7, bx + 8 * len(s["badge"]) + 14, y + 25, 5, fill=theme.WARN, outline="",
                               tags="text")
            c.create_text(bx + 4 * len(s["badge"]) + 7, y + 16, text=s["badge"], fill="#ffffff",
                          font=(SANS, 8, "bold"), tags="text")
        desc = c.create_text(x, y + 36, text=s["text"], anchor="nw", fill="#d6d8de", font=(SANS, 10), tags="text",
                             width=int(self.w * 0.56))
        if s.get("tag"):
            ty = c.bbox(desc)[3] + 10
            label = c.create_text(x + 11, ty + 11, text=s["tag"], anchor="w", fill="#6f9bff", font=(SANS, 8, "bold"),
                                  tags="text")
            box = theme.rounded_rect(c, x, ty, c.bbox(label)[2] + 11, ty + 22, 8, fill="#18233f", outline="",
                                     tags="text")
            c.tag_raise(label, box)
        if s.get("button"):
            label, cmd = s["button"]
            self._button = CanvasButton(c, label, cmd, primary=True, height=34)
            c.create_window(x, self.h - 24, window=self._button, anchor="sw", tags="text")
            if s.get("note"):
                c.create_text(x + int(self._button.cget("width")) + 18, self.h - 41, text=s["note"], anchor="w",
                              fill="#c8cad1", font=(SANS, 9, "bold"), tags="text")

    def _draw_dots(self):
        d = self.dots
        d.delete("all")
        w = d.winfo_width() or self.w
        n = len(self.slides)
        total = (n - 1) * 14 + 26
        x = (w - total) / 2
        self._dot_boxes = []
        for i in range(n):
            if i == self.index:
                theme.rounded_rect(d, x, 6, x + 24, 11, 2, fill=theme.ACCENT, outline="")
                self._dot_boxes.append((x, x + 24))
                x += 32
            else:
                d.create_oval(x, 5, x + 6, 11, fill="#2a2c34", outline="")
                self._dot_boxes.append((x - 4, x + 10))
                x += 14

    def _dot_click(self, event):
        for i, (a, b) in enumerate(getattr(self, "_dot_boxes", [])):
            if a <= event.x <= b:
                self.show(i)

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(self.interval, lambda: self.show(self.index + 1))


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def banner_art(icon_paths, hue=(25, 45, 110)):
    """Slide background: dark gradient, soft glow and a faded collage of the given game icons."""
    def make(w, h):
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
        img = Image.new("RGB", (w, h), (12, 13, 18))
        d = ImageDraw.Draw(img)
        for x in range(w):
            t = x / max(1, w - 1)
            d.line([(x, 0), (x, h)], fill=tuple(int(12 + (c - 12) * t * 0.9) for c in hue))
        glow = Image.new("RGB", (w, h), (0, 0, 0))
        ImageDraw.Draw(glow).ellipse([w * 0.45, -h * 0.4, w * 1.2, h * 1.2], fill=hue)
        img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(h * 0.25)), 0.35)
        icons = []
        for p in icon_paths[:9]:
            try:
                with Image.open(p) as im:
                    icons.append(im.convert("RGBA"))
            except OSError:
                pass
        if icons:
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            cell = int(h * 0.36)
            for k, icon in enumerate(icons):
                col, row = k % 3, k // 3
                x = int(w * 0.50 + col * cell * 0.95 + (row % 2) * cell * 0.3)
                y = int(-cell * 0.15 + row * cell * 0.8)
                ic = icon.resize((cell, cell), Image.LANCZOS).rotate(-12, expand=True)
                layer.alpha_composite(ic, (x, y))
            layer = layer.filter(ImageFilter.GaussianBlur(1.2))
            a = layer.getchannel("A").point(lambda v: int(v * 0.55))
            layer.putalpha(a)
            img = img.convert("RGBA")
            img.alpha_composite(layer)
        shade = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(shade)
        for x in range(w):
            sd.line([(x, 0), (x, h)], fill=int(200 * max(0.0, 1 - x / (w * 0.75))))
        dark = Image.new("RGBA", (w, h), (8, 9, 13, 255))
        dark.putalpha(shade)
        img = img.convert("RGBA")
        img.alpha_composite(dark)
        return ImageEnhance.Contrast(img.convert("RGB")).enhance(1.05)
    return make


def _cover(img, w, h):
    """Scale and centre-crop an image to exactly w x h."""
    from PIL import Image
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, int(img.width * scale + 0.5)), max(h, int(img.height * scale + 0.5))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def image_art(path, fallback, shade=0.85, extent=0.75):
    """Slide/card background from a picture (e.g. Steam art) with a dark left fade for text."""
    def make(w, h):
        from PIL import Image, ImageDraw
        try:
            with Image.open(path) as src:
                img = _cover(src.convert("RGB"), w, h)
        except Exception:
            return fallback(w, h)
        if shade:
            mask = Image.new("L", (w, h), 0)
            d = ImageDraw.Draw(mask)
            for x in range(w):
                d.line([(x, 0), (x, h)], fill=int(255 * shade * max(0.0, 1 - x / (w * extent)) ** 1.2))
            dark = Image.new("RGB", (w, h), (8, 9, 13))
            img = Image.composite(dark, img, mask)
            bottom = Image.new("L", (w, h), 0)
            bd = ImageDraw.Draw(bottom)
            for y in range(h):
                bd.line([(0, y), (w, y)], fill=int(120 * max(0.0, (y - h * 0.55) / (h * 0.45))))
            img = Image.composite(dark, img, bottom)
        return img
    return make
