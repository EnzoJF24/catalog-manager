"""
Parser for "G.A. Murdock" list-price catalogs (water treatment & plumbing parts).
InDesign-generated, US Letter (612 x 792 pt), English, prices in USD.

Page anatomy (pages 3..N-1; cover, T&C and back cover carry no products):
  - Category tabs:   vertical strip on the outer edge (AgencyFB 12pt). The tabs
                     for the categories present on the page are rendered white.
  - Family title:    ErasITC-Demi 10pt, e.g. "John Guest® Check Valves"
  - Family photo:    one raster image in the left column (x < ~160 pt)
  - Table header:    Pragmatica-Bold 7pt white on blue. First column is always
                     the part number ("Part Number" / "Part #" / ...), last
                     column is always "List". Middle columns vary per table.
  - Table rows:      Pragmatica-Book 7pt cells, price in NovelMonoPro 6pt.

Because the middle columns change from table to table, column ranges are read
from every header row instead of being hard-coded. Text roles are identified
by font rather than by x-position, which keeps the parser stable across pages.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from app.parsers.base_parser import BaseParser
from app.models.product import Product, ProductImage, ProcessingSession
from app.logging_config.logger import get_logger

log = get_logger("ga_murdock_parser")

# ─── Font roles (calibrated from the 2026 list-price catalog) ────────────────
FONT_TAB      = "AgencyFB"
FONT_TITLE    = "ErasITC-Demi"
FONT_HEADER   = "Pragmatica-Bold"
FONT_CELL     = "Pragmatica-Book"
FONT_PRICE    = "NovelMonoPro"
TITLE_MIN_SIZE = 9.5
WHITE = 0xFFFFFF

# Rows are ~9.5 pt apart; prices sit ~1 pt above their row's text baseline
LINE_Y_TOL        = 2.5
HEADER_Y_TOL      = 3.0
# Split header labels ("Dimen-" / "sions") sit on a second line this close
HEADER_WRAP_GAP   = 10.0
SKU_ALIGN_TOL     = 10.0   # part numbers are left-aligned under their header
TABLE_X_PAD_LEFT  = 15.0
TABLE_X_PAD_RIGHT = 30.0

# Family photos live in the left column
IMG_MAX_CENTER_X = 160.0
IMG_MIN_SIDE_PT  = 20.0
IMG_RENDER_DPI   = 200
# Placeholder images: ≥ 97 % of pixels near white
BLANK_PIXEL_LEVEL = 245
BLANK_RATIO       = 0.97

PRICE_RE = re.compile(r"\$\s*[\d,]+(?:\.\d{2})?")
# Part numbers are upper-case codes; a few are letters only (TSNIPS, FLK-KIT)
# and a few carry an internal space (GAM GA090). Checked BEFORE upper-casing
# so that a stray lower-case label never qualifies as a part number.
SKU_RE   = re.compile(r"^[A-Z0-9][A-Z0-9\-./+ ]{2,24}$")
# Footnote markers glued to part numbers (their meaning varies per table)
SKU_MARKERS_RE   = re.compile(r"[*•]")
SKU_QUALIFIER_RE = re.compile(r"\s*\(([^)]*)\)\s*")   # "RO122P (plastic)"
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Category tabs, in the order they are printed on the page edge
CATEGORY_ORDER = [
    "Valves", "EZ-Adapters", "Drain Products", "Regulators", "Gauges",
    "Fittings", "Tubing", "Systems", "Pumps", "Tanks", "Housings", "Filters",
    "Membranes", "Faucets", "Tools", "Chemicals", "Instruments",
]
CATEGORY_KEYWORDS = {
    "Valves":         r"valve",
    "EZ-Adapters":    r"\bez\b|adapter",
    "Drain Products": r"drain|saddle|air gap",
    "Regulators":     r"regulator",
    "Gauges":         r"gauge",
    "Fittings":       r"fitting|connector|elbow|\btees?\b|union|stem|plug|collet|clip",
    "Tubing":         r"tubing",
    "Systems":        r"system",
    "Pumps":          r"pump",
    "Tanks":          r"\btanks?\b|vessel",
    "Housings":       r"housing|bracket|o-ring",
    "Filters":        r"filter|cartridge|block|spheres",
    "Membranes":      r"membrane|restrictor",
    "Faucets":        r"faucet",
    "Tools":          r"tool|wrench|core bit|cutter|hole kit",
    "Chemicals":      r"rust|clean|sanitiz|oxidant|sequestrant|regenerant|feeder",
    "Instruments":    r"meter|analysis|detector|sensor|floodstop",
}

# Brand prefixes found in family titles (longest first). Titles without a
# known brand keep brand empty — brand is honest data, never a guess.
KNOWN_BRANDS = [
    ("SeaTech / AquaLock", "SeaTech / AquaLock"),
    ("AirGap International", "AirGap International"),
    ("John Guest", "John Guest"),
    ("PRF / Merlin", "PRF / Merlin"),
    ("HM Digital", "HM Digital"),
    ("Ameri-Block", "Ameri-Block"),
    ("Hydronamic", "Hydronamic"),
    ("Structural", "Structural"),
    ("Tomlinson", "Tomlinson"),
    ("SHOK BLOK", "SHOK BLOK"),
    ("Omnipure", "Omnipure"),
    ("Spectrum", "Spectrum"),
    ("Mur-lok", "Mur-lok"),
    ("Li Kuan", "Li Kuan"),
    ("FilmTec", "FilmTec"),
    ("Aquatec", "Aquatec"),
    ("Norgren", "Norgren"),
    ("Pentair", "Pentair"),
    ("Pentek", "Pentek"),
    ("Relton", "Relton"),
    ("Watts", "Watts"),
    ("Toray", "Toray"),
    ("Aries", "Aries"),
    ("Clack", "Clack"),
    ("QMP", "QMP"),
    ("CSM", "CSM"),
]

# Column labels whose value reads fine on its own inside a description
BARE_VALUE_LABELS = {"description", "type", "dimensions", "dimen.", "filter type"}
QTY_LABELS        = {"qty", "box qty", "case qty"}
PART_LABELS       = {"part number", "part #"}
MODEL_LABELS      = {"model"}


# ─── Internal structures ─────────────────────────────────────────────────────

@dataclass
class _Span:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font: str
    size: float
    color: int

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class _Column:
    label: str
    x0: float
    x1: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class _Table:
    y: float                    # header baseline
    columns: list[_Column]
    title: str = ""
    lines: list[list[_Span]] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return self.columns[0].x0 - TABLE_X_PAD_LEFT

    @property
    def x1(self) -> float:
        return self.columns[-1].x1 + TABLE_X_PAD_RIGHT


@dataclass
class _Family:
    title: str
    y0: float                   # title top
    y1: float = float("inf")    # next title top (region end)
    skus: list[str] = field(default_factory=list)


class GAMurdockParser(BaseParser):
    """
    Parser for G.A. Murdock list-price catalogs (InDesign, US Letter, USD).
    """

    SUPPLIER_NAME = "G.A. Murdock"
    DETECTION_KEYWORDS = ["G.A. Murdock, Inc.", "G. A. Murdock", "LIST PRICE"]
    DETECTION_PATTERNS = [r"G\.\s?A\.\s?Murdock\s+\d{4}\s+Price\s+List"]

    def __init__(self, pdf_path: Path, output_dir: Path):
        super().__init__(pdf_path, output_dir)
        self._doc: Optional[fitz.Document] = None
        # Rows with a part number but no published price
        self._skipped_products: list[dict] = []
        # {page_num: [_Family, ...]} — built by extract_products, consumed by extract_images
        self._families_by_page: dict[int, list[_Family]] = {}

    def _open_doc(self) -> fitz.Document:
        if self._doc is None:
            self._doc = fitz.open(str(self.pdf_path))
        return self._doc

    def _close_doc(self):
        if self._doc:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None

    def __enter__(self):
        self._open_doc()
        return self

    def __exit__(self, *_):
        self._close_doc()

    # ─── BaseParser interface ─────────────────────────────────────────────────

    def validate_pdf(self) -> tuple[bool, str]:
        try:
            doc = self._open_doc()
            if doc.page_count == 0:
                return False, "The PDF has no pages."
            # Page 1 is a cover with almost no text — scan the first pages
            sample = "\n".join(doc[i].get_text("text") for i in range(min(3, doc.page_count)))
            if not any(kw in sample for kw in self.DETECTION_KEYWORDS):
                return False, (
                    f"No detection keywords found on the first pages "
                    f"— this PDF may not belong to {self.SUPPLIER_NAME}."
                )
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def detect_layout(self) -> dict:
        doc = self._open_doc()
        page = doc[min(2, doc.page_count - 1)]
        return {
            "page_count": doc.page_count,
            "page_width_pts": page.rect.width,
            "page_height_pts": page.rect.height,
            "has_images": len(page.get_images()) > 0,
            "word_count_p3": len(page.get_text("words")),
            "supplier": self.SUPPLIER_NAME,
        }

    def extract_products(self, session: ProcessingSession) -> list[Product]:
        doc = self._open_doc()
        session.total_pages = doc.page_count
        products: list[Product] = []
        seen_skus: set[str] = set()
        duplicates = 0
        category_idx = 0

        for page_num in range(doc.page_count):
            try:
                page_products, category_idx = self._parse_page(
                    doc[page_num], page_num, category_idx
                )
            except Exception as e:
                msg = f"Page {page_num + 1} error: {e}"
                session.errors.append(msg)
                log.error(msg)
                continue

            for p in page_products:
                if p.sku in seen_skus:
                    # Same part listed in two sections (e.g. Fittings and Faucets)
                    duplicates += 1
                    continue
                seen_skus.add(p.sku)
                products.append(p)
            log.debug(f"Page {page_num + 1}/{doc.page_count}: +{len(page_products)} products")

        session.products_found = len(products)

        if duplicates:
            session.warnings.append(
                f"{duplicates} part number(s) listed in more than one section — kept the first occurrence"
            )
        if self._skipped_products:
            msg = (
                f"{len(self._skipped_products)} product(s) without a published price discarded "
                f"(see logs for details)"
            )
            session.warnings.append(msg)
            log.warning(msg)
            for s in self._skipped_products:
                session.warnings.append(f"  SKIPPED page {s['page']}: {s['sku']} — {s['desc'][:40]}")

        return products

    def extract_images(self, session: ProcessingSession) -> list[ProductImage]:
        """
        One photo per product family: render the left-column image of each
        family once and link every SKU of that family to the same file.
        """
        doc = self._open_doc()
        best_by_sku: dict[str, ProductImage] = {}
        total_found = 0
        used_names: set[str] = set()

        for page_num, families in self._families_by_page.items():
            if not families:
                continue
            page = doc[page_num]
            try:
                infos = page.get_image_info()
            except Exception as e:
                log.error(f"Image error on page {page_num + 1}: {e}")
                continue

            candidates = [
                fitz.Rect(info["bbox"]) for info in infos
                if (info["bbox"][0] + info["bbox"][2]) / 2 < IMG_MAX_CENTER_X
                and info["bbox"][2] - info["bbox"][0] >= IMG_MIN_SIDE_PT
                and info["bbox"][3] - info["bbox"][1] >= IMG_MIN_SIDE_PT
            ]
            total_found += len(candidates)

            for fam_i, fam in enumerate(families):
                if not fam.skus:
                    continue
                # A preceding title without products (e.g. "Faucet Colors")
                # often holds this family's photos above the title.
                region_top = fam.y0
                if fam_i > 0 and not families[fam_i - 1].skus:
                    region_top = families[fam_i - 1].y0
                in_region = sorted(
                    (r for r in candidates if region_top - 5 <= (r.y0 + r.y1) / 2 < fam.y1),
                    key=lambda r: -(r.width * r.height),
                )
                rect = next((r for r in in_region if not self._is_blank(page, r)), None)
                if rect is None:
                    continue

                name = self._slugify(fam.title) or f"family-p{page_num + 1}"
                if name in used_names:
                    name = f"{name}-p{page_num + 1}"
                used_names.add(name)
                out_path = self.output_dir / f"{name}.png"

                try:
                    if out_path.exists():
                        w_px, h_px = int(rect.width), int(rect.height)
                    else:
                        # Rendering the clip (instead of extracting the raw stream)
                        # flattens CMYK / soft-masked images into plain RGB.
                        pix = page.get_pixmap(clip=rect, dpi=IMG_RENDER_DPI, alpha=False)
                        pix.save(str(out_path))
                        w_px, h_px = pix.width, pix.height
                except Exception as e:
                    log.warning(f"  Error saving image on page {page_num + 1} ({fam.title}): {e}")
                    continue

                for sku in fam.skus:
                    best_by_sku[sku] = ProductImage(
                        sku=sku,
                        file_path=out_path,
                        page_num=page_num,
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        width_px=w_px,
                        height_px=h_px,
                        # Shared family photo: good match, but not SKU-specific
                        confidence=0.9,
                    )

        product_images = list(best_by_sku.values())
        session.images_found     = total_found
        session.images_matched   = len(product_images)
        session.images_unmatched = len(self._products) - len(product_images)

        for p in self._products:
            pi = best_by_sku.get(p.sku)
            if pi:
                p.image_path       = pi.file_path
                p.image_confidence = pi.confidence

        log.info(
            f"Images: {total_found} family photos, "
            f"{len(product_images)}/{len(self._products)} products with an image"
        )
        return product_images

    @staticmethod
    def _is_blank(page: fitz.Page, rect: fitz.Rect) -> bool:
        """True for placeholder images that render as (almost) plain white."""
        pix = page.get_pixmap(clip=rect, dpi=36, colorspace=fitz.csGRAY, alpha=False)
        samples = pix.samples
        if not samples:
            return True
        near_white = sum(1 for v in samples if v >= BLANK_PIXEL_LEVEL)
        return near_white / len(samples) >= BLANK_RATIO

    # ─── Page parsing ─────────────────────────────────────────────────────────

    def _parse_page(
        self, page: fitz.Page, page_num: int, category_idx: int
    ) -> tuple[list[Product], int]:
        spans = self._collect_spans(page)

        tables = self._find_tables(spans)
        if not tables:
            self._families_by_page[page_num] = []
            return [], category_idx

        page_tabs = {s.text for s in spans if s.font.startswith(FONT_TAB) and s.color == WHITE}
        families = self._find_families(spans)
        self._assign_body_spans(spans, tables, families)

        products: list[Product] = []
        # Tables above the first title continue the previous page's family
        carried_category = CATEGORY_ORDER[category_idx]
        fam_category: dict[int, str] = {}
        for fam_i, fam in enumerate(families):
            category_idx = self._resolve_category(fam.title, page_tabs, category_idx)
            fam_category[fam_i] = CATEGORY_ORDER[category_idx]

        for table in tables:
            fam_i = self._family_index_for(table.y, families)
            fam = families[fam_i] if fam_i is not None else None
            title = fam.title if fam else ""
            category = fam_category.get(fam_i, carried_category)

            for row in self._build_rows(table):
                product = self._row_to_product(row, table, title, category, page_num)
                if product:
                    products.append(product)
                    if fam:
                        fam.skus.append(product.sku)

        self._families_by_page[page_num] = families
        return products, category_idx

    @staticmethod
    def _collect_spans(page: fitz.Page) -> list[_Span]:
        spans: list[_Span] = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    # Some cells carry stray NUL glyphs; drop control characters
                    text = CONTROL_CHARS_RE.sub("", s["text"]).replace("\xa0", " ").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    spans.append(_Span(text, x0, y0, x1, y1, s["font"], s["size"], s["color"]))
        return spans

    def _find_tables(self, spans: list[_Span]) -> list[_Table]:
        """Group white bold header spans into header rows → one _Table each."""
        header_spans = sorted(
            (s for s in spans if s.font.startswith(FONT_HEADER) and s.color == WHITE),
            key=lambda s: (s.y0, s.x0),
        )
        rows: list[list[_Span]] = []
        for s in header_spans:
            if rows and abs(s.y0 - rows[-1][0].y0) <= HEADER_Y_TOL:
                rows[-1].append(s)
            else:
                rows.append([s])

        tables: list[_Table] = []
        for row in rows:
            row.sort(key=lambda s: s.x0)
            is_wrap_line = (
                tables
                and len(row) < len(tables[-1].columns)
                and row[0].y0 - tables[-1].y <= HEADER_WRAP_GAP
            )
            if is_wrap_line:
                # Second line of a wrapped label ("Dimen-" / "sions")
                prev = tables[-1]
                for s in row:
                    col = min(prev.columns, key=lambda c: abs(c.xc - s.xc))
                    col.label = (col.label.rstrip("-") if col.label.endswith("-")
                                 else col.label + " ") + s.text
                    col.x0, col.x1 = min(col.x0, s.x0), max(col.x1, s.x1)
                continue

            columns: list[_Column] = []
            for s in row:
                # Labels split mid-word ("Box Q" + "ty") sit back-to-back
                if columns and s.x0 - columns[-1].x1 < 2.0:
                    columns[-1].label += s.text
                    columns[-1].x1 = s.x1
                else:
                    columns.append(_Column(s.text, s.x0, s.x1))
            if len(columns) < 2 or columns[-1].label.lower() != "list":
                continue
            is_sub_header = (
                tables
                and columns[0].label.lower() not in PART_LABELS
                and abs(columns[0].x0 - tables[-1].columns[0].x0) <= 5.0
            )
            if is_sub_header:
                # "Replacement Components" restarts a table but omits columns
                # (e.g. Model / Description) that its rows still carry.
                columns = [_Column(c.label, c.x0, c.x1) for c in tables[-1].columns]
            tables.append(_Table(y=row[0].y0, columns=columns))
        return tables

    @staticmethod
    def _find_families(spans: list[_Span]) -> list[_Family]:
        """
        Family titles: lines containing an ErasITC-Demi ≥ 9.5 pt span.
        Kerned letters come as separate spans, sometimes in a fallback font
        ("Li" + "q" + "uid-Filled", "Pentek®" + "Q" + "uick"), so every span
        on the title line is merged, adding a space only across real gaps.
        """
        candidates = sorted(
            (s for s in spans
             if s.color != WHITE and not s.font.startswith((FONT_TAB, FONT_HEADER, FONT_CELL, FONT_PRICE))
             and (s.size >= TITLE_MIN_SIZE - 0.5 or s.text in ("®", "™", "�"))),
            key=lambda s: s.yc,
        )
        # Group by baseline first, then order left-to-right: a fallback-font
        # capital can sit ~0.5 pt lower than the rest of its word.
        rows: list[list[_Span]] = []
        for s in candidates:
            if rows and abs(s.yc - rows[-1][0].yc) <= LINE_Y_TOL:
                rows[-1].append(s)
            else:
                rows.append([s])
        lines: list[list[_Span]] = []
        for row in rows:
            row.sort(key=lambda s: s.x0)
            lines.append([row[0]])
            for s in row[1:]:
                if s.x0 - lines[-1][-1].x1 < 15:
                    lines[-1].append(s)
                else:
                    lines.append([s])

        families = []
        for ln in lines:
            if not any(s.font.startswith(FONT_TITLE) and s.size >= TITLE_MIN_SIZE for s in ln):
                continue
            text = ln[0].text
            for prev, s in zip(ln, ln[1:]):
                text += ("" if s.x0 - prev.x1 < 1.5 else " ") + s.text
            families.append(_Family(title=GAMurdockParser._clean_text(text), y0=ln[0].y0))
        families.sort(key=lambda f: f.y0)
        for a, b in zip(families, families[1:]):
            a.y1 = b.y0
        return families

    @staticmethod
    def _family_index_for(table_y: float, families: list[_Family]) -> Optional[int]:
        """Nearest family title above the table header."""
        idx = None
        for i, fam in enumerate(families):
            if fam.y0 < table_y:
                idx = i
        return idx

    @staticmethod
    def _assign_body_spans(spans: list[_Span], tables: list[_Table], families: list[_Family]):
        """
        Attach every cell/price span to the closest table header above it,
        unless a family title sits in between (e.g. an "Also available:"
        box under a table is not part of that table).
        """
        body = [
            s for s in spans
            if (s.font.startswith(FONT_CELL) or s.font.startswith(FONT_PRICE))
            and s.color != WHITE and s.text not in ("®", "™", "�")
        ]
        title_ys = [f.y0 for f in families]
        for s in sorted(body, key=lambda s: (s.y0, s.x0)):
            owner = None
            for t in tables:
                if t.y < s.y0 - 1 and t.x0 <= s.xc <= t.x1:
                    if owner is None or t.y > owner.y:
                        owner = t
            if owner is None or any(owner.y < ty < s.y0 for ty in title_ys):
                continue
            if owner.lines and abs(s.yc - owner.lines[-1][0].yc) <= LINE_Y_TOL:
                owner.lines[-1].append(s)
            else:
                owner.lines.append([s])

    def _build_rows(self, table: _Table) -> list[dict]:
        """
        Turn the table's text lines into rows.
        A line whose first cell is left-aligned with the part-number header
        starts a new row; any other line continues the previous row (wrapped
        cells — a wrapped description can start close to the first column).
        """
        rows: list[dict] = []
        first_col = table.columns[0]

        for line in table.lines:
            line.sort(key=lambda s: s.x0)
            prices = [s for s in line if s.font.startswith(FONT_PRICE)]
            cells  = [s for s in line if not s.font.startswith(FONT_PRICE)]

            starts_row = bool(cells) and abs(cells[0].x0 - first_col.x0) <= SKU_ALIGN_TOL
            if starts_row:
                row = {"sku": cells[0].text, "y": cells[0].yc, "cells": {}, "price": ""}
                rows.append(row)
                rest = cells[1:]
            elif rows:
                row = rows[-1]
                rest = cells
            else:
                continue

            for s in rest:
                col_i = self._column_for(s, table.columns[1:-1]) + 1
                row["cells"].setdefault(col_i, []).append(s.text)
            for p in prices:
                row["price"] = row["price"] or p.text
        return rows

    @staticmethod
    def _column_for(s: _Span, columns: list[_Column]) -> int:
        """Index of the middle column that best overlaps the span."""
        if not columns:
            return 0
        best_i, best_score = 0, None
        for i, c in enumerate(columns):
            overlap = min(s.x1, c.x1 + 4) - max(s.x0, c.x0 - 4)
            score = (overlap, -abs(s.xc - c.xc))
            if best_score is None or score > best_score:
                best_i, best_score = i, score
        return best_i

    def _row_to_product(
        self, row: dict, table: _Table, title: str, category: str, page_num: int
    ) -> Optional[Product]:
        raw_sku = row["sku"]
        markers = set(SKU_MARKERS_RE.findall(raw_sku))
        raw_sku = SKU_MARKERS_RE.sub("", raw_sku)
        qualifiers = SKU_QUALIFIER_RE.findall(raw_sku)
        raw_sku = SKU_QUALIFIER_RE.sub("", raw_sku).strip()
        if not SKU_RE.match(raw_sku):
            return None
        sku = self._normalize_sku(raw_sku)

        brand, product_line = self._split_brand(title)

        attrs: list[str] = [q.strip() for q in qualifiers if q.strip()]
        notes: list[str] = []
        prev_label = None
        for col_i in sorted(row["cells"]):
            label = table.columns[col_i].label
            value = self._clean_text(" ".join(row["cells"][col_i]))
            if not value:
                continue
            key = label.lower()
            if col_i in (0, len(table.columns) - 1):
                # Only happens in "Part Number | List" tables: plain text cell
                attrs.append(value)
            elif key in QTY_LABELS:
                notes.append(f"{label}: {value}")
            elif key in MODEL_LABELS:
                notes.append(f"Model: {value}")
            elif key in BARE_VALUE_LABELS:
                attrs.append(value)
            elif label == prev_label and attrs:
                # Repeated labels ("End", "End") describe both sides of the part
                attrs[-1] += f" x {value}"
            else:
                attrs.append(f"{self._clean_text(label)} {value}")
            prev_label = label
        for marker in sorted(markers):
            notes.append(f"See supplier footnote ({marker})")

        description = product_line
        if attrs:
            description = f"{product_line} — {', '.join(attrs)}" if product_line else ", ".join(attrs)

        price = 0.0
        m = PRICE_RE.search(row["price"])
        if m:
            price = self._parse_price(m.group())

        if price <= 0:
            log.warning(
                f"[SKIPPED] page {page_num + 1} SKU={sku} desc='{description[:40]}' "
                f"— no published price"
            )
            self._skipped_products.append({
                "page": page_num + 1, "sku": sku, "desc": description,
                "price_raw": row["price"], "reason": "no published price",
            })
            return None

        product = Product(
            sku=sku,
            brand=brand,
            description=description,
            price_original=price,
            category=category,
            page_num=page_num,
            notes=" · ".join(notes),
        )
        product.row_y = row["y"]
        return product

    # ─── Text helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_category(title: str, page_tabs: set[str], current_idx: int) -> int:
        """
        Pick the category for a family title.
        Only the tabs highlighted on this page are candidates. The title's
        keywords decide between them (the most specific / later tab wins,
        e.g. "Faucet Installation Wrench" → Tools); otherwise the previous
        family's category carries over while it is still highlighted.
        """
        candidates = [i for i, name in enumerate(CATEGORY_ORDER) if name in page_tabs]
        if not candidates:
            return current_idx
        lowered = title.lower()
        matches = [i for i in candidates if re.search(CATEGORY_KEYWORDS[CATEGORY_ORDER[i]], lowered)]
        if matches:
            return max(matches)
        if current_idx in candidates:
            return current_idx
        ahead = [i for i in candidates if i > current_idx]
        return ahead[0] if ahead else candidates[0]

    @staticmethod
    def _split_brand(title: str) -> tuple[str, str]:
        """'John Guest Check Valves' → ('John Guest', 'Check Valves')."""
        for prefix, brand in KNOWN_BRANDS:
            if title.lower().startswith(prefix.lower()):
                rest = title[len(prefix):].lstrip(" -–/®™")
                return brand, rest or title
        return "", title

    @staticmethod
    def _clean_text(text: str) -> str:
        # Marks are often glued to the next word ("Slim Line®Housings");
        # U+FFFD is a ® whose glyph has no Unicode mapping in the PDF.
        text = re.sub(r"[®™�]", " ", text)
        text = text.replace("”", '"').replace("“", '"').replace("’", "'")
        text = re.sub(r"\s+", " ", text).strip()
        # "Big Blue® /Big Clear" → "Big Blue/Big Clear" (keeps "SeaTech / AquaLock")
        return re.sub(r"(?<=\w) /(?=\w)", "/", text)

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return slug[:60]

    def __del__(self):
        self._close_doc()   # fallback: close if context manager was not used
