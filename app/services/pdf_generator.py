"""
PDF Generator v2: catálogo comercial profesional con ReportLab.
Cambios vs v1:
  - Imagen centrada en la tarjeta mediante Table anidado (ALIGN CENTER)
  - Cabeceras de categoría NUNCA quedan solas al final de página (KeepTogether)
  - Layout responsivo: card_width se calcula según products_per_row
  - Estilos de párrafo pre-instanciados para mejor rendimiento
  - PlaceholderBox como clase de módulo (no nested) → evita AttributeError _canv
"""
from __future__ import annotations
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, HRFlowable, KeepTogether, CondPageBreak,
)
from reportlab.platypus.flowables import Flowable
from reportlab.pdfgen.canvas import Canvas

from app.config.settings import settings
from app.logging_config.logger import get_logger

log = get_logger("pdf_generator")

# ── Colores ───────────────────────────────────────────────────────────────────
RED   = colors.HexColor("#C0392B")
DARK  = colors.HexColor("#2C3E50")
GREY  = colors.HexColor("#7F8C8D")
LIGHT = colors.HexColor("#ECF0F1")
WHITE = colors.white
BLACK = colors.black

PAGE_W, PAGE_H = A4
MARGIN      = 15 * mm
HEADER_H    = 10 * mm
FOOTER_H    = 8  * mm
USABLE_W    = PAGE_W - 2 * MARGIN   # ancho utilizable para contenido
CAT_MIN_HEIGHT = 55 * mm            # altura mínima para no "orphanear" una categoría


# ── Flowables personalizados ──────────────────────────────────────────────────

class PlaceholderBox(Flowable):
    """Cuadro gris cuando no hay imagen de producto."""

    def __init__(self, size: float):
        super().__init__()
        self._sz = size

    def wrap(self, aW, aH):
        return self._sz, self._sz

    def draw(self):                    # ReportLab asigna self.canv antes de llamar draw()
        c = self.canv
        c.saveState()
        c.setFillColor(LIGHT)
        c.setStrokeColor(GREY)
        c.setLineWidth(0.5)
        c.rect(0, 0, self._sz, self._sz, fill=1, stroke=1)
        c.setFillColor(GREY)
        c.setFont("Helvetica", 7)
        c.drawCentredString(self._sz / 2, self._sz / 2 - 3, "Sin imagen")
        c.restoreState()


