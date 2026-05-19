"""Dashboard frame — stats + 4 widgets (última import / top categorías / salud / actividad)."""
from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional
import customtkinter as ctk

from app.logging_config.logger import get_logger
log = get_logger("dashboard_frame")

from app.core.app_controller import AppController
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED, BG_DEEPEST,
    ACCENT_PRIMARY,
    ACCENT_BLUE,
    ACCENT_SUCCESS,
    ACCENT_WARNING,
    ACCENT_PURPLE,
    ACCENT_DANGER,
    TEXT_PRIMARY, TEXT_HEADING, TEXT_MUTED, TEXT_SUBTLE,
    RADIUS_CARD, RADIUS_CHIP,
    font_title, font_body, font_small, font_label, font_bold,
)
from app.ui.components.tooltip import Tooltip


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt[:19])
        return dt.strftime("%d/%m/%Y %H:%M")
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
            return "hace un instante"
        mins = secs // 60
        if mins < 60:
            return f"hace {mins} min"
        hours = mins // 60
        if hours < 24:
            return f"hace {hours} h"
        days = hours // 24
        if days == 1:
            return "ayer"
        if days < 30:
            return f"hace {days} días"
        return "hace +1 mes"
    except (ValueError, TypeError):
        return "—"


# ── Activity-log helpers ─────────────────────────────────────────────────────
# Visual colour/icon for each activity kind. The kind values match what the
# controller writes via db.log_activity().
ACTIVITY_STYLE: dict[str, tuple[str, str]] = {
    "import":       ("📥", ACCENT_BLUE),
    "edit_batch":   ("✏",  ACCENT_WARNING),
    "excel":        ("📊", ACCENT_SUCCESS),
    "pdf":          ("📋", ACCENT_PURPLE),
    "margin_apply": ("💰", ACCENT_PURPLE),
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
            head["summary"] = f"Editaste {total} productos (en {len(group)} lotes)"
        else:
            head["summary"] = head["summary"] + f"  · ×{len(group)}"
        head["count"] = total
    return head


# ── Stat card ────────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    def __init__(self, parent, title: str, value: str, color: str):
        super().__init__(parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        self.grid_columnconfigure(0, weight=1)
        self._val_label = ctk.CTkLabel(
            self, text=value,
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color=color,
        )
        self._val_label.grid(row=0, column=0, padx=18, pady=(14, 2))
        ctk.CTkLabel(
            self, text=title,
            font=font_small(),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, padx=18, pady=(0, 14))

    def update_value(self, value: str):
        self._val_label.configure(text=value)


# ── Dashboard ────────────────────────────────────────────────────────────────

class DashboardFrame(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController,
                 navigate_cb: Optional[Callable[..., None]] = None):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller  = controller
        self.navigate_cb = navigate_cb
        self._cards: dict[str, StatCard] = {}
        # Chip-frame references kept so we can re-bind on each render
        self._health_chip_widgets: list[ctk.CTkFrame] = []
        # SKUs of products whose image files are missing on disk (from last on_show)
        self._missing_image_skus: list[str] = []
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stats")
        self.grid_rowconfigure(3, weight=1)

        # ── Header ───────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="Dashboard",
            font=font_title(), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, columnspan=4, padx=24, pady=(20, 2), sticky="w")

        ctk.CTkLabel(
            self, text="Resumen y estado del catálogo",
            font=font_body(), text_color=TEXT_MUTED,
        ).grid(row=1, column=0, columnspan=4, padx=24, pady=(0, 14), sticky="w")

        # ── Stat cards (4) ───────────────────────────────────────────────────
        card_defs = [
            ("total",        "Total",          ACCENT_PRIMARY),
            ("active",       "Activos",        ACCENT_SUCCESS),
            ("inactive",     "Inactivos",      ACCENT_WARNING),
            ("discontinued", "Discontinuados", TEXT_MUTED),
        ]
        for col, (key, label, color) in enumerate(card_defs):
            card = StatCard(self, label, "—", color)
            card.grid(row=2, column=col, padx=(24 if col == 0 else 6,
                                                24 if col == 3 else 6),
                      pady=4, sticky="ew")
            self._cards[key] = card

        # Tooltips on all stat cards
        Tooltip(
            self._cards["total"],
            "Total de productos en la base de datos, incluyendo activos,\n"
            "inactivos y discontinuados.",
        )
        Tooltip(
            self._cards["active"],
            "Productos activos: visibles en el catálogo y disponibles para\n"
            "incluir en exportaciones de Excel y PDF.\n\n"
            "Un producto es activo cuando no está marcado como inactivo\n"
            "ni discontinuado.",
        )
        Tooltip(
            self._cards["inactive"],
            "Productos marcados como inactivos manualmente desde la solapa\n"
            "Productos.\n\n"
            "No aparecen en exportaciones de 'Solo activos' pero siguen en\n"
            "la base de datos. Podés reactivarlos en cualquier momento.",
        )
        Tooltip(
            self._cards["discontinued"],
            "Productos que aparecían en importaciones anteriores pero ya no\n"
            "figuran en el catálogo más reciente del proveedor.\n\n"
            "Se marcan automáticamente al importar un PDF nuevo: cualquier SKU\n"
            "que no aparezca en el PDF actual queda marcado como discontinuado.\n\n"
            "⚠  No es posible desmarcarlos manualmente desde la interfaz.",
        )

        # ── 4 main widgets in a 2×2 grid ─────────────────────────────────────
        widgets_frame = ctk.CTkFrame(self, fg_color=BG_BASE, corner_radius=0)
        widgets_frame.grid(row=3, column=0, columnspan=4,
                           padx=24, pady=(14, 16), sticky="nsew")
        widgets_frame.grid_columnconfigure(0, weight=1, uniform="dash")
        widgets_frame.grid_columnconfigure(1, weight=1, uniform="dash")
        widgets_frame.grid_rowconfigure(0, weight=1)
        widgets_frame.grid_rowconfigure(1, weight=1)

        # Top-left: Última importación (redesigned)
        self._build_last_import_card(widgets_frame, row=0, col=0)
        # Top-right: Salud (now rowspan=1)
        self._build_health_card(widgets_frame, row=0, col=1)
        # Bottom-left: Top categorías
        self._build_top_categories_card(widgets_frame, row=1, col=0)
        # Bottom-right: Actividad reciente (NEW)
        self._build_activity_card(widgets_frame, row=1, col=1)

    # ── Última importación (redesigned) ───────────────────────────────────────

    def _build_last_import_card(self, parent, row: int, col: int):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        card.grid(row=row, column=col, padx=(0, 6), pady=(0, 6), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)

        # Header row: title + status badge
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(14, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        _li_title = ctk.CTkLabel(
            header, text="📥  Última importación",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT_BLUE,
        )
        _li_title.grid(row=0, column=0, sticky="w")
        Tooltip(
            _li_title,
            "Resumen de la última importación de PDF realizada.\n\n"
            "Muestra proveedor, fecha, cantidad de productos procesados,\n"
            "imágenes vinculadas y duración de la importación.\n\n"
            "La barra de progreso indica el porcentaje de productos\n"
            "a los que se les pudo asignar una imagen (match de imágenes).",
            wraplength=340,
        )

        self._li_badge = ctk.CTkLabel(
            header, text="", padx=10, pady=2,
            font=ctk.CTkFont(size=10, weight="bold"),
            corner_radius=6, fg_color="transparent",
        )
        self._li_badge.grid(row=0, column=1, sticky="e")

        # Big proveedor name
        self._li_supplier = ctk.CTkLabel(
            card, text="—",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="w",
        )
        self._li_supplier.grid(row=1, column=0, padx=16, pady=(2, 0), sticky="w")

        # Relative time line (hace X · martes 14:32)
        self._li_when = ctk.CTkLabel(
            card, text="",
            font=font_small(), text_color=TEXT_MUTED, anchor="w",
        )
        self._li_when.grid(row=2, column=0, padx=16, pady=(0, 10), sticky="w")

        # 3 chips: productos / imágenes / duración
        chips = ctk.CTkFrame(card, fg_color="transparent")
        chips.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")
        chips.grid_columnconfigure((0, 1, 2), weight=1, uniform="chip")

        self._li_chip_products = self._make_stat_chip(chips, "📦", "—", "productos", ACCENT_PRIMARY)
        self._li_chip_products.grid(row=0, column=0, padx=4, sticky="ew")

        self._li_chip_images = self._make_stat_chip(chips, "🖼", "—", "imágenes", ACCENT_BLUE)
        self._li_chip_images.grid(row=0, column=1, padx=4, sticky="ew")

        self._li_chip_duration = self._make_stat_chip(chips, "⏱", "—", "duración", ACCENT_PURPLE)
        self._li_chip_duration.grid(row=0, column=2, padx=4, sticky="ew")

        # Image-match progress bar
        prog_wrap = ctk.CTkFrame(card, fg_color="transparent")
        prog_wrap.grid(row=4, column=0, padx=16, pady=(6, 14), sticky="ew")
        prog_wrap.grid_columnconfigure(0, weight=1)

        prog_header = ctk.CTkFrame(prog_wrap, fg_color="transparent")
        prog_header.grid(row=0, column=0, sticky="ew")
        prog_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            prog_header, text="Match de imágenes",
            font=font_small(), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self._li_pct_label = ctk.CTkLabel(
            prog_header, text="—",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_HEADING, anchor="e",
        )
        self._li_pct_label.grid(row=0, column=1, sticky="e")

        self._li_progress = ctk.CTkProgressBar(
            prog_wrap, height=8, fg_color=BG_ELEVATED,
            progress_color=ACCENT_SUCCESS,
        )
        self._li_progress.set(0)
        self._li_progress.grid(row=1, column=0, pady=(4, 0), sticky="ew")

    def _make_stat_chip(self, parent, icon: str, value: str, label: str,
                        color: str) -> ctk.CTkFrame:
        chip = ctk.CTkFrame(parent, fg_color=BG_DEEPEST, corner_radius=8)
        chip.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            chip, text=icon, font=ctk.CTkFont(size=15),
            text_color=color,
        ).grid(row=0, column=0, padx=8, pady=(8, 0))
        val = ctk.CTkLabel(
            chip, text=value,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_HEADING,
        )
        val.grid(row=1, column=0, padx=8, pady=(0, 0))
        ctk.CTkLabel(
            chip, text=label,
            font=font_small(), text_color=TEXT_MUTED,
        ).grid(row=2, column=0, padx=8, pady=(0, 8))
        # store the value label for later updates
        chip._value_label = val          # type: ignore[attr-defined]
        return chip

    def _set_chip_value(self, chip: ctk.CTkFrame, value: str):
        try:
            chip._value_label.configure(text=value)   # type: ignore[attr-defined]
        except Exception:
            pass

    # ── Top categorías (sin cambios estructurales) ───────────────────────────

    def _build_top_categories_card(self, parent, row: int, col: int):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        card.grid(row=row, column=col, padx=(0, 6), pady=(6, 0), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        _tc_title = ctk.CTkLabel(
            card, text="🏷  Top categorías",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT_PURPLE,
        )
        _tc_title.grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")
        Tooltip(
            _tc_title,
            "Las 6 categorías con mayor cantidad de productos activos.\n\n"
            "La barra muestra la proporción relativa de cada categoría\n"
            "respecto a la que tiene más productos.",
        )

        self._tc_container = ctk.CTkFrame(card, fg_color="transparent")
        self._tc_container.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self._tc_container.grid_columnconfigure(0, weight=1)

    def _render_top_categories(self, items: list[dict]):
        for w in self._tc_container.winfo_children():
            w.destroy()

        if not items:
            ctk.CTkLabel(
                self._tc_container, text="Sin categorías registradas.",
                font=font_small(), text_color=TEXT_SUBTLE,
            ).grid(row=0, column=0, padx=4, pady=8, sticky="w")
            return

        max_count = max(it["count"] for it in items) or 1
        for i, it in enumerate(items[:6]):
            cat   = it["category"]
            count = it["count"]
            pct   = count / max_count

            row = ctk.CTkFrame(self._tc_container, fg_color="transparent", height=22)
            row.grid(row=i, column=0, padx=2, pady=1, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row, text=cat[:24],
                font=font_small(), text_color=TEXT_HEADING,
                anchor="w", width=145,
            ).grid(row=0, column=0, padx=(2, 6), sticky="w")

            bar_bg = ctk.CTkFrame(row, fg_color=BG_ELEVATED, height=10, corner_radius=3)
            bar_bg.grid(row=0, column=1, padx=4, sticky="ew")
            bar_bg.grid_propagate(False)
            bar_bg.grid_columnconfigure(0, weight=1)
            fill = ctk.CTkFrame(bar_bg, fg_color=ACCENT_PURPLE, corner_radius=3)
            fill.place(relx=0, rely=0, relwidth=pct, relheight=1)

            ctk.CTkLabel(
                row, text=str(count),
                font=font_small(), text_color=TEXT_MUTED,
                anchor="e", width=46,
            ).grid(row=0, column=2, padx=(6, 4), sticky="e")

    # ── Salud del catálogo (rowspan=1 + double-click) ────────────────────────

    def _build_health_card(self, parent, row: int, col: int):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        card.grid(row=row, column=col, padx=(6, 0), pady=(0, 6), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(
            card, text="🩺  Salud del catálogo",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT_SUCCESS,
        )
        title.grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        Tooltip(
            title,
            "Lista de alertas sobre la calidad de los datos del catálogo.\n"
            "Doble-click en una alerta para abrir los productos afectados.",
        )

        self._health_container = ctk.CTkFrame(card, fg_color="transparent")
        self._health_container.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="nsew")
        self._health_container.grid_columnconfigure(0, weight=1)

    def _render_health(self, health: dict):
        for w in self._health_container.winfo_children():
            w.destroy()
        self._health_chip_widgets.clear()

        checks = [
            ("no_image",       "Sin imagen",        "Productos activos sin imagen vinculada.\nProbablemente no se hayan extraído correctamente del PDF.\n\nDoble-click → abrir Productos filtrados."),
            ("missing_image",  "Imagen no encontrada", "Productos activos que tienen imagen asignada en la base de\ndatos, pero el archivo ya no existe en disco.\n\nEstos archivos probablemente fueron borrados manualmente de\nla carpeta 'extracted_images/'.\n\nDoble-click → ver productos con imagen asignada."),
            ("zero_price",     "Precio = 0",        "Productos activos cuyo Precio Final quedó en $0.\nRevisá manualmente — puede ser un error de parseo.\n\nDoble-click → abrir Productos filtrados."),
            ("low_margin",     "Margen < 10%",      "Productos activos con margen menor al 10%.\nPueden ser precios sospechosamente bajos.\n\nDoble-click → abrir Productos filtrados."),
            ("no_description", "Sin descripción",   "Productos activos sin texto en el campo Descripción.\n\nDoble-click → abrir Productos filtrados."),
        ]

        any_issue = False
        for i, (key, label, tip) in enumerate(checks):
            count = int(health.get(key, 0) or 0)
            if count == 0:
                continue
            any_issue = True

            chip = ctk.CTkFrame(
                self._health_container,
                fg_color=BG_DEEPEST, corner_radius=RADIUS_CHIP,
                border_color=ACCENT_WARNING, border_width=1,
                cursor="hand2",
            )
            chip.grid(row=i, column=0, padx=2, pady=3, sticky="ew")
            chip.grid_columnconfigure(1, weight=1)

            icon = ctk.CTkLabel(
                chip, text="⚠", font=ctk.CTkFont(size=14),
                text_color=ACCENT_WARNING, width=24,
            )
            icon.grid(row=0, column=0, padx=(10, 4), pady=6)

            lbl = ctk.CTkLabel(
                chip, text=label,
                font=font_label(), text_color=TEXT_HEADING, anchor="w",
            )
            lbl.grid(row=0, column=1, padx=4, pady=6, sticky="w")

            num = ctk.CTkLabel(
                chip, text=f"{count}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=ACCENT_WARNING, width=50, anchor="e",
            )
            num.grid(row=0, column=2, padx=(4, 12), pady=6, sticky="e")

            Tooltip(chip, tip)

            # Bind double-click to navigate — bind on chip AND every inner widget
            handler = (lambda e, k=key, lbl=label, n=count:
                       self._open_health_filter(k, lbl, n))
            for w in (chip, icon, lbl, num):
                w.bind("<Double-Button-1>", handler, add="+")

            self._health_chip_widgets.append(chip)

        if not any_issue:
            ok = ctk.CTkFrame(
                self._health_container,
                fg_color=BG_DEEPEST, corner_radius=RADIUS_CHIP,
                border_color=ACCENT_SUCCESS, border_width=1,
            )
            ok.grid(row=0, column=0, padx=2, pady=8, sticky="ew")
            ok.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                ok, text="✓", font=ctk.CTkFont(size=18, weight="bold"),
                text_color=ACCENT_SUCCESS, width=30,
            ).grid(row=0, column=0, padx=(14, 6), pady=12)
            ctk.CTkLabel(
                ok, text="Sin alertas — el catálogo está saludable.",
                font=font_label(), text_color=TEXT_HEADING, anchor="w",
            ).grid(row=0, column=1, padx=6, pady=12, sticky="w")

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

    # ── Actividad reciente (NEW) ──────────────────────────────────────────────

    def _build_activity_card(self, parent, row: int, col: int):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
        card.grid(row=row, column=col, padx=(6, 0), pady=(6, 0), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(
            card, text="⏱  Actividad reciente",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=ACCENT_WARNING,
        )
        title.grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")
        Tooltip(
            title,
            "Últimas acciones del sistema (importaciones, ediciones masivas,\n"
            "generaciones de Excel/PDF). Las ediciones consecutivas del mismo\n"
            "tipo se agrupan automáticamente para evitar ruido.",
        )

        self._ar_container = ctk.CTkFrame(card, fg_color="transparent")
        self._ar_container.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._ar_container.grid_columnconfigure(0, weight=1)

    def _render_activity(self, rows: list[dict]):
        for w in self._ar_container.winfo_children():
            w.destroy()

        collapsed = _collapse_activity(rows)[:6]

        if not collapsed:
            ctk.CTkLabel(
                self._ar_container,
                text="Sin actividad registrada todavía.\n"
                     "Importá un PDF o editá productos para verla acá.",
                font=font_small(), text_color=TEXT_SUBTLE, justify="left",
            ).grid(row=0, column=0, padx=8, pady=18, sticky="w")
            return

        for i, entry in enumerate(collapsed):
            icon, color = ACTIVITY_STYLE.get(entry["kind"], ("•", TEXT_MUTED))
            row = ctk.CTkFrame(self._ar_container, fg_color="transparent")
            row.grid(row=i, column=0, padx=2, pady=2, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row, text=icon, width=22,
                font=ctk.CTkFont(size=14), text_color=color,
            ).grid(row=0, column=0, padx=(4, 6), pady=2, sticky="w")

            ctk.CTkLabel(
                row, text=entry["summary"],
                font=font_small(), text_color=TEXT_HEADING, anchor="w",
            ).grid(row=0, column=1, padx=2, pady=2, sticky="w")

            ts_lbl = ctk.CTkLabel(
                row, text=_humanize_delta(entry["ts"]),
                font=ctk.CTkFont(size=10), text_color=TEXT_SUBTLE, anchor="e",
            )
            ts_lbl.grid(row=0, column=2, padx=(6, 6), pady=2, sticky="e")
            # Exact timestamp on hover
            try:
                Tooltip(ts_lbl, _fmt_dt(entry["ts"]))
            except Exception:
                pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_show(self):
        try:
            data = self.controller.get_dashboard_data()
        except Exception as e:
            log.error(f"Dashboard data fetch failed: {e}")
            return

        # Stat cards
        stats = data.get("stats", {})
        self._cards["total"].update_value(str(stats.get("total", 0)))
        self._cards["active"].update_value(str(stats.get("active", 0)))
        self._cards["inactive"].update_value(str(stats.get("inactive", 0)))
        self._cards["discontinued"].update_value(str(stats.get("discontinued", 0)))

        # Última importación
        self._render_last_import(data.get("last_import"))

        # Top categorías + Salud
        self._render_top_categories(data.get("top_categories", []))
        health = data.get("health", {})
        self._missing_image_skus = health.get("missing_image_skus") or []
        self._render_health(health)

        # Actividad reciente
        try:
            activity = self.controller.get_recent_activity(limit=30)
        except Exception:
            activity = []
        self._render_activity(activity)

    def _render_last_import(self, last: Optional[dict]):
        if not last:
            self._li_supplier.configure(text="Sin importaciones aún")
            self._li_when.configure(text="Importá un PDF desde la solapa Importar PDF.")
            self._li_badge.configure(text="", fg_color="transparent")
            self._set_chip_value(self._li_chip_products, "—")
            self._set_chip_value(self._li_chip_images, "—")
            self._set_chip_value(self._li_chip_duration, "—")
            self._li_progress.set(0)
            self._li_pct_label.configure(text="—")
            return

        # Status badge: derive from errors / warnings stored on session
        errors_raw = last.get("errors_json") or "[]"
        warns_raw  = last.get("warnings_json") or "[]"
        try:
            import json as _json
            n_err  = len(_json.loads(errors_raw))
            n_warn = len(_json.loads(warns_raw))
        except Exception:
            n_err = n_warn = 0

        if n_err > 0:
            self._li_badge.configure(text="✗ ERRORES", text_color="#FFFFFF", fg_color=ACCENT_DANGER)
        elif n_warn > 0:
            self._li_badge.configure(text="⚠ ADVERTENCIAS", text_color="#FFFFFF", fg_color=ACCENT_WARNING)
        else:
            self._li_badge.configure(text="✓ ÉXITO", text_color="#FFFFFF", fg_color=ACCENT_SUCCESS)

        # Supplier + when
        self._li_supplier.configure(text=last.get("supplier_name") or "—")
        started = last.get("started_at")
        when_txt = f"{_humanize_delta(started)}  ·  {_fmt_dt(started)}"
        self._li_when.configure(text=when_txt)

        # Chips
        n_prod   = int(last.get("products_found", 0) or 0)
        n_match  = int(last.get("images_matched", 0) or 0)
        n_found  = int(last.get("images_found", 0) or 0)
        self._set_chip_value(self._li_chip_products, str(n_prod))
        self._set_chip_value(self._li_chip_images, f"{n_match}/{n_prod}")

        duration = ""
        try:
            ended = last.get("completed_at")
            if started and ended:
                s = datetime.fromisoformat(started[:19]) if isinstance(started, str) else started
                e = datetime.fromisoformat(ended[:19])   if isinstance(ended, str)   else ended
                secs = (e - s).total_seconds()
                duration = f"{secs:.1f}s"
        except Exception:
            pass
        self._set_chip_value(self._li_chip_duration, duration or "—")

        # Progress bar
        pct = (n_match / n_prod) if n_prod else 0
        self._li_progress.set(pct)
        self._li_pct_label.configure(text=f"{int(pct * 100)}%")
        # Progress color depending on quality
        if pct >= 0.9:
            self._li_progress.configure(progress_color=ACCENT_SUCCESS)
        elif pct >= 0.7:
            self._li_progress.configure(progress_color=ACCENT_WARNING)
        else:
            self._li_progress.configure(progress_color=ACCENT_DANGER)
