"""Dashboard frame — KPIs + last import / catalog health / top categories / recent activity."""
from __future__ import annotations
import json
from datetime import datetime
from typing import Callable, Optional
import customtkinter as ctk

from app.logging_config.logger import get_logger
log = get_logger("dashboard_frame")

from app.core.app_controller import AppController
from app.ui.icons import icon
from app.ui.theme import (
    BG_BASE, BG_ELEVATED, BG_HOVER, BORDER,
    ACCENT, SUCCESS, WARNING, DANGER,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    PAGE_PADX, FONT_SEMIBOLD,
    font_small, font_label, font_caps, font_number,
    card, section_title, page_header, pill, set_pill, fmt_int,
)
from app.ui.components.tooltip import Tooltip


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt[:19])
        return dt.strftime("%m/%d/%Y %H:%M")
    except (ValueError, TypeError):
        return str(dt)[:16]


def _humanize_delta(then: datetime) -> str:
    """Short relative-time label."""
    if then is None:
        return "—"
    try:
        if isinstance(then, str):
            then = datetime.fromisoformat(then[:19])
        delta = datetime.now() - then
        secs  = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        mins = secs // 60
        if mins < 60:
            return f"{mins} min ago"
        hours = mins // 60
        if hours < 24:
            return f"{hours} h ago"
        days = hours // 24
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days} days ago"
        return "1+ month ago"
    except (ValueError, TypeError):
        return "—"


# ── Activity-log helpers ─────────────────────────────────────────────────────
# Icon for each activity kind. The kind values match what the controller
# writes via db.log_activity().
ACTIVITY_ICON: dict[str, str] = {
    "import":       "upload",
    "edit_batch":   "edit",
    "excel":        "sheet",
    "pdf":          "file_text",
    "margin_apply": "percent",
}


def _collapse_activity(rows: list[dict], window_secs: int = 300) -> list[dict]:
    """
    Visual aggregation: consecutive same-`kind` entries within `window_secs`
    are merged into one display row. Counts sum, summary is rewritten to
    show the group size. Important events (import, pdf, etc.) almost always
    stay alone — only `edit_batch` typically collapses.
    """
    if not rows:
        return []

    rows = sorted(rows, key=lambda r: r["ts"], reverse=True)

    def _ts(r):
        v = r["ts"]
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v[:19])
            except (ValueError, TypeError):
                return datetime.now()
        return v

    out: list[dict] = []
    group: list[dict] = [rows[0]]

    for entry in rows[1:]:
        last = group[-1]
        same_kind = entry["kind"] == last["kind"]
        try:
            delta = abs((_ts(last) - _ts(entry)).total_seconds())
        except Exception:
            delta = 10**9
        if same_kind and delta <= window_secs:
            group.append(entry)
        else:
            out.append(_collapsed_entry(group))
            group = [entry]
    out.append(_collapsed_entry(group))
    return out


def _collapsed_entry(group: list[dict]) -> dict:
    """Make one display row from a (1+)-sized cluster of activity rows."""
    head = dict(group[0])
    if len(group) > 1:
        total = sum(int(g.get("count") or 0) for g in group)
        kind = head["kind"]
        # Rewrite summary so the user sees the cluster size at a glance.
        if kind == "edit_batch" and total > 0:
            head["summary"] = f"Edited {total} products (in {len(group)} batches)"
        else:
            head["summary"] = head["summary"] + f"  · ×{len(group)}"
        head["count"] = total
    return head


# Health checks: (key, label, explanation shown on hover)
HEALTH_CHECKS = [
    ("no_image",       "Products without an image",
     "Active products without a linked image — they were probably not\n"
     "extracted from the PDF.\n\nDouble-click to open them in Products."),
    ("missing_image",  "Image file missing on disk",
     "The database links an image, but the file was deleted from the\n"
     "'extracted_images/' folder.\n\nDouble-click to open them in Products."),
    ("zero_price",     "Final price is $0",
     "Active products whose Final Price ended up at $0 — usually a\n"
     "parsing problem worth reviewing.\n\nDouble-click to open them in Products."),
    ("low_margin",     "Margin below 10%",
     "Active products with a margin under 10% — prices may be\n"
     "suspiciously low.\n\nDouble-click to open them in Products."),
    ("no_description", "Missing description",
     "Active products with an empty Description field.\n\n"
     "Double-click to open them in Products."),
]


