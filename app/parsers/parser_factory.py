"""
ParserFactory: auto-detects the correct parser for a given PDF.
To add a new supplier, import its parser class and add it to REGISTERED_PARSERS.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Type

import fitz

from app.parsers.base_parser import BaseParser
from app.parsers.mayoristas_i_parser import MayoristasIParser
from app.parsers.ga_murdock_parser import GAMurdockParser
from app.logging_config.logger import get_logger

log = get_logger("parser_factory")


# ─── Registry: add new parsers here ──────────────────────────────────────────
REGISTERED_PARSERS: list[Type[BaseParser]] = [
    MayoristasIParser,
    GAMurdockParser,
    # Future: ProviderBParser, ProviderCParser, ...
]


class ParserFactory:
    """
    Attempts to detect the correct parser by scanning the PDF for known keywords/patterns.
    Falls back to the first registered parser on failure.
    """

    @classmethod
    def detect(cls, pdf_path: Path) -> Optional[Type[BaseParser]]:
        """
        Returns the best-matching parser class for the given PDF.
        Returns None if no match found.
        """
        log.info(f"Detecting parser for: {pdf_path.name}")
        sample_text = cls._extract_sample_text(pdf_path)

        if not sample_text:
            log.warning("Could not extract sample text for detection")
            return None

        scores: dict[Type[BaseParser], int] = {}

        for parser_cls in REGISTERED_PARSERS:
            score = 0

            # Keyword matching
            for kw in parser_cls.DETECTION_KEYWORDS:
                if kw in sample_text:
                    score += 2
                    log.debug(f"  [{parser_cls.SUPPLIER_NAME}] keyword hit: '{kw}'")

            # Pattern matching
            for pattern in parser_cls.DETECTION_PATTERNS:
                if re.search(pattern, sample_text, re.IGNORECASE):
                    score += 3
                    log.debug(f"  [{parser_cls.SUPPLIER_NAME}] pattern hit: '{pattern}'")

            scores[parser_cls] = score
            log.debug(f"  [{parser_cls.SUPPLIER_NAME}] total score: {score}")

        if not scores:
            return None

        best_cls = max(scores, key=lambda k: scores[k])
        best_score = scores[best_cls]

        if best_score == 0:
            supported = ", ".join(p.SUPPLIER_NAME for p in REGISTERED_PARSERS)
            log.warning(
                f"No parser matched this PDF. "
                f"Supported suppliers: {supported}"
            )
            return None

        log.info(f"Detected parser: {best_cls.SUPPLIER_NAME} (score={best_score})")
        return best_cls

    @classmethod
    def create(
        cls,
        pdf_path: Path,
        output_dir: Path,
        force_parser: Optional[str] = None,
    ) -> Optional[BaseParser]:
        """
        Create and return a parser instance.
        Optionally force a specific parser by SUPPLIER_NAME.
        """
        if force_parser:
            for parser_cls in REGISTERED_PARSERS:
                if parser_cls.SUPPLIER_NAME.lower() == force_parser.lower():
                    log.info(f"Using forced parser: {parser_cls.SUPPLIER_NAME}")
                    return parser_cls(pdf_path, output_dir)
            log.warning(f"Force parser '{force_parser}' not found, falling back to auto-detect")

        detected = cls.detect(pdf_path)
        if detected:
            return detected(pdf_path, output_dir)

        log.error("No parser available for this PDF")
        return None

    @classmethod
    def list_parsers(cls) -> list[dict]:
        """Return info about all registered parsers."""
        return [
            {
                "name": p.SUPPLIER_NAME,
                "class": p.__name__,
                "keywords": p.DETECTION_KEYWORDS,
            }
            for p in REGISTERED_PARSERS
        ]

    @staticmethod
    def _extract_sample_text(pdf_path: Path, pages: int = 3) -> str:
        """Extract text from the first N pages for detection."""
        try:
            doc = fitz.open(str(pdf_path))
            text_parts = []
            for i in range(min(pages, doc.page_count)):
                text_parts.append(doc[i].get_text("text"))
            doc.close()
            return "\n".join(text_parts)
        except Exception as e:
            log.error(f"Sample text extraction failed: {e}")
            return ""
