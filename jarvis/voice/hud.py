"""Floating "Jarvis orb" HUD.

A small, borderless, always-on-top window that shows at a glance whether
Jarvis is idle, hearing you, thinking, or speaking, plus a live mic-level
bar so you can see it picking up your voice. Runs on its own thread (like
the TTS engine); the rest of the app just calls .state() and .level().
If Tkinter can't open a window, it degrades to a silent no-op and voice
keeps working.

The orb is drawn to feel alive: it breathes (a smooth radial glow that
swells on a sine), swells a little more when it hears you, and emits soft
sonar-style pulse rings that quicken with activity — calm when idle, rapid
when speaking. Colour still encodes state, and the mic bar under it is the
wake-threshold tuning aid.

Use `create(cfg)` to get either a live Hud or a null no-op.
"""

import math
import threading
import time

PANEL = "#0d1117"          # dark glass panel the orb sits on
KEY = "#010203"            # colour-keyed to transparent (panel corners)
EDGE = "#20293a"           # 1px panel border
W, H = 200, 214

# state -> (orb colour, label, breaths+pulses per second)
_STATES = {
    "idle":      ("#3f6d8f", 'listening for\n"Hey Jarvis"', 0.55),
    "listening": ("#3ddc84", "go ahead, sir",              1.6),
    "thinking":  ("#f5a623", "thinking…",                  2.6),
    "speaking":  ("#22d3ee", "speaking",                   3.2),
    "off":       ("#39424f", "voice off",                  0.0),
}

CX, CY = W / 2, 88         # orb centre
BASE_R = 28                # resting orb radius
R_OUT = 68                 # outer reach of the glow
GLOW_STEPS = 26
RING_LIFE = 1.6            # seconds for a pulse ring to travel out and fade


class Hud(threading.Thread):
    def __init__(self, cfg: dict):
        super().__init__(daemon=True, name="hud")
        hcfg = cfg.get("hud") or {}
        self.enabled = bool(hcfg.get("enabled", True))
        self.corner = hcfg.get("corner", "bottom-right")
        self._state = "off"
        self._level = 0.0   # target mic level 0..1, set from audio threads
        self._shown = 0.0   # smoothed level actually drawn
        self._phase = 0.0   # breathing phase, seconds
        self._rings = []    # live pulse rings, each a 0..1 progress
        self._ring_t = 0.0  # time since last ring spawned
        self._keyed = False # True if transparent corners are active
        self._alive = True
        self.ok = False
        if self.enabled:
            self.start()

    # ---- public API (safe to call from any thread) ----
    def state(self, name: str):
        if name in _STATES:
            self._state = name

    def level(self, value: float):
        self._level = 0.0 if value < 0 else 1.0 if value > 1 else float(value)

    def shutdown(self):
        self._alive = False

    # ---- everything below runs on the hud thread only ----
    def run(self):
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("Jarvis")
            root.overrideredirect(True)            # borderless
            root.attributes("-topmost", True)
            # Colour-key the panel corners to transparent for a rounded,
            # floating look; harmless if the platform ignores it.
            try:
                root.configure(bg=KEY)
                root.attributes("-transparentcolor", KEY)
                root.attributes("-alpha", 0.96)    # a touch of glass
                self._keyed = True
            except Exception:
                root.configure(bg=PANEL)
            self._place(root)
            bg = KEY if self._keyed else PANEL
            canvas = tk.Canvas(root, width=W, height=H, bg=bg,
                               highlightthickness=0)
            canvas.pack()
            self._enable_drag(root, canvas)
            self.ok = True
        except Exception:
            self.enabled = False
            return

        last = time.time()
        while self._alive:
            now = time.time()
            dt, last = now - last, now
            self._advance(dt)
            try:
                self._draw(canvas)
                root.update()      # pump events without a blocking mainloop
            except Exception:
                break
            time.sleep(0.03)
        try:
            root.destroy()
        except Exception:
            pass

    def _place(self, root):
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        m = 24
        x = m if "left" in self.corner else sw - W - m
        y = m if "top" in self.corner else sh - H - m - 48
        root.geometry(f"{W}x{H}+{x}+{y}")

    def _enable_drag(self, root, canvas):
        anchor = {"x": 0, "y": 0}

        def start(e):
            anchor["x"], anchor["y"] = e.x, e.y

        def move(e):
            root.geometry(f"+{root.winfo_x() + e.x - anchor['x']}"
                          f"+{root.winfo_y() + e.y - anchor['y']}")

        canvas.bind("<Button-1>", start)
        canvas.bind("<B1-Motion>", move)

    def _advance(self, dt):
        """Step time-based animation: breathing, mic easing, pulse rings."""
        speed = _STATES.get(self._state, _STATES["off"])[2]
        self._phase += dt
        # ease the drawn mic level toward its target so it looks smooth
        self._shown += (self._level - self._shown) * min(1.0, dt * 12)
        # advance and retire rings, then spawn a new one on the beat
        self._rings = [p + dt / RING_LIFE for p in self._rings
                       if p + dt / RING_LIFE < 1.0]
        if speed > 0:
            self._ring_t += dt
            interval = max(0.30, 1.15 / speed)
            if self._ring_t >= interval:
                self._ring_t = 0.0
                self._rings.append(0.0)

    def _draw(self, canvas):
        color, label, speed = _STATES.get(self._state, _STATES["off"])
        canvas.delete("all")

        # rounded glass panel (corners fall on the transparent key)
        _round_rect(canvas, 5, 5, W - 5, H - 5, 20, fill=EDGE)
        _round_rect(canvas, 6, 6, W - 6, H - 6, 19, fill=PANEL)

        # breathing 0..1, plus a little swell from the mic
        breath = (math.sin(self._phase * speed * 2 * math.pi) + 1) / 2 if speed else 0.5
        r = BASE_R + breath * 5 + self._shown * 7
        glow_out = R_OUT + breath * 6

        # soft radial glow: many overlapping ovals, dim outside -> bright core
        for i in range(GLOW_STEPS):
            t = i / (GLOW_STEPS - 1)                    # 0 outer .. 1 inner
            gr = r + (glow_out - r) * (1 - t)
            _oval(canvas, CX, CY, gr, _dim(color, 0.04 + t * t * 0.34))

        # sonar pulse rings emanating from the orb
        for p in self._rings:
            rr = r + (glow_out - r + 6) * p
            fade = (1 - p) ** 1.3
            canvas.create_oval(CX - rr, CY - rr, CX + rr, CY + rr,
                               outline=_dim(color, 0.5 * fade),
                               width=max(1, int(1 + 2 * fade)))

        # glassy sphere: lit from the upper-left with a specular highlight
        for i in range(6):
            t = i / 5
            rr = r * (1 - t * 0.85)
            off = r * 0.16 * t
            _oval(canvas, CX - off, CY - off, rr, _mix(color, "#eafcff", t * 0.55))
        hr = r * 0.24
        _oval(canvas, CX - r * 0.3, CY - r * 0.34, hr, _mix(color, "#ffffff", 0.75))

        # label
        canvas.create_text(CX, 160, text=label, fill="#c9d1d9",
                           font=("Segoe UI", 10), justify="center")

        # mic-level bar: dark pill track + green->cyan gradient fill
        bx0, bx1, by, bh = 24, W - 24, 190, 7
        _round_rect(canvas, bx0, by, bx1, by + bh, bh / 2, fill="#1b2230")
        w = (bx1 - bx0) * self._shown
        if w >= bh:
            _hbar(canvas, bx0, by, w, bh, "#3ddc84", "#22d3ee")


