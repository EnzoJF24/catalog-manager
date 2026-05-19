"""
Settings frame: márgenes globales, historial, parsers registrados.
La configuración de marca/empresa y del PDF vive en la solapa Catálogo.
"""
from __future__ import annotations
import threading
from tkinter import messagebox
import customtkinter as ctk

from app.core.app_controller import AppController
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_DEEPEST,
    ACCENT_BLUE, ACCENT_BLUE_H,
    ACCENT_SUCCESS,
    ACCENT_PURPLE, ACCENT_PURPLE_H,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    RADIUS_CARD, RADIUS_BUTTON,
    font_title, font_label, font_small, font_bold, font_mono,
)
from app.ui.components.spinner import Spinner


class SettingsFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller = controller
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        scroll.grid_rowconfigure(2, weight=1)

        # Título
        ctk.CTkLabel(
            scroll, text="Configuración",
            font=font_title(), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=24, pady=(24, 10), sticky="w")

        # ── Márgenes ─────────────────────────────────────────────────────────
        margin_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        margin_card.grid(row=1, column=0, padx=24, pady=(0, 10), sticky="ew")
        margin_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            margin_card, text="💰  Márgenes y Precios",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT_PURPLE,
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

        ctk.CTkLabel(
            margin_card,
            text="Re-aplica el margen global configurado a todos los productos activos de la base de datos.\n"
                 "Útil cuando cambiás el % de margen y querés actualizar todos los precios de una vez.",
            font=font_small(), text_color=TEXT_MUTED, justify="left",
        ).grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 8), sticky="w")

        self._reapply_btn = ctk.CTkButton(
            margin_card, text="💰  Re-aplicar margen a todos los productos", height=38,
            fg_color=ACCENT_PURPLE, hover_color=ACCENT_PURPLE_H,
            font=font_bold(), corner_radius=RADIUS_BUTTON,
            command=self._reapply_margins,
        )
        self._reapply_btn.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 4), sticky="ew")

        self._reapply_spinner = Spinner(margin_card, icon_color=ACCENT_PURPLE)
        self._reapply_spinner.grid(row=3, column=0, columnspan=2,
                                    padx=16, pady=(0, 14), sticky="w")

        # ── Historial ────────────────────────────────────────────────────────
        hist = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        hist.grid(row=2, column=0, padx=24, pady=10, sticky="nsew")
        hist.grid_columnconfigure(0, weight=1)
        hist.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            hist, text="📜  Historial de importaciones",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT_BLUE,
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        self.hist_text = ctk.CTkTextbox(
            hist, fg_color=BG_DEEPEST, text_color=TEXT_HEADING,
            font=font_mono(),
        )
        self.hist_text.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")

        ctk.CTkButton(
            hist, text="🔄  Cargar historial", height=36,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_H,
            font=font_label(),
            command=self._load_history,
        ).grid(row=2, column=0, padx=16, pady=(0, 14), sticky="w")

        # ── Parsers registrados ──────────────────────────────────────────────
        pf = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        pf.grid(row=3, column=0, padx=24, pady=10, sticky="ew")
        pf.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            pf, text="🔌  Parsers registrados",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT_SUCCESS,
        ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")

        from app.parsers.parser_factory import ParserFactory
        parsers = ParserFactory.list_parsers()
        for i, p in enumerate(parsers):
            ctk.CTkLabel(
                pf,
                text=f"  ✓  {p['name']}  ({p['class']})",
                font=font_label(), text_color=TEXT_HEADING,
            ).grid(row=i + 1, column=0, padx=16, pady=3, sticky="w")

        ctk.CTkLabel(
            pf,
            text="Para agregar proveedores: implementa BaseParser y regístralo en parser_factory.py",
            font=font_small(), text_color=TEXT_SUBTLE,
        ).grid(row=len(parsers) + 1, column=0, padx=16, pady=(4, 14), sticky="w")

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _reapply_margins(self):
        ok = messagebox.askyesno(
            "Re-aplicar margen",
            "¿Aplicar el margen global configurado a todos los productos activos?\n\n"
            "Esto recalculará el Precio Final de cada producto usando el margen actual.",
        )
        if not ok:
            return

        self._reapply_btn.configure(state="disabled")
        self._reapply_spinner.start("Re-aplicando margen a todos los productos...")

        def _run():
            try:
                count = self.controller.reapply_margins()
                self.after(0, lambda c=count: self._reapply_done(c))
            except Exception as e:
                self.after(0, lambda err=str(e): self._reapply_error(err))

        threading.Thread(target=_run, daemon=True).start()

    def _reapply_done(self, count: int):
        self._reapply_spinner.stop()
        self._reapply_btn.configure(state="normal")
        messagebox.showinfo("Éxito", f"✓  Margen re-aplicado a {count} productos.")

    def _reapply_error(self, error: str):
        self._reapply_spinner.stop()
        self._reapply_btn.configure(state="normal")
        messagebox.showerror("Error", error)

    def _load_history(self):
        try:
            sessions = self.controller.get_session_history(limit=15)
            self.hist_text.delete("1.0", "end")
            if not sessions:
                self.hist_text.insert("end", "Sin historial de importaciones.\n")
                return
            import json
            for s in sessions:
                started = str(s.get("started_at", ""))[:16]
                warns_raw = s.get("warnings_json", "[]") or "[]"
                try:
                    warns = json.loads(warns_raw)
                except Exception:
                    warns = []
                skipped = [w for w in warns if "descartados" in w.lower() or "SKIPPED" in w]
                skip_tag = f"  ⚠ {skipped[0]}" if skipped else ""
                line = (
                    f"[{started}]  ID={s.get('session_id','?')}  "
                    f"Proveedor={s.get('supplier_name','?')}  "
                    f"Productos={s.get('products_found', 0)}  "
                    f"Imgs={s.get('images_matched', 0)}/{s.get('images_found', 0)}"
                    f"{skip_tag}\n"
                )
                self.hist_text.insert("end", line)
        except Exception as e:
            self.hist_text.insert("end", f"Error: {e}\n")

    def on_show(self):
        self._load_history()

    def on_hide(self):
        pass
