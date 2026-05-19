"""
Import frame — tema unificado + validaciones de input + barra de progreso real.
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
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED, BG_DEEPEST,
    ACCENT_PRIMARY, ACCENT_PRIMARY_H, ACCENT_SUCCESS, ACCENT_SUCCESS_H,
    ACCENT_BLUE,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    RADIUS_CARD, RADIUS_BUTTON,
    font_title, font_small, font_label, font_bold, font_mono,
)
from app.ui.components.spinner import Spinner

log = get_logger("import_frame")

_SUFFIX_RE = re.compile(r"^$|^[.,]\d{1,2}$")


def _labeled_field(parent, label: str, row: int, col: int,
                   var: ctk.StringVar, width: int = 100,
                   suffix: str = "", widget_type: str = "entry",
                   option_values: list = None,
                   helper: str = "",
                   placeholder: str = "") -> None:
    cell = ctk.CTkFrame(parent, fg_color="transparent")
    cell.grid(row=row, column=col, padx=8, pady=4, sticky="nw")

    ctk.CTkLabel(
        cell, text=label, text_color=TEXT_MUTED,
        font=font_small(), anchor="w",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))

    if widget_type == "entry":
        ctk.CTkEntry(
            cell, textvariable=var, width=width, height=32,
            placeholder_text=placeholder,
        ).grid(row=1, column=0, sticky="w")
        if suffix:
            ctk.CTkLabel(
                cell, text=suffix, text_color=TEXT_SUBTLE,
                font=font_label(),
            ).grid(row=1, column=1, padx=(4, 0), sticky="w")
    else:
        ctk.CTkOptionMenu(
            cell, variable=var, values=option_values or [], width=width, height=32,
        ).grid(row=1, column=0, sticky="w")

    if helper:
        ctk.CTkLabel(
            cell, text=helper, text_color=TEXT_SUBTLE,
            font=ctk.CTkFont(size=10), anchor="w", justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))


class ImportFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller   = controller
        self._running     = False
        self._selected_pdf: str = ""
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="Importar PDF de Proveedor",
            font=font_title(), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=24, pady=(24, 4), sticky="w")

        # Price config panel
        config = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        config.grid(row=2, column=0, padx=24, pady=(0, 12), sticky="ew")

        ctk.CTkLabel(
            config, text="💲  Configuración de Precios",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, columnspan=5, padx=16, pady=(14, 8), sticky="w")

        ctk.CTkFrame(config, height=1, fg_color=BG_ELEVATED).grid(
            row=1, column=0, columnspan=5, padx=16, pady=(0, 10), sticky="ew"
        )

        self.margin_var = ctk.StringVar(value=str(self.controller.margin_config.margin_pct))
        self.iva_var    = ctk.StringVar(value=str(self.controller.margin_config.iva_pct))
        self.round_var  = ctk.StringVar(value=str(self.controller.margin_config.round_to_nearest))
        self.suffix_var = ctk.StringVar(value=self.controller.margin_config.price_suffix)

        _labeled_field(
            config, "Margen (%)", row=2, col=0,
            var=self.margin_var, width=90, suffix="%",
            helper="Se suma sobre el precio original.\nEj: 30 → +30 %",
        )
        _labeled_field(
            config, "IVA (%)", row=2, col=1,
            var=self.iva_var, width=80, suffix="%",
            helper="Se aplica después del margen.\nDejar en 0 si ya viene incluido.",
        )
        _labeled_field(
            config, "Redondear al múltiplo de", row=2, col=2,
            var=self.round_var, width=100,
            widget_type="optionmenu",
            option_values=["0", "10", "50", "100", "500", "1000"],
            helper="0 = sin redondeo.\nEj: 100 → $1.234 se vuelve $1.200",
        )
        _labeled_field(
            config, "Terminación del precio", row=2, col=3,
            var=self.suffix_var, width=110, placeholder=",99",
            helper="Texto al final del precio.\nEj: ,99 → $1.234,99",
        )

        # ── Vista previa en vivo ─────────────────────────────────────────────
        preview_frame = ctk.CTkFrame(config, fg_color=BG_ELEVATED, corner_radius=8)
        preview_frame.grid(row=3, column=0, columnspan=5,
                           padx=16, pady=(10, 14), sticky="ew")
        preview_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            preview_frame, text="Vista previa:",
            font=font_small(), text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=(14, 8), pady=10, sticky="w")

        self._preview_label = ctk.CTkLabel(
            preview_frame, text="—",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_HEADING, anchor="w",
        )
        self._preview_label.grid(row=0, column=1, padx=4, pady=10, sticky="w")

        # Trace all 4 vars to update preview
        for v in (self.margin_var, self.iva_var, self.round_var, self.suffix_var):
            v.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

        # ── Barra de selección (compacta, horizontal) ─────────────────────────
        drop_zone = ctk.CTkFrame(
            self, fg_color=BG_ELEVATED, corner_radius=10,
            border_color=ACCENT_PRIMARY, border_width=2,
        )
        drop_zone.grid(row=3, column=0, padx=24, pady=(0, 12), sticky="ew")
        drop_zone.grid_columnconfigure(2, weight=1)   # filename expands

        ctk.CTkLabel(
            drop_zone, text="📄", font=ctk.CTkFont(size=20),
        ).grid(row=0, column=0, padx=(12, 6), pady=10)

        ctk.CTkLabel(
            drop_zone, text="PDF del proveedor:",
            font=font_label(), text_color=TEXT_MUTED,
        ).grid(row=0, column=1, padx=(0, 8), pady=10, sticky="w")

        self.file_label = ctk.CTkLabel(
            drop_zone, text="Ningún archivo seleccionado",
            font=font_small(), text_color=TEXT_SUBTLE, anchor="w",
        )
        self.file_label.grid(row=0, column=2, padx=4, pady=10, sticky="ew")

        ctk.CTkButton(
            drop_zone, text="📂  Elegir", height=34, width=110,
            fg_color=ACCENT_PRIMARY, hover_color=ACCENT_PRIMARY_H,
            font=font_bold(), corner_radius=RADIUS_BUTTON,
            command=self._choose_file,
        ).grid(row=0, column=3, padx=(8, 6), pady=10)

        self.import_btn = ctk.CTkButton(
            drop_zone, text="🚀  Importar", height=34, width=140,
            fg_color=ACCENT_SUCCESS, hover_color=ACCENT_SUCCESS_H,
            font=ctk.CTkFont(size=13, weight="bold"), corner_radius=RADIUS_BUTTON,
            command=self._start_import,
        )
        self.import_btn.grid(row=0, column=4, padx=(0, 12), pady=10)

        # Progress panel
        prog_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        prog_frame.grid(row=4, column=0, padx=24, pady=(0, 16), sticky="nsew")
        prog_frame.grid_columnconfigure(0, weight=1)
        prog_frame.grid_rowconfigure(2, weight=1)

        # Status row: spinner (inline) + status label
        status_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        status_row.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="ew")
        status_row.grid_columnconfigure(1, weight=1)

        self._progress_spinner = Spinner(status_row, with_label=False)
        self._progress_spinner.grid(row=0, column=0, padx=(0, 4), sticky="w")

        self.progress_label = ctk.CTkLabel(
            status_row, text="Listo para importar",
            font=font_label(), text_color=TEXT_MUTED, anchor="w",
        )
        self.progress_label.grid(row=0, column=1, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(
            prog_frame, height=8,
            fg_color=BG_ELEVATED, progress_color=ACCENT_PRIMARY,
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, padx=16, pady=4, sticky="ew")

        self.log_text = ctk.CTkTextbox(
            prog_frame, fg_color=BG_DEEPEST, text_color=ACCENT_SUCCESS,
            font=font_mono(),
        )
        self.log_text.grid(row=2, column=0, padx=16, pady=(4, 6), sticky="nsew")

    # ── File selection ────────────────────────────────────────────────────────

    def _choose_file(self):
        path = filedialog.askopenfilename(
            title="Seleccionar PDF del proveedor",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._selected_pdf = path
            self.file_label.configure(
                text=f"✓  {Path(path).name}", text_color=ACCENT_SUCCESS
            )

    # ── Input validation (I3 fix) ─────────────────────────────────────────────

    def _validate_inputs(self) -> tuple[bool, float, float, int, str]:
        """
        Validate price config inputs.
        Returns (ok, margin, iva, round_to, suffix).
        Shows a messagebox and returns ok=False on any invalid input.
        """
        def _parse_pct(val: str, name: str, lo: float, hi: float) -> float | None:
            try:
                v = float(val.strip().replace(",", "."))
                if not (lo <= v <= hi):
                    raise ValueError(f"fuera de rango [{lo}–{hi}]")
                return v
            except ValueError as e:
                messagebox.showwarning(
                    "Valor inválido",
                    f"'{name}' debe ser un número entre {lo} y {hi}.\nDetalle: {e}",
                )
                return None

        margin = _parse_pct(self.margin_var.get() or "0", "Margen %", 0, 1000)
        if margin is None:
            return False, 0, 0, 0, ""

        iva = _parse_pct(self.iva_var.get() or "0", "IVA %", 0, 100)
        if iva is None:
            return False, 0, 0, 0, ""

        try:
            round_to = int(self.round_var.get() or "0")
        except ValueError:
            messagebox.showwarning("Valor inválido", "'Redondear a' debe ser un número entero.")
            return False, 0, 0, 0, ""

        suffix = self.suffix_var.get().strip()
        if not _SUFFIX_RE.match(suffix):
            messagebox.showwarning(
                "Sufijo inválido",
                f"El sufijo '{suffix}' no es válido.\n"
                "Debe estar vacío, o tener la forma '.XX' o ',XX' (ej: ,99 o .99).",
            )
            return False, 0, 0, 0, ""

        return True, margin, iva, round_to, suffix

    # ── Import ────────────────────────────────────────────────────────────────

    def _start_import(self):
        if not self._selected_pdf:
            messagebox.showwarning("Sin archivo", "Seleccioná un PDF primero.")
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
                    "PDF ya importado",
                    f"Este PDF ya fue importado el {started}.\n"
                    f"Proveedor: {prev.get('supplier_name', '?')}  |  "
                    f"Productos: {prev.get('products_found', 0)}\n\n"
                    "¿Importar de todas formas? Los datos existentes serán actualizados.",
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
            messagebox.showerror("Error de configuración", str(e))
            return

        self._running = True
        self.import_btn.configure(state="disabled", text="Procesando...")
        self.log_text.delete("1.0", "end")
        self.progress_bar.set(0)
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
        self.progress_label.configure(text=msg)
        self.progress_bar.set(pct / 100)
        self.log_text.insert("end", f"[{pct:3.0f}%] {msg}\n")
        self.log_text.see("end")

    def _import_done(self, session):
        self._running = False
        self._progress_spinner.stop()
        self.import_btn.configure(state="normal", text="🚀  Importar")
        self.progress_bar.set(1.0)

        skipped = [w for w in session.warnings
                   if "SKIPPED" in w or "descartados" in w.lower()]
        other   = [w for w in session.warnings if w not in skipped]

        lines = [
            f"\n{'='*44}",
            f"IMPORTACIÓN COMPLETA",
            f"Session ID:  {session.session_id}",
            f"Proveedor:   {session.supplier_name}",
            f"Páginas:     {session.total_pages}",
            f"Productos:   {session.products_found}",
            f"Imágenes:    {session.images_matched}/{session.products_found}  (refs en PDF: {session.images_found})",
            f"Duración:    {session.duration_seconds:.1f}s",
        ]
        if skipped:
            lines.append(f"Advertencias: {skipped[0]}")
        if session.errors:
            lines.append(f"Errores: {'; '.join(session.errors[:3])}")
        lines.append("=" * 44)

        self.log_text.insert("end", "\n".join(lines))
        self.log_text.see("end")

        if session.errors:
            messagebox.showwarning(
                "Importación con errores",
                f"{session.products_found} productos importados.\n"
                f"{len(session.errors)} error(es) — revisá el log."
            )
        elif skipped:
            messagebox.showwarning(
                "Importación con advertencias",
                f"{session.products_found} productos importados.\n\n"
                f"{skipped[0]}\n\nRevisá el log para ver cuáles SKUs fueron omitidos."
            )
        else:
            total = session.products_found or 1
            pct   = int(100 * session.images_matched / total)
            messagebox.showinfo(
                "Importación exitosa",
                f"{session.products_found} productos importados correctamente.\n"
                f"Imágenes vinculadas: {session.images_matched}/{total} ({pct}%)"
            )

    def _import_error(self, error: str):
        self._running = False
        self._progress_spinner.stop()
        self.import_btn.configure(state="normal", text="🚀  Importar")
        self.log_text.insert("end", f"\nERROR: {error}\n")
        messagebox.showerror("Error de importación", error)

    # ── Live preview ──────────────────────────────────────────────────────────

    def _update_preview(self):
        """Recompute the price preview from current config values."""
        if not hasattr(self, "_preview_label"):
            return
        sample_price = 1000.0
        try:
            margin = float((self.margin_var.get() or "0").replace(",", "."))
            iva    = float((self.iva_var.get()    or "0").replace(",", "."))
            try:
                rnd = int(self.round_var.get() or "0")
            except ValueError:
                rnd = 0
            sfx = self.suffix_var.get() or ""

            p = Product(sku="", brand="", description="", price_original=sample_price, category="")
            p.apply_margin(margin, iva, rnd, sfx)
            final = p.price_final

            # Format the original as Argentine $1.000
            orig_str  = f"$ {int(sample_price):,}".replace(",", ".")
            final_str = f"$ {int(final):,}".replace(",", ".") + (sfx if sfx else "")
            self._preview_label.configure(
                text=f"{orig_str}   →   {final_str}",
                text_color=TEXT_HEADING,
            )
        except (ValueError, TypeError):
            self._preview_label.configure(
                text="(valores inválidos)",
                text_color=TEXT_SUBTLE,
            )

    def on_show(self):
        pass

    def on_hide(self):
        pass
