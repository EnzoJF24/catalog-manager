"""
Abstract base parser — all supplier parsers must implement this interface.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.models.product import Product, ProductImage, ProcessingSession
from app.logging_config.logger import get_logger

log = get_logger("base_parser")


class BaseParser(ABC):
    """
    Abstract base class for all supplier PDF parsers.

    Each concrete parser must:
    - Implement extract_products()
    - Implement extract_images()
    - Implement detect_layout()
    - Implement validate_pdf()
    - Expose SUPPLIER_NAME and DETECTION_KEYWORDS class attributes
    """

    SUPPLIER_NAME: str = "Unknown"
    DETECTION_KEYWORDS: list[str] = []      # Keywords to auto-detect this parser
    DETECTION_PATTERNS: list[str] = []      # Regex patterns for detection

    def __init__(self, pdf_path: Path, output_dir: Path):
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session: Optional[ProcessingSession] = None
        self._products: list[Product] = []
        self._images: list[ProductImage] = []
        log.info(f"{self.__class__.__name__} initialized for {pdf_path.name}")

    # ─── Abstract interface ───────────────────────────────────────────────────

    @abstractmethod
    def validate_pdf(self) -> tuple[bool, str]:
        """
        Validate the PDF is readable and matches expected format.
        Returns: (is_valid, message)
        """
        ...

    @abstractmethod
    def detect_layout(self) -> dict:
        """
        Analyze the PDF layout and return structural info.
        Returns dict with keys like: columns, has_images, category_style, etc.
        """
        ...

    @abstractmethod
    def extract_products(self, session: ProcessingSession) -> list[Product]:
        """
        Main extraction method. Parse all pages and return Product list.
        Must update session counters as it goes.
        """
        ...

    @abstractmethod
    def extract_images(self, session: ProcessingSession) -> list[ProductImage]:
        """
        Extract all product images from the PDF.
        Must attempt to associate each image with a product SKU.
        """
        ...

    # ─── Concrete helpers ─────────────────────────────────────────────────────

    def run(self, session: ProcessingSession) -> tuple[list[Product], list[ProductImage]]:
        """
        Full pipeline: validate → detect → extract products → extract images.
        Safe wrapper with error handling.
        """
        self.session = session
        log.info(f"Starting parse: {self.SUPPLIER_NAME} | {self.pdf_path.name}")

        valid, msg = self.validate_pdf()
        if not valid:
            session.errors.append(f"Validation failed: {msg}")
            log.error(f"PDF validation failed: {msg}")
            return [], []

        try:
            layout = self.detect_layout()
            log.debug(f"Layout detected: {layout}")
        except Exception as e:
            log.warning(f"Layout detection failed (non-fatal): {e}")

        try:
            products = self.extract_products(session)
            self._products = products
            session.products_found = len(products)
            log.info(f"Extracted {len(products)} products")
        except Exception as e:
            log.exception(f"Product extraction failed: {e}")
            session.errors.append(f"Product extraction error: {e}")
            products = []

        try:
            images = self.extract_images(session)
            self._images = images
            log.info(
                f"Extracted {session.images_found} images, "
                f"matched {session.images_matched}"
            )
        except Exception as e:
            log.exception(f"Image extraction failed: {e}")
            session.warnings.append(f"Image extraction error: {e}")
            images = []

        return products, images

    @staticmethod
    def _parse_price(text: str) -> float:
        """
        Parse Argentine-style price strings like '$ 1.484,90' → 1484.90
        Also handles '1484.90', '1,484.90' (US style), etc.
        """
        import re
        text = text.strip().replace("$", "").replace(" ", "")
        # Detect Argentine format: dots as thousands, comma as decimal
        # e.g. 1.484,90 → 1484.90
        if re.search(r"\d\.\d{3},\d{2}$", text) or re.search(r"^\d{1,3}(\.\d{3})+,\d{2}$", text):
            text = text.replace(".", "").replace(",", ".")
        else:
            # US format or simple: remove commas as thousands sep
            text = text.replace(",", "")
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _normalize_sku(sku: str) -> str:
        return sku.strip().upper()

    @staticmethod
    def _normalize_text(text: str) -> str:
        import re
        return re.sub(r"\s+", " ", text).strip()
