"""
Catálogo frame — genera el Excel (snapshot) y el PDF comercial.
Incluye la configuración visual del PDF (marca, colores, layout).
"""
from __future__ import annotations
import os
import sys
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, messagebox
from typing import Callable, Optional
import customtkinter as ctk

from app.config.settings import settings
from app.core.app_controller import AppController
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED, BG_DEEPEST,
    ACCENT_PRIMARY, ACCENT_PRIMARY_H,
    ACCENT_BLUE, ACCENT_BLUE_H,
    ACCENT_SUCCESS,
    ACCENT_WARNING,
    ACCENT_PURPLE, ACCENT_PURPLE_H,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    RADIUS_CARD, RADIUS_BUTTON,
    font_label, font_small, font_bold, font_mono,
)
from app.ui.components.spinner import Spinner
from app.ui.components.tooltip import Tooltip


# ── Helpers ──────────────────────────────────────────────────────────────────

def _open_file(path: Path):
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror("Error al abrir archivo", str(e))


def _humanize_delta(then: datetime) -> str:
    if then is None:
        return "—"
    delta = datetime.now() - then
    secs  = int(delta.total_seconds())
    if secs < 60:
        return "hace unos segundos"
    mins = secs // 60
    if mins < 60:
        return f"hace {mins} min"
    hours = mins // 60
    if hours < 24:
        return f"hace {hours} h"
    days = hours // 24
    if days == 1:
        return "hace 1 día"
    if days < 30:
        return f"hace {days} días"
    return "hace más de 1 mes"


def _safe_color(value: str) -> str:
    """Return a valid hex color or TEXT_SUBTLE as fallback."""
    v = value.strip()
    if v.startswith("#") and len(v) in (4, 7):
        try:
            int(v[1:], 16)
            return v
        except ValueError:
            pass
    return TEXT_SUBTLE


# ── Inline color picker (compact, single row) ────────────────────────────────

