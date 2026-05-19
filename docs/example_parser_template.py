"""
Template parser for the Catalog Manager.

This file is a starting point for adding support for a new supplier's PDF
price list. It is NOT loaded by the application — it lives in docs/ as
reference material only.

To create a real parser:
    1. Copy this file to:  app/parsers/<your_supplier>_parser.py
    2. Rename the class:   <YourSupplier>Parser
    3. Replace SUPPLIER_NAME and DETECTION_KEYWORDS
    4. Adjust column x-coordinates in the COL_* constants
    5. Register the parser in app/parsers/parser_factory.py
    6. Drop a real PDF in the Import tab and watch the logs

For a full walkthrough see  docs/ADDING_A_PARSER.md.
For a complete reference implementation see  app/parsers/mayoristas_i_parser.py.
"""
from __future__ import annotations
import re

import fitz  # PyMuPDF

from app.models.product import Product, ProductImage, ProcessingSession
from app.parsers.base_parser import BaseParser
from app.logging_config.logger import get_logger

log = get_logger("example_parser")


# ─── 1. Detection rules ──────────────────────────────────────────────────────
#
# How the ParserFactory finds your parser:
#   When the user imports a PDF, the factory reads page 1 of the file and
#   matches its text against every registered parser's DETECTION_KEYWORDS.
#   The first parser whose keywords appear wins.
#
# Choose keywords that are:
#   - Reliably present on page 1 of EVERY catalog from this supplier
#   - Unique enough that they won't accidentally match another supplier
#
# Good candidates: company name, a column-header phrase, a footer line.

