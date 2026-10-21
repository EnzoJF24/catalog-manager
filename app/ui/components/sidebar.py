"""
Navigation sidebar — uses centralised branding and theme.
"""
from __future__ import annotations
from typing import Callable
import customtkinter as ctk

from app.config.branding import APP_NAME, APP_VERSION
from app.ui.icons import icon
from app.ui.theme import (
    BG_SIDEBAR, BG_ELEVATED, BG_HOVER, BORDER, ACCENT, ACCENT_SOFT,
    TEXT_PRIMARY, TEXT_MUTED, TEXT_SUBTLE,
    RADIUS_BUTTON, FONT_FAMILY, FONT_SEMIBOLD,
    font_small,
)
from app.ui.components.about_dialog import AboutDialog

# (key, label, icon name)
NAV_ITEMS = [
    ("dashboard", "Dashboard",  "dashboard"),
    ("import",    "Import PDF", "upload"),
    ("products",  "Products",   "package"),
    ("excel",     "Catalog",    "book"),
    ("files",     "Files",      "folder"),
    ("settings",  "Tools",      "sliders"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, navigate_cb: Callable[[str], None]):
        super().__init__(parent, width=224, fg_color=BG_SIDEBAR, corner_radius=0)
        self.navigate_cb = navigate_cb
        self.grid_propagate(False)
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._icons: dict[str, str] = {}
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Wordmark
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, padx=18, pady=(22, 22), sticky="w")
        mark = ctk.CTkFrame(brand, width=30, height=30, corner_radius=8, fg_color=ACCENT)
        mark.grid(row=0, column=0, rowspan=2)
        mark.grid_propagate(False)
        ctk.CTkLabel(mark, text="", image=icon("logo", "#FFFFFF", 16)).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(
            brand, text=APP_NAME,
            font=ctk.CTkFont(family=FONT_SEMIBOLD, size=14),
            text_color=TEXT_PRIMARY, anchor="w",
        ).grid(row=0, column=1, padx=(10, 0), sticky="sw")
        ctk.CTkLabel(
            brand, text="Supplier PDF → catalog",
            font=font_small(), text_color=TEXT_SUBTLE, anchor="w",
        ).grid(row=1, column=1, padx=(10, 0), sticky="nw")

        # Navigation
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=1, column=0, padx=12, sticky="ew")
        nav.grid_columnconfigure(0, weight=1)
        for i, (key, label, icon_name) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                nav, text=label, anchor="w", height=36,
                image=icon(icon_name, TEXT_MUTED, 18), compound="left",
                corner_radius=RADIUS_BUTTON,
                font=ctk.CTkFont(family=FONT_FAMILY, size=13),
                fg_color="transparent", hover_color=BG_HOVER,
                text_color=TEXT_MUTED, border_spacing=10,
                command=lambda k=key: self.navigate_cb(k),
            )
            btn.grid(row=i, column=0, pady=1, sticky="ew")
            self._buttons[key] = btn
            self._icons[key] = icon_name

        # Footer
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=3, column=0, sticky="ew"
        )
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, padx=14, pady=10, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer, text=f"v{APP_VERSION}", font=font_small(),
            text_color=TEXT_SUBTLE, anchor="w",
        ).grid(row=0, column=0, padx=4, sticky="w")
        ctk.CTkButton(
            footer, text="", image=icon("info", TEXT_SUBTLE, 16),
            width=28, height=28, corner_radius=6,
            fg_color="transparent", hover_color=BG_ELEVATED,
            command=self._open_about,
        ).grid(row=0, column=1, sticky="e")

    def _open_about(self):
        try:
            AboutDialog.open(self.winfo_toplevel())
        except Exception:
            pass

    def set_active(self, key: str):
        for k, btn in self._buttons.items():
            active = k == key
            btn.configure(
                fg_color=ACCENT_SOFT if active else "transparent",
                text_color=TEXT_PRIMARY if active else TEXT_MUTED,
                image=icon(self._icons[k], ACCENT if active else TEXT_MUTED, 18),
            )
