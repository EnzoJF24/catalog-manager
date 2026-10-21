"""
Import frame — file selection, pricing rules with live preview, progress and result summary.
"""
from __future__ import annotations
import re
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk

from app.core.app_controller import AppController
from app.logging_config.logger import get_logger
from app.models.product import Product
from app.parsers.parser_factory import ParserFactory
from app.utils.formatting import format_price, parse_number
from app.ui.icons import icon
from app.ui.theme import (
    BG_BASE, BG_ELEVATED, BG_DEEPEST, BORDER, BORDER_STRONG,
    ACCENT, ACCENT_SOFT,
    TEXT_PRIMARY, TEXT_MUTED, TEXT_SUBTLE,
    PAGE_PADX, RADIUS_BUTTON, RADIUS_CARD,
    font_small, font_label, font_mono, font_caps, font_number, font_sub,
    card, section_title, page_header, primary_button, secondary_button,
    entry, option_menu, field_caption, pill, set_pill, fmt_int,
)
from app.ui.components.spinner import Spinner

log = get_logger("import_frame")

_SUFFIX_RE = re.compile(r"^$|^[.,]\d{1,2}$")
_PREVIEW_COST = 1000.0


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class ImportFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller   = controller
        self._running     = False
        self._selected_pdf: str = ""
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=3, uniform="imp")
        self.grid_columnconfigure(1, weight=2, uniform="imp")
        self.grid_rowconfigure(2, weight=1)

        page_header(self, "Import supplier PDF",
                    "The supplier is detected automatically from the document.").grid(
            row=0, column=0, columnspan=2, padx=PAGE_PADX, pady=(26, 18), sticky="ew")

        self._build_source_card()
        self._build_pricing_card()
        self._build_progress_card()

    # ── Source file ───────────────────────────────────────────────────────────

    def _build_source_card(self):
        c = card(self, row=1, column=0, padx=(PAGE_PADX, 6), sticky="nsew")
        c.grid_columnconfigure(0, weight=1)
        c.grid_rowconfigure(1, weight=1)
        section_title(c, "Source file").grid(row=0, column=0, padx=20, pady=(18, 12), sticky="ew")

        drop = ctk.CTkFrame(c, fg_color=BG_DEEPEST, corner_radius=RADIUS_CARD,
                            border_width=1, border_color=BORDER_STRONG)
        drop.grid(row=1, column=0, padx=20, sticky="nsew")
        drop.grid_columnconfigure(1, weight=1)
        drop.grid_rowconfigure((0, 1), weight=1)

        badge = ctk.CTkFrame(drop, width=44, height=44, corner_radius=12, fg_color=ACCENT_SOFT)
        badge.grid(row=0, column=0, rowspan=2, padx=(18, 14), pady=18)
        badge.grid_propagate(False)
        self._file_icon = ctk.CTkLabel(badge, text="", image=icon("upload", ACCENT, 20))
        self._file_icon.place(relx=0.5, rely=0.5, anchor="center")

        self.file_label = ctk.CTkLabel(drop, text="No file selected", font=font_sub(),
                                       text_color=TEXT_PRIMARY, anchor="w")
        self.file_label.grid(row=0, column=1, sticky="sw")
        supported = ", ".join(p["name"] for p in ParserFactory.list_parsers())
        self._file_meta = ctk.CTkLabel(drop, text=f"Supported suppliers: {supported}",
                                       font=font_small(), text_color=TEXT_MUTED, anchor="w")
        self._file_meta.grid(row=1, column=1, sticky="nw")

        self.browse_btn = secondary_button(drop, "Browse…", self._choose_file, width=96)
        self.browse_btn.grid(row=0, column=2, rowspan=2, padx=18)

        actions = ctk.CTkFrame(c, fg_color="transparent")
        actions.grid(row=2, column=0, padx=20, pady=(14, 18), sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(actions, text="Products already in the database are updated in place.",
                     font=font_small(), text_color=TEXT_SUBTLE, anchor="w").grid(row=0, column=0, sticky="w")
        self.import_btn = primary_button(actions, "Import", self._start_import,
                                         icon=icon("upload", "#FFFFFF", 16), width=120)
        self.import_btn.grid(row=0, column=1, sticky="e")

    # ── Pricing ───────────────────────────────────────────────────────────────

    def _build_pricing_card(self):
        c = card(self, row=1, column=1, padx=(6, PAGE_PADX), sticky="nsew")
        c.grid_columnconfigure((0, 1), weight=1, uniform="price")
        section_title(c, "Pricing rules").grid(row=0, column=0, columnspan=2,
                                               padx=20, pady=(18, 12), sticky="ew")

        mc = self.controller.margin_config
        self.margin_var = ctk.StringVar(value=f"{mc.margin_pct:g}")
        self.iva_var    = ctk.StringVar(value=f"{mc.iva_pct:g}")
        self.round_var  = ctk.StringVar(value=str(mc.round_to_nearest))
        self.suffix_var = ctk.StringVar(value=mc.price_suffix)

        def field(row, col, caption, widget_factory):
            cell = ctk.CTkFrame(c, fg_color="transparent")
            cell.grid(row=row, column=col, padx=(20 if col == 0 else 6, 6 if col == 0 else 20),
                      pady=(0, 10), sticky="ew")
            cell.grid_columnconfigure(0, weight=1)
            field_caption(cell, caption).grid(row=0, column=0, sticky="w", pady=(0, 4))
            widget_factory(cell).grid(row=1, column=0, sticky="ew")

        field(1, 0, "Margin %",     lambda p: entry(p, self.margin_var, width=100))
        field(1, 1, "Tax %",        lambda p: entry(p, self.iva_var, width=100))
        field(2, 0, "Round up to",  lambda p: option_menu(
            p, self.round_var, ["0", "10", "50", "100", "500", "1000"], width=100))
        field(2, 1, "Price ending", lambda p: entry(p, self.suffix_var, width=100, placeholder=".99"))

        preview = ctk.CTkFrame(c, fg_color=BG_ELEVATED, corner_radius=RADIUS_BUTTON)
        preview.grid(row=3, column=0, columnspan=2, padx=20, pady=(4, 18), sticky="ew")
        preview.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(preview, text=f"{format_price(_PREVIEW_COST, 0)} cost  →", font=font_label(),
                     text_color=TEXT_MUTED).grid(row=0, column=0, padx=(14, 8), pady=10, sticky="w")
        self._preview_label = ctk.CTkLabel(preview, text="—", font=font_number(16),
                                           text_color=TEXT_PRIMARY, anchor="w")
        self._preview_label.grid(row=0, column=1, sticky="w")

        for v in (self.margin_var, self.iva_var, self.round_var, self.suffix_var):
            v.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

    # ── Progress & result ─────────────────────────────────────────────────────

    def _build_progress_card(self):
        c = card(self, row=2, column=0, columnspan=2, padx=PAGE_PADX, pady=(12, 22), sticky="nsew")
        c.grid_columnconfigure(0, weight=1)
        c.grid_rowconfigure(3, weight=1)

        status = ctk.CTkFrame(c, fg_color="transparent")
        status.grid(row=0, column=0, padx=20, pady=(16, 0), sticky="ew")
        status.grid_columnconfigure(1, weight=1)
        self._progress_spinner = Spinner(status, with_label=False, icon_color=ACCENT)
        self._progress_spinner.grid(row=0, column=0, sticky="w")
        self.progress_label = ctk.CTkLabel(status, text="Ready to import", font=font_sub(),
                                           text_color=TEXT_PRIMARY, anchor="w")
        self.progress_label.grid(row=0, column=1, sticky="w")
        self._result_pill = pill(status)
        self._result_pill.grid(row=0, column=2, padx=(8, 0), sticky="e")
        self._pct_label = ctk.CTkLabel(status, text="", font=font_caps(), text_color=TEXT_MUTED)
        self._pct_label.grid(row=0, column=3, padx=(10, 0), sticky="e")

        self.progress_bar = ctk.CTkProgressBar(c, height=6, corner_radius=3,
                                               fg_color=BG_ELEVATED, progress_color=ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, padx=20, pady=(10, 0), sticky="ew")

        # Result summary — filled in when an import finishes
        self._summary = ctk.CTkFrame(c, fg_color="transparent")
        self._summary.grid(row=2, column=0, padx=20, pady=(14, 0), sticky="ew")
        self._summary_vals: dict[str, ctk.CTkLabel] = {}
        for i, (key, caption) in enumerate([("supplier", "SUPPLIER"), ("products", "PRODUCTS"),
                                            ("images", "WITH IMAGE"), ("pages", "PAGES"),
                                            ("duration", "DURATION")]):
            cell = ctk.CTkFrame(self._summary, fg_color="transparent")
            cell.grid(row=0, column=i, padx=(0, 40), sticky="w")
            ctk.CTkLabel(cell, text=caption, font=font_caps(), text_color=TEXT_SUBTLE,
                         anchor="w").grid(row=0, column=0, sticky="w")
            val = ctk.CTkLabel(cell, text="—", font=font_number(16), text_color=TEXT_PRIMARY, anchor="w")
            val.grid(row=1, column=0, sticky="w")
            self._summary_vals[key] = val
        self._summary.grid_remove()

        self.log_text = ctk.CTkTextbox(
            c, fg_color=BG_DEEPEST, text_color=TEXT_MUTED, font=font_mono(),
            border_width=1, border_color=BORDER, corner_radius=RADIUS_BUTTON,
        )
        self.log_text.grid(row=3, column=0, padx=20, pady=(14, 20), sticky="nsew")
        self.log_text.insert("end", "The import log will appear here.\n")

    # ── File selection ────────────────────────────────────────────────────────

    def _choose_file(self):
        path = filedialog.askopenfilename(
            title="Select the supplier PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.set_selected_pdf(path)

    def set_selected_pdf(self, path: str):
        self._selected_pdf = path
        p = Path(path)
        try:
            size = _human_size(p.stat().st_size)
        except OSError:
            size = ""
        self.file_label.configure(text=p.name)
        # Size only — the full path would expose the local user folder in screenshots
        self._file_meta.configure(text=f"PDF document  ·  {size}" if size else "PDF document")
        self._file_icon.configure(image=icon("file_text", ACCENT, 20))

    # ── Input validation (I3 fix) ─────────────────────────────────────────────

    def _validate_inputs(self) -> tuple[bool, float, float, int, str]:
        """
        Validate price config inputs.
        Returns (ok, margin, iva, round_to, suffix).
        Shows a messagebox and returns ok=False on any invalid input.
        """
        def _parse_pct(val: str, name: str, lo: float, hi: float) -> float | None:
            try:
                v = parse_number(val)
                if not (lo <= v <= hi):
                    raise ValueError(f"out of range [{lo}–{hi}]")
                return v
            except ValueError as e:
                messagebox.showwarning(
                    "Invalid value",
                    f"'{name}' must be a number between {lo} and {hi}.\nDetails: {e}",
                )
                return None

        margin = _parse_pct(self.margin_var.get() or "0", "Margin %", 0, 1000)
        if margin is None:
            return False, 0, 0, 0, ""

        iva = _parse_pct(self.iva_var.get() or "0", "Tax %", 0, 100)
        if iva is None:
            return False, 0, 0, 0, ""

        try:
            round_to = int(self.round_var.get() or "0")
        except ValueError:
            messagebox.showwarning("Invalid value", "'Round up to' must be a whole number.")
            return False, 0, 0, 0, ""

        suffix = self.suffix_var.get().strip()
        if not _SUFFIX_RE.match(suffix):
            messagebox.showwarning(
                "Invalid price ending",
                f"The price ending '{suffix}' is not valid.\n"
                "Leave it empty or use the form '.XX' (e.g. .99).",
            )
            return False, 0, 0, 0, ""

        return True, margin, iva, round_to, suffix

    # ── Import ────────────────────────────────────────────────────────────────

    def _start_import(self):
        if not self._selected_pdf:
            messagebox.showwarning("No file", "Select a PDF first.")
            return
        if self._running:
            return

        ok, margin, iva, round_to, suffix = self._validate_inputs()
        if not ok:
            return

        # U3: warn if this exact PDF was already imported before
        try:
            prev = self.controller.find_previous_import(self._selected_pdf)
            if prev:
                started = str(prev.get("started_at", ""))[:16]
                proceed = messagebox.askyesno(
                    "PDF already imported",
                    f"This PDF was already imported on {started}.\n"
                    f"Supplier: {prev.get('supplier_name', '?')}  |  "
                    f"Products: {prev.get('products_found', 0)}\n\n"
                    "Import anyway? Existing data will be updated.",
                )
                if not proceed:
                    return
        except Exception:
            pass  # Don't block the import if the check itself fails

        try:
            self.controller.update_margin_config(
                margin_pct=margin, iva_pct=iva, round_to=round_to, suffix=suffix,
            )
        except ValueError as e:
            messagebox.showerror("Configuration error", str(e))
            return

        self._running = True
        self.import_btn.configure(state="disabled", text="Importing…")
        self.log_text.delete("1.0", "end")
        self.progress_bar.set(0)
        self._summary.grid_remove()
        set_pill(self._result_pill, "")
        self._progress_spinner.start()

        def _progress(msg: str, pct: float):
            self.after(0, lambda m=msg, p=pct: self._update_progress(m, p))

        def _run():
            try:
                session = self.controller.import_pdf(self._selected_pdf, _progress)
                self.after(0, lambda s=session: self._import_done(s))
            except Exception as e:
                self.after(0, lambda err=str(e): self._import_error(err))

        threading.Thread(target=_run, daemon=True).start()

    def _update_progress(self, msg: str, pct: float):
        self.progress_label.configure(text=msg.lstrip("✓ ").strip())
        self._pct_label.configure(text=f"{pct:.0f}%")
        self.progress_bar.set(pct / 100)
        self.log_text.insert("end", f"[{pct:3.0f}%] {msg}\n")
        self.log_text.see("end")

    def _import_done(self, session):
        self._running = False
        self._progress_spinner.stop()
        self.import_btn.configure(state="normal", text="Import")
        self.progress_bar.set(1.0)
        self._pct_label.configure(text="")

        skipped = [w for w in session.warnings
                   if "SKIPPED" in w or "discarded" in w.lower()]
        # Indented warnings are per-SKU details of the note above them
        notes = [w for w in session.warnings if not w.startswith(" ")]

        self._summary_vals["supplier"].configure(text=session.supplier_name or "—")
        self._summary_vals["products"].configure(text=fmt_int(session.products_found))
        self._summary_vals["images"].configure(text=fmt_int(session.images_matched))
        self._summary_vals["pages"].configure(text=fmt_int(session.total_pages))
        self._summary_vals["duration"].configure(text=f"{session.duration_seconds:.1f} s")
        self._summary.grid()

        if session.errors:
            self.progress_label.configure(text="Import finished with errors")
            set_pill(self._result_pill, f"{len(session.errors)} error(s)", "danger")
        else:
            self.progress_label.configure(text="Import complete")
            if notes:
                set_pill(self._result_pill, f"{len(notes)} note{'s' if len(notes) > 1 else ''}", "warning")
            else:
                set_pill(self._result_pill, "Completed", "success")

        self.log_text.insert("end", "\n")
        for w in notes:
            self.log_text.insert("end", f"note   {w}\n")
        for e in session.errors[:5]:
            self.log_text.insert("end", f"error  {e}\n")
        self.log_text.see("end")

        if session.errors:
            messagebox.showwarning(
                "Import finished with errors",
                f"{session.products_found} products imported.\n"
                f"{len(session.errors)} error(s) — check the log."
            )
        elif skipped:
            messagebox.showwarning(
                "Import finished with warnings",
                f"{session.products_found} products imported.\n\n"
                f"{skipped[0]}\n\nCheck the log to see which SKUs were skipped."
            )
        else:
            total = session.products_found or 1
            pct   = int(100 * session.images_matched / total)
            messagebox.showinfo(
                "Import successful",
                f"{session.products_found} products imported successfully.\n"
                f"Linked images: {session.images_matched}/{total} ({pct}%)"
            )

    def _import_error(self, error: str):
        self._running = False
        self._progress_spinner.stop()
        self.import_btn.configure(state="normal", text="Import")
        self.progress_label.configure(text="Import failed")
        set_pill(self._result_pill, "Error", "danger")
        self.log_text.insert("end", f"\nerror  {error}\n")
        messagebox.showerror("Import error", error)

    # ── Live preview ──────────────────────────────────────────────────────────

    def _update_preview(self):
        """Recompute the price preview from current config values."""
        if not hasattr(self, "_preview_label"):
            return
        try:
            margin = parse_number(self.margin_var.get() or "0")
            iva    = parse_number(self.iva_var.get()    or "0")
            try:
                rnd = int(self.round_var.get() or "0")
            except ValueError:
                rnd = 0
            sfx = self.suffix_var.get() or ""

            p = Product(sku="", brand="", description="", price_original=_PREVIEW_COST, category="")
            p.apply_margin(margin, iva, rnd, sfx)
            # price_final already carries the ending (.99), so format it as-is
            self._preview_label.configure(text=format_price(p.price_final), text_color=TEXT_PRIMARY)
        except (ValueError, TypeError):
            self._preview_label.configure(text="invalid values", text_color=TEXT_SUBTLE)

    def on_show(self):
        pass

    def on_hide(self):
        pass
