"""
Catalog frame — generates the Excel snapshot and the commercial PDF.
Includes the PDF's visual settings (company, colors, layout) with a live preview.
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
from app.ui.icons import icon
from app.ui.theme import (
    BG_BASE, BG_ELEVATED, BG_DEEPEST, BORDER, BORDER_STRONG,
    ACCENT, TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    PAGE_PADX, RADIUS_BUTTON, FONT_SEMIBOLD, FONT_FAMILY,
    font_label, font_small, font_mono,
    card, section_title, page_header, primary_button, secondary_button, icon_button,
    entry, option_menu, field_caption, pill, set_pill, fmt_int,
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
        messagebox.showerror("Could not open file", str(e))


def _humanize_delta(then: datetime) -> str:
    if then is None:
        return "—"
    delta = datetime.now() - then
    secs  = int(delta.total_seconds())
    if secs < 60:
        return "a few seconds ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    if days == 1:
        return "1 day ago"
    if days < 30:
        return f"{days} days ago"
    return "over 1 month ago"


def _safe_color(value: str, fallback: str = TEXT_SUBTLE) -> str:
    """Return a valid hex color or the fallback."""
    v = value.strip()
    if v.startswith("#") and len(v) in (4, 7):
        try:
            int(v[1:], 16)
            return v
        except ValueError:
            pass
    return fallback


# ── Inline color picker (compact, single row) ────────────────────────────────

class InlineColorPicker(ctk.CTkFrame):
    """Hex entry + swatch button that opens the system colour chooser."""

    def __init__(self, parent, initial: str, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._var = ctk.StringVar(value=initial)

        self._swatch = ctk.CTkButton(
            self, text="", width=34, height=34, corner_radius=RADIUS_BUTTON,
            fg_color=_safe_color(initial), hover_color=_safe_color(initial),
            border_width=1, border_color=BORDER_STRONG, command=self._open_picker,
        )
        self._swatch.grid(row=0, column=0, padx=(0, 8))
        entry(self, self._var, width=104).grid(row=0, column=1)

        self._var.trace_add("write", lambda *_: self._sync_swatch())

    @property
    def var(self) -> ctk.StringVar:
        return self._var

    def get(self) -> str:
        return self._var.get().strip()

    def _sync_swatch(self):
        c = _safe_color(self._var.get())
        self._swatch.configure(fg_color=c, hover_color=c)

    def _open_picker(self):
        result = colorchooser.askcolor(
            color=_safe_color(self._var.get()), title="Choose color",
            parent=self.winfo_toplevel(),
        )
        if result and result[1]:
            self._var.set(result[1].upper())


# ── Live PDF preview ─────────────────────────────────────────────────────────

class CatalogPreview(ctk.CTkFrame):
    """Miniature of a catalog page reflecting the current branding settings."""

    def __init__(self, parent):
        super().__init__(parent, fg_color="#FFFFFF", corner_radius=6, width=250, height=320,
                         border_width=1, border_color=BORDER)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._header = ctk.CTkFrame(self, height=22, corner_radius=0)
        self._header.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 0))
        self._header.grid_propagate(False)
        self._header_lbl = ctk.CTkLabel(self._header, text="", text_color="#FFFFFF",
                                        font=ctk.CTkFont(family=FONT_SEMIBOLD, size=9), anchor="w")
        self._header_lbl.place(x=10, rely=0.5, anchor="w")

        self._category = ctk.CTkFrame(self, height=16, corner_radius=4)
        self._category.grid(row=1, column=0, sticky="ew", padx=12, pady=(12, 8))
        self._category.grid_propagate(False)
        ctk.CTkLabel(self._category, text="VALVES", text_color="#FFFFFF",
                     font=ctk.CTkFont(family=FONT_SEMIBOLD, size=8)).place(x=8, rely=0.5, anchor="w")

        self._grid = ctk.CTkFrame(self, fg_color="transparent")
        self._grid.grid(row=2, column=0, sticky="nsew", padx=12)

        self._footer = ctk.CTkFrame(self, height=16, corner_radius=0)
        self._footer.grid(row=3, column=0, sticky="ew", padx=1, pady=(0, 1))

        self._prices = ["$23.48", "$27.40", "$27.99", "$30.30", "$23.84", "$28.42"]

    def render(self, company: str, primary: str, secondary: str, per_row: int):
        primary   = _safe_color(primary, ACCENT)
        secondary = _safe_color(secondary, "#0B2E44")
        self._header.configure(fg_color=primary)
        self._header_lbl.configure(text=(company or "My Company").upper()[:34])
        self._category.configure(fg_color=primary)
        self._footer.configure(fg_color=secondary)

        for w in self._grid.winfo_children():
            w.destroy()
        per_row = max(1, min(3, per_row))
        rows = {1: 2, 2: 2, 3: 3}[per_row]
        for c in range(per_row):
            self._grid.grid_columnconfigure(c, weight=1, uniform="tile")
        for i in range(per_row * rows):
            tile = ctk.CTkFrame(self._grid, fg_color="transparent")
            tile.grid(row=i // per_row, column=i % per_row, padx=3, pady=3, sticky="nsew")
            tile.grid_columnconfigure(0, weight=1)
            ctk.CTkFrame(tile, fg_color="#E9ECEF", corner_radius=3,
                         height={1: 70, 2: 52, 3: 34}[per_row]).grid(row=0, column=0, sticky="ew")
            ctk.CTkFrame(tile, fg_color="#C9CED6", corner_radius=2, height=4).grid(
                row=1, column=0, padx=8, pady=(5, 2), sticky="ew")
            ctk.CTkLabel(tile, text=self._prices[i % len(self._prices)], text_color=primary,
                         font=ctk.CTkFont(family=FONT_SEMIBOLD, size=9), height=14).grid(row=2, column=0)


# ── Catalog frame ────────────────────────────────────────────────────────────

class ExcelFrame(ctk.CTkFrame):
    """Catalog tab — generates Excel/PDF + configures the PDF's appearance."""

    def __init__(self, parent, controller: AppController,
                 navigate_cb: Optional[Callable[[str], None]] = None):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller  = controller
        self.navigate_cb = navigate_cb
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(3, weight=1)

        head = page_header(self, "Catalog", "Export the price list to Excel or CSV, or publish the PDF catalog.")
        head.grid(row=0, column=0, columnspan=2, padx=PAGE_PADX, pady=(26, 18), sticky="ew")
        actions = ctk.CTkFrame(head, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        self.active_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            actions, text="Active only", variable=self.active_only_var,
            font=font_label(), text_color=TEXT_MUTED,
            checkbox_width=18, checkbox_height=18, corner_radius=5, border_width=1,
            fg_color=ACCENT, border_color=BORDER_STRONG, hover_color=BG_ELEVATED,
        ).grid(row=0, column=0, padx=(0, 16))
        self._export_btn = secondary_button(actions, "Export Excel", self._export,
                                            icon=icon("sheet", TEXT_HEADING, 15), width=130)
        self._export_btn.grid(row=0, column=1, padx=(0, 8))
        self._csv_btn = secondary_button(actions, "Export CSV", self._export_csv,
                                         icon=icon("sheet", TEXT_HEADING, 15), width=120)
        self._csv_btn.grid(row=0, column=2, padx=(0, 8))
        self._pdf_btn = primary_button(actions, "Generate PDF", self._gen_pdf,
                                       icon=icon("file_text", "#FFFFFF", 15), width=140)
        self._pdf_btn.grid(row=0, column=3)

        # ── Status strip ─────────────────────────────────────────────────────
        self._status_bar = card(self, row=1, column=0, columnspan=2, padx=PAGE_PADX, pady=(0, 12), sticky="ew")
        self._status_bar.grid_columnconfigure(1, weight=1)
        self._action_spinner = Spinner(self._status_bar, icon_color=ACCENT)
        self._action_spinner.grid(row=0, column=0, padx=(16, 0), pady=10, sticky="w")
        self._lbl_status = ctk.CTkLabel(self._status_bar, text="Loading status…", font=font_label(),
                                        text_color=TEXT_HEADING, anchor="w")
        self._lbl_status.grid(row=0, column=1, padx=(20, 8), pady=12, sticky="w")
        self._badge = pill(self._status_bar)
        self._badge.grid(row=0, column=2, padx=16, sticky="e")
        self._badge_tooltip = Tooltip(self._badge, "", wraplength=400)

        # ── Settings + preview ───────────────────────────────────────────────
        cfg = card(self, row=2, column=0, padx=(PAGE_PADX, 6), sticky="nsew")
        cfg.grid_columnconfigure((0, 1), weight=1, uniform="cfg")
        section_title(cfg, "PDF appearance", "applies to the next generated PDF").grid(
            row=0, column=0, columnspan=2, padx=20, pady=(18, 14), sticky="ew")

        self.company_var = ctk.StringVar(value=self.controller.get_setting("company_name", "My Company"))
        self.slogan_var  = ctk.StringVar(value=self.controller.get_setting("company_slogan", "Product Catalog"))
        self.cols_var    = ctk.StringVar(value=self.controller.get_setting("products_per_row", "2"))

        def field(row, col, caption, build, span=1):
            cell = ctk.CTkFrame(cfg, fg_color="transparent")
            cell.grid(row=row, column=col, columnspan=span,
                      padx=(20 if col == 0 else 8, 20 if col + span == 2 else 8), pady=(0, 12), sticky="ew")
            cell.grid_columnconfigure(0, weight=1)
            field_caption(cell, caption).grid(row=0, column=0, sticky="w", pady=(0, 4))
            w = build(cell)
            w.grid(row=1, column=0, sticky="w" if isinstance(w, (InlineColorPicker, ctk.CTkOptionMenu)) else "ew")
            return w

        field(1, 0, "Company name", lambda p: entry(p, self.company_var))
        field(1, 1, "Tagline",      lambda p: entry(p, self.slogan_var))
        self._color_primary = field(2, 0, "Primary color", lambda p: InlineColorPicker(
            p, self.controller.get_setting("primary_color", "#C0392B")))
        self._color_secondary = field(2, 1, "Secondary color", lambda p: InlineColorPicker(
            p, self.controller.get_setting("secondary_color", "#2C3E50")))
        field(3, 0, "Products per row", lambda p: option_menu(p, self.cols_var, ["1", "2", "3"], width=90))

        save_row = ctk.CTkFrame(cfg, fg_color="transparent")
        save_row.grid(row=4, column=0, columnspan=2, padx=20, pady=(4, 18), sticky="ew")
        save_row.grid_columnconfigure(0, weight=1)
        secondary_button(save_row, "Save settings", self._save_pdf_config,
                         icon=icon("save", TEXT_HEADING, 15), width=140).grid(row=0, column=1, sticky="e")

        prev_card = card(self, row=2, column=1, padx=(6, PAGE_PADX), sticky="nsew")
        prev_card.grid_columnconfigure(0, weight=1)
        section_title(prev_card, "Preview").grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")
        self._preview = CatalogPreview(prev_card)
        self._preview.grid(row=1, column=0, padx=20, pady=(0, 20))

        for v in (self.company_var, self.cols_var, self._color_primary.var, self._color_secondary.var):
            v.trace_add("write", lambda *_: self._refresh_preview())
        self._refresh_preview()

        # ── Output log ───────────────────────────────────────────────────────
        log_card = card(self, row=3, column=0, columnspan=2, padx=PAGE_PADX, pady=(12, 22), sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        section_title(log_card, "Output").grid(row=0, column=0, padx=20, pady=(16, 8), sticky="ew")
        self.result_log = ctk.CTkTextbox(
            log_card, fg_color=BG_DEEPEST, text_color=TEXT_MUTED, font=font_mono(),
            border_width=1, border_color=BORDER, corner_radius=RADIUS_BUTTON, height=90,
        )
        self.result_log.grid(row=1, column=0, padx=20, pady=(0, 18), sticky="nsew")

    def _refresh_preview(self):
        try:
            per_row = int(self.cols_var.get() or 2)
        except ValueError:
            per_row = 2
        self._preview.render(self.company_var.get(), self._color_primary.get(),
                             self._color_secondary.get(), per_row)

    # ── Status refresh ────────────────────────────────────────────────────────

    def _refresh_status(self):
        try:
            stats  = self.controller.get_stats()
            status = self.controller.get_excel_status()
        except Exception:
            return

        db_mod  = status["last_db_mod"]
        excel_g = status["last_excel_gen"]
        parts = [f"{fmt_int(stats.get('total', 0))} products"]
        parts.append(f"last change {_humanize_delta(db_mod)}" if db_mod else "no changes yet")
        parts.append(f"Excel exported {_humanize_delta(excel_g)}" if excel_g else "no Excel exported yet")
        self._lbl_status.configure(text="  ·  ".join(parts))

        if status["is_stale"]:
            set_pill(self._badge, "Excel out of date", "warning")
            self._badge_tooltip.update_text(
                "The database changed (imports or edits) after the Excel file\n"
                "was last exported. Export it again to get up-to-date data."
            )
        elif status["has_excel"]:
            set_pill(self._badge, "Excel up to date", "success")
            self._badge_tooltip.update_text("Nothing has changed since the Excel file was last exported.")
        else:
            set_pill(self._badge, "")
            self._badge_tooltip.update_text("")

    # ── Save PDF config ───────────────────────────────────────────────────────

    def _save_pdf_config(self):
        try:
            self.controller.set_setting("company_name",     self.company_var.get().strip())
            self.controller.set_setting("company_slogan",   self.slogan_var.get().strip())
            self.controller.set_setting("primary_color",    self._color_primary.get())
            self.controller.set_setting("secondary_color",  self._color_secondary.get())
            self.controller.set_setting("products_per_row", self.cols_var.get())
            self._log("Settings saved — they apply to the next generated PDF.")
            messagebox.showinfo(
                "Saved",
                "Settings saved.\n"
                "Changes will apply the next time the PDF is generated.",
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ── Export Excel ──────────────────────────────────────────────────────────

    def _export(self):
        self._set_busy(True)
        self._action_spinner.start("Generating Excel…")

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
        self._log(f"Excel saved   {settings.display_path(path)}")
        open_now = messagebox.askyesno(
            "Excel generated",
            f"File saved to:\n{path}\n\nOpen it now?",
        )
        if open_now:
            _open_file(path)

    # ── Export CSV ────────────────────────────────────────────────────────────

    def _export_csv(self):
        self._set_busy(True)
        self._action_spinner.start("Generating CSV…")

        def _run():
            try:
                path = self.controller.export_csv(self.active_only_var.get())
                self.after(0, lambda p=path: self._csv_done(p))
            except Exception as e:
                self.after(0, lambda err=str(e): self._generic_error("CSV", err))

        threading.Thread(target=_run, daemon=True).start()

    def _csv_done(self, path: Path):
        self._action_spinner.stop()
        self._set_busy(False)
        self._refresh_status()
        self._log(f"CSV saved     {settings.display_path(path)}")
        open_now = messagebox.askyesno(
            "CSV generated",
            f"File saved to:\n{path}\n\nOpen it now?",
        )
        if open_now:
            _open_file(path)

    # ── Generate PDF ──────────────────────────────────────────────────────────

    def _gen_pdf(self):
        self._set_busy(True)
        self._action_spinner.start("Generating PDF catalog…")

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
        self._refresh_status()
        self._log(f"PDF saved     {settings.display_path(path)}")
        open_now = messagebox.askyesno(
            "PDF catalog generated",
            f"Catalog saved to:\n{path}\n\nOpen it now?",
        )
        if open_now:
            _open_file(path)

    def _generic_error(self, context: str, error: str):
        self._action_spinner.stop()
        self._set_busy(False)
        self._refresh_status()
        self._log(f"error ({context})  {error}")
        messagebox.showerror(f"Error — {context}", error)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self._export_btn.configure(state=state)
        self._csv_btn.configure(state=state)
        self._pdf_btn.configure(state=state)
        if busy:
            self._lbl_status.configure(text="")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S  ")
        self.result_log.insert("end", ts + msg + "\n")
        self.result_log.see("end")

    def on_show(self):
        self._refresh_status()

    def on_hide(self):
        pass