class _NullHud:
    """Silent stand-in used when the HUD is disabled or can't open."""
    ok = False
    enabled = False

    def state(self, *_):
        pass

    def level(self, *_):
        pass

    def shutdown(self):
        pass


def create(cfg: dict):
    """Return a live Hud if enabled, else a no-op _NullHud."""
    hud = Hud(cfg)
    return hud if hud.enabled else _NullHud()


# ---- drawing helpers ----
def _oval(canvas, cx, cy, r, fill):
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")


def _round_rect(c, x0, y0, x1, y1, r, **kw):
    c.create_rectangle(x0 + r, y0, x1 - r, y1, **kw)
    c.create_rectangle(x0, y0 + r, x1, y1 - r, **kw)
    for ax, ay, start in ((x0, y0, 90), (x1 - 2 * r, y0, 0),
                          (x0, y1 - 2 * r, 180), (x1 - 2 * r, y1 - 2 * r, 270)):
        c.create_arc(ax, ay, ax + 2 * r, ay + 2 * r,
                     start=start, extent=90, style="pieslice", outline="", **kw)


def _hbar(canvas, x0, y, w, h, c0, c1):
    """A rounded, horizontal gradient fill (c0 -> c1) for the mic bar."""
    steps = max(2, int(w))
    for i in range(steps):
        t = i / (steps - 1)
        x = x0 + w * t
        canvas.create_line(x, y, x, y + h, fill=_mix(c0, c1, t))
    rad = h / 2
    _oval(canvas, x0 + rad, y + rad, rad, c0)
    _oval(canvas, x0 + w - rad, y + rad, rad, _mix(c0, c1, 1.0))


def _blend(hex_a: str, hex_b: str, t: float) -> str:
    a = (int(hex_a[i:i + 2], 16) for i in (1, 3, 5))
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _dim(hex_color: str, alpha: float) -> str:
    """Blend a colour toward the dark panel by (1 - alpha) — fakes a glow."""
    return _blend(PANEL, hex_color, alpha)


def _mix(hex_color: str, toward: str, t: float) -> str:
    """Blend a colour toward another (e.g. white) by t — fakes a lit sphere."""
    return _blend(hex_color, toward, t)
