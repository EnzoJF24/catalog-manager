"""
Settings frame: global margins, import history, registered parsers.
Company branding and PDF settings live in the Catalog tab.
"""
from __future__ import annotations
import json
import threading
from tkinter import messagebox
import customtkinter as ctk

from app.core.app_controller import AppController
from app.ui.icons import icon
from app.ui.theme import (
    BG_BASE, BG_ELEVATED, BORDER, ACCENT, ACCENT_SOFT,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    PAGE_PADX, FONT_SEMIBOLD,
    font_label, font_small, font_caps, font_mono,
    card, section_title, page_header, secondary_button, icon_button, pill, fmt_int,
)
from app.ui.components.spinner import Spinner

# Import-history columns: (header, width, anchor)
_HISTORY_COLS = [
    ("DATE",       140, "w"),
    ("SUPPLIER",   190, "w"),
    ("PRODUCTS",    90, "e"),
    ("WITH IMAGE",  96, "e"),
    ("NOTES",      330, "w"),
    ("SESSION",    100, "w"),
]


class SettingsFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller = controller
        self._build()

    def _build(self):
        self.grid_columnconfigure((0, 1), weight=1, uniform="tools")
        self.grid_rowconfigure(2, weight=1)

        page_header(self, "Tools", "Maintenance actions, import history and supported suppliers.").grid(
            row=0, column=0, columnspan=2, padx=PAGE_PADX, pady=(26, 18), sticky="ew")

        # ── Pricing maintenance ──────────────────────────────────────────────
        pricing = card(self, row=1, column=0, padx=(PAGE_PADX, 6), sticky="nsew")
        pricing.grid_columnconfigure(0, weight=1)
        section_title(pricing, "Re-apply pricing").grid(row=0, column=0, padx=20, pady=(18, 6), sticky="ew")
        ctk.CTkLabel(
            pricing,
            text="Recalculates every active product's final price with the current rules — "
                 "useful after changing the margin.",
            font=font_label(), text_color=TEXT_MUTED, justify="left", anchor="w", wraplength=440,
        ).grid(row=1, column=0, padx=20, sticky="w")
        self._rules_label = ctk.CTkLabel(pricing, text="", font=font_mono(), text_color=TEXT_HEADING,
                                         anchor="w", fg_color=BG_ELEVATED, corner_radius=6)
        self._rules_label.grid(row=2, column=0, padx=20, pady=(12, 0), sticky="w", ipadx=10, ipady=4)

        act = ctk.CTkFrame(pricing, fg_color="transparent")
        act.grid(row=3, column=0, padx=20, pady=(14, 18), sticky="ew")
        act.grid_columnconfigure(1, weight=1)
        self._reapply_btn = secondary_button(act, "Re-apply margin to all products", self._reapply_margins,
                                             icon=icon("percent", TEXT_HEADING, 15))
        self._reapply_btn.grid(row=0, column=0, sticky="w")
        self._reapply_spinner = Spinner(act, icon_color=ACCENT)
        self._reapply_spinner.grid(row=0, column=1, padx=12, sticky="w")

        # ── Registered parsers ───────────────────────────────────────────────
        pf = card(self, row=1, column=1, padx=(6, PAGE_PADX), sticky="nsew")
        pf.grid_columnconfigure(0, weight=1)
        section_title(pf, "Supplier parsers", "auto-detected on import").grid(
            row=0, column=0, padx=20, pady=(18, 10), sticky="ew")

        from app.parsers.parser_factory import ParserFactory
        parsers = ParserFactory.list_parsers()
        for i, p in enumerate(parsers):
            row = ctk.CTkFrame(pf, fg_color="transparent")
            row.grid(row=i + 1, column=0, padx=20, pady=4, sticky="ew")
            row.grid_columnconfigure(1, weight=1)
            badge = ctk.CTkFrame(row, width=30, height=30, corner_radius=8, fg_color=ACCENT_SOFT)
            badge.grid(row=0, column=0, rowspan=2, padx=(0, 12))
            badge.grid_propagate(False)
            ctk.CTkLabel(badge, text="", image=icon("code", ACCENT, 15)).place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(row, text=p["name"], font=ctk.CTkFont(family=FONT_SEMIBOLD, size=13),
                         text_color=TEXT_PRIMARY, anchor="w").grid(row=0, column=1, sticky="sw")
            ctk.CTkLabel(row, text=p["class"], font=font_small(), text_color=TEXT_SUBTLE,
                         anchor="w").grid(row=1, column=1, sticky="nw")
            pill(row, "Active", "success").grid(row=0, column=2, rowspan=2, sticky="e")

        ctk.CTkLabel(
            pf, text="New suppliers: implement BaseParser and register it in parser_factory.py",
            font=font_small(), text_color=TEXT_SUBTLE, anchor="w",
        ).grid(row=len(parsers) + 1, column=0, padx=20, pady=(8, 18), sticky="w")

        # ── Import history ───────────────────────────────────────────────────
        hist = card(self, row=2, column=0, columnspan=2, padx=PAGE_PADX, pady=(12, 22), sticky="nsew")
        hist.grid_columnconfigure(0, weight=1)
        hist.grid_rowconfigure(3, weight=1)
        head = section_title(hist, "Import history")
        head.grid(row=0, column=0, padx=20, pady=(14, 6), sticky="ew")
        icon_button(head, icon("refresh", TEXT_MUTED, 15), self._load_history, size=30).grid(
            row=0, column=1, sticky="e")

        cols = ctk.CTkFrame(hist, fg_color="transparent")
        cols.grid(row=1, column=0, padx=20, sticky="ew")
        for i, (h, w, anchor) in enumerate(_HISTORY_COLS):
            ctk.CTkLabel(cols, text=h, font=font_caps(), text_color=TEXT_SUBTLE, width=w,
                         anchor=anchor).grid(row=0, column=i, padx=(0, 16), pady=(0, 6), sticky="w")
        ctk.CTkFrame(hist, height=1, fg_color=BORDER, corner_radius=0).grid(row=2, column=0, sticky="ew", padx=1)

        self._hist_rows = ctk.CTkScrollableFrame(hist, fg_color="transparent", corner_radius=0,
                                                 scrollbar_button_color=BG_ELEVATED)
        self._hist_rows.grid(row=3, column=0, padx=8, pady=(4, 10), sticky="nsew")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _reapply_margins(self):
        ok = messagebox.askyesno(
            "Re-apply margin",
            "Apply the configured global margin to all active products?\n\n"
            "This recalculates every product's Final Price using the current margin.",
        )
        if not ok:
            return

        self._reapply_btn.configure(state="disabled")
        self._reapply_spinner.start("Re-applying margin…")

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
        messagebox.showinfo("Success", f"✓  Margin re-applied to {count} products.")

    def _reapply_error(self, error: str):
        self._reapply_spinner.stop()
        self._reapply_btn.configure(state="normal")
        messagebox.showerror("Error", error)

    def _refresh_rules(self):
        mc = self.controller.margin_config
        rnd = f"round up to {mc.round_to_nearest}" if mc.round_to_nearest else "no rounding"
        end = f"ending {mc.price_suffix}" if mc.price_suffix else "no price ending"
        self._rules_label.configure(text=f"margin {mc.margin_pct:g}%  ·  tax {mc.iva_pct:g}%  ·  {rnd}  ·  {end}")

    def _load_history(self):
        for w in self._hist_rows.winfo_children():
            w.destroy()
        try:
            sessions = self.controller.get_session_history(limit=15)
        except Exception as e:
            ctk.CTkLabel(self._hist_rows, text=f"Error: {e}", font=font_label(),
                         text_color=TEXT_MUTED).grid(row=0, column=0, padx=12, pady=12, sticky="w")
            return

        if not sessions:
            ctk.CTkLabel(self._hist_rows, text="No imports yet.", font=font_label(),
                         text_color=TEXT_MUTED).grid(row=0, column=0, padx=12, pady=12, sticky="w")
            return

        for r, s in enumerate(sessions):
            try:
                warns = json.loads(s.get("warnings_json", "[]") or "[]")
            except Exception:
                warns = []
            notes = [w for w in warns if not str(w).startswith(" ")]
            note_txt = notes[0] if notes else "—"
            if len(notes) > 1:
                note_txt += f"  (+{len(notes) - 1})"
            values = [
                str(s.get("started_at", ""))[:16],
                s.get("supplier_name", "?"),
                fmt_int(s.get("products_found", 0)),
                fmt_int(s.get("images_matched", 0)),
                note_txt,
                s.get("session_id", "?"),
            ]
            for c, (val, (_, w, anchor)) in enumerate(zip(values, _HISTORY_COLS)):
                ctk.CTkLabel(
                    self._hist_rows, text=val, width=w, anchor=anchor,
                    font=font_mono() if c in (0, 5) else font_label(),
                    text_color=TEXT_PRIMARY if c == 1 else (TEXT_MUTED if c in (0, 4, 5) else TEXT_HEADING),
                    wraplength=w if c == 4 else 0, justify="left",
                ).grid(row=r, column=c, padx=(12 if c == 0 else 0, 16), pady=5, sticky="w")

    def on_show(self):
        self._refresh_rules()
        self._load_history()

    def on_hide(self):
        pass
