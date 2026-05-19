"""
AppController: the central coordinator.
Provides a clean API for the UI layer to call without touching services directly.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from app.config.settings import settings
from app.database.db_manager import DatabaseManager
from app.services.product_service import ProductService
from app.services.excel_service import ExcelService
from app.services.pdf_generator import PDFGenerator
from app.models.product import MarginConfig, ProcessingSession
from app.logging_config.logger import get_logger, setup_logging

log = get_logger("app_controller")

# Setting keys used for staleness tracking
KEY_LAST_DB_MOD    = "last_db_modification"
KEY_LAST_EXCEL_GEN = "last_excel_generation"


class AppController:
    """
    Single entry point for all UI → business logic interactions.
    Instantiate once and pass to all UI components.
    """

    def __init__(self):
        # Initialize logging first
        setup_logging(
            settings.LOGS_DIR,
            level=settings.LOG_LEVEL,
            rotation=settings.LOG_ROTATION,
            retention=settings.LOG_RETENTION,
        )
        from app.config.branding import APP_NAME, APP_VERSION
        log.info(f"Starting {APP_NAME} v{APP_VERSION}")

        # Wire up services
        self.db = DatabaseManager(settings.DB_PATH)
        self.product_svc = ProductService(self.db, settings.IMAGES_DIR)
        self.excel_svc = ExcelService(self.db, settings.EXCELS_DIR)
        self.pdf_gen = PDFGenerator(
            output_dir=settings.PDFS_DIR,
            company_name=self.get_setting("company_name", settings.COMPANY_NAME),
            company_slogan=self.get_setting("company_slogan", settings.COMPANY_SLOGAN),
            primary_color=self.get_setting("primary_color", settings.PRIMARY_COLOR),
            secondary_color=self.get_setting("secondary_color", settings.SECONDARY_COLOR),
        )

        # Restore last margin config
        self.margin_config = MarginConfig(
            margin_pct=float(self.get_setting("last_margin_pct", str(settings.DEFAULT_MARGIN_PCT))),
            iva_pct=float(self.get_setting("last_iva_pct", str(settings.DEFAULT_IVA_PCT))),
            round_to_nearest=int(self.get_setting("last_round_to", "0")),
            price_suffix=self.get_setting("last_price_suffix", ""),
        )

        log.info("AppController ready")

    # ─── PDF import ───────────────────────────────────────────────────────────

    def import_pdf(
        self,
        pdf_path: str,
        progress_cb: Optional[Callable[[str, float], None]] = None,
        force_parser: Optional[str] = None,
    ) -> ProcessingSession:
        """Import a supplier PDF with full pipeline."""
        self._save_margin_config()  # Persist current margin config
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")
        session = self.product_svc.import_pdf(
            path, self.margin_config, progress_cb, force_parser
        )
        if not session.errors:
            self._mark_db_modified()
            # Activity log: 1 import = 1 entry
            supplier = session.supplier_name or "proveedor"
            self.db.log_activity(
                kind="import",
                summary=f"Importaste catálogo de {supplier} ({session.products_found} prod)",
                count=session.products_found,
                metadata={
                    "session_id": session.session_id,
                    "pdf": path.name,
                    "images": f"{session.images_matched}/{session.products_found}",
                },
            )
        return session

    # ─── Excel ───────────────────────────────────────────────────────────────

    def export_excel(self, active_only: bool = False) -> Path:
        path = self.excel_svc.generate_excel(
            active_only=active_only,
            round_to=self.margin_config.round_to_nearest,
            suffix=self.margin_config.price_suffix,
        )
        self._mark_excel_generated()
        # Activity log
        try:
            n = len(self.db.get_all_products(include_inactive=not active_only))
        except Exception:
            n = 0
        self.db.log_activity(
            kind="excel",
            summary=f"Descargaste Excel ({n} prod)" + (" — solo activos" if active_only else ""),
            count=n,
            metadata={"file": path.name},
        )
        return path

    def reimport_excel(self, excel_path: str) -> dict:
        result = self.excel_svc.reimport_excel(Path(excel_path))
        self._mark_db_modified()
        n = int(result.get("updated", 0) or 0)
        self.db.log_activity(
            kind="edit_batch",
            summary=f"Re-importaste Excel ({n} productos actualizados)",
            count=n,
            metadata={"file": Path(excel_path).name, "source": "excel_reimport"},
        )
        return result

    # ─── PDF catalog ─────────────────────────────────────────────────────────

    def generate_catalog_pdf(self, active_only: bool = True) -> Path:
        """Generate the final commercial catalog PDF."""
        # Refresh PDFGenerator with latest branding
        self.pdf_gen = PDFGenerator(
            output_dir=settings.PDFS_DIR,
            company_name=self.get_setting("company_name", settings.COMPANY_NAME),
            company_slogan=self.get_setting("company_slogan", settings.COMPANY_SLOGAN),
            primary_color=self.get_setting("primary_color", settings.PRIMARY_COLOR),
            secondary_color=self.get_setting("secondary_color", settings.SECONDARY_COLOR),
            products_per_row=int(self.get_setting("products_per_row", "2")),
        )
        products = self.db.get_all_products(include_inactive=not active_only)
        path = self.pdf_gen.generate(products)
        n = len(products)
        self.db.log_activity(
            kind="pdf",
            summary=f"Generaste catálogo PDF ({n} prod)" + (" — solo activos" if active_only else ""),
            count=n,
            metadata={"file": Path(path).name if path else ""},
        )
        return path

    # ─── Products ────────────────────────────────────────────────────────────

    def get_products(self, include_inactive: bool = True) -> list[dict]:
        return self.db.get_all_products(include_inactive=include_inactive)

    def get_products_page(
        self,
        *,
        filter_mode: str = "Todos",
        search: str = "",
        health_filter: str = "",
        sku_list: list = [],        # noqa: B006
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        return self.db.get_products_page(
            filter_mode=filter_mode, search=search,
            health_filter=health_filter,
            sku_list=sku_list,
            limit=limit, offset=offset,
        )

    def get_recent_activity(self, limit: int = 30) -> list[dict]:
        return self.db.get_recent_activity(limit=limit)

    def get_product(self, sku: str) -> Optional[dict]:
        return self.db.get_product(sku)

    def update_product(self, sku: str, changes: dict) -> None:
        """Persist user-driven inline edits for a single product."""
        self.db.update_product_fields(sku, changes)
        self._mark_db_modified()

    def set_product_active(self, sku: str, active: bool):
        self.db.set_product_active(sku, active)
        self._mark_db_modified()

    def clear_legacy_brand_fallback(self) -> int:
        """
        Maintenance utility for catalogs imported before the brand fallback
        was removed from the parser. Clears `brand` for every row where it
        equals `category` (the legacy fallback value). Returns affected rows.
        """
        n = self.db.clear_brand_where_equals_category()
        if n > 0:
            self._mark_db_modified()
        return n

    def reapply_margins(self) -> int:
        count = self.product_svc.apply_margin_to_all(self.margin_config)
        self._mark_db_modified()
        self.db.log_activity(
            kind="margin_apply",
            summary=f"Re-aplicaste margen del {self.margin_config.margin_pct:g}% a {count} productos",
            count=count,
            metadata={
                "margin_pct": self.margin_config.margin_pct,
                "iva_pct":    self.margin_config.iva_pct,
                "round_to":   self.margin_config.round_to_nearest,
                "suffix":     self.margin_config.price_suffix,
            },
        )
        return count

    def log_edit_batch(self, n_saved: int) -> None:
        """
        Called by ProductsFrame after a user saves a batch of inline edits.
        One save action = one activity entry, regardless of how many SKUs changed.
        """
        if n_saved <= 0:
            return
        label = "1 producto" if n_saved == 1 else f"{n_saved} productos"
        self.db.log_activity(
            kind="edit_batch",
            summary=f"Editaste {label}",
            count=n_saved,
            metadata={"source": "inline"},
        )

    # ─── Settings ────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        return self.db.get_setting(key, default)

    def set_setting(self, key: str, value: str):
        self.db.set_setting(key, value)

    def update_margin_config(
        self,
        margin_pct: float,
        iva_pct: float = 0.0,
        round_to: int = 0,
        suffix: str = "",
    ):
        self.margin_config = MarginConfig(
            margin_pct=margin_pct,
            iva_pct=iva_pct,
            round_to_nearest=round_to,
            price_suffix=suffix,
        )
        self._save_margin_config()

    def _save_margin_config(self):
        self.db.set_setting("last_margin_pct", str(self.margin_config.margin_pct))
        self.db.set_setting("last_iva_pct",    str(self.margin_config.iva_pct))
        self.db.set_setting("last_round_to",   str(self.margin_config.round_to_nearest))
        self.db.set_setting("last_price_suffix", self.margin_config.price_suffix)

    # ─── Stats ───────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        all_products = self.db.get_all_products(include_inactive=True)
        active   = sum(1 for p in all_products if p.get("active"))
        inactive = sum(1 for p in all_products if not p.get("active"))
        disc     = sum(1 for p in all_products if p.get("discontinued"))
        sessions = self.db.get_sessions(limit=1)
        last_import = sessions[0]["started_at"] if sessions else None
        return {
            "total":       len(all_products),
            "active":      active,
            "inactive":    inactive,
            "discontinued": disc,
            "last_import": last_import,
        }

    def get_session_history(self, limit: int = 10) -> list[dict]:
        return self.db.get_sessions(limit=limit)

    def find_previous_import(self, pdf_path: str) -> Optional[dict]:
        """Return the most recent session that processed the same PDF path, if any."""
        return self.db.find_session_by_pdf(pdf_path)

    # ─── Dashboard ───────────────────────────────────────────────────────────

    def get_missing_image_info(self) -> dict:
        """
        Filesystem check: find active products whose image_path no longer
        exists on disk (e.g. manually deleted from extracted_images/).
        Returns {"count": N, "skus": ["SKU1", "SKU2", ...]}.
        Called once per Dashboard on_show().
        """
        try:
            from pathlib import Path
            rows = self.db.get_active_image_paths()
            missing_skus = [
                r["sku"] for r in rows
                if r["image_path"] and not Path(r["image_path"]).exists()
            ]
            return {"count": len(missing_skus), "skus": missing_skus}
        except Exception:
            return {"count": 0, "skus": []}

    def get_dashboard_data(self) -> dict:
        """Aggregate data for the dashboard widgets."""
        stats = self.get_stats()
        sessions = self.db.get_sessions(limit=1)
        last_session = sessions[0] if sessions else None
        health = self.db.get_health_metrics()
        missing = self.get_missing_image_info()
        health["missing_image"]      = missing["count"]
        health["missing_image_skus"] = missing["skus"]
        return {
            "stats":          stats,
            "last_import":    last_session,
            "top_categories": self.db.get_top_categories(limit=8),
            "health":         health,
        }

    # ─── Excel status / staleness ────────────────────────────────────────────

    def get_excel_status(self) -> dict:
        """
        Returns timestamps and staleness flag for the Excel tab UI.
            {
              'last_db_mod':    datetime | None,
              'last_excel_gen': datetime | None,
              'is_stale':       bool,
              'has_excel':      bool,
            }
        """
        db_mod    = self._parse_iso(self.get_setting(KEY_LAST_DB_MOD, ""))
        excel_gen = self._parse_iso(self.get_setting(KEY_LAST_EXCEL_GEN, ""))
        has_excel = excel_gen is not None
        # Stale only meaningful when both timestamps exist
        is_stale  = bool(db_mod and excel_gen and db_mod > excel_gen)
        # Also stale if DB was modified but no Excel has ever been generated
        if db_mod and not excel_gen:
            is_stale = True
        return {
            "last_db_mod":    db_mod,
            "last_excel_gen": excel_gen,
            "is_stale":       is_stale,
            "has_excel":      has_excel,
        }

    # ─── Tracking helpers ────────────────────────────────────────────────────

    def _mark_db_modified(self):
        self.set_setting(KEY_LAST_DB_MOD, datetime.now().isoformat(timespec="seconds"))

    def _mark_excel_generated(self):
        self.set_setting(KEY_LAST_EXCEL_GEN, datetime.now().isoformat(timespec="seconds"))

    @staticmethod
    def _parse_iso(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None
