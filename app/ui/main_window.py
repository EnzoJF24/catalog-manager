"""
Main window: clean frame transitions + responsive resize + integrated FilesFrame.
"""
from __future__ import annotations
from typing import Optional

import customtkinter as ctk

from app.config.branding import WINDOW_TITLE
from app.core.app_controller import AppController
from app.ui.components.sidebar import Sidebar
from app.ui.components.dashboard_frame import DashboardFrame
from app.ui.components.import_frame import ImportFrame
from app.ui.components.products_frame import ProductsFrame
from app.ui.components.excel_frame import ExcelFrame
from app.ui.components.files_frame import FilesFrame
from app.ui.components.settings_frame import SettingsFrame
from app.logging_config.logger import get_logger

log = get_logger("main_window")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Global UI polish: readable text color on disabled buttons.
from app.ui.theme import apply_global_button_disabled_color
apply_global_button_disabled_color()


class MainWindow(ctk.CTk):

    def __init__(self, controller: AppController):
        super().__init__()
        self.controller  = controller
        self._active_key: Optional[str] = None

        self.title(WINDOW_TITLE)
        self.geometry("1320x820")
        self.minsize(1280, 820)

        self._build_layout()
        self._show_frame("dashboard")

        # Responsive resize: force a re-layout when the window changes size
        self.bind("<Configure>", self._on_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        log.info("Main window opened")

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(self, self._show_frame)
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        # Uniform-background container → avoids a flash when switching tabs
        from app.ui.theme import BG_BASE
        self.content = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._frames: dict[str, ctk.CTkFrame] = {
            "dashboard": DashboardFrame(self.content, self.controller, self._show_frame),
            "import":    ImportFrame(self.content, self.controller),
            "products":  ProductsFrame(self.content, self.controller),
            "excel":     ExcelFrame(self.content, self.controller, self._show_frame),
            "files":     FilesFrame(self.content, self.controller),
            "settings":  SettingsFrame(self.content, self.controller),
        }
        for frame in self._frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_frame(self, name: str, **kwargs):
        """
        Switch to a frame. Optional **kwargs are forwarded to the target's
        `apply_external_args(**kwargs)` method after on_show — used by Dashboard
        to pre-filter Products via health-chip double-click.
        """
        if name == self._active_key and not kwargs:
            return

        target = self._frames.get(name)
        if target is None:
            log.warning(f"Unknown frame: {name}")
            return

        # 1. on_hide on the outgoing frame (skipped if we are already on it)
        if self._active_key and self._active_key != name:
            prev = self._frames[self._active_key]
            if hasattr(prev, "on_hide"):
                try:
                    prev.on_hide()
                except Exception as e:
                    log.warning(f"on_hide error ({self._active_key}): {e}")

        # 2. Raise the frame and update state before the repaint
        target.tkraise()
        self._active_key = name
        self.sidebar.set_active(name)
        self.update_idletasks()

        # 3. Defer on_show by 1 ms so the frame fully repaints before its
        #    content starts populating (avoids a visual artifact).
        self.after(1, lambda t=target, n=name, k=kwargs: self._run_on_show(t, n, k))
        log.debug(f"→ {name} {kwargs if kwargs else ''}")

    def _run_on_show(self, target, name: str, kwargs: dict):
        if name != self._active_key:
            return  # The user moved to another tab before the repaint
        if hasattr(target, "on_show"):
            try:
                target.on_show()
            except Exception as e:
                log.warning(f"on_show error ({name}): {e}")
        # Apply external args (e.g., Dashboard → Products with health_filter)
        if kwargs and hasattr(target, "apply_external_args"):
            try:
                target.apply_external_args(**kwargs)
            except Exception as e:
                log.warning(f"apply_external_args error ({name}): {e}")

    # ── Resize ────────────────────────────────────────────────────────────────

    def _on_configure(self, event):
        """Propagate resize to all frames to avoid visual artifacts."""
        if event.widget is self:
            self.update_idletasks()

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        # Warn if ProductsFrame has unsaved inline edits
        products_frame = self._frames.get("products")
        if products_frame and getattr(products_frame, "_pending", None):
            from tkinter import messagebox
            n = len(products_frame._pending)
            ok = messagebox.askyesno(
                "Unsaved changes",
                f"There are {n} unsaved change(s) in Products.\n"
                "Close anyway? Pending changes will be lost.",
            )
            if not ok:
                return

        if self._active_key:
            frame = self._frames.get(self._active_key)
            if frame and hasattr(frame, "on_hide"):
                try:
                    frame.on_hide()
                except Exception:
                    pass
        log.info("Closing application")
        self.destroy()
