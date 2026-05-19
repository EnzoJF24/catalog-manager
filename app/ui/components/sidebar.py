"""
Sidebar de navegación — usa branding y theme centralizados.
"""
from __future__ import annotations
from typing import Callable
import customtkinter as ctk

from app.config.branding import APP_NAME, APP_VERSION, APP_AUTHOR
from app.ui.theme import (
    BG_CARD, BG_ELEVATED, ACCENT_PRIMARY,
    TEXT_PRIMARY, TEXT_MUTED, TEXT_SUBTLE, TEXT_LINK,
    font_small,
)
from app.ui.components.about_dialog import AboutDialog

NAV_ITEMS = [
    ("dashboard", "📊 Dashboard",      "dashboard"),
    ("import",    "📥 Importar PDF",   "import"),
    ("products",  "📦 Productos",       "products"),
    ("excel",     "📋 Catálogo",        "excel"),
    ("files",     "📁 Archivos",        "files"),
    ("settings",  "🛠 Herramientas",   "settings"),
]


class Sidebar(ctk.CTkFrame):
    def __init__(self, parent, navigate_cb: Callable[[str], None]):
        super().__init__(parent, width=210, fg_color=BG_CARD, corner_radius=0)
        self.navigate_cb = navigate_cb
        self.grid_propagate(False)
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(len(NAV_ITEMS) + 2, weight=1)

        # App name
        ctk.CTkLabel(
            self,
            text="🗂 " + APP_NAME,
            font=ctk.CTkFont(family="Helvetica", size=13, weight="bold"),
            text_color=ACCENT_PRIMARY,
            wraplength=185,
            justify="left",
        ).grid(row=0, column=0, padx=16, pady=(20, 4), sticky="w")

        # Separator line
        ctk.CTkFrame(self, height=1, fg_color=BG_ELEVATED).grid(
            row=1, column=0, padx=12, pady=(0, 10), sticky="ew"
        )

        # Nav buttons
        for i, (key, label, _) in enumerate(NAV_ITEMS):
            btn = ctk.CTkButton(
                self,
                text=label,
                anchor="w",
                height=40,
                corner_radius=8,
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                hover_color=BG_ELEVATED,
                text_color=TEXT_MUTED,
                border_spacing=8,
                command=lambda k=key: self.navigate_cb(k),
            )
            btn.grid(row=i + 2, column=0, padx=10, pady=2, sticky="ew")
            self._buttons[key] = btn

        # Footer: version + author + ℹ button (opens About dialog)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=99, column=0, padx=10, pady=(4, 14), sticky="sew")
        footer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            footer,
            text=f"v{APP_VERSION}  ·  {APP_AUTHOR}",
            font=font_small(),
            text_color=TEXT_SUBTLE,
            wraplength=160,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, padx=(4, 4), sticky="w")

        ctk.CTkButton(
            footer, text="ℹ", width=26, height=26,
            fg_color="transparent", hover_color=BG_ELEVATED,
            text_color=TEXT_LINK,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=6,
            command=self._open_about,
        ).grid(row=0, column=1, padx=(0, 4), sticky="e")

    def _open_about(self):
        try:
            AboutDialog.open(self.winfo_toplevel())
        except Exception:
            pass

    def set_active(self, key: str):
        for k, btn in self._buttons.items():
            if k == key:
                btn.configure(fg_color=BG_ELEVATED, text_color=TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_MUTED)
