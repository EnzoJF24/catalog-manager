"""
Database layer using SQLAlchemy Core + SQLite.
Handles product persistence, image cache, and session history.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Float, Boolean, Integer, DateTime, Text,
    select, update, insert, delete, and_, or_, func, desc
)
from sqlalchemy.engine import Engine

from app.logging_config.logger import get_logger

log = get_logger("database")


def _get_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    # WAL journal + NORMAL sync: faster bulk writes, safe on power-loss
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        conn.commit()
    return engine


metadata = MetaData()

products_table = Table(
    "products", metadata,
    Column("sku", String(100), primary_key=True),
    Column("brand", String(200)),
    Column("description", Text),
    Column("category", String(200), index=True),
    Column("price_original", Float),
    Column("price_final", Float),
    Column("margin_pct", Float, default=0.0),
    Column("iva_pct", Float, default=0.0),
    Column("round_to_nearest", Integer, default=0),
    Column("price_suffix", String(10), default=""),
    Column("active", Boolean, default=True, index=True),
    Column("discontinued", Boolean, default=False),
    Column("notes", Text, default=""),
    Column("image_path", String(500)),
    Column("image_confidence", Float, default=0.0),
    Column("first_seen", DateTime),
    Column("last_seen", DateTime),
    Column("processing_id", String(20)),
    Column("page_num", Integer, default=0),
)

image_cache_table = Table(
    "image_cache", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sku", String(100), index=True),
    Column("file_path", String(500)),
    Column("page_num", Integer),
    Column("bbox_json", Text),     # JSON [x0,y0,x1,y1]
    Column("width_px", Integer),
    Column("height_px", Integer),
    Column("confidence", Float),
    Column("created_at", DateTime, default=datetime.now),
)

sessions_table = Table(
    "processing_sessions", metadata,
    Column("session_id", String(20), primary_key=True),
    Column("pdf_path", Text),
    Column("supplier_name", String(200)),
    Column("parser_name", String(200)),
    Column("started_at", DateTime),
    Column("completed_at", DateTime),
    Column("total_pages", Integer),
    Column("products_found", Integer),
    Column("images_found", Integer),
    Column("images_matched", Integer),
    Column("errors_json", Text),
    Column("warnings_json", Text),
)

settings_table = Table(
    "app_settings", metadata,
    Column("key", String(100), primary_key=True),
    Column("value", Text),
    Column("updated_at", DateTime),
)

# Activity log — one row per user-meaningful action (import, edit batch,
# excel/pdf generation, margin reapply). Designed to be impossible to flood:
# each "intention" is one row regardless of how many records it touched.
activity_log_table = Table(
    "activity_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime, nullable=False, index=True),
    Column("kind", String(40), nullable=False, index=True),
    Column("summary", Text, nullable=False),
    Column("count", Integer, default=0),
    Column("metadata_json", Text, default=""),
)


class DatabaseManager:
    """Central database access point."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.engine = _get_engine(db_path)
        self._create_tables()
        log.info(f"Database initialized at {db_path}")

    def _create_tables(self):
        metadata.create_all(self.engine)
        self._migrate()
        log.debug("Tables ensured")

    def _migrate(self):
        """Add columns introduced in v2.0 to existing databases (safe no-op if already present)."""
        new_cols = [
            ("round_to_nearest", "INTEGER DEFAULT 0"),
            ("price_suffix",     "TEXT DEFAULT ''"),
        ]
        with self.engine.begin() as conn:
            for col_name, col_def in new_cols:
                try:
                    conn.exec_driver_sql(
                        f"ALTER TABLE products ADD COLUMN {col_name} {col_def}"
                    )
                    log.info(f"Migration: added column products.{col_name}")
                except Exception as e:
                    # Expected: "duplicate column name" when column already exists.
                    # Any other error (e.g. DB corruption) is logged as a warning.
                    if "duplicate column name" not in str(e).lower():
                        log.warning(f"Migration warning for {col_name}: {e}")

    # ─── Products ─────────────────────────────────────────────────────────────

    def get_product(self, sku: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(products_table).where(products_table.c.sku == sku)
            ).mappings().first()
            return dict(row) if row else None

    def get_all_products(self, include_inactive: bool = True) -> list[dict]:
        with self.engine.connect() as conn:
            stmt = select(products_table)
            if not include_inactive:
                stmt = stmt.where(products_table.c.active == True)
            rows = conn.execute(stmt).mappings().all()
            return [dict(r) for r in rows]

    def upsert_product(self, product_data: dict) -> str:
        """
        Insert or update product.
        - 'active' and 'notes' are preserved from the existing row unless
          explicitly included in product_data.
        - 'discontinued' is only changed when explicitly present in product_data;
          it is NOT silently reset to False on every import (fixes I5).
        """
        sku = product_data["sku"]
        existing = self.get_product(sku)
        with self.engine.begin() as conn:
            if existing:
                # Fields the user owns — only overwrite when caller is explicit
                preserved = {"active", "notes", "sku"}
                if "discontinued" not in product_data:
                    preserved.add("discontinued")
                update_data = {k: v for k, v in product_data.items()
                               if k not in preserved}
                update_data["last_seen"] = datetime.now()
                conn.execute(
                    update(products_table)
                    .where(products_table.c.sku == sku)
                    .values(**update_data)
                )
                action = "updated"
            else:
                product_data.setdefault("first_seen", datetime.now())
                product_data["last_seen"] = datetime.now()
                product_data.setdefault("active", True)
                product_data.setdefault("discontinued", False)
                conn.execute(insert(products_table).values(**product_data))
                action = "inserted"
        log.debug(f"Product {sku}: {action}")
        return action

    def bulk_upsert_products(self, products_data: list[dict]) -> tuple[int, int]:
        """
        Insert or update all products in a single transaction.
        Identical preservation semantics to upsert_product (active/notes/discontinued).
        Returns (inserted, updated) counts.
        """
        if not products_data:
            return 0, 0

        skus = [d["sku"] for d in products_data]

        with self.engine.begin() as conn:
            # 1. Load all existing rows in ONE query
            existing_rows = conn.execute(
                select(
                    products_table.c.sku,
                    products_table.c.active,
                    products_table.c.discontinued,
                    products_table.c.notes,
                ).where(products_table.c.sku.in_(skus))
            ).mappings().all()
            existing_by_sku = {r["sku"]: dict(r) for r in existing_rows}

            to_insert: list[dict] = []
            now = datetime.now()

            for data in products_data:
                sku = data["sku"]
                if sku in existing_by_sku:
                    preserved = {"active", "notes", "sku"}
                    if "discontinued" not in data:
                        preserved.add("discontinued")
                    update_vals = {k: v for k, v in data.items() if k not in preserved}
                    update_vals["last_seen"] = now
                    conn.execute(
                        update(products_table)
                        .where(products_table.c.sku == sku)
                        .values(**update_vals)
                    )
                else:
                    row = dict(data)
                    row.setdefault("first_seen", now)
                    row["last_seen"] = now
                    row.setdefault("active", True)
                    row.setdefault("discontinued", False)
                    to_insert.append(row)

            # 2. Batch INSERT all new products in one statement
            if to_insert:
                conn.execute(insert(products_table), to_insert)

        inserted = len(to_insert)
        updated  = len(products_data) - inserted
        log.debug(f"bulk_upsert: {inserted} inserted, {updated} updated")
        return inserted, updated

    def bulk_cache_images(self, images: list[dict]) -> None:
        """
        Replace all image-cache entries for the given SKUs in one transaction.
        Each dict must have: sku, file_path, page_num, bbox, width_px, height_px, confidence.
        """
        if not images:
            return
        skus = [d["sku"] for d in images]
        now  = datetime.now()
        rows = [
            {
                "sku":        d["sku"],
                "file_path":  str(d["file_path"]),
                "page_num":   d["page_num"],
                "bbox_json":  json.dumps(list(d["bbox"])),
                "width_px":   d["width_px"],
                "height_px":  d["height_px"],
                "confidence": d["confidence"],
                "created_at": now,
            }
            for d in images
        ]
        with self.engine.begin() as conn:
            conn.execute(
                delete(image_cache_table)
                .where(image_cache_table.c.sku.in_(skus))
            )
            conn.execute(insert(image_cache_table), rows)
        log.debug(f"bulk_cache_images: {len(rows)} entries written")

    def mark_discontinued(self, skus_seen: list[str]) -> int:
        """Mark products NOT in current import as discontinued."""
        with self.engine.begin() as conn:
            stmt = (
                update(products_table)
                .where(
                    and_(
                        products_table.c.sku.notin_(skus_seen),
                        products_table.c.discontinued == False
                    )
                )
                .values(discontinued=True, last_seen=datetime.now())
            )
            result = conn.execute(stmt)
            count = result.rowcount
        if count:
            log.info(f"Marked {count} products as discontinued")
        return count

    def update_product_fields(self, sku: str, fields: dict) -> None:
        """
        Update arbitrary product columns directly — used for user-driven inline edits.
        Unlike upsert_product(), this method writes ALL supplied fields including
        'active' and 'discontinued' without preservation logic.
        """
        update_data = {k: v for k, v in fields.items() if k not in ("sku",)}
        if not update_data:
            return
        update_data["last_seen"] = datetime.now()
        with self.engine.begin() as conn:
            conn.execute(
                update(products_table)
                .where(products_table.c.sku == sku)
                .values(**update_data)
            )
        log.debug(f"update_product_fields {sku}: {list(update_data.keys())}")

    def set_product_active(self, sku: str, active: bool):
        with self.engine.begin() as conn:
            conn.execute(
                update(products_table)
                .where(products_table.c.sku == sku)
                .values(active=active)
            )

    def clear_brand_where_equals_category(self) -> int:
        """
        One-shot cleanup utility: clear `brand` for every product where
        brand == category. These rows were created by the legacy parser
        fallback (now removed) that copied the category into the brand
        column when the supplier's PDF didn't specify a brand.

        Returns the number of rows affected. Safe to run multiple times.
        """
        with self.engine.begin() as conn:
            result = conn.execute(
                update(products_table)
                .where(products_table.c.brand == products_table.c.category)
                .values(brand="")
            )
            n = result.rowcount or 0
        log.info(f"clear_brand_where_equals_category: {n} rows cleared")
        return n

    def bulk_update_active(self, sku_active_map: dict[str, bool]):
        """Bulk update active flags from Excel reimport."""
        with self.engine.begin() as conn:
            for sku, active in sku_active_map.items():
                conn.execute(
                    update(products_table)
                    .where(products_table.c.sku == sku)
                    .values(active=active)
                )
        log.info(f"Bulk updated {len(sku_active_map)} active flags")

    # ─── Image cache ──────────────────────────────────────────────────────────

    def cache_image(self, sku: str, file_path: Path, page_num: int,
                    bbox: tuple, width_px: int, height_px: int,
                    confidence: float) -> None:
        with self.engine.begin() as conn:
            # Remove old entries for this SKU first
            conn.execute(
                delete(image_cache_table)
                .where(image_cache_table.c.sku == sku)
            )
            conn.execute(insert(image_cache_table).values(
                sku=sku,
                file_path=str(file_path),
                page_num=page_num,
                bbox_json=json.dumps(list(bbox)),
                width_px=width_px,
                height_px=height_px,
                confidence=confidence,
                created_at=datetime.now(),
            ))

    def get_cached_image(self, sku: str) -> Optional[dict]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(image_cache_table)
                .where(image_cache_table.c.sku == sku)
                .order_by(image_cache_table.c.created_at.desc())
                .limit(1)
            ).mappings().first()
            return dict(row) if row else None

    # ─── Sessions ─────────────────────────────────────────────────────────────

    def save_session(self, session_data: dict):
        with self.engine.begin() as conn:
            conn.execute(insert(sessions_table).values(**session_data))

    def get_sessions(self, limit: int = 20) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(sessions_table)
                .order_by(sessions_table.c.started_at.desc())
                .limit(limit)
            ).mappings().all()
            return [dict(r) for r in rows]

    def find_session_by_pdf(self, pdf_path: str) -> Optional[dict]:
        """Return the most recent session that imported the given PDF path, or None."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(sessions_table)
                .where(sessions_table.c.pdf_path == pdf_path)
                .order_by(sessions_table.c.started_at.desc())
                .limit(1)
            ).mappings().first()
            return dict(row) if row else None

    # ─── App settings ─────────────────────────────────────────────────────────

    def set_setting(self, key: str, value: str):
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(settings_table).where(settings_table.c.key == key)
            ).first()
            if existing:
                conn.execute(
                    update(settings_table)
                    .where(settings_table.c.key == key)
                    .values(value=value, updated_at=datetime.now())
                )
            else:
                conn.execute(insert(settings_table).values(
                    key=key, value=value, updated_at=datetime.now()
                ))

    def get_setting(self, key: str, default: str = "") -> str:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(settings_table).where(settings_table.c.key == key)
            ).first()
            return row.value if row else default

    # ─── Paginated product queries ────────────────────────────────────────────

    def get_products_page(
        self,
        *,
        filter_mode: str = "All",
        search: str = "",
        health_filter: str = "",
        sku_list: list = [],          # noqa: B006 — intentional mutable default
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """
        Return (rows, total_count) for a single page of products.

        filter_mode:   'All' | 'Active' | 'Inactive' | 'Discontinued'
        search:        free text matched against sku/description/brand/category
        health_filter: '' | 'no_image' | 'zero_price' | 'low_margin' | 'no_description'
                       (overlay filter triggered from Dashboard health chips)
        sku_list:      explicit allowlist of SKUs — overrides all other filters
                       when non-empty (used by missing_image chip navigation)
        """
        stmt = select(products_table)
        count_stmt = select(func.count()).select_from(products_table)

        conditions = []
        if filter_mode == "Active":
            conditions.append(products_table.c.active == True)
            conditions.append(products_table.c.discontinued == False)
        elif filter_mode == "Inactive":
            conditions.append(products_table.c.active == False)
        elif filter_mode == "Discontinued":
            conditions.append(products_table.c.discontinued == True)

        if search:
            like = f"%{search.lower()}%"
            # SQLite LIKE is case-insensitive for ASCII by default
            conditions.append(
                or_(
                    func.lower(products_table.c.sku).like(like),
                    func.lower(products_table.c.description).like(like),
                    func.lower(products_table.c.brand).like(like),
                    func.lower(products_table.c.category).like(like),
                )
            )

        # sku_list: exact-SKU allowlist — takes priority over all other filters.
        # Used by the missing_image chip (filesystem check produces a concrete
        # list of SKUs; we can't express that check in SQL).
        if sku_list:
            conditions.append(products_table.c.sku.in_(sku_list))
        else:
            # Health filter (from Dashboard double-click) — always implies
            # "active + non-discontinued" so the user sees the same set the
            # health metric counted.
            if health_filter:
                conditions.append(products_table.c.active == True)
                conditions.append(products_table.c.discontinued == False)
                if health_filter == "no_image":
                    conditions.append(or_(
                        products_table.c.image_path == None,    # noqa: E711
                        products_table.c.image_path == "",
                    ))
                elif health_filter == "zero_price":
                    conditions.append(or_(
                        products_table.c.price_final == None,   # noqa: E711
                        products_table.c.price_final == 0,
                    ))
                elif health_filter == "low_margin":
                    conditions.append(and_(
                        products_table.c.margin_pct != None,    # noqa: E711
                        products_table.c.margin_pct < 10,
                    ))
                elif health_filter == "no_description":
                    conditions.append(or_(
                        products_table.c.description == None,   # noqa: E711
                        products_table.c.description == "",
                    ))

        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        stmt = stmt.order_by(products_table.c.sku).limit(limit).offset(offset)

        with self.engine.connect() as conn:
            total = conn.execute(count_stmt).scalar() or 0
            rows  = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows], int(total)

    # ─── Dashboard queries ────────────────────────────────────────────────────

    def get_top_categories(self, limit: int = 8) -> list[dict]:
        """Return [{'category': str, 'count': int}] ordered by count desc."""
        stmt = (
            select(
                products_table.c.category,
                func.count().label("count"),
            )
            .where(products_table.c.category != None)  # noqa: E711
            .where(products_table.c.category != "")
            .group_by(products_table.c.category)
            .order_by(desc("count"))
            .limit(limit)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [{"category": r["category"], "count": int(r["count"])} for r in rows]

    def get_health_metrics(self) -> dict:
        """
        Return counts of products with potential data issues.
        Only counts products that are active (non-discontinued).
        """
        active_only = and_(
            products_table.c.active == True,
            products_table.c.discontinued == False,
        )

        def _count(extra) -> int:
            stmt = (
                select(func.count())
                .select_from(products_table)
                .where(and_(active_only, extra))
            )
            with self.engine.connect() as conn:
                return int(conn.execute(stmt).scalar() or 0)

        return {
            "no_image": _count(
                or_(products_table.c.image_path == None,        # noqa: E711
                    products_table.c.image_path == "")
            ),
            "zero_price": _count(
                or_(products_table.c.price_final == None,       # noqa: E711
                    products_table.c.price_final == 0)
            ),
            "low_margin": _count(
                and_(products_table.c.margin_pct != None,       # noqa: E711
                     products_table.c.margin_pct < 10)
            ),
            "no_description": _count(
                or_(products_table.c.description == None,       # noqa: E711
                    products_table.c.description == "")
            ),
        }

    def get_active_image_paths(self) -> list[dict]:
        """
        Returns [{sku, image_path}, ...] for all active, non-discontinued
        products that have a non-null, non-empty image_path.
        Used by the controller to check which files no longer exist on disk.
        """
        stmt = (
            select(products_table.c.sku, products_table.c.image_path)
            .where(and_(
                products_table.c.active == True,
                products_table.c.discontinued == False,
                products_table.c.image_path != None,   # noqa: E711
                products_table.c.image_path != "",
            ))
        )
        with self.engine.connect() as conn:
            return [{"sku": row[0], "image_path": row[1]}
                    for row in conn.execute(stmt)]

    # ─── Activity log ─────────────────────────────────────────────────────────

    def log_activity(self, kind: str, summary: str,
                     count: int = 0, metadata: Optional[dict] = None) -> None:
        """
        Record one user-meaningful action. Designed to be flood-resistant:
        each call is one atomic intention (one import, one batch save,
        one Excel generation), never per-field changes.
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(activity_log_table).values(
                    ts=datetime.now(),
                    kind=kind,
                    summary=summary,
                    count=int(count or 0),
                    metadata_json=json.dumps(metadata) if metadata else "",
                ))
        except Exception as e:
            # Activity logging must never break the user's action
            log.warning(f"log_activity failed ({kind}): {e}")

    def get_recent_activity(self, limit: int = 30) -> list[dict]:
        """
        Return the most recent activity entries, ordered by ts desc.
        Caller is responsible for any visual aggregation/collapsing.
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(activity_log_table)
                .order_by(activity_log_table.c.ts.desc())
                .limit(limit)
            ).mappings().all()
            return [dict(r) for r in rows]
