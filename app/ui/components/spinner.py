"""
Spinner — minimalist braille loading indicator.

Compact inline replacement for LoadingOverlay. Place it inside any frame
next to (or instead of) status text. Renders a single animated character
plus an optional message — no full-screen dimming.

Usage:
    spinner = Spinner(parent)
    spinner.grid(row=0, column=0, sticky="w")
    spinner.start("Generating Excel...")
    # ... background work ...
    spinner.stop()
"""
from __future__ import annotations
import customtkinter as ctk
from app.ui.theme import ACCENT_PRIMARY, TEXT_MUTED, font_small

# 10-frame braille rotation — smooth at ~80ms per frame
_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_INTERVAL_MS = 80


class Spinner(ctk.CTkFrame):
    """Inline braille spinner with optional status label."""

    def __init__(
        self,
        parent,
        with_label: bool = True,
        icon_color: str = ACCENT_PRIMARY,
        text_color: str = TEXT_MUTED,
        icon_size: int = 16,
    ):
        super().__init__(parent, fg_color="transparent")
        self._with_label = with_label
        self._frame_idx = 0
        self._after_id = None

        self._icon = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont(size=icon_size),
            text_color=icon_color,
            width=20,
        )
        self._icon.grid(row=0, column=0, padx=(0, 6), sticky="w")

        if with_label:
            self._label = ctk.CTkLabel(
                self, text="",
                font=font_small(),
                text_color=text_color,
                anchor="w",
            )
            self._label.grid(row=0, column=1, sticky="w")
            self.grid_columnconfigure(1, weight=1)
        else:
            self._label = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, message: str = ""):
        """Start the rotation. Safe to call repeatedly (resets animation)."""
        self.stop()
        if self._label is not None:
            self._label.configure(text=message)
        self._frame_idx = 0
        self._show()
        self._tick()

    def stop(self):
        """Halt the rotation and clear icon + message."""
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._icon.configure(text="")
        if self._label is not None:
            self._label.configure(text="")
        self._hide()

    # Hidden while idle so an empty spinner never reserves layout space.
    # grid_remove() keeps the grid options, so grid() restores the position.
    def _show(self):
        if self.winfo_manager() == "" and getattr(self, "_was_gridded", False):
            ctk.CTkFrame.grid(self)   # base grid(): restores the remembered options

    def _hide(self):
        if self.winfo_manager() == "grid":
            self._was_gridded = True
            self.grid_remove()

    def grid(self, *args, **kwargs):
        super().grid(*args, **kwargs)
        self._was_gridded = True
        if not self.running:
            self.after_idle(self._hide)

    def set_message(self, message: str):
        """Update message without restarting the animation."""
        if self._label is not None:
            self._label.configure(text=message)

    @property
    def running(self) -> bool:
        return self._after_id is not None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _tick(self):
        if not self.winfo_exists():
            return
        self._icon.configure(text=_FRAMES[self._frame_idx])
        self._frame_idx = (self._frame_idx + 1) % len(_FRAMES)
        self._after_id = self.after(_INTERVAL_MS, self._tick)