# ── KPI card ─────────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    """Caption with a status dot, a large neutral number and a one-line context."""

    def __init__(self, parent, title: str, dot_color: str):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._card = card(self, row=0, column=0, sticky="nsew")
        self._card.grid_columnconfigure(1, weight=1)

        ctk.CTkFrame(self._card, width=8, height=8, corner_radius=4, fg_color=dot_color).grid(
            row=0, column=0, padx=(18, 8), pady=(16, 0), sticky="w")
        ctk.CTkLabel(self._card, text=title, font=font_label(), text_color=TEXT_MUTED,
                     anchor="w").grid(row=0, column=1, pady=(16, 0), sticky="w")

        self._val_label = ctk.CTkLabel(self._card, text="—", font=font_number(28),
                                       text_color=TEXT_PRIMARY, anchor="w")
        self._val_label.grid(row=1, column=0, columnspan=2, padx=18, pady=(4, 0), sticky="w")

        self._hint = ctk.CTkLabel(self._card, text="", font=font_small(),
                                  text_color=TEXT_SUBTLE, anchor="w")
        self._hint.grid(row=2, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="w")

    @property
    def surface(self) -> ctk.CTkFrame:
        return self._card

    def update_value(self, value: str, hint: str = ""):
        self._val_label.configure(text=value)
        self._hint.configure(text=hint)


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController,
                 navigate_cb: Optional[Callable[..., None]] = None):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller  = controller
        self.navigate_cb = navigate_cb
        self._cards: dict[str, StatCard] = {}
        # SKUs of products whose image files are missing on disk (from last on_show)
        self._missing_image_skus: list[str] = []
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stats")
        self.grid_rowconfigure(3, weight=1)

        header = page_header(self, "Dashboard", " ")
        header.grid(row=0, column=0, columnspan=4, padx=PAGE_PADX, pady=(26, 18), sticky="ew")
        self._subtitle = header.grid_slaves(row=1, column=0)[0]

        # ── KPI cards ────────────────────────────────────────────────────────
        card_defs = [
            ("total",        "Total products", ACCENT),
            ("active",       "Active",         SUCCESS),
            ("inactive",     "Inactive",       WARNING),
            ("discontinued", "Discontinued",   TEXT_SUBTLE),
        ]
        for col, (key, label, dot) in enumerate(card_defs):
            sc = StatCard(self, label, dot)
            sc.grid(row=1, column=col,
                    padx=(PAGE_PADX if col == 0 else 6, PAGE_PADX if col == 3 else 6),
                    sticky="nsew")
            self._cards[key] = sc

        Tooltip(self._cards["total"].surface,
                "Every product in the database: active, inactive and discontinued.")
        Tooltip(self._cards["active"].surface,
                "Visible in the catalog and included in Excel and PDF exports.")
        Tooltip(self._cards["inactive"].surface,
                "Hidden manually from the Products tab. Left out of 'Active only'\n"
                "exports, but kept in the database — reactivate them any time.")
        Tooltip(self._cards["discontinued"].surface,
                "Products from earlier imports that are missing from the supplier's\n"
                "latest PDF. Flagged automatically on import.")

        # ── 2 × 2 widget grid ────────────────────────────────────────────────
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.grid(row=3, column=0, columnspan=4, padx=PAGE_PADX, pady=(12, 22), sticky="nsew")
        grid.grid_columnconfigure(0, weight=3, uniform="dash")
        grid.grid_columnconfigure(1, weight=2, uniform="dash")
        grid.grid_rowconfigure((0, 1), weight=1)

        self._build_last_import_card(grid, row=0, col=0)
        self._build_health_card(grid, row=0, col=1)
        self._build_top_categories_card(grid, row=1, col=0)
        self._build_activity_card(grid, row=1, col=1)

    # ── Last import ───────────────────────────────────────────────────────────

    def _build_last_import_card(self, parent, row: int, col: int):
        c = card(parent, row=row, column=col, padx=(0, 6), pady=(0, 6), sticky="nsew")
        c.grid_columnconfigure(0, weight=1)

        head = section_title(c, "Last import")
        head.grid(row=0, column=0, padx=20, pady=(18, 0), sticky="ew")
        self._li_badge = pill(head)
        self._li_badge.grid(row=0, column=1, sticky="e")
        Tooltip(head, "The most recent supplier PDF import: supplier, when it ran,\n"
                      "products processed, linked images and duration.")

        self._li_supplier = ctk.CTkLabel(c, text="—", font=ctk.CTkFont(family=FONT_SEMIBOLD, size=20),
                                         text_color=TEXT_PRIMARY, anchor="w")
        self._li_supplier.grid(row=1, column=0, padx=20, pady=(12, 0), sticky="w")

        self._li_when = ctk.CTkLabel(c, text="", font=font_label(), text_color=TEXT_MUTED, anchor="w")
        self._li_when.grid(row=2, column=0, padx=20, sticky="w")

        stats = ctk.CTkFrame(c, fg_color="transparent")
        stats.grid(row=3, column=0, padx=20, pady=(18, 0), sticky="ew")
        stats.grid_columnconfigure((0, 1, 2), weight=1, uniform="li")
        self._li_stats: dict[str, ctk.CTkLabel] = {}
        for i, (key, caption) in enumerate([("products", "PRODUCTS"), ("images", "WITH IMAGE"),
                                            ("duration", "DURATION")]):
            cell = ctk.CTkFrame(stats, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="w")
            if i:
                ctk.CTkFrame(cell, width=1, height=36, fg_color=BORDER).grid(
                    row=0, column=0, rowspan=2, padx=(0, 16))
            ctk.CTkLabel(cell, text=caption, font=font_caps(), text_color=TEXT_SUBTLE,
                         anchor="w").grid(row=0, column=1, sticky="w")
            val = ctk.CTkLabel(cell, text="—", font=font_number(18), text_color=TEXT_PRIMARY, anchor="w")
            val.grid(row=1, column=1, sticky="w")
            self._li_stats[key] = val

        cov = ctk.CTkFrame(c, fg_color="transparent")
        cov.grid(row=4, column=0, padx=20, pady=(20, 20), sticky="ew")
        cov.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(cov, text="Image coverage", font=font_small(), text_color=TEXT_MUTED,
                     anchor="w").grid(row=0, column=0, sticky="w")
        self._li_pct_label = ctk.CTkLabel(cov, text="—", font=font_caps(), text_color=TEXT_HEADING)
        self._li_pct_label.grid(row=0, column=1, sticky="e")
        self._li_progress = ctk.CTkProgressBar(cov, height=6, corner_radius=3,
                                               fg_color=BG_ELEVATED, progress_color=ACCENT)
        self._li_progress.set(0)
        self._li_progress.grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky="ew")

    # ── Catalog health ────────────────────────────────────────────────────────

    def _build_health_card(self, parent, row: int, col: int):
        c = card(parent, row=row, column=col, padx=(6, 0), pady=(0, 6), sticky="nsew")
        c.grid_columnconfigure(0, weight=1)
        section_title(c, "Catalog health", "double-click to review").grid(
            row=0, column=0, padx=20, pady=(18, 8), sticky="ew")
        self._health_container = ctk.CTkFrame(c, fg_color="transparent")
        self._health_container.grid(row=1, column=0, padx=10, pady=(0, 14), sticky="nsew")
        self._health_container.grid_columnconfigure(0, weight=1)

    def _render_health(self, health: dict):
        for w in self._health_container.winfo_children():
            w.destroy()

        for i, (key, label, tip) in enumerate(HEALTH_CHECKS):
            count = int(health.get(key, 0) or 0)
            failing = count > 0
            row = ctk.CTkFrame(self._health_container, fg_color="transparent", corner_radius=8,
                               cursor="hand2" if failing else "")
            row.grid(row=i, column=0, pady=1, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            ic = ctk.CTkLabel(row, text="", width=20,
                              image=icon("alert" if failing else "check_circle",
                                         WARNING if failing else SUCCESS, 16))
            ic.grid(row=0, column=0, padx=(10, 10), pady=2)
            lbl = ctk.CTkLabel(row, text=label, font=font_label(),
                               text_color=TEXT_HEADING if failing else TEXT_MUTED, anchor="w")
            lbl.grid(row=0, column=1, sticky="w")
            num = ctk.CTkLabel(row, text=fmt_int(count) if failing else "OK", font=font_caps(),
                               text_color=WARNING if failing else TEXT_SUBTLE)
            num.grid(row=0, column=2, padx=(6, 12), sticky="e")
            Tooltip(row, tip)

            if failing:
                handler = (lambda e, k=key, l=label, n=count: self._open_health_filter(k, l, n))
                for w in (row, ic, lbl, num):
                    w.bind("<Double-Button-1>", handler, add="+")
                    w.bind("<Enter>", lambda e, r=row: r.configure(fg_color=BG_HOVER), add="+")
                    w.bind("<Leave>", lambda e, r=row: r.configure(fg_color="transparent"), add="+")

    def _open_health_filter(self, key: str, label: str, count: int):
        """Navigate to Products with the given health filter active."""
        if not self.navigate_cb:
            return
        try:
            kwargs: dict = dict(health_filter=key, health_label=label, health_count=count)
            # missing_image cannot be expressed in SQL — pass the exact SKU list
            if key == "missing_image":
                kwargs["missing_skus"] = list(self._missing_image_skus)
            self.navigate_cb("products", **kwargs)
        except Exception:
            # Fallback to plain navigation if signature mismatch
            self.navigate_cb("products")

    # ── Top categories ────────────────────────────────────────────────────────

    def _build_top_categories_card(self, parent, row: int, col: int):
        c = card(parent, row=row, column=col, padx=(0, 6), pady=(6, 0), sticky="nsew")
        c.grid_columnconfigure(0, weight=1)
        section_title(c, "Top categories", "active products").grid(
            row=0, column=0, padx=20, pady=(18, 10), sticky="ew")
        self._tc_container = ctk.CTkFrame(c, fg_color="transparent")
        self._tc_container.grid(row=1, column=0, padx=20, pady=(0, 16), sticky="nsew")
        self._tc_container.grid_columnconfigure(1, weight=1)

    def _render_top_categories(self, items: list[dict]):
        for w in self._tc_container.winfo_children():
            w.destroy()

        if not items:
            ctk.CTkLabel(self._tc_container, text="No categories yet.", font=font_small(),
                         text_color=TEXT_SUBTLE).grid(row=0, column=0, pady=8, sticky="w")
            return

        max_count = max(it["count"] for it in items) or 1
        for i, it in enumerate(items[:6]):
            ctk.CTkLabel(self._tc_container, text=it["category"][:26], font=font_label(),
                         text_color=TEXT_HEADING, anchor="w", width=150).grid(
                row=i, column=0, pady=1, sticky="w")
            bar_bg = ctk.CTkFrame(self._tc_container, fg_color=BG_ELEVATED, height=6, corner_radius=3)
            bar_bg.grid(row=i, column=1, padx=12, sticky="ew")
            bar_bg.grid_propagate(False)
            ctk.CTkFrame(bar_bg, fg_color=ACCENT, corner_radius=3).place(
                relx=0, rely=0, relwidth=max(it["count"] / max_count, 0.02), relheight=1)
            ctk.CTkLabel(self._tc_container, text=fmt_int(it["count"]), font=font_label(),
                         text_color=TEXT_MUTED, width=44, anchor="e").grid(row=i, column=2, sticky="e")

    # ── Recent activity ───────────────────────────────────────────────────────

    def _build_activity_card(self, parent, row: int, col: int):
        c = card(parent, row=row, column=col, padx=(6, 0), pady=(6, 0), sticky="nsew")
        c.grid_columnconfigure(0, weight=1)
        head = section_title(c, "Recent activity")
        head.grid(row=0, column=0, padx=20, pady=(18, 10), sticky="ew")
        Tooltip(head, "Latest imports, bulk edits and Excel/PDF exports.\n"
                      "Consecutive edits of the same kind are grouped.")
        self._ar_container = ctk.CTkFrame(c, fg_color="transparent")
        self._ar_container.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="nsew")
        self._ar_container.grid_columnconfigure(1, weight=1)

    def _render_activity(self, rows: list[dict]):
        for w in self._ar_container.winfo_children():
            w.destroy()

        collapsed = _collapse_activity(rows)[:6]
        if not collapsed:
            ctk.CTkLabel(self._ar_container,
                         text="No activity yet — import a PDF or edit products to see it here.",
                         font=font_small(), text_color=TEXT_SUBTLE, justify="left",
                         wraplength=320).grid(row=0, column=0, columnspan=3, pady=10, sticky="w")
            return

        for i, entry in enumerate(collapsed):
            badge = ctk.CTkFrame(self._ar_container, width=28, height=28, corner_radius=7,
                                 fg_color=BG_ELEVATED)
            badge.grid(row=i, column=0, pady=3, sticky="w")
            badge.grid_propagate(False)
            ctk.CTkLabel(badge, text="", image=icon(ACTIVITY_ICON.get(entry["kind"], "clock"),
                                                     TEXT_MUTED, 14)).place(relx=0.5, rely=0.5, anchor="center")
            ctk.CTkLabel(self._ar_container, text=entry["summary"], font=font_label(),
                         text_color=TEXT_HEADING, anchor="w").grid(row=i, column=1, padx=10, sticky="w")
            ts = ctk.CTkLabel(self._ar_container, text=_humanize_delta(entry["ts"]),
                              font=font_small(), text_color=TEXT_SUBTLE, anchor="e")
            ts.grid(row=i, column=2, sticky="e")
            try:
                Tooltip(ts, _fmt_dt(entry["ts"]))
            except Exception:
                pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_show(self):
        try:
            data = self.controller.get_dashboard_data()
        except Exception as e:
            log.error(f"Dashboard data fetch failed: {e}")
            return

        stats  = data.get("stats", {})
        total  = int(stats.get("total", 0) or 0)
        active = int(stats.get("active", 0) or 0)
        share  = f"{active / total:.0%} of the catalog" if total else ""
        self._cards["total"].update_value(fmt_int(total), "in the database")
        self._cards["active"].update_value(fmt_int(active), share)
        self._cards["inactive"].update_value(fmt_int(stats.get("inactive", 0)), "hidden from exports")
        self._cards["discontinued"].update_value(fmt_int(stats.get("discontinued", 0)),
                                                 "missing from the latest import")

        last = data.get("last_import")
        self._render_last_import(last)
        self._subtitle.configure(
            text=f"{fmt_int(total)} products · last import {_humanize_delta(last.get('started_at'))}"
            if last else "Import a supplier PDF to get started"
        )

        self._render_top_categories(data.get("top_categories", []))
        health = data.get("health", {})
        self._missing_image_skus = health.get("missing_image_skus") or []
        self._render_health(health)

        try:
            activity = self.controller.get_recent_activity(limit=30)
        except Exception:
            activity = []
        self._render_activity(activity)

    def _render_last_import(self, last: Optional[dict]):
        if not last:
            self._li_supplier.configure(text="No imports yet")
            self._li_when.configure(text="Import a supplier PDF from the Import PDF tab.")
            set_pill(self._li_badge, "")
            for v in self._li_stats.values():
                v.configure(text="—")
            self._li_progress.set(0)
            self._li_pct_label.configure(text="—")
            return

        try:
            n_err = len(json.loads(last.get("errors_json") or "[]"))
            warns = json.loads(last.get("warnings_json") or "[]")
            # Indented lines are details of the warning above them
            n_warn = len([w for w in warns if not str(w).startswith(" ")])
        except Exception:
            n_err = n_warn = 0

        if n_err:
            set_pill(self._li_badge, f"{n_err} error{'s' if n_err > 1 else ''}", "danger")
        elif n_warn:
            set_pill(self._li_badge, f"{n_warn} note{'s' if n_warn > 1 else ''}", "warning")
        else:
            set_pill(self._li_badge, "Completed", "success")

        self._li_supplier.configure(text=last.get("supplier_name") or "—")
        started = last.get("started_at")
        self._li_when.configure(text=f"{_humanize_delta(started)}  ·  {_fmt_dt(started)}")

        n_prod  = int(last.get("products_found", 0) or 0)
        n_match = int(last.get("images_matched", 0) or 0)
        self._li_stats["products"].configure(text=fmt_int(n_prod))
        self._li_stats["images"].configure(text=fmt_int(n_match))

        duration = "—"
        try:
            ended = last.get("completed_at")
            if started and ended:
                s = datetime.fromisoformat(started[:19]) if isinstance(started, str) else started
                e = datetime.fromisoformat(ended[:19])   if isinstance(ended, str)   else ended
                duration = f"{(e - s).total_seconds():.1f} s"
        except Exception:
            pass
        self._li_stats["duration"].configure(text=duration)

        pct = (n_match / n_prod) if n_prod else 0
        self._li_progress.set(pct)
        self._li_pct_label.configure(text=f"{pct:.1%}")
        self._li_progress.configure(
            progress_color=ACCENT if pct >= 0.9 else (WARNING if pct >= 0.7 else DANGER))