class InlineColorPicker(ctk.CTkFrame):
    """Compact color picker: hex entry + swatch + button — all in one horizontal row."""

    def __init__(self, parent, initial: str, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._var = ctk.StringVar(value=initial)

        self._entry = ctk.CTkEntry(self, textvariable=self._var, width=90, height=28)
        self._entry.grid(row=0, column=0, padx=(0, 4))

        self._swatch = ctk.CTkLabel(
            self, text="", width=28, height=28,
            corner_radius=6, fg_color=_safe_color(initial),
        )
        self._swatch.grid(row=0, column=1, padx=2)

        ctk.CTkButton(
            self, text="🎨", width=34, height=28,
            fg_color=BG_ELEVATED, hover_color=ACCENT_BLUE,
            font=ctk.CTkFont(size=12), corner_radius=6,
            command=self._open_picker,
        ).grid(row=0, column=2, padx=(2, 0))

        self._var.trace_add("write", lambda *_: self._swatch.configure(
            fg_color=_safe_color(self._var.get())
        ))

    def get(self) -> str:
        return self._var.get().strip()

    def _open_picker(self):
        initial = _safe_color(self._var.get())
        result = colorchooser.askcolor(
            color=initial, title="Elegir color",
            parent=self.winfo_toplevel(),
        )
        if result and result[1]:
            self._var.set(result[1].upper())


# ── Catálogo frame ───────────────────────────────────────────────────────────

class ExcelFrame(ctk.CTkFrame):
    """Solapa Catálogo — genera Excel/PDF + configura la apariencia del PDF."""

    def __init__(self, parent, controller: AppController,
                 navigate_cb: Optional[Callable[[str], None]] = None):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller  = controller
        self.navigate_cb = navigate_cb
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)   # console gets remaining height

        # ── Row 0: status bar ────────────────────────────────────────────────
        self._status_bar = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        self._status_bar.grid(row=0, column=0, padx=20, pady=(14, 6), sticky="ew")
        self._status_bar.grid_columnconfigure(1, weight=1)

        self._lbl_status = ctk.CTkLabel(
            self._status_bar, text="Cargando estado…",
            font=font_label(), text_color=TEXT_HEADING, anchor="w",
        )
        self._lbl_status.grid(row=0, column=0, columnspan=2, padx=14, pady=10, sticky="w")

        self._badge = ctk.CTkLabel(
            self._status_bar, text="",
            font=ctk.CTkFont(size=10, weight="bold"),
            corner_radius=6, fg_color="transparent",
            padx=8, pady=2,
        )
        self._badge.grid(row=0, column=2, padx=(0, 14), pady=10, sticky="e")
        # Tooltip — text rewritten per state inside _refresh_status()
        self._badge_tooltip = Tooltip(self._badge, "", wraplength=400)

        # ── Row 1: actions card ──────────────────────────────────────────────
        actions = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        actions.grid(row=1, column=0, padx=20, pady=6, sticky="ew")
        actions.grid_columnconfigure(1, weight=1)   # spacer — checkbox left, buttons right

        # Checkbox (left)
        self.active_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            actions, text="Solo activos",
            variable=self.active_only_var,
            text_color=TEXT_MUTED, font=font_small(),
            checkbox_width=18, checkbox_height=18,
        ).grid(row=0, column=0, padx=16, pady=14, sticky="w")

        # Buttons (right) — fixed width so they never stretch
        btn_box = ctk.CTkFrame(actions, fg_color="transparent")
        btn_box.grid(row=0, column=2, padx=(0, 14), pady=10, sticky="e")

        self._export_btn = ctk.CTkButton(
            btn_box, text="📥  Descargar Excel",
            height=38, width=200,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_H,
            font=font_bold(), corner_radius=RADIUS_BUTTON,
            command=self._export,
        )
        self._export_btn.grid(row=0, column=0, padx=(0, 8))

        self._pdf_btn = ctk.CTkButton(
            btn_box, text="🚀  Generar PDF",
            height=38, width=190,
            fg_color=ACCENT_PURPLE, hover_color=ACCENT_PURPLE_H,
            font=font_bold(), corner_radius=RADIUS_BUTTON,
            command=self._gen_pdf,
        )
        self._pdf_btn.grid(row=0, column=1)

        # Shared spinner (below the toolbar row, left-aligned)
        self._action_spinner = Spinner(actions, icon_color=ACCENT_BLUE)
        self._action_spinner.grid(row=1, column=0, columnspan=3,
                                   padx=14, pady=(0, 6), sticky="w")

        # ── Row 2: PDF config card ───────────────────────────────────────────
        cfg = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        cfg.grid(row=2, column=0, padx=20, pady=6, sticky="ew")
        cfg.grid_columnconfigure(1, weight=1)
        cfg.grid_columnconfigure(3, weight=1)

        # Header
        ctk.CTkLabel(
            cfg, text="🎨  Configuración del catálogo PDF",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT_PRIMARY,
        ).grid(row=0, column=0, columnspan=4, padx=14, pady=(12, 4), sticky="w")

        ctk.CTkFrame(cfg, height=1, fg_color=BG_ELEVATED).grid(
            row=1, column=0, columnspan=4, padx=14, pady=(0, 8), sticky="ew"
        )

        # Nombre empresa | Slogan
        ctk.CTkLabel(
            cfg, text="Nombre empresa:", width=116,
            font=font_small(), text_color=TEXT_MUTED, anchor="e",
        ).grid(row=2, column=0, padx=(14, 6), pady=4, sticky="e")
        self.company_var = ctk.StringVar(
            value=self.controller.get_setting("company_name", "Mi Empresa")
        )
        ctk.CTkEntry(cfg, textvariable=self.company_var, height=28).grid(
            row=2, column=1, padx=(0, 14), pady=4, sticky="ew"
        )
        ctk.CTkLabel(
            cfg, text="Slogan:", width=72,
            font=font_small(), text_color=TEXT_MUTED, anchor="e",
        ).grid(row=2, column=2, padx=(0, 6), pady=4, sticky="e")
        self.slogan_var = ctk.StringVar(
            value=self.controller.get_setting("company_slogan", "Catálogo de Productos")
        )
        ctk.CTkEntry(cfg, textvariable=self.slogan_var, height=28).grid(
            row=2, column=3, padx=(0, 14), pady=4, sticky="ew"
        )

        # Color primario | Color secundario
        ctk.CTkLabel(
            cfg, text="Color primario:", width=116,
            font=font_small(), text_color=TEXT_MUTED, anchor="e",
        ).grid(row=3, column=0, padx=(14, 6), pady=4, sticky="e")
        self._color_primary = InlineColorPicker(
            cfg, self.controller.get_setting("primary_color", "#C0392B")
        )
        self._color_primary.grid(row=3, column=1, padx=(0, 14), pady=4, sticky="w")

        ctk.CTkLabel(
            cfg, text="Color secundario:", width=72,
            font=font_small(), text_color=TEXT_MUTED, anchor="e",
        ).grid(row=3, column=2, padx=(0, 6), pady=4, sticky="e")
        self._color_secondary = InlineColorPicker(
            cfg, self.controller.get_setting("secondary_color", "#2C3E50")
        )
        self._color_secondary.grid(row=3, column=3, padx=(0, 14), pady=4, sticky="w")

        # Productos por fila (left) | Guardar (right, fixed width)
        ctk.CTkLabel(
            cfg, text="Productos por fila:", width=116,
            font=font_small(), text_color=TEXT_MUTED, anchor="e",
        ).grid(row=4, column=0, padx=(14, 6), pady=(4, 14), sticky="e")
        self.cols_var = ctk.StringVar(
            value=self.controller.get_setting("products_per_row", "2")
        )
        ctk.CTkOptionMenu(
            cfg, variable=self.cols_var, values=["1", "2", "3"],
            width=70, height=28,
        ).grid(row=4, column=1, padx=(0, 14), pady=(4, 14), sticky="w")

        ctk.CTkButton(
            cfg, text="💾  Guardar configuración",
            height=32, width=220,
            fg_color=ACCENT_PRIMARY, hover_color=ACCENT_PRIMARY_H,
            font=font_bold(), corner_radius=8,
            command=self._save_pdf_config,
        ).grid(row=4, column=2, columnspan=2, padx=(0, 14), pady=(4, 14), sticky="e")

        # ── Row 3: console log ───────────────────────────────────────────────
        log_card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        log_card.grid(row=3, column=0, padx=20, pady=(6, 14), sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            log_card, text="📜  Registro de operaciones",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_HEADING,
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        self.result_log = ctk.CTkTextbox(
            log_card, fg_color=BG_DEEPEST, text_color=ACCENT_SUCCESS,
            font=font_mono(),
        )
        self.result_log.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

    # ── Status refresh ────────────────────────────────────────────────────────

    def _refresh_status(self):
        try:
            stats  = self.controller.get_stats()
            status = self.controller.get_excel_status()
        except Exception:
            return

        total   = stats.get("total", 0)
        db_mod  = status["last_db_mod"]
        excel_g = status["last_excel_gen"]

        parts = [f"📦 {total} productos"]
        if db_mod:
            parts.append(f"🕐 Última modificación: {_humanize_delta(db_mod)}")
        else:
            parts.append("🕐 Sin modificaciones")
        if excel_g:
            parts.append(f"📥 Excel: {_humanize_delta(excel_g)}")
        else:
            parts.append("📥 Sin Excel generado")

        self._lbl_status.configure(text="  ·  ".join(parts))

        if status["is_stale"]:
            self._badge.configure(
                text="⚠ DESACTUALIZADO", text_color="#FFFFFF",
                fg_color=ACCENT_WARNING,
            )
            self._status_bar.configure(border_color=ACCENT_WARNING, border_width=1)
            self._badge_tooltip.update_text(
                "El Excel descargado quedó desactualizado.\n\n"
                "Se realizaron cambios en la base de datos (importaciones o ediciones)\n"
                "después de la última generación del archivo.\n\n"
                "Volvé a descargarlo para tener los datos al día."
            )
        elif status["has_excel"]:
            self._badge.configure(
                text="✓ ACTUALIZADO", text_color="#FFFFFF",
                fg_color=ACCENT_SUCCESS,
            )
            self._status_bar.configure(border_color=ACCENT_SUCCESS, border_width=1)
            self._badge_tooltip.update_text(
                "El Excel está al día con la base de datos.\n\n"
                "No se hicieron cambios desde la última generación."
            )
        else:
            self._badge.configure(text="", fg_color="transparent")
            self._status_bar.configure(border_width=0)
            self._badge_tooltip.update_text("")

    # ── Save PDF config ───────────────────────────────────────────────────────

    def _save_pdf_config(self):
        try:
            self.controller.set_setting("company_name",   self.company_var.get().strip())
            self.controller.set_setting("company_slogan", self.slogan_var.get().strip())
            self.controller.set_setting("primary_color",   self._color_primary.get())
            self.controller.set_setting("secondary_color", self._color_secondary.get())
            self.controller.set_setting("products_per_row", self.cols_var.get())
            self._log("✓  Configuración guardada. Se aplicará en la próxima generación de PDF.")
            messagebox.showinfo(
                "Guardado",
                "Configuración guardada.\n"
                "Los cambios se aplicarán en la próxima generación del PDF.",
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Export Excel ──────────────────────────────────────────────────────────

    def _export(self):
        self._set_busy(True, blue=True)
        self._action_spinner.start("Generando Excel...")

        def _run():
            try:
                path = self.controller.export_excel(self.active_only_var.get())
                self.after(0, lambda p=path: self._export_done(p))
            except Exception as e:
                self.after(0, lambda err=str(e): self._generic_error("Excel", err))

        threading.Thread(target=_run, daemon=True).start()

    def _export_done(self, path: Path):
        self._action_spinner.stop()
        self._set_busy(False)
        self._refresh_status()
        self._log(f"✓  Excel guardado: {settings.display_path(path)}")
        abrir = messagebox.askyesno(
            "Excel generado",
            f"Archivo guardado en:\n{path}\n\n¿Querés abrirlo ahora?",
        )
        if abrir:
            _open_file(path)

    # ── Generate PDF ──────────────────────────────────────────────────────────

    def _gen_pdf(self):
        self._set_busy(True, blue=False)
        self._action_spinner.start("Generando catálogo PDF...")

        def _run():
            try:
                path = self.controller.generate_catalog_pdf()
                self.after(0, lambda p=path: self._pdf_done(p))
            except Exception as e:
                self.after(0, lambda err=str(e): self._generic_error("PDF", err))

        threading.Thread(target=_run, daemon=True).start()

    def _pdf_done(self, path: Path):
        self._action_spinner.stop()
        self._set_busy(False)
        self._log(f"✓  PDF guardado: {settings.display_path(path)}")
        abrir = messagebox.askyesno(
            "Catálogo PDF generado",
            f"Catálogo guardado en:\n{path}\n\n¿Querés abrirlo ahora?",
        )
        if abrir:
            _open_file(path)

    def _generic_error(self, context: str, error: str):
        self._action_spinner.stop()
        self._set_busy(False)
        self._log(f"✗  Error ({context}): {error}")
        messagebox.showerror(f"Error — {context}", error)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool, blue: bool = True):
        state = "disabled" if busy else "normal"
        self._export_btn.configure(state=state)
        self._pdf_btn.configure(state=state)
        # Spinner colour matches the active action
        if busy:
            self._action_spinner._icon.configure(
                text_color=ACCENT_BLUE if blue else ACCENT_PURPLE
            )

    def _log(self, msg: str):
        ts = datetime.now().strftime("[%H:%M:%S] ")
        self.result_log.insert("end", ts + msg + "\n")
        self.result_log.see("end")

    def on_show(self):
        self._refresh_status()

    def on_hide(self):
        pass
