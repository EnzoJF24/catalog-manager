"""
About dialog — small modal popup with app credits and contact link.

Triggered from the sidebar's info button. Kept intentionally lightweight:
no images, no extra dependencies, no logo file required.
"""
from __future__ import annotations
import webbrowser
import customtkinter as ctk

from app.config.branding import APP_NAME, APP_VERSION, APP_AUTHOR
from app.ui.icons import icon
from app.ui.theme import (
    BG_BASE, ACCENT, TEXT_PRIMARY, TEXT_MUTED, TEXT_SUBTLE, TEXT_LINK,
    font_title, font_label, font_small, font_sub,
    card, divider, primary_button, ghost_button,
)


# Contact info — kept here as the single source of truth for the dialog
AUTHOR_EMAIL = "enzofulcheri@gmail.com"


class AboutDialog(ctk.CTkToplevel):
    """Modal-ish About popup. Auto-centers over the parent window."""

    _instance: "AboutDialog | None" = None    # singleton guard

    def __init__(self, master):
        super().__init__(master)
        self.title("About")
        self.geometry("420x320")
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

        body = card(self, row=0, column=0, padx=18, pady=(18, 10), sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="w")
        mark = ctk.CTkFrame(head, width=40, height=40, corner_radius=10, fg_color=ACCENT)
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        mark.grid_propagate(False)
        ctk.CTkLabel(mark, text="", image=icon("logo", "#FFFFFF", 22)).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(head, text=APP_NAME, font=font_title(), text_color=TEXT_PRIMARY,
                     anchor="w").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(head, text=f"Version {APP_VERSION}", font=font_small(),
                     text_color=TEXT_MUTED, anchor="w").grid(row=1, column=1, sticky="w")

        divider(body).grid(row=1, column=0, padx=20, sticky="ew")

        ctk.CTkLabel(body, text="Developed by", font=font_small(), text_color=TEXT_SUBTLE,
                     anchor="w").grid(row=2, column=0, padx=20, pady=(14, 0), sticky="w")
        ctk.CTkLabel(body, text=APP_AUTHOR, font=font_sub(), text_color=TEXT_PRIMARY,
                     anchor="w").grid(row=3, column=0, padx=20, sticky="w")

        email = ghost_button(body, AUTHOR_EMAIL, self._open_email,
                             icon=icon("mail", TEXT_LINK, 15), height=30, text_color=TEXT_LINK)
        email.grid(row=4, column=0, padx=12, pady=(8, 16), sticky="w")

        ctk.CTkLabel(
            self, text=f"© {APP_AUTHOR}  ·  Licensed for internal use",
            font=font_small(), text_color=TEXT_SUBTLE,
        ).grid(row=1, column=0, padx=20, sticky="w")

        primary_button(self, "Close", self._close, width=96).grid(
            row=1, column=0, padx=18, pady=(4, 16), sticky="e")

    # ── Behaviour ─────────────────────────────────────────────────────────────

    def _open_email(self):
        try:
            webbrowser.open(f"mailto:{AUTHOR_EMAIL}?subject=Catalog%20Manager%20-%20Question")
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