class ExampleSupplierParser(BaseParser):
    """Parser for the fictional "Example Supplier" wholesale catalogs."""

    SUPPLIER_NAME: str = "Example Supplier"

    DETECTION_KEYWORDS: list[str] = [
        "Example Supplier S.A.",
        "WHOLESALE PRICE LIST",
        "Cat. N°",
    ]

    # Optional regex patterns (use them when keyword matching is too fuzzy).
    DETECTION_PATTERNS: list[str] = [
        r"Example\s+Supplier",
        r"Catalog\s+#\d{4}",
    ]

    # ─── 2. Column x-coordinates ─────────────────────────────────────────────
    #
    # All extraction works by reading the PDF as a stream of word tuples
    # (x0, y0, x1, y1, text) and filtering them by x-coordinate.
    # You MUST find the x-range of each column in your supplier's PDF.
    #
    # DISCOVERY SNIPPET — run this against page 1 of a real PDF and inspect
    # the printed (x, y, text) tuples to identify column boundaries:
    #
    #     import fitz
    #     doc = fitz.open("supplier_sample.pdf")
    #     for w in doc[0].get_text("words")[:80]:
    #         print(f"x={w[0]:6.1f}  y={w[1]:6.1f}  text={w[4]!r}")
    #
    # Replace the placeholders below with the ranges you observe.
    COL_SKU_MIN_X:   float =  30.0
    COL_SKU_MAX_X:   float = 100.0
    COL_BRAND_MIN_X: float = 100.0
    COL_BRAND_MAX_X: float = 220.0
    COL_DESC_MIN_X:  float = 220.0
    COL_DESC_MAX_X:  float = 480.0
    COL_PRICE_MIN_X: float = 480.0

    # SKU validation: regex that defines what counts as a valid SKU for this
    # supplier. Anything that doesn't match is treated as a non-product line
    # (category header, page footer, etc.) and skipped.
    SKU_RE = re.compile(r"^[A-Z]{2,4}\d{2,6}$")     # e.g. ABC1234

    # ─── 3. Required: validate_pdf ───────────────────────────────────────────

    def validate_pdf(self) -> tuple[bool, str]:
        """
        Quick sanity check before parsing.
        Return (True, "") if the PDF is readable and looks like the right format.
        Return (False, reason) otherwise — the UI shows `reason` to the user.
        """
        try:
            doc = fitz.open(str(self.pdf_path))
            try:
                if doc.page_count == 0:
                    return False, "The PDF is empty."

                page0_text = doc[0].get_text("text")
                if not any(kw in page0_text for kw in self.DETECTION_KEYWORDS):
                    return False, (
                        f"Expected keywords not found — this PDF may not be "
                        f"a {self.SUPPLIER_NAME} catalog."
                    )

                return True, ""
            finally:
                doc.close()
        except Exception as e:
            return False, f"Error opening PDF: {e}"

    # ─── 4. Required: detect_layout ──────────────────────────────────────────

    def detect_layout(self) -> dict:
        """
        Return a dict describing the PDF's structure. The result is logged
        for diagnostics — it is not consumed by other layers. Return whatever
        metadata is useful for debugging future parsing issues.
        """
        with fitz.open(str(self.pdf_path)) as doc:
            return {
                "supplier":   self.SUPPLIER_NAME,
                "pages":      doc.page_count,
                "columns":    ["SKU", "Brand", "Description", "Price"],
                "has_images": True,    # TODO: detect from the PDF itself
            }

    # ─── 5. Required: extract_products ───────────────────────────────────────

    def extract_products(self, session: ProcessingSession) -> list[Product]:
        """
        Main extraction loop: iterate pages, identify product rows,
        return a list of Product objects. Update session counters as you go.
        """
        doc = self._open_doc()
        session.total_pages = doc.page_count
        products: list[Product] = []

        for page_num in range(doc.page_count):
            try:
                page_products = self._parse_page(doc[page_num], page_num)
                products.extend(page_products)
            except Exception as e:
                log.warning(f"Page {page_num + 1} failed: {e}")
                session.warnings.append(f"Page {page_num + 1}: {e}")
            session.pages_processed += 1

        return products

    def _parse_page(self, page, page_num: int) -> list[Product]:
        """
        Parse a single page: extract words → group into rows by y-coord →
        split each row into columns by x-coord → emit Product objects.
        """
        words = page.get_text("words")
        if not words:
            return []

        # Step 1 — group words into rows by their y-coordinate.
        # Words within Y_TOLERANCE pixels vertically belong to the same row.
        Y_TOLERANCE = 3.0   # tune for your PDF's line spacing
        rows: dict[int, list] = {}
        for w in words:
            _, y0, _, _, _ = w
            bucket = round(y0 / Y_TOLERANCE)
            rows.setdefault(bucket, []).append(w)

        # Step 2 — process each row top-to-bottom.
        products: list[Product] = []
        for bucket in sorted(rows.keys()):
            product = self._try_extract_product(rows[bucket], page_num)
            if product:
                products.append(product)
        return products

    def _try_extract_product(self, row_words: list, page_num: int):
        """
        Filter words by column x-ranges, normalize, build a Product.
        Returns None if the row doesn't look like a real product line.
        """
        sku_words   = [w for w in row_words if self.COL_SKU_MIN_X   <= w[0] < self.COL_SKU_MAX_X]
        brand_words = [w for w in row_words if self.COL_BRAND_MIN_X <= w[0] < self.COL_BRAND_MAX_X]
        desc_words  = [w for w in row_words if self.COL_DESC_MIN_X  <= w[0] < self.COL_DESC_MAX_X]
        price_words = [w for w in row_words if w[0] >= self.COL_PRICE_MIN_X]

        if not sku_words or not price_words:
            return None

        sku        = self._normalize_sku(" ".join(w[4] for w in sku_words))
        brand_text = self._normalize_text(" ".join(w[4] for w in brand_words))
        desc_text  = self._normalize_text(" ".join(w[4] for w in desc_words))
        price      = self._parse_price(" ".join(w[4] for w in price_words))

        # Skip rows whose SKU doesn't match the supplier's pattern (these are
        # usually category headers, page numbers, or other non-product lines).
        if not self.SKU_RE.match(sku):
            return None

        if price <= 0:
            log.debug(f"page {page_num + 1}: skipping SKU {sku!r} — no price")
            return None

        return Product(
            sku=sku,
            brand=brand_text,        # honest: empty when not in the source PDF
            description=desc_text,
            price_original=price,
            category="",             # TODO: extract category from section headers
            page_num=page_num,
        )

    # ─── 6. Required: extract_images ─────────────────────────────────────────

    def extract_images(self, session: ProcessingSession) -> list[ProductImage]:
        """
        Find every image in the PDF and try to associate it with a product
        SKU by comparing the image's bounding box against product row
        coordinates.

        Image extraction is the most complex part to implement well.
        For an initial parser, returning an empty list is perfectly fine —
        products will simply have no images and the rest of the app handles
        that gracefully (the dashboard will surface them via the "No image"
        health check).

        For a full reference implementation see the `_extract_image_with_bbox`
        and related methods in app/parsers/mayoristas_i_parser.py.
        """
        session.images_found   = 0
        session.images_matched = 0
        return []

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _open_doc(self) -> fitz.Document:
        """Open the PDF document. Cached so we don't pay the open cost twice."""
        if not hasattr(self, "_doc") or self._doc is None:
            self._doc = fitz.open(str(self.pdf_path))
        return self._doc

    def _close_doc(self):
        """Called by ProductService.import_pdf() to release the file handle."""
        if getattr(self, "_doc", None) is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None


# ─── 7. Register the parser ──────────────────────────────────────────────────
#
# Once your parser file is in app/parsers/, open app/parsers/parser_factory.py
# and add an import and a registry entry:
#
#     from app.parsers.example_supplier_parser import ExampleSupplierParser
#
#     REGISTERED_PARSERS: list[Type[BaseParser]] = [
#         MayoristasIParser,
#         ExampleSupplierParser,    # ← add here
#     ]
#
# That's it. The factory will auto-detect your parser when the user imports
# a matching PDF through the Import tab.
