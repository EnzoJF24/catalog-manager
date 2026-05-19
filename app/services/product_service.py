"""
Product service: orchestrates parsing, persistence, and margin application.
"""
from __future__ import annotations
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from app.config.settings import settings
from app.database.db_manager import DatabaseManager
from app.models.product import Product, ProductImage, ProcessingSession, MarginConfig
from app.logging_config.logger import get_logger

log = get_logger("product_service")


class ProductService:
    """
    High-level service that ties together PDF parsing,
    persistence, and margin logic.
    """

    def __init__(self, db: DatabaseManager, images_base_dir: Path):
        self.db = db
        self.images_base_dir = images_base_dir

    # ─── Full import pipeline ─────────────────────────────────────────────────

    def import_pdf(
        self,
        pdf_path: Path,
        margin_config: MarginConfig,
        progress_cb: Optional[Callable[[str, float], None]] = None,
        force_parser: Optional[str] = None,
    ) -> ProcessingSession:
        """
        Full PDF import pipeline:
          detect parser → extract → apply margins → persist → return session.
        """
        session = ProcessingSession(
            pdf_path=str(pdf_path),
        )

        def _progress(msg: str, pct: float):
            log.info(f"[{pct:.0f}%] {msg}")
            if progress_cb:
                progress_cb(msg, pct)

        _progress("Detectando proveedor...", 5)

        # Detect parser class before creating the output directory so we can
        # use a permanent per-supplier folder instead of a session-scoped one.
        from app.parsers.parser_factory import ParserFactory, REGISTERED_PARSERS
        if force_parser:
            parser_cls = next(
                (cls for cls in REGISTERED_PARSERS
                 if cls.SUPPLIER_NAME.lower() == force_parser.lower()),
                None,
            ) or ParserFactory.detect(pdf_path)
        else:
            parser_cls = ParserFactory.detect(pdf_path)

        if not parser_cls:
            supported = ", ".join(p.SUPPLIER_NAME for p in REGISTERED_PARSERS)
            session.errors.append(
                f"Este PDF no corresponde a ningún proveedor soportado. "
                f"Proveedores soportados: {supported}."
            )
            session.complete()
            return session

        # One permanent folder per supplier — images are reused across re-imports
        supplier_safe = re.sub(r"[^\w\-]", "_", parser_cls.SUPPLIER_NAME)
        output_dir    = self.images_base_dir / supplier_safe
        output_dir.mkdir(parents=True, exist_ok=True)

        parser = parser_cls(pdf_path, output_dir)
        session.supplier_name = parser.SUPPLIER_NAME
        session.parser_name   = parser.__class__.__name__
        _progress(f"Parser: {parser.SUPPLIER_NAME}", 10)

        # Run extraction — close the PDF file handle immediately after, before
        # any further processing, so Windows doesn't keep the file locked.
        _progress("Extrayendo productos...", 15)
        try:
            products, images = parser.run(session)
        finally:
            parser._close_doc()

        if not products:
            session.errors.append("No se extrajeron productos.")
            session.complete()
            return session

        _progress(f"Aplicando márgenes ({margin_config.margin_pct}%)...", 60)
        for p in products:
            p.apply_margin(
                margin_config.margin_pct,
                margin_config.iva_pct,
                margin_config.round_to_nearest,
                margin_config.price_suffix,
            )
            p.processing_id = session.session_id

        _progress("Persistiendo en base de datos...", 70)
        self._persist_products(products, images, session)

        _progress("Guardando sesión...", 90)
        self._save_session(session)

        session.complete()
        _progress(f"✓ Completado: {len(products)} productos", 100)
        log.info(
            f"Import complete: session={session.session_id}, "
            f"products={session.products_found}, "
            f"images={session.images_matched}/{session.images_found}"
        )
        return session

    def _persist_products(
        self,
        products: list[Product],
        images: list[ProductImage],
        session: ProcessingSession,
    ):
        """Bulk-upsert all products and cache image metadata in two transactions."""
        img_by_sku = {pi.sku: pi for pi in images}

        # Build product rows
        products_data = []
        for p in products:
            pi = img_by_sku.get(p.sku)
            products_data.append({
                "sku":              p.sku,
                "brand":            p.brand,
                "description":      p.description,
                "category":         p.category,
                "price_original":   p.price_original,
                "price_final":      p.price_final,
                "margin_pct":       p.margin_pct,
                "iva_pct":          p.iva_pct,
                "round_to_nearest": p.round_to_nearest,
                "price_suffix":     p.price_suffix,
                "active":           p.active,
                "notes":            p.notes,
                "image_path":       self._rel_path(pi.file_path) if pi else None,
                "image_confidence": pi.confidence if pi else 0.0,
                "first_seen":       p.first_seen,
                "last_seen":        datetime.now(),
                "processing_id":    session.session_id,
                "page_num":         p.page_num,
            })

        # Single transaction for all products
        self.db.bulk_upsert_products(products_data)

        # Single transaction for all image cache entries
        images_data = [
            {
                "sku":        pi.sku,
                "file_path":  pi.file_path,
                "page_num":   pi.page_num,
                "bbox":       pi.bbox,
                "width_px":   pi.width_px,
                "height_px":  pi.height_px,
                "confidence": pi.confidence,
            }
            for pi in images
        ]
        self.db.bulk_cache_images(images_data)

        skus_seen = [p.sku for p in products]
        discontinued = self.db.mark_discontinued(skus_seen)
        if discontinued:
            session.warnings.append(f"{discontinued} productos marcados como discontinuados")

    def _save_session(self, session: ProcessingSession):
        self.db.save_session({
            "session_id":    session.session_id,
            "pdf_path":      session.pdf_path,
            "supplier_name": session.supplier_name,
            "parser_name":   session.parser_name,
            "started_at":    session.started_at,
            "completed_at":  session.completed_at,
            "total_pages":   session.total_pages,
            "products_found": session.products_found,
            "images_found":  session.images_found,
            "images_matched": session.images_matched,
            "errors_json":   json.dumps(session.errors, ensure_ascii=False),
            "warnings_json": json.dumps(session.warnings, ensure_ascii=False),
        })

    # ─── Query helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _rel_path(p: Path) -> str:
        """Store image paths relative to BASE_DIR so project is portable."""
        try:
            return str(p.relative_to(settings.BASE_DIR))
        except ValueError:
            return str(p)

    def get_active_products(self) -> list[dict]:
        return self.db.get_all_products(include_inactive=False)

    def get_all_products(self) -> list[dict]:
        return self.db.get_all_products(include_inactive=True)

    def apply_margin_to_all(
        self, margin_config: MarginConfig, active_only: bool = True
    ) -> int:
        """Re-apply margin to all persisted products and update DB."""
        rows = self.get_active_products() if active_only else self.get_all_products()
        updated = 0
        for row in rows:
            p = Product(
                sku=row["sku"],
                brand=row["brand"] or "",
                description=row["description"] or "",
                price_original=row["price_original"] or 0.0,
                category=row["category"] or "",
            )
            p.apply_margin(
                margin_config.margin_pct,
                margin_config.iva_pct,
                margin_config.round_to_nearest,
                margin_config.price_suffix,
            )
            self.db.upsert_product({
                "sku":              p.sku,
                "brand":            p.brand,
                "description":      p.description,
                "category":         p.category,
                "price_original":   p.price_original,
                "price_final":      p.price_final,
                "margin_pct":       p.margin_pct,
                "iva_pct":          p.iva_pct,
                "round_to_nearest": p.round_to_nearest,
                "price_suffix":     p.price_suffix,
                "last_seen":        datetime.now(),
            })
            updated += 1
        log.info(f"Re-applied margin to {updated} products")
        return updated
