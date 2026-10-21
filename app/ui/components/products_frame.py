"""
Products management frame.

Architecture:
  * Row widgets are built ONCE (in _build_rows_once) and reused on every page change
    — just StringVar/BooleanVar values are updated. No destroy/recreate per page.
  * Pagination + filter + search are done at the SQL layer via controller.get_products_page().
    Only 20 rows + 1 COUNT query per page change. No full-table load.
  * Search triggers on Enter / search button click. No live debounce.
  * Edits accumulate in self._pending (per-SKU dict of changes). Saving sends a bulk
    write to DB and refreshes the current page from the DB.
  * Cells look like plain text until focused, when they show an input border.
"""
from __future__ import annotations
from tkinter import messagebox
import customtkinter as ctk

from app.core.app_controller import AppController
from app.models.product import Product
from app.utils.formatting import format_price, parse_number
from app.ui.icons import icon
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED, BG_HOVER, BG_ROW_ALT, BORDER, BORDER_STRONG,
    ACCENT, ACCENT_SOFT, ACCENT_TEXT, WARNING,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    PAGE_PADX, RADIUS_BUTTON, FONT_FAMILY, FONT_SEMIBOLD,
    font_small, font_label, font_caps,
    card, page_header, primary_button, secondary_button, icon_button,
    segmented, pill, fmt_int,
)

PAGE_SIZE   = 15
ROW_H       = 32          # product row height in pixels
ENTRY_H     = 26          # CTkEntry height inside rows
ENTRY_INSET = 7           # left/right text padding inside a CTkEntry

# Filter values — also understood by DatabaseManager.get_products_page()
FILTER_ALL          = "All"
FILTER_ACTIVE       = "Active"
FILTER_INACTIVE     = "Inactive"
FILTER_DISCONTINUED = "Discontinued"


def _fmt_num(value) -> str:
    """Editable number text: 18.06 → '18.06', 18.5 → '18.5', 1000.0 → '1000'."""
    return f"{float(value or 0):.2f}".rstrip("0").rstrip(".")


class _EntryText:
    """
    StringVar-like adapter over a CTkEntry. CTkEntry cannot show its
    placeholder when bound to a textvariable, so the search box keeps no
    variable and is read/written through this object instead.
    """

    def __init__(self, entry: ctk.CTkEntry):
        self._entry = entry

    def get(self) -> str:
        return self._entry.get()

    def set(self, value: str):
        self._entry.delete(0, "end")
        if value:
            self._entry.insert(0, value)
        else:
            # Restore the placeholder after clearing programmatically
            self._entry.master.focus_set()
        self._entry.event_generate("<<SearchChanged>>")


class ProductsFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller = controller

        # ── Page state ───────────────────────────────────────────────────────
        self._current_page: int = 0
        self._total_pages: int = 1
        self._total_count: int = 0
        self._page_items: list[dict] = []   # current page's product dicts (raw from the DB)

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
        self._rows: list[dict] = []
        self._hover_row: int | None = None

        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # table fills remaining height

        # ── Row 0: header + save bar ─────────────────────────────────────────
        head = page_header(self, "Products", " ")
        head.grid(row=0, column=0, padx=PAGE_PADX, pady=(26, 14), sticky="ew")
        self._subtitle = head.grid_slaves(row=1, column=0)[0]

        save_bar = ctk.CTkFrame(head, fg_color="transparent")
        save_bar.grid(row=0, column=1, rowspan=2, sticky="e")
        self.save_hint = ctk.CTkLabel(save_bar, text="", font=font_label(), text_color=TEXT_SUBTLE)
        self.save_hint.grid(row=0, column=0, padx=(0, 12))
        self.discard_btn = secondary_button(save_bar, "Discard", self._discard_pending, width=90)
        self.discard_btn.grid(row=0, column=1, padx=(0, 8))
        self.save_btn = primary_button(save_bar, "Save changes", self._save_pending,
                                       icon=icon("save", "#FFFFFF", 15), width=140)
        self.save_btn.grid(row=0, column=2)

        # ── Row 1: toolbar ───────────────────────────────────────────────────
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, padx=PAGE_PADX, pady=(0, 12), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)

        search_box = ctk.CTkFrame(toolbar, fg_color=BG_ELEVATED, corner_radius=RADIUS_BUTTON,
                                  border_width=1, border_color=BORDER_STRONG, height=34)
        search_box.grid(row=0, column=0, sticky="ew")
        search_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search_box, text="", image=icon("search", TEXT_SUBTLE, 15)).grid(
            row=0, column=0, padx=(12, 4))
        self.search_entry = ctk.CTkEntry(
            search_box, placeholder_text="Search by SKU, description, brand or category",
            height=30, border_width=0, fg_color=BG_ELEVATED,
            text_color=TEXT_PRIMARY, placeholder_text_color=TEXT_SUBTLE,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
        )
        self.search_entry.grid(row=0, column=1, padx=(0, 4), pady=2, sticky="ew")
        self.search_entry.bind("<Return>", lambda e: self._trigger_search())
        self.search_entry.bind("<KeyRelease>", self._toggle_clear_btn, add="+")
        self.search_entry.bind("<<SearchChanged>>", self._toggle_clear_btn, add="+")
        self.search_var = _EntryText(self.search_entry)

        self._clear_btn = icon_button(search_box, icon("x", TEXT_MUTED, 14), self._clear_search, size=28)
        self._clear_btn.grid(row=0, column=2, padx=(0, 4))
        self._clear_btn.grid_remove()

        self.filter_var = ctk.StringVar(value=FILTER_ALL)
        segmented(toolbar, [FILTER_ALL, FILTER_ACTIVE, FILTER_INACTIVE, FILTER_DISCONTINUED],
                  variable=self.filter_var, command=lambda *_: self._on_filter_change()).grid(
            row=0, column=1, padx=(10, 0))

        icon_button(toolbar, icon("refresh", TEXT_MUTED, 16), self._reload, size=34).grid(
            row=0, column=2, padx=(6, 0))

        # External-filter chip (hidden until apply_external_args is called)
        self._ext_filter_frame = ctk.CTkFrame(toolbar, fg_color=ACCENT_SOFT, corner_radius=RADIUS_BUTTON)
        self._ext_filter_frame.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky="w")
        self._ext_filter_frame.grid_remove()
        ctk.CTkLabel(self._ext_filter_frame, text="", image=icon("alert", WARNING, 14)).grid(
            row=0, column=0, padx=(10, 6), pady=4)
        self._ext_filter_label = ctk.CTkLabel(self._ext_filter_frame, text="", font=font_label(),
                                              text_color=ACCENT_TEXT)
        self._ext_filter_label.grid(row=0, column=1, pady=4)
        icon_button(self._ext_filter_frame, icon("x", ACCENT_TEXT, 13),
                    self._clear_external_filter, size=26).grid(row=0, column=2, padx=(6, 4))

        # ── Row 2: table ─────────────────────────────────────────────────────
        self.table_frame = card(self, row=2, column=0, padx=PAGE_PADX, pady=(0, 22), sticky="nsew")
        self.table_frame.grid_columnconfigure(0, weight=1)
        self.table_frame.grid_rowconfigure(2, weight=1)

        # Column definitions: (header_label, width_px, is_entry_col, align)
        col_defs = [
            ("SKU",          104, False, "w"),
            ("ACTIVE",        56, False, "w"),
            ("BRAND",        116, True,  "w"),
            ("DESCRIPTION",  300, True,  "w"),
            ("CATEGORY",     112, True,  "w"),
            ("COST",          80, True,  "e"),
            ("MARGIN %",      72, True,  "e"),
            ("FINAL PRICE",   96, False, "e"),
        ]
        self._col_widths   = [w for _, w, _, _ in col_defs]
        self._col_is_entry = [e for _, _, e, _ in col_defs]

        # Register numeric validator (reused for all price/margin entries)
        self._vcmd_num = (self.register(self._validate_nonneg_number), "%P")

        header_frame = ctk.CTkFrame(self.table_frame, fg_color="transparent", height=36)
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        ctk.CTkLabel(header_frame, text="", width=14).grid(row=0, column=0, padx=(6, 0))
        for i, (h, w, is_entry, align) in enumerate(col_defs):
            # Entry text is inset by the entry's own padding; match it in the header
            inset = ENTRY_INSET if is_entry else 0
            pad = (4 + inset, 4) if align == "w" else (4, 4 + inset)
            ctk.CTkLabel(
                header_frame, text=h, width=w - inset, font=font_caps(), text_color=TEXT_SUBTLE,
                anchor=align,
            ).grid(row=0, column=i + 1, padx=pad, pady=6, sticky="w")
        ctk.CTkFrame(self.table_frame, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=1, column=0, sticky="ew", padx=1)

        self.rows_container = ctk.CTkFrame(self.table_frame, fg_color="transparent", corner_radius=0)
        self.rows_container.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 4))
        self.rows_container.grid_columnconfigure(0, weight=1)

        self._build_rows_once()

        self._empty_label = ctk.CTkLabel(
            self.rows_container, text="No products match the selected filters.",
            text_color=TEXT_MUTED, font=font_label(),
        )

        # Footer: count + pagination
        ctk.CTkFrame(self.table_frame, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=3, column=0, sticky="ew", padx=1)
        footer = ctk.CTkFrame(self.table_frame, fg_color="transparent")
        footer.grid(row=4, column=0, padx=16, pady=8, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self.stats_label = ctk.CTkLabel(footer, text="", font=font_label(), text_color=TEXT_MUTED, anchor="w")
        self.stats_label.grid(row=0, column=0, sticky="w")

        pag = ctk.CTkFrame(footer, fg_color="transparent")
        pag.grid(row=0, column=1, sticky="e")
        self.btn_first = icon_button(pag, icon("chevrons_left", TEXT_MUTED, 16), self._go_first, size=30)
        self.btn_prev  = icon_button(pag, icon("chevron_left", TEXT_MUTED, 16), self._go_prev, size=30)
        self.page_label = ctk.CTkLabel(pag, text="1 / 1", font=font_label(), text_color=TEXT_HEADING,
                                       width=70)
        self.btn_next  = icon_button(pag, icon("chevron_right", TEXT_MUTED, 16), self._go_next, size=30)
        self.btn_last  = icon_button(pag, icon("chevrons_right", TEXT_MUTED, 16), self._go_last, size=30)
        for i, w in enumerate((self.btn_first, self.btn_prev, self.page_label, self.btn_next, self.btn_last)):
            w.grid(row=0, column=i, padx=1)

        self._update_save_bar()

    def _build_rows_once(self):
        """Create the 20 row widgets once. Reused across all page changes."""
        self._init_in_progress = True
        for row_i in range(PAGE_SIZE):
            row = ctk.CTkFrame(self.rows_container, fg_color=BG_CARD, corner_radius=6, height=ROW_H)
            row.grid(row=row_i, column=0, sticky="ew", pady=0)
            row.grid_propagate(False)
            row.grid_remove()

            r_state = {
                "frame":    row,
                "sku":      None,   # currently-shown SKU (None when row is unused)
                "original": {},     # snapshot of original DB values for change detection
                "vars":     {},     # field → ctk.Variable
                "widgets":  {},     # field → widget (for color updates)
                "entries":  [],     # entries repainted with the row background
                "bg":       BG_CARD,
            }

            # Col 0 — indicator dot (pending / discontinued)
            ind = ctk.CTkLabel(row, text="", width=14, font=ctk.CTkFont(size=9))
            ind.grid(row=0, column=0, padx=(6, 0), sticky="w")
            r_state["widgets"]["indicator"] = ind

            # Col 1 — SKU (read-only)
            sku_lbl = ctk.CTkLabel(row, text="", text_color=TEXT_PRIMARY, width=self._col_widths[0],
                                   font=ctk.CTkFont(family=FONT_SEMIBOLD, size=12), anchor="w")
            sku_lbl.grid(row=0, column=1, padx=4, sticky="w")
            r_state["widgets"]["sku"] = sku_lbl

            # Col 2 — Active switch
            active_var = ctk.BooleanVar(value=True)
            sw = ctk.CTkSwitch(
                row, text="", variable=active_var, width=self._col_widths[1],
                switch_width=32, switch_height=16, progress_color=ACCENT,
                button_color=TEXT_PRIMARY, button_hover_color="#FFFFFF", fg_color=BORDER_STRONG,
                command=lambda i=row_i: self._on_active_change(i),
            )
            sw.grid(row=0, column=2, padx=4, sticky="w")
            r_state["vars"]["active"] = active_var
            r_state["widgets"]["active"] = sw

            # Cols 3-5 — text entries. Brand may legitimately be empty, so it
            # gets a "—" placeholder that makes the empty state intentional.
            for col_idx, field, width, placeholder in [
                (3, "brand",       self._col_widths[2], "—"),
                (4, "description", self._col_widths[3], ""),
                (5, "category",    self._col_widths[4], ""),
            ]:
                var = ctk.StringVar()
                e = self._cell_entry(row, var, width, row_i)
                e.configure(placeholder_text=placeholder)
                e.grid(row=0, column=col_idx, padx=4, sticky="w")
                var.trace_add("write", lambda *_, i=row_i, f=field: self._on_text_change(i, f))
                r_state["vars"][field] = var
                r_state["widgets"][field] = e
                r_state["entries"].append(e)

            # Cols 6-7 — numeric entries (cost, margin %)
            for col_idx, field, width in [
                (6, "price_original", self._col_widths[5]),
                (7, "margin_pct",     self._col_widths[6]),
            ]:
                var = ctk.StringVar()
                e = self._cell_entry(row, var, width, row_i, justify="right")
                e.configure(validate="key", validatecommand=self._vcmd_num)
                e.grid(row=0, column=col_idx, padx=4, sticky="w")
                var.trace_add("write", lambda *_, i=row_i, f=field: self._on_numeric_change(i, f))
                r_state["vars"][field] = var
                r_state["widgets"][field] = e
                r_state["entries"].append(e)

            # Col 8 — Final Price (auto-calculated, read-only)
            final_lbl = ctk.CTkLabel(row, text="", text_color=TEXT_PRIMARY, width=self._col_widths[7],
                                     font=ctk.CTkFont(family=FONT_SEMIBOLD, size=12), anchor="e")
            final_lbl.grid(row=0, column=8, padx=(4, 10), sticky="w")
            r_state["widgets"]["price_final"] = final_lbl

            # Row hover highlight
            for w in (row, ind, sku_lbl, final_lbl):
                w.bind("<Enter>", lambda e, i=row_i: self._set_hover(i), add="+")
            row.bind("<Leave>", lambda e, i=row_i: self._clear_hover(i, e), add="+")

            self._rows.append(r_state)
        self._init_in_progress = False

    def _cell_entry(self, row, var, width: int, row_i: int, justify: str = "left") -> ctk.CTkEntry:
        """Entry that blends into the row and shows an input border only while focused."""
        e = ctk.CTkEntry(
            row, textvariable=var, width=width, height=ENTRY_H, justify=justify,
            corner_radius=6, border_width=1, fg_color=BG_CARD, border_color=BG_CARD,
            text_color=TEXT_HEADING, placeholder_text_color=TEXT_SUBTLE,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        e.bind("<FocusIn>", lambda ev, w=e: w.configure(border_color=ACCENT, fg_color=BG_ELEVATED), add="+")
        e.bind("<FocusOut>", lambda ev, w=e, i=row_i: self._repaint_entry(w, i), add="+")
        e.bind("<Enter>", lambda ev, i=row_i: self._set_hover(i), add="+")
        return e

    # ── Row painting ──────────────────────────────────────────────────────────

    def _row_bg(self, row_i: int) -> str:
        r = self._rows[row_i]
        if r["sku"] is not None and r["sku"] in self._pending:
            return ACCENT_SOFT
        if self._hover_row == row_i:
            return BG_HOVER
        return BG_ROW_ALT if row_i % 2 else BG_CARD

    def _paint_row(self, row_i: int):
        r = self._rows[row_i]
        bg = self._row_bg(row_i)
        r["bg"] = bg
        r["frame"].configure(fg_color=bg)
        for e in r["entries"]:
            self._repaint_entry(e, row_i)

    def _repaint_entry(self, e: ctk.CTkEntry, row_i: int):
        if e.focus_get() is getattr(e, "_entry", None):
            return   # keep the focused look
        bg = self._rows[row_i]["bg"]
        e.configure(fg_color=bg, border_color=bg)

    def _set_hover(self, row_i: int):
        if self._hover_row == row_i:
            return
        prev, self._hover_row = self._hover_row, row_i
        if prev is not None:
            self._paint_row(prev)
        self._paint_row(row_i)

    def _clear_hover(self, row_i: int, event):
        # <Leave> also fires when the pointer moves onto a child widget
        frame = self._rows[row_i]["frame"]
        x, y = frame.winfo_pointerxy()
        under = frame.winfo_containing(x, y)
        if under is not None and str(under).startswith(str(frame)):
            return
        if self._hover_row == row_i:
            self._hover_row = None
            self._paint_row(row_i)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_show(self):
        self._reload()

    def on_hide(self):
        pass

    # ── Data fetch / pagination ───────────────────────────────────────────────

    def _reload(self):
        if self._pending:
            ok = messagebox.askyesno(
                "Unsaved changes",
                f"There are {len(self._pending)} unsaved change(s).\n"
                "Reload anyway? Pending changes will be lost.",
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
            messagebox.showerror("Error loading products", str(e))
            return

        self._page_items  = items
        self._total_count = total
        self._total_pages = max(1, -(-total // PAGE_SIZE))
        # Clamp current page if out of range (e.g., after a search)
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)
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
        self._hover_row = None

        if not self._page_items:
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
        r           = self._rows[row_i]
        sku         = p.get("sku", "")
        pending     = self._pending.get(sku, {})
        is_disc     = bool(p.get("discontinued", False))
        is_active   = bool(p.get("active", True))
        orig_price  = p.get("price_original", 0) or 0
        orig_margin = p.get("margin_pct", 0) or 0

        # Snapshot original values used for change detection
        r["sku"]      = sku
        r["original"] = {
            "active":           is_active,
            "brand":            str(p.get("brand") or ""),
            "description":      str(p.get("description") or ""),
            "category":         str(p.get("category") or ""),
            "price_original":   _fmt_num(orig_price),
            "margin_pct":       _fmt_num(orig_margin),
            "iva_pct":          float(p.get("iva_pct") or 0),
            "round_to_nearest": int(p.get("round_to_nearest") or 0),
            "price_suffix":     str(p.get("price_suffix") or ""),
            "discontinued":     is_disc,
        }

        r["widgets"]["sku"].configure(text=sku, text_color=TEXT_MUTED if is_disc else TEXT_PRIMARY)
        r["vars"]["active"].set(bool(pending.get("active", is_active)))

        for field in ("brand", "description", "category"):
            r["vars"][field].set(str(pending.get(field, r["original"][field])))

        # Pending values are kept exactly as typed; stored ones are formatted
        disp_price  = str(pending["price_original"]) if "price_original" in pending else _fmt_num(orig_price)
        disp_margin = str(pending["margin_pct"])     if "margin_pct" in pending     else _fmt_num(orig_margin)
        r["vars"]["price_original"].set(disp_price)
        r["vars"]["margin_pct"].set(disp_margin)

        self._update_row_highlight(row_i)
        self._update_final_label(row_i)

    def _update_final_label(self, row_i: int):
        r = self._rows[row_i]
        try:
            orig   = parse_number(r["vars"]["price_original"].get() or "0")
            margin = parse_number(r["vars"]["margin_pct"].get() or "0")
            p = Product(sku="", brand="", description="", price_original=orig, category="")
            p.apply_margin(margin, r["original"]["iva_pct"], r["original"]["round_to_nearest"],
                           r["original"]["price_suffix"])
            r["widgets"]["price_final"].configure(text=format_price(p.price_final))
        except (ValueError, TypeError):
            r["widgets"]["price_final"].configure(text="—")

    def _update_stats(self):
        total = self._total_count
        if total == 0:
            text = "No results"
        else:
            start = self._current_page * PAGE_SIZE + 1
            end   = min(start + PAGE_SIZE - 1, total)
            text  = f"Showing {fmt_int(start)}–{fmt_int(end)} of {fmt_int(total)}"
        self.stats_label.configure(text=text)
        scope = self.filter_var.get().lower()
        self._subtitle.configure(
            text=f"{fmt_int(total)} {'' if scope == 'all' else scope + ' '}products"
                 + (f" matching “{self.search_var.get().strip()}”" if self.search_var.get().strip() else "")
        )

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
            self.save_btn.configure(state="normal", fg_color=ACCENT,
                                    text=f"Save {n} change{'s' if n > 1 else ''}")
            self.discard_btn.configure(state="normal")
            self.save_hint.configure(text=f"{n} unsaved", text_color=WARNING)
        else:
            self.save_btn.configure(state="disabled", fg_color=BG_ELEVATED, text="Save changes")
            self.discard_btn.configure(state="disabled")
            self.save_hint.configure(text="Click any cell to edit", text_color=TEXT_SUBTLE)

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

    def _track(self, row_i: int, field: str, new_val):
        r = self._rows[row_i]
        sku = r["sku"]
        if sku is None:
            return
        if sku not in self._pending:
            self._pending[sku] = {}
        if new_val != r["original"][field]:
            self._pending[sku][field] = new_val
        else:
            self._pending[sku].pop(field, None)
            if not self._pending[sku]:
                del self._pending[sku]
        self._update_row_highlight(row_i)
        self._update_save_bar()

    def _on_active_change(self, row_i: int):
        if self._init_in_progress:
            return
        self._track(row_i, "active", self._rows[row_i]["vars"]["active"].get())

    def _on_text_change(self, row_i: int, field: str):
        if self._init_in_progress:
            return
        self._track(row_i, field, self._rows[row_i]["vars"][field].get())

    def _on_numeric_change(self, row_i: int, field: str):
        if self._init_in_progress:
            return
        self._track(row_i, field, self._rows[row_i]["vars"][field].get().strip())
        self._update_final_label(row_i)

    def _update_row_highlight(self, row_i: int):
        r = self._rows[row_i]
        sku = r["sku"]
        if sku is None:
            return
        is_pending = sku in self._pending
        is_disc    = r["original"].get("discontinued", False)
        r["widgets"]["indicator"].configure(
            text="●" if (is_pending or is_disc) else "",
            text_color=ACCENT if is_pending else TEXT_SUBTLE,
        )
        self._paint_row(row_i)

    # ── Save / Discard ────────────────────────────────────────────────────────

    def _save_pending(self):
        n = len(self._pending)
        if n == 0:
            return

        skus    = list(self._pending.keys())
        preview = "\n".join(f"  • {s}" for s in skus[:8])
        if len(skus) > 8:
            preview += f"\n  … and {len(skus) - 8} more"

        ok = messagebox.askyesno(
            "Confirm changes",
            f"Save changes to {n} product(s):\n\n{preview}\n\nContinue?",
        )
        if not ok:
            return

        errors = []
        saved  = 0

        for sku, changes in list(self._pending.items()):
            existing = self.controller.get_product(sku)
            if not existing:
                errors.append(f"{sku}: not found in the database")
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
                        price_orig = parse_number(changes["price_original"])
                        update_dict["price_original"] = price_orig
                    except (ValueError, TypeError):
                        errors.append(f"{sku}: invalid cost '{changes['price_original']}'")
                        continue

                if "margin_pct" in changes:
                    try:
                        margin_pct = parse_number(changes["margin_pct"])
                        update_dict["margin_pct"] = margin_pct
                    except (ValueError, TypeError):
                        errors.append(f"{sku}: invalid margin '{changes['margin_pct']}'")
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
        self._fetch_and_render()   # refresh current page from the DB

        # Activity log: one entry per save action (batch), never per-SKU
        if saved > 0:
            try:
                self.controller.log_edit_batch(saved)
            except Exception:
                pass

        if errors:
            messagebox.showwarning(
                "Saved with warnings",
                f"{saved} product(s) saved.\n\nErrors:\n" + "\n".join(errors),
            )
        else:
            messagebox.showinfo("Saved", f"✓  {saved} product(s) updated.")

    def _discard_pending(self):
        n = len(self._pending)
        if n == 0:
            return
        ok = messagebox.askyesno(
            "Discard changes",
            f"Discard {n} unsaved change(s)?\nThis cannot be undone.",
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
        self.filter_var.set(FILTER_ACTIVE)

        chip_text = f"Health filter: {label or key}"
        if count is not None:
            chip_text += f"  ·  {fmt_int(count)} product(s)"
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
