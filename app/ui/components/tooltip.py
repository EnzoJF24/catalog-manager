"""
Tooltip — floating hover tooltip for any widget.

Uses a borderless Toplevel positioned just below the target widget.
Lightweight, theme-consistent, no external deps.

Usage:
    Tooltip(my_widget, "Explanation text")
"""
from __future__ import annotations
import tkinter as tk
from app.ui.theme import BG_DEEPEST, TEXT_HEADING, BORDER_COLOR


class Tooltip:
    """
    Attaches show/hide behaviour to a widget on hover.
    The tooltip is owned by this object — no need to store the instance,
    but doing so won't hurt.
    """

    def __init__(
        self,
        widget,
        text: str,
        delay_ms: int = 400,
        wraplength: int = 280,
    ):
        self._widget     = widget
        self._text       = text
        self._delay      = delay_ms
        self._wraplength = wraplength
        self._after_id   = None
        self._tip        = None

        widget.bind("<Enter>",  self._schedule, add="+")
        widget.bind("<Leave>",  self._hide,     add="+")
        widget.bind("<Button>", self._hide,     add="+")
        widget.bind("<Destroy>", self._hide,    add="+")

    # ── Public ────────────────────────────────────────────────────────────────

    def update_text(self, text: str):
        self._text = text
        if self._tip is not None:
            # Always hide the current popup; only re-show if text is non-empty.
            self._hide()
            if text:
                self._show()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after_id = self._widget.after(self._delay, self._show)
        except tk.TclError:
            pass  # Widget destroyed

    def _cancel(self):
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None:
            return
        try:
            if not self._widget.winfo_exists():
                return
            wx = self._widget.winfo_rootx()
            wy = self._widget.winfo_rooty()
            wh = self._widget.winfo_height()
        except tk.TclError:
            return

        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        # Outer border = a single-pixel frame in BORDER_COLOR
        tw.configure(bg=BORDER_COLOR)

        inner = tk.Frame(tw, bg=BG_DEEPEST, bd=0)
        inner.pack(padx=1, pady=1)

        tk.Label(
            inner,
            text=self._text,
            bg=BG_DEEPEST, fg=TEXT_HEADING,
            font=("Segoe UI", 10),
            justify="left",
            wraplength=self._wraplength,
            padx=10, pady=6,
        ).pack()

        # Measure height AFTER adding content (needed for vertical flip).
        # Width: use wraplength-based estimate — winfo_reqwidth() is unreliable
        # on Windows with DPI scaling and can cause excessive left-clamping.
        tw.update_idletasks()
        tip_w = self._wraplength + 24   # wraplength + label padx*2 + border*2
        tip_h = tw.winfo_reqheight()
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()

        # Horizontal: start below-right of widget; shift left only if needed.
        x = wx + 12
        if x + tip_w > screen_w - 4:
            x = screen_w - tip_w - 4
        x = max(4, x)

        # Vertical: prefer below the widget; flip above if it would be clipped
        # (40 px buffer accounts for Windows taskbar at screen bottom).
        y_below = wy + wh + 6
        y_above = wy - tip_h - 6
        y = y_below if y_below + tip_h <= screen_h - 40 else max(0, y_above)

        tw.wm_geometry(f"+{x}+{y}")
        self._tip = tw

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None