class CategoryDivider(Flowable):
    """Barra roja de categoría a ancho completo."""

    def __init__(self, text: str, primary_color=None, width: float = USABLE_W):
        super().__init__()
        self.text          = text
        self.primary_color = primary_color or RED
        self._w            = width
        self._h            = 11 * mm

    def wrap(self, aW, aH):
        return self._w, self._h

    def draw(self):                    # self.canv ← asignado por ReportLab
        c = self.canv
        c.saveState()
        c.setFillColor(self.primary_color)
        c.roundRect(0, 0, self._w, self._h, 3 * mm, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(7 * mm, 3.5 * mm, self.text.upper())
        c.restoreState()


class PageNumCanvas(Canvas):
    """Canvas que dibuja encabezado y pie en todas las páginas."""

    def __init__(self, *args, company_name="", primary_color=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company_name  = company_name
        self.primary_color = primary_color or RED
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_frame(self._pageNumber, total)
            super().showPage()
        super().save()

    def _draw_frame(self, page_num: int, total: int):
        self.saveState()
        # Encabezado
        self.setFillColor(self.primary_color)
        self.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, fill=1, stroke=0)
        self.setFillColor(WHITE)
        self.setFont("Helvetica-Bold", 9)
        self.drawString(MARGIN, PAGE_H - 6.5 * mm, self.company_name.upper())
        self.setFont("Helvetica", 8)
        self.drawRightString(
            PAGE_W - MARGIN, PAGE_H - 6.5 * mm,
            f"Lista de Precios — {datetime.now().strftime('%d/%m/%Y')}"
        )
        # Pie
        self.setFillColor(colors.HexColor("#2C3E50"))
        self.rect(0, 0, PAGE_W, FOOTER_H, fill=1, stroke=0)
        self.setFillColor(WHITE)
        self.setFont("Helvetica", 8)
        self.drawCentredString(PAGE_W / 2, 2.5 * mm, f"Página {page_num} de {total}")
        self.restoreState()


# ── Generador principal ───────────────────────────────────────────────────────

class PDFGenerator:

    def __init__(
        self,
        output_dir: Path,
        company_name: str    = "Mi Empresa",
        company_slogan: str  = "Catálogo de Productos",
        primary_color: str   = "#C0392B",
        secondary_color: str = "#2C3E50",
        products_per_row: int = 2,
    ):
        self.output_dir       = output_dir
        self.company_name     = company_name
        self.company_slogan   = company_slogan
        self.primary_color    = colors.HexColor(primary_color)
        self.secondary_color  = colors.HexColor(secondary_color)
        self.products_per_row = max(1, min(3, products_per_row))
        self._init_styles()

    def _init_styles(self):
        """Pre-instancia estilos de párrafo para reutilización."""
        self._style_sku = ParagraphStyle(
            "SKU", fontName="Helvetica-Bold", fontSize=7,
            textColor=GREY, alignment=TA_CENTER, leading=10,
        )
        self._style_desc = ParagraphStyle(
            "Desc", fontName="Helvetica", fontSize=8.5,
            textColor=DARK, alignment=TA_CENTER, leading=12, wordWrap="CJK",
        )
        self._style_price = ParagraphStyle(
            "Price", fontName="Helvetica-Bold", fontSize=13,
            textColor=self.primary_color, alignment=TA_CENTER, leading=16,
        )
        self._style_cover_title = ParagraphStyle(
            "CoverTitle", fontName="Helvetica-Bold", fontSize=36,
            textColor=self.primary_color, alignment=TA_CENTER, leading=44,
        )
        self._style_slogan = ParagraphStyle(
            "Slogan", fontName="Helvetica", fontSize=16,
            textColor=self.secondary_color, alignment=TA_CENTER, leading=22,
        )
        self._style_meta = ParagraphStyle(
            "Meta", fontName="Helvetica", fontSize=12,
            textColor=GREY, alignment=TA_CENTER, leading=18,
        )
        self._style_disc = ParagraphStyle(
            "Disc", fontName="Helvetica-Oblique", fontSize=9,
            textColor=GREY, alignment=TA_CENTER, leading=14,
        )

    # ── API pública ───────────────────────────────────────────────────────────

    def generate(self, products: list[dict], filename: Optional[str] = None) -> Path:
        active = [p for p in products if p.get("active")]
        if not active:
            raise ValueError("No hay productos activos para generar el catálogo.")

        fname    = filename or f"catalogo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        out_path = self.output_dir / fname

        def canvas_factory(*args, **kwargs):
            return PageNumCanvas(
                *args,
                company_name=self.company_name,
                primary_color=self.primary_color,
                **kwargs,
            )

        doc = SimpleDocTemplate(
            str(out_path), pagesize=A4,
            topMargin=HEADER_H + 5 * mm,
            bottomMargin=FOOTER_H + 5 * mm,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
        )

        story = []
        story += self._build_cover(len(active))
        story.append(PageBreak())
        story += self._build_catalog(active)

        log.info(f"Generando PDF: {len(active)} productos activos...")
        doc.build(story, canvasmaker=canvas_factory)
        log.info(f"PDF guardado: {out_path}")
        return out_path

    # ── Portada ───────────────────────────────────────────────────────────────

    def _build_cover(self, count: int) -> list:
        story = [
            Spacer(1, 55 * mm),
            Paragraph(self.company_name.upper(), self._style_cover_title),
            Spacer(1, 6 * mm),
            Paragraph(self.company_slogan, self._style_slogan),
            Spacer(1, 10 * mm),
            HRFlowable(width="60%", thickness=3, color=self.primary_color, hAlign="CENTER"),
            Spacer(1, 10 * mm),
            Paragraph(f"Fecha: {datetime.now().strftime('%d de %B de %Y')}", self._style_meta),
            Spacer(1, 4 * mm),
            Paragraph(f"{count} productos disponibles", self._style_meta),
            Spacer(1, 20 * mm),
            Paragraph(
                "Los precios pueden sufrir modificaciones sin previo aviso.<br/>"
                "Consulte disponibilidad de stock antes de realizar su pedido.",
                self._style_disc,
            ),
        ]
        return story

    # ── Catálogo ──────────────────────────────────────────────────────────────

    def _build_catalog(self, products: list[dict]) -> list:
        """
        Construye el cuerpo del catálogo agrupado por categoría.
        Garantiza que el divider de categoría NUNCA quede solo al final de página:
        envuelve [divider + primera fila de productos] en KeepTogether.
        """
        # Calcular dimensiones de tarjeta según columnas
        col_gap   = 4 * mm
        card_w    = (USABLE_W - col_gap * (self.products_per_row - 1)) / self.products_per_row
        n         = self.products_per_row

        # Agrupar por categoría
        categories: dict[str, list[dict]] = {}
        for p in products:
            cat = (p.get("category") or "General").strip()
            categories.setdefault(cat, []).append(p)

        story = []

        for cat_name, cat_prods in categories.items():
            story.append(Spacer(1, 4 * mm))

            divider = CategoryDivider(cat_name, self.primary_color, width=USABLE_W)
            chunks  = self._chunk(cat_prods, n)

            # Pad último chunk
            last = chunks[-1]
            while len(last) < n:
                last.append(None)

            first_row_table = self._build_row_table(chunks[0], card_w, col_gap)

            # Divider + primera fila → KeepTogether (nunca orphan)
            story.append(KeepTogether([
                divider,
                Spacer(1, 3 * mm),
                first_row_table,
                Spacer(1, 3 * mm),
            ]))

            # Filas restantes normales
            for chunk in chunks[1:]:
                story.append(self._build_row_table(chunk, card_w, col_gap))
                story.append(Spacer(1, 3 * mm))

        return story

    def _build_row_table(
        self,
        products: list[Optional[dict]],
        card_w: float,
        col_gap: float,
    ) -> Table:
        """
        Construye una tabla de 1 fila × N columnas.
        Cada celda contiene una tarjeta de producto (tabla anidada 1 col × M filas).
        """
        cells = [self._build_product_card(p, card_w) for p in products]

        col_widths = [card_w] * len(cells)
        t = Table([cells], colWidths=col_widths)
        t.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), col_gap / 2),
            ("RIGHTPADDING",  (0, 0), (-1, -1), col_gap / 2),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            # Separadores verticales suaves entre columnas
            ("LINEAFTER",  (0, 0), (-2, -1), 0.4, LIGHT),
            ("LINEBELOW",  (0, 0), (-1, -1), 0.4, LIGHT),
        ]))
        return t

    def _build_product_card(
        self,
        product: Optional[dict],
        card_w: float,
    ) -> Table:
        """
        Tarjeta de producto: tabla 1 col × N filas.
        ALIGN=CENTER en el TableStyle centra la imagen y los párrafos.
        """
        if not product:
            return Table([[Spacer(1, 1)]], colWidths=[card_w])

        img_size = min(36 * mm, card_w - 10 * mm)

        # Imagen — resolve relative paths stored in DB
        img_path_raw = product.get("image_path")
        img_path = str(settings.resolve_path(img_path_raw)) if img_path_raw else None
        if img_path and Path(img_path).exists():
            try:
                img_f = RLImage(img_path, width=img_size, height=img_size)
            except Exception:
                img_f = PlaceholderBox(img_size)
        else:
            img_f = PlaceholderBox(img_size)

        # Textos
        sku   = product.get("sku", "")
        brand = (product.get("brand") or "").strip()
        desc  = (product.get("description") or "")
        if len(desc) > 80:
            desc = desc[:77] + "…"
        price = product.get("price_final", 0.0) or 0.0
        # Formato argentino: punto miles, coma decimal
        price_str = f"$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        # SKU line: include brand only when present. Empty brand = just SKU
        # (no trailing "·" separator). Keeps the catalog tidy when the
        # supplier didn't specify a brand for a product.
        sku_line = f"{sku}  ·  {brand}" if brand else sku

        data = [
            [img_f],
            [Spacer(1, 2 * mm)],
            [Paragraph(sku_line, self._style_sku)],
            [Spacer(1, 1.5 * mm)],
            [Paragraph(desc, self._style_desc)],
            [Spacer(1, 2.5 * mm)],
            [Paragraph(price_str, self._style_price)],
            [Spacer(1, 3 * mm)],
        ]

        inner = Table(data, colWidths=[card_w - 6 * mm])
        inner.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return inner

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def _chunk(lst: list, n: int) -> list[list]:
        return [lst[i: i + n] for i in range(0, len(lst), n)]
