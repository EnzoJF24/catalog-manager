"""
About dialog — small modal popup with app credits and contact link.

Triggered from the sidebar's ℹ button. Kept intentionally lightweight:
no images, no extra dependencies, no logo file required.
"""
from __future__ import annotations
import webbrowser
import customtkinter as ctk

from app.config.branding import APP_NAME, APP_VERSION, APP_AUTHOR
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED, BG_DEEPEST,
    ACCENT_PRIMARY, ACCENT_PRIMARY_H,
    ACCENT_BLUE, ACCENT_BLUE_H,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE, TEXT_LINK,
    RADIUS_CARD, RADIUS_BUTTON,
    font_title, font_label, font_small, font_bold,
)


# Contact info — kept here as the single source of truth for the dialog
AUTHOR_EMAIL = "enzofulcheri@gmail.com"


class AboutDialog(ctk.CTkToplevel):
    """Modal-ish About popup. Auto-centers over the parent window."""

    _instance: "AboutDialog | None" = None    # singleton guard

    def __init__(self, master):
        super().__init__(master)
        self.title("Acerca de")
        self.geometry("440x360")
        self.resizable(False, False)
        self.configure(fg_color=BG_BASE)
        self.transient(master)        # follows parent in z-order
        self.grab_set()               # modal
        self._center_over(master)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda *_: self._close())

    # ── Singleton helper so repeated clicks don't stack windows ───────────────
    @classmethod
    def open(cls, master):
        if cls._instance is not None and cls._instance.winfo_exists():
            cls._instance.lift()
            cls._instance.focus_force()
            return cls._instance
        cls._instance = cls(master)
        return cls._instance

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        # Main card
        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        card.grid(row=0, column=0, padx=18, pady=18, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        # App name + version
        ctk.CTkLabel(
            card, text="🗂  " + APP_NAME,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=ACCENT_PRIMARY,
        ).grid(row=0, column=0, padx=20, pady=(18, 2), sticky="w")

        ctk.CTkLabel(
            card, text=f"Versión {APP_VERSION}",
            font=font_small(), text_color=TEXT_MUTED,
        ).grid(row=1, column=0, padx=20, pady=(0, 10), sticky="w")

        # Separator
        ctk.CTkFrame(card, height=1, fg_color=BG_ELEVATED).grid(
            row=2, column=0, padx=20, pady=4, sticky="ew"
        )

        # Credits
        ctk.CTkLabel(
            card, text="Desarrollado por",
            font=font_small(), text_color=TEXT_MUTED,
        ).grid(row=3, column=0, padx=20, pady=(12, 0), sticky="w")

        ctk.CTkLabel(
            card, text=APP_AUTHOR,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_HEADING,
        ).grid(row=4, column=0, padx=20, pady=(0, 14), sticky="w")

        # Contact section
        ctk.CTkLabel(
            card, text="Contacto / Reportar un error",
            font=font_small(), text_color=TEXT_MUTED,
        ).grid(row=5, column=0, padx=20, pady=(2, 4), sticky="w")

        contact_row = ctk.CTkFrame(card, fg_color="transparent")
        contact_row.grid(row=6, column=0, padx=18, pady=(0, 14), sticky="ew")
        contact_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            contact_row, text="📧",
            font=ctk.CTkFont(size=15), text_color=TEXT_LINK,
        ).grid(row=0, column=0, padx=(4, 8), pady=4)

        ctk.CTkButton(
            contact_row, text=AUTHOR_EMAIL, height=30,
            fg_color=BG_DEEPEST, hover_color=BG_ELEVATED,
            text_color=TEXT_LINK, font=font_label(),
            corner_radius=6, anchor="w",
            command=self._open_email,
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=4)

        # Footer (copyright/license)
        ctk.CTkLabel(
            card,
            text=f"© {APP_AUTHOR}  ·  Uso interno autorizado",
            font=ctk.CTkFont(size=10), text_color=TEXT_SUBTLE,
        ).grid(row=7, column=0, padx=20, pady=(8, 14), sticky="w")

        # Close button
        ctk.CTkButton(
            self, text="Cerrar", height=34, width=120,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_H,
            font=font_bold(), corner_radius=RADIUS_BUTTON,
            command=self._close,
        ).grid(row=1, column=0, padx=18, pady=(0, 14))

    # ── Behaviour ─────────────────────────────────────────────────────────────

    def _open_email(self):
        try:
            webbrowser.open(f"mailto:{AUTHOR_EMAIL}?subject=Catálogo%20-%20Consulta")
        except Exception:
            pass

    def _center_over(self, master):
        try:
            self.update_idletasks()
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width()
            mh = master.winfo_height()
            w  = self.winfo_width()
            h  = self.winfo_height()
            x  = mx + (mw - w) // 2
            y  = my + (mh - h) // 2
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _close(self):
        type(self)._instance = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
