"""WASD movement for Minecraft Dungeons via a virtual Xbox 360 controller.

The game only moves with the mouse or a gamepad, so W/A/S/D are fed into
the left stick of a virtual pad (ViGEmBus driver + `vgamepad` package).
Input is local to this PC, so it works in any world, including a friend's.
"""
import math
import os
import sys
import threading

from . import game

VK_W, VK_A, VK_S, VK_D = 0x57, 0x41, 0x53, 0x44
VK_UP, VK_LEFT, VK_DOWN, VK_RIGHT = 0x26, 0x25, 0x28, 0x27
VK_SHIFT = 0x10
POLL_SECONDS = 1 / 120


def stick_from_keys(up, left, down, right, slow=False):
    """Left-stick vector for the pressed direction keys (y up, length <= 1)."""
    x = (1 if right else 0) - (1 if left else 0)
    y = (1 if up else 0) - (1 if down else 0)
    if x and y:
        x, y = x * math.sqrt(0.5), y * math.sqrt(0.5)
    if slow:
        x, y = x * 0.5, y * 0.5
    return float(x), float(y)


class WasdUnavailable(Exception):
    pass


def _foreground_process_name(user32, kernel32):
    import ctypes
    from ctypes import wintypes
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


class WasdMovement:
    """Background thread: while the game window is focused, WASD drives the virtual stick."""

    def __init__(self, arrows=True, shift_walk=True):
        self.arrows = arrows
        self.shift_walk = shift_walk
        self._thread = None
        self._stop = threading.Event()
        self.error = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        if sys.platform != "win32":
            raise WasdUnavailable("WASD-режим работает только в Windows")
        try:
            import vgamepad
        except ImportError as e:
            raise WasdUnavailable("Не установлен пакет vgamepad: pip install vgamepad") from e
        try:
            pad = vgamepad.VX360Gamepad()
        except Exception as e:
            raise WasdUnavailable(
                "Не удалось создать виртуальный геймпад. Установите драйвер ViGEmBus "
                "(ставится вместе с vgamepad) и перезапустите загрузчик.") from e
        self._stop.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, args=(pad,), daemon=True, name="wasd")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._thread = None

    def _run(self, pad):
        import ctypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)  # noqa: E731
        game_names = {n.lower() for n in game.GAME_PROCESSES}
        last = None
        try:
            while not self._stop.is_set():
                stick = (0.0, 0.0)
                if _foreground_process_name(user32, kernel32).lower() in game_names:
                    up = down(VK_W) or (self.arrows and down(VK_UP))
                    left = down(VK_A) or (self.arrows and down(VK_LEFT))
                    back = down(VK_S) or (self.arrows and down(VK_DOWN))
                    right = down(VK_D) or (self.arrows and down(VK_RIGHT))
                    stick = stick_from_keys(up, left, back, right, self.shift_walk and down(VK_SHIFT))
                if stick != last:
                    pad.left_joystick_float(x_value_float=stick[0], y_value_float=stick[1])
                    pad.update()
                    last = stick
                self._stop.wait(POLL_SECONDS)
        except Exception as e:
            self.error = str(e)
        finally:
            try:
                pad.reset()
                pad.update()
            except Exception:
                pass
