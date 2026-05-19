"""
Core data models using dataclasses + Pydantic for validation.
"""
from __future__ import annotations
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from pathlib import Path

# Accepts empty suffix, '.XX', or ',XX' (Argentine comma decimal). Compiled once.
SUFFIX_PATTERN = re.compile(r"^[.,]\d{1,2}$")


@dataclass
class ProductImage:
    """Represents an extracted product image."""
    sku: str
    file_path: Path
    page_num: int
    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1 in PDF pts
    width_px: int = 0
    height_px: int = 0
    confidence: float = 1.0  # association confidence (0-1)

    @property
    def exists(self) -> bool:
        return self.file_path.exists()


@dataclass
class Product:
    """Core product model extracted from supplier PDF."""
    sku: str
    brand: str
    description: str
    price_original: float
    category: str

    # Computed / overrideable
    price_final: float = 0.0
    margin_pct: float = 0.0
    iva_pct: float = 0.0
    round_to_nearest: int = 0
    price_suffix: str = ""

    # Status & persistence
    active: bool = True
    discontinued: bool = False
    notes: str = ""

    # Image
    image_path: Optional[Path] = None
    image_confidence: float = 0.0

    # Metadata
    page_num: int = 0
    row_index: int = 0   # pixel y-center of the product row (used for image association)
    row_y: float = 0.0   # PDF y-coordinate of the product row
    processing_id: str = ""
    last_seen: Optional[datetime] = None
    first_seen: Optional[datetime] = None

    def __post_init__(self):
        if self.first_seen is None:
            self.first_seen = datetime.now()
        self.last_seen = datetime.now()
        if self.price_final == 0.0 and self.price_original > 0:
            self.price_final = self.price_original

    def apply_margin(self, margin_pct: float, iva_pct: float = 0.0,
                     round_to: int = 0, suffix: str = "") -> float:
        """
        Compute and set price_final.
        Order: base x margin x IVA -> round_to (ceil) -> suffix appended.
        suffix must match SUFFIX_PATTERN (e.g. '.99', ',99'); anything else is ignored.
        For computation the suffix is normalised to use a dot internally.
        """
        price = self.price_original * (1 + margin_pct / 100)
        if iva_pct > 0:
            price *= (1 + iva_pct / 100)
        if round_to > 0:
            price = math.ceil(price / round_to) * round_to
        valid_suffix = suffix if (suffix and SUFFIX_PATTERN.match(suffix)) else ""
        if valid_suffix:
            # Normalise comma → dot for float() parsing; store the original suffix verbatim
            dot_suffix = valid_suffix.replace(",", ".")
            price = float(f"{int(price)}{dot_suffix}")
        self.price_final = round(price, 2)
        self.margin_pct = margin_pct
        self.iva_pct = iva_pct
        self.round_to_nearest = round_to
        self.price_suffix = valid_suffix
        return self.price_final


@dataclass
class ProcessingSession:
    """Tracks a single PDF processing run."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    pdf_path: str = ""
    supplier_name: str = ""
    parser_name: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    total_pages: int = 0
    products_found: int = 0
    images_found: int = 0
    images_matched: int = 0
    images_unmatched: int = 0

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()

    def complete(self):
        self.completed_at = datetime.now()


@dataclass
class MarginConfig:
    """Reusable margin / pricing configuration."""
    margin_pct: float = 30.0
    iva_pct: float = 0.0
    round_to_nearest: int = 0
    price_suffix: str = ""
    label: str = "Default"
