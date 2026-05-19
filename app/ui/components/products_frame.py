"""
Products management frame.

Architecture:
  * Row widgets are built ONCE (in _build_rows_once) and reused on every page change
    — just StringVar/BooleanVar values are updated. No destroy/recreate per page.
  * Pagination + filter + search are done at the SQL layer via controller.get_products_page().
    Only 20 rows + 1 COUNT query per page change. No full-table load.
  * Search triggers on Enter / search button click. No live debounce.
  * Edits accumulate in self._pending (per-SKU dict of changes). Saving sends a bulk
    write to DB and refreshes the current page from BD.
"""
from __future__ import annotations
from tkinter import messagebox
import customtkinter as ctk

from app.core.app_controller import AppController
from app.models.product import Product
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED,
    ACCENT_PRIMARY, ACCENT_BLUE, ACCENT_BLUE_H,
    ACCENT_SUCCESS, ACCENT_SUCCESS_H,
    ACCENT_WARNING,
    ACCENT_DANGER, ACCENT_DANGER_H,
    BTN_SECONDARY, BTN_SECONDARY_H,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    BTN_TEXT_DISABLED,
    RADIUS_CARD,
    font_small, font_label, font_bold,
)

PAGE_SIZE   = 20
BG_PENDING  = "#0d2a1a"   # dark green tint — row has unsaved changes
BG_DIRTY    = "#091a10"   # action bar background when changes are pending
ROW_H       = 30          # product row height in pixels
ENTRY_H     = 24          # CTkEntry height inside rows


class ProductsFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller = controller

        # ── Page state ───────────────────────────────────────────────────────
        self._current_page: int = 0
        self._total_pages: int = 1
        self._total_count: int = 0
        self._page_items: list[dict] = []   # current page's product dicts (raw from BD)

        # ── Edit state ───────────────────────────────────────────────────────
        # {sku: {field: new_value}} — in-memory edits not yet persisted
        self._pending: dict[str, dict] = {}
        # Suppresses StringVar / BooleanVar traces while we update widget values programmatically
        self._init_in_progress = False

        # ── External (health) filter — set by Dashboard double-click ─────────
        self._ext_filter_key:  str = ""
        self._ext_filter_text: str = ""
        self._ext_filter_skus: list = []   # explicit SKU list for missing_image

        # ── Reusable row widgets (created once, reused per page) ─────────────
        # Each row is a dict with all the widgets + their vars; populated in _build_rows_once.
        self._rows: list[dict] = []

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # table fills remaining height

        # ── Row 0: search / filter toolbar (with title on left) ──────────────
        toolbar = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        toolbar.grid(row=0, column=0, padx=20, pady=(12, 4), sticky="ew")
        toolbar.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            toolbar, text="Productos",
            font=font_bold(), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=(14, 10), pady=6, sticky="w")

        # Lupa is a clickable button (also triggers search)
        ctk.CTkButton(
            toolbar, text="🔍", width=30, height=30,
            fg_color=BG_ELEVATED, hover_color=ACCENT_BLUE,
            font=ctk.CTkFont(size=13), corner_radius=6,
            command=self._trigger_search,
        ).grid(row=0, column=1, padx=(0, 4), pady=6)

        self.search_var = ctk.StringVar()
        # Bind Enter key on the entry to trigger search
        self.search_entry = ctk.CTkEntry(
            toolbar, textvariable=self.search_var,
            placeholder_text="Buscar SKU, descripción, marca o categoría…",
            height=30,
        )
        self.search_entry.grid(row=0, column=2, padx=4, pady=6, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self._trigger_search())

        # Clear button (hidden until there's text)
        self._clear_btn = ctk.CTkButton(
            toolbar, text="✕", width=28, height=30,
            fg_color=BG_ELEVATED, hover_color=ACCENT_DANGER,
            font=ctk.CTkFont(size=13), corner_radius=6,
            command=self._clear_search,
        )
        self._clear_btn.grid(row=0, column=3, padx=(0, 4), pady=6)
        self._clear_btn.grid_remove()
        # Show/hide ✕ based on text content
        self.search_var.trace_add("write", self._toggle_clear_btn)

        self.filter_var = ctk.StringVar(value="Todos")
        ctk.CTkOptionMenu(
            toolbar, variable=self.filter_var,
            values=["Todos", "Activos", "Inactivos", "Discontinuados"],
            width=135, height=30,
            command=lambda *_: self._on_filter_change(),
        ).grid(row=0, column=4, padx=(4, 6), pady=6)

        ctk.CTkButton(
            toolbar, text="🔄", width=34, height=30,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_H,
            font=ctk.CTkFont(size=14), corner_radius=6,
            command=self._reload,
        ).grid(row=0, column=5, padx=(0, 10), pady=6)

        # External-filter chip row (hidden until set_external_filter is called).
        # Shows "Filtro activo: <label> (N) [✕]" anchored to the left.
        self._ext_filter_frame = ctk.CTkFrame(
            toolbar, fg_color=BG_ELEVATED, corner_radius=6,
            border_color=ACCENT_WARNING, border_width=1,
        )
        self._ext_filter_frame.grid(row=1, column=0, columnspan=6,
                                    padx=10, pady=(0, 8), sticky="w")
        self._ext_filter_frame.grid_remove()  # hidden by default

        ctk.CTkLabel(
            self._ext_filter_frame, text="🩺",
            font=ctk.CTkFont(size=12), text_color=ACCENT_WARNING,
        ).grid(row=0, column=0, padx=(10, 4), pady=4)

        self._ext_filter_label = ctk.CTkLabel(
            self._ext_filter_frame, text="",
            font=font_small(), text_color=TEXT_HEADING,
        )
        self._ext_filter_label.grid(row=0, column=1, padx=4, pady=4)

        ctk.CTkButton(
            self._ext_filter_frame, text="✕  Quitar filtro",
            width=110, height=22,
            fg_color=ACCENT_DANGER, hover_color=ACCENT_DANGER_H,
            text_color_disabled=BTN_TEXT_DISABLED,
            font=ctk.CTkFont(size=10, weight="bold"), corner_radius=5,
            command=self._clear_external_filter,
        ).grid(row=0, column=2, padx=(8, 8), pady=3)

        # ── Row 1: action bar (save/discard + stats + pagination) ────────────
        self._action_bar = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        self._action_bar.grid(row=1, column=0, padx=20, pady=(0, 4), sticky="ew")

        self.save_btn = ctk.CTkButton(
            self._action_bar, text="💾  Guardar cambios", width=168, height=28,
            fg_color=ACCENT_SUCCESS, hover_color=ACCENT_SUCCESS_H,
            font=font_bold(), corner_radius=6,
            state="disabled",
            command=self._save_pending,
        )
        self.save_btn.grid(row=0, column=0, padx=(10, 4), pady=5)

        self.discard_btn = ctk.CTkButton(
            self._action_bar, text="✕  Descartar", width=100, height=28,
            fg_color=ACCENT_DANGER, hover_color=ACCENT_DANGER_H,
            font=font_small(), corner_radius=6,
            state="disabled",
            command=self._discard_pending,
        )
        self.discard_btn.grid(row=0, column=1, padx=(0, 6), pady=5)

        self.save_hint = ctk.CTkLabel(
            self._action_bar,
            text="Sin cambios pendientes  ·  Editá cualquier celda para comenzar",
            font=font_small(), text_color=TEXT_SUBTLE, anchor="w",
        )
        self.save_hint.grid(row=0, column=2, padx=4, pady=5, sticky="w")
        self._action_bar.grid_columnconfigure(2, weight=1)

        # Stats + pagination (right side of action bar)
        right = ctk.CTkFrame(self._action_bar, fg_color="transparent")
        right.grid(row=0, column=3, padx=(4, 10), pady=5, sticky="e")

        self.stats_label = ctk.CTkLabel(
            right, text="", font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED, anchor="e",
        )
        self.stats_label.grid(row=0, column=0, padx=(0, 10))

        pag_cfg = dict(
            width=26, height=26,
            fg_color=BG_ELEVATED, hover_color=ACCENT_BLUE,
            font=ctk.CTkFont(size=11), corner_radius=5,
        )
        self.btn_first = ctk.CTkButton(right, text="⏮", **pag_cfg, command=self._go_first)
        self.btn_first.grid(row=0, column=1, padx=1)
        self.btn_prev  = ctk.CTkButton(right, text="◀",  **pag_cfg, command=self._go_prev)
        self.btn_prev.grid(row=0, column=2, padx=1)
        self.page_label = ctk.CTkLabel(
            right, text="1 / 1", font=ctk.CTkFont(size=10),
            text_color=TEXT_HEADING, width=58, anchor="center",
        )
        self.page_label.grid(row=0, column=3, padx=4)
        self.btn_next  = ctk.CTkButton(right, text="▶",  **pag_cfg, command=self._go_next)
        self.btn_next.grid(row=0, column=4, padx=1)
        self.btn_last  = ctk.CTkButton(right, text="⏭", **pag_cfg, command=self._go_last)
        self.btn_last.grid(row=0, column=5, padx=1)

        # ── Row 2: table ─────────────────────────────────────────────────────
        self.table_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        self.table_frame.grid(row=2, column=0, padx=20, pady=(0, 8), sticky="nsew")
        self.table_frame.grid_columnconfigure(0, weight=1)
        self.table_frame.grid_rowconfigure(1, weight=1)

        # Column definitions: (header_label, width_px, is_entry_col)
        col_defs = [
            ("SKU",           88,  False),
            ("Activo",        54,  False),
            ("Marca",        110,  True),
            ("Descripción",  280,  True),
            ("Categoría",    130,  True),
            ("Precio Orig.",  95,  True),
            ("Margen %",      68,  True),
            ("Precio Final", 100,  False),
        ]
        self._col_widths = [w for _, w, _ in col_defs]
        self._col_is_entry = [e for _, _, e in col_defs]

        # Register numeric validator (reused for all price/margin entries)
        self._vcmd_num = (self.register(self._validate_nonneg_number), "%P")

        # ── Header row ───────────────────────────────────────────────────────
        header_frame = ctk.CTkFrame(
            self.table_frame, fg_color=BG_ELEVATED, corner_radius=6, height=24,
        )
        header_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        header_frame.grid_propagate(False)

        ctk.CTkLabel(
            header_frame, text="", width=14,
            font=ctk.CTkFont(size=8),
        ).grid(row=0, column=0, padx=(6, 0), pady=2, sticky="w")

        for i, (h, w, is_entry) in enumerate(col_defs):
            hpad = 3 if is_entry else 4
            ctk.CTkLabel(
                header_frame, text=h, width=w,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=ACCENT_PRIMARY,
            ).grid(row=0, column=i + 1, padx=hpad, pady=2, sticky="w")

        # ── Rows container (holds 20 reusable row widgets) ──────────────────
        self.rows_container = ctk.CTkFrame(
            self.table_frame, fg_color=BG_CARD, corner_radius=0,
        )
        self.rows_container.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 4))
        self.rows_container.grid_columnconfigure(0, weight=1)

        # Build 20 reusable rows + an "empty state" label
        self._build_rows_once()

        self._empty_label = ctk.CTkLabel(
            self.rows_container,
            text="No se encontraron productos con los filtros seleccionados.",
            text_color=TEXT_MUTED, font=font_label(),
        )
        # Not gridded yet; shown when page is empty

    def _build_rows_once(self):
        """Create the 20 row widgets once. Reused across all page changes."""
        self._init_in_progress = True
        for row_i in range(PAGE_SIZE):
            row = ctk.CTkFrame(
                self.rows_container, fg_color=BG_CARD,
                corner_radius=3, height=ROW_H,
            )
            row.grid(row=row_i, column=0, sticky="ew", pady=1)
            row.grid_propagate(False)
            # Pre-hidden until populated
            row.grid_remove()

            # State carried by the row, mutated when we populate it
            r_state = {
                "frame":   row,
                "sku":     None,           # currently-shown SKU (None when row is unused)
                "original": {},            # snapshot of original BD values for change detection
                "vars":    {},             # field → ctk.Variable
                "widgets": {},             # field → widget (for color updates)
            }

            # Col 0 — indicator dot (●=pending, D=discontinued)
            ind = ctk.CTkLabel(
                row, text="", width=14, font=ctk.CTkFont(size=8),
            )
            ind.grid(row=0, column=0, padx=(6, 0), pady=4, sticky="w")
            r_state["widgets"]["indicator"] = ind

            # Col 1 — SKU (read-only)
            sku_lbl = ctk.CTkLabel(
                row, text="", text_color=TEXT_HEADING,
                width=self._col_widths[0], font=ctk.CTkFont(size=11), anchor="w",
            )
            sku_lbl.grid(row=0, column=1, padx=4, pady=4, sticky="w")
            r_state["widgets"]["sku"] = sku_lbl

            # Col 2 — Active checkbox
            active_var = ctk.BooleanVar(value=True)
            chk = ctk.CTkCheckBox(
                row, text="", variable=active_var,
                width=self._col_widths[1],
                checkbox_width=16, checkbox_height=16,
                command=lambda i=row_i: self._on_active_change(i),
            )
            chk.grid(row=0, column=2, padx=4, pady=4, sticky="w")
            r_state["vars"]["active"] = active_var
            r_state["widgets"]["active"] = chk

            # Cols 3-5 — text entries (marca, descripción, categoría).
            # Brand is the only field that legitimately may be empty (when the
            # supplier doesn't specify one), so it gets a visible "—" placeholder
            # to make the empty state intentional rather than looking broken.
            for col_idx, field, width, placeholder in [
                (3, "brand",       self._col_widths[2], "—"),
                (4, "description", self._col_widths[3], ""),
                (5, "category",    self._col_widths[4], ""),
            ]:
                var = ctk.StringVar()
                entry = ctk.CTkEntry(
                    row, textvariable=var, width=width, height=ENTRY_H,
                    font=ctk.CTkFont(size=11),
                    placeholder_text=placeholder,
                )
                entry.grid(row=0, column=col_idx, padx=3, pady=3, sticky="w")
                var.trace_add(
                    "write",
                    lambda *_, i=row_i, f=field: self._on_text_change(i, f),
                )
                r_state["vars"][field] = var
                r_state["widgets"][field] = entry

            # Cols 6-7 — numeric entries (precio original, margen %)
            for col_idx, field, width in [
                (6, "price_original", self._col_widths[5]),
                (7, "margin_pct",     self._col_widths[6]),
            ]:
                var = ctk.StringVar()
                entry = ctk.CTkEntry(
                    row, textvariable=var, width=width, height=ENTRY_H,
                    font=ctk.CTkFont(size=11),
                    validate="key", validatecommand=self._vcmd_num,
                )
                entry.grid(row=0, column=col_idx, padx=3, pady=3, sticky="w")
                var.trace_add(
                    "write",
                    lambda *_, i=row_i, f=field: self._on_numeric_change(i, f),
                )
                r_state["vars"][field] = var
                r_state["widgets"][field] = entry

            # Col 8 — Precio Final (auto-calculated, read-only)
            final_lbl = ctk.CTkLabel(
                row, text="", text_color=ACCENT_SUCCESS,
                width=self._col_widths[7],
                font=ctk.CTkFont(size=11, weight="bold"), anchor="w",
            )
            final_lbl.grid(row=0, column=8, padx=4, pady=4, sticky="w")
            r_state["widgets"]["price_final"] = final_lbl

            self._rows.append(r_state)
        self._init_in_progress = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_show(self):
        # If DB changed since last view, reload. Otherwise just re-render.
        self._reload()

    def on_hide(self):
        pass

    # ── Data fetch / pagination ───────────────────────────────────────────────

    def _reload(self):
        if self._pending:
            ok = messagebox.askyesno(
                "Cambios sin guardar",
                f"Hay {len(self._pending)} cambio(s) sin guardar.\n"
                "¿Recargar de todas formas? Se perderán los cambios pendientes.",
            )
            if not ok:
                return
            self._pending.clear()
            self._update_save_bar()
        self._current_page = 0
        self._fetch_and_render()

    def _trigger_search(self):
        # A user-initiated search supersedes the dashboard health filter
        if self._ext_filter_key and self.search_var.get().strip():
            self._ext_filter_key  = ""
            self._ext_filter_text = ""
            self._ext_filter_skus = []
            self._ext_filter_frame.grid_remove()
        self._current_page = 0
        self._fetch_and_render()

    def _clear_search(self):
        self.search_var.set("")
        self._current_page = 0
        self._fetch_and_render()

    def _on_filter_change(self):
        self._current_page = 0
        self._fetch_and_render()

    def _toggle_clear_btn(self, *_):
        if self.search_var.get():
            self._clear_btn.grid()
        else:
            self._clear_btn.grid_remove()

    def _fetch_and_render(self):
        """Pull a single page from the DB and update the reusable row widgets."""
        try:
            items, total = self.controller.get_products_page(
                filter_mode=self.filter_var.get(),
                search=self.search_var.get().strip(),
                health_filter=self._ext_filter_key,
                sku_list=self._ext_filter_skus,
                limit=PAGE_SIZE,
                offset=self._current_page * PAGE_SIZE,
            )
        except Exception as e:
            messagebox.showerror("Error cargando productos", str(e))
            return

        self._page_items  = items
        self._total_count = total
        self._total_pages = max(1, -(-total // PAGE_SIZE))
        # Clamp current page if out of range (e.g., after a search)
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)
            # Re-fetch with corrected offset
            items, total = self.controller.get_products_page(
                filter_mode=self.filter_var.get(),
                search=self.search_var.get().strip(),
                health_filter=self._ext_filter_key,
                sku_list=self._ext_filter_skus,
                limit=PAGE_SIZE,
                offset=self._current_page * PAGE_SIZE,
            )
            self._page_items = items

        self._update_stats()
        self._update_pagination_controls()
        self._render_page()

    def _render_page(self):
        """Update the 20 reusable row widgets with the current page's data."""
        self._init_in_progress = True

        if not self._page_items:
            # Hide all rows, show empty label
            for r in self._rows:
                r["frame"].grid_remove()
                r["sku"] = None
            self._empty_label.grid(row=0, column=0, padx=24, pady=40)
        else:
            self._empty_label.grid_forget()
            for row_i, r in enumerate(self._rows):
                if row_i < len(self._page_items):
                    self._populate_row(row_i, self._page_items[row_i])
                    r["frame"].grid()
                else:
                    r["frame"].grid_remove()
                    r["sku"] = None

        self._init_in_progress = False

    def _populate_row(self, row_i: int, p: dict):
        """Push a product's values into row #row_i widgets."""
        r          = self._rows[row_i]
        sku        = p.get("sku", "")
        pending    = self._pending.get(sku, {})
        is_pending = bool(pending)
        is_disc    = bool(p.get("discontinued", False))
        is_active  = bool(p.get("active", True))
        orig_price = p.get("price_original", 0) or 0
        orig_margin = p.get("margin_pct", 0) or 0

        # Snapshot original values used for change detection
        r["sku"]      = sku
        r["original"] = {
            "active":         is_active,
            "brand":          str(p.get("brand") or ""),
            "description":    str(p.get("description") or ""),
            "category":       str(p.get("category") or ""),
            "price_original": str(int(orig_price)),
            "margin_pct":     str(int(orig_margin)),
            "iva_pct":        float(p.get("iva_pct") or 0),
            "round_to_nearest": int(p.get("round_to_nearest") or 0),
            "price_suffix":   str(p.get("price_suffix") or ""),
            "discontinued":   is_disc,
        }

        # Background color
        if is_pending:
            bg = BG_PENDING
        elif row_i % 2 == 0:
            bg = BG_ELEVATED
        else:
            bg = BG_CARD
        r["frame"].configure(fg_color=bg)

        # Indicator dot
        ind_text  = "●" if is_pending else ("D" if is_disc else "")
        ind_color = ACCENT_WARNING if is_pending else (TEXT_MUTED if is_disc else bg)
        r["widgets"]["indicator"].configure(text=ind_text, text_color=ind_color)

        # SKU label
        r["widgets"]["sku"].configure(text=sku)

        # Set vars (using pending overrides where applicable)
        r["vars"]["active"].set(bool(pending.get("active", is_active)))

        for field in ("brand", "description", "category"):
            val = str(pending.get(field, r["original"][field]))
            r["vars"][field].set(val)

        disp_price  = str(int(pending.get("price_original", orig_price) or 0))
        disp_margin = str(int(pending.get("margin_pct",     orig_margin) or 0))
        r["vars"]["price_original"].set(disp_price)
        r["vars"]["margin_pct"].set(disp_margin)

        # Recalculate Precio Final from current pending values (or stored)
        self._update_final_label(row_i)

    def _update_final_label(self, row_i: int):
        r = self._rows[row_i]
        try:
            orig   = float(r["vars"]["price_original"].get().replace(",", ".") or 0)
            margin = float(r["vars"]["margin_pct"].get().replace(",", ".") or 0)
            iva    = r["original"]["iva_pct"]
            rnd    = r["original"]["round_to_nearest"]
            sfx    = r["original"]["price_suffix"]
            p = Product(sku="", brand="", description="", price_original=orig, category="")
            p.apply_margin(margin, iva, rnd, sfx)
            r["widgets"]["price_final"].configure(text=f"$ {p.price_final:,.0f}")
        except (ValueError, TypeError):
            r["widgets"]["price_final"].configure(text="—")

    def _update_stats(self):
        total = self._total_count
        if total == 0:
            text = "Sin resultados"
        else:
            start = self._current_page * PAGE_SIZE + 1
            end   = min(start + PAGE_SIZE - 1, total)
            text  = f"{start}–{end} de {total}"
        self.stats_label.configure(text=text)

    def _update_pagination_controls(self):
        p = self._current_page
        t = self._total_pages
        self.page_label.configure(text=f"{p + 1} / {t}")
        fp = "normal" if p > 0     else "disabled"
        nl = "normal" if p < t - 1 else "disabled"
        self.btn_first.configure(state=fp)
        self.btn_prev.configure(state=fp)
        self.btn_next.configure(state=nl)
        self.btn_last.configure(state=nl)

    def _update_save_bar(self):
        n = len(self._pending)
        if n > 0:
            self._action_bar.configure(fg_color=BG_DIRTY)
            self.save_btn.configure(
                state="normal",
                text=f"💾  Guardar {n} cambio{'s' if n > 1 else ''}",
            )
            self.discard_btn.configure(state="normal")
            self.save_hint.configure(
                text=f"  {n} producto{'s' if n > 1 else ''} con cambios sin guardar",
                text_color=ACCENT_WARNING,
            )
        else:
            self._action_bar.configure(fg_color=BG_CARD)
            self.save_btn.configure(state="disabled", text="💾  Guardar cambios")
            self.discard_btn.configure(state="disabled")
            self.save_hint.configure(
                text="Sin cambios pendientes  ·  Editá cualquier celda para comenzar",
                text_color=TEXT_SUBTLE,
            )

    # ── Input validation ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_nonneg_number(proposed: str) -> bool:
        """Allow only non-negative real numbers (and intermediate states like '1.' or '')."""
        if proposed == "":
            return True
        v = proposed.replace(",", ".")
        if v.count(".") > 1 or v.startswith("-"):
            return False
        try:
            float(v.rstrip(".") or "0")
            return True
        except ValueError:
            return False

    # ── Change tracking ───────────────────────────────────────────────────────

    def _on_active_change(self, row_i: int):
        if self._init_in_progress:
            return
        r = self._rows[row_i]
        sku = r["sku"]
        if sku is None:
            return
        new_val = r["vars"]["active"].get()
        orig    = r["original"]["active"]

        if sku not in self._pending:
            self._pending[sku] = {}
        if new_val != orig:
            self._pending[sku]["active"] = new_val
        else:
            self._pending[sku].pop("active", None)
            if not self._pending[sku]:
                del self._pending[sku]

        self._update_row_highlight(row_i)
        self._update_save_bar()

    def _on_text_change(self, row_i: int, field: str):
        if self._init_in_progress:
            return
        r = self._rows[row_i]
        sku = r["sku"]
        if sku is None:
            return
        new_val = r["vars"][field].get()
        orig    = r["original"][field]

        if sku not in self._pending:
            self._pending[sku] = {}
        if new_val != orig:
            self._pending[sku][field] = new_val
        else:
            self._pending[sku].pop(field, None)
            if not self._pending[sku]:
                del self._pending[sku]

        self._update_row_highlight(row_i)
        self._update_save_bar()

    def _on_numeric_change(self, row_i: int, field: str):
        if self._init_in_progress:
            return
        r = self._rows[row_i]
        sku = r["sku"]
        if sku is None:
            return
        new_val = r["vars"][field].get().strip()
        orig    = r["original"][field]

        if sku not in self._pending:
            self._pending[sku] = {}
        if new_val != orig:
            self._pending[sku][field] = new_val
        else:
            self._pending[sku].pop(field, None)
            if not self._pending[sku]:
                del self._pending[sku]

        self._update_row_highlight(row_i)
        self._update_save_bar()
        self._update_final_label(row_i)

    def _update_row_highlight(self, row_i: int):
        r = self._rows[row_i]
        sku = r["sku"]
        if sku is None:
            return
        is_pending = sku in self._pending
        if is_pending:
            bg = BG_PENDING
        elif row_i % 2 == 0:
            bg = BG_ELEVATED
        else:
            bg = BG_CARD
        r["frame"].configure(fg_color=bg)

        is_disc   = r["original"].get("discontinued", False)
        ind_text  = "●" if is_pending else ("D" if is_disc else "")
        ind_color = ACCENT_WARNING if is_pending else (TEXT_MUTED if is_disc else bg)
        r["widgets"]["indicator"].configure(text=ind_text, text_color=ind_color)

    # ── Save / Discard ────────────────────────────────────────────────────────

    def _save_pending(self):
        n = len(self._pending)
        if n == 0:
            return

        skus    = list(self._pending.keys())
        preview = "\n".join(f"  • {s}" for s in skus[:8])
        if len(skus) > 8:
            preview += f"\n  … y {len(skus) - 8} más"

        ok = messagebox.askyesno(
            "Confirmar cambios",
            f"Guardar cambios en {n} producto(s):\n\n{preview}\n\n¿Continuar?",
        )
        if not ok:
            return

        errors = []
        saved  = 0

        for sku, changes in list(self._pending.items()):
            existing = self.controller.get_product(sku)
            if not existing:
                errors.append(f"{sku}: no encontrado en BD")
                continue
            try:
                update_dict: dict = {}

                if "active" in changes:
                    update_dict["active"] = bool(changes["active"])

                for tf in ("brand", "description", "category"):
                    if tf in changes:
                        update_dict[tf] = str(changes[tf]).strip()

                price_orig = None
                margin_pct = None

                if "price_original" in changes:
                    try:
                        price_orig = float(str(changes["price_original"]).replace(",", "."))
                        update_dict["price_original"] = price_orig
                    except (ValueError, TypeError):
                        errors.append(f"{sku}: precio inválido '{changes['price_original']}'")
                        continue

                if "margin_pct" in changes:
                    try:
                        margin_pct = float(str(changes["margin_pct"]).replace(",", "."))
                        update_dict["margin_pct"] = margin_pct
                    except (ValueError, TypeError):
                        errors.append(f"{sku}: margen inválido '{changes['margin_pct']}'")
                        continue

                if price_orig is not None or margin_pct is not None:
                    _o  = price_orig if price_orig  is not None else float(existing.get("price_original") or 0)
                    _m  = margin_pct if margin_pct  is not None else float(existing.get("margin_pct")     or 0)
                    _iv = float(existing.get("iva_pct")          or 0)
                    _rn = int(existing.get("round_to_nearest")   or 0)
                    _sx = existing.get("price_suffix")           or ""
                    prod = Product(sku=sku, brand="", description="", price_original=_o, category="")
                    prod.apply_margin(_m, _iv, _rn, _sx)
                    update_dict["price_final"] = prod.price_final
                    update_dict["margin_pct"]  = _m

                if not update_dict:
                    continue

                self.controller.update_product(sku, update_dict)
                saved += 1
            except Exception as e:
                errors.append(f"{sku}: {e}")

        self._pending.clear()
        self._update_save_bar()
        self._fetch_and_render()   # refresh current page from BD

        # Activity log: one entry per save action (batch), never per-SKU
        if saved > 0:
            try:
                self.controller.log_edit_batch(saved)
            except Exception:
                pass

        if errors:
            messagebox.showwarning(
                "Guardado con advertencias",
                f"{saved} producto(s) guardado(s).\n\nErrores:\n" + "\n".join(errors),
            )
        else:
            messagebox.showinfo("Guardado", f"✓  {saved} producto(s) actualizado(s).")

    def _discard_pending(self):
        n = len(self._pending)
        if n == 0:
            return
        ok = messagebox.askyesno(
            "Descartar cambios",
            f"¿Descartar {n} cambio(s) sin guardar?\nEsta acción no se puede deshacer.",
        )
        if ok:
            self._pending.clear()
            self._update_save_bar()
            self._fetch_and_render()

    # ── Pagination ────────────────────────────────────────────────────────────

    def _go_first(self):
        self._current_page = 0
        self._fetch_and_render()

    def _go_prev(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._fetch_and_render()

    def _go_next(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._fetch_and_render()

    def _go_last(self):
        self._current_page = self._total_pages - 1
        self._fetch_and_render()

    # ── External (health) filter API ──────────────────────────────────────────

    def apply_external_args(self, **kwargs):
        """
        Called by MainWindow after navigating here from Dashboard.
        Accepts: health_filter='no_image|zero_price|low_margin|no_description|missing_image',
                 health_label='display label', health_count=N,
                 missing_skus=[...] (only for missing_image — exact SKU list).
        """
        key   = (kwargs.get("health_filter") or "").strip()
        label = (kwargs.get("health_label") or "").strip()
        count = kwargs.get("health_count")

        if not key:
            return

        self._ext_filter_key  = key
        self._ext_filter_text = label or key
        self._ext_filter_skus = list(kwargs.get("missing_skus") or [])

        # Reset other filters so the user sees the health-filtered set exactly
        # as it was counted on the Dashboard (active + non-discontinued).
        self.search_var.set("")
        self.filter_var.set("Activos")

        # Update visible chip
        chip_text = f"Filtro de salud: {label or key}"
        if count is not None:
            chip_text += f"  ·  {count} producto(s)"
        self._ext_filter_label.configure(text=chip_text)
        self._ext_filter_frame.grid()

        self._current_page = 0
        self._fetch_and_render()

    def _clear_external_filter(self):
        if not self._ext_filter_key:
            return
        self._ext_filter_key  = ""
        self._ext_filter_text = ""
        self._ext_filter_skus = []
        self._ext_filter_frame.grid_remove()
        self._current_page = 0
        self._fetch_and_render()
