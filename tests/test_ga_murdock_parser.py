"""
Tests for the G.A. Murdock list-price parser.

Unit tests build synthetic text spans, so they run without the supplier PDF.
The integration test runs against the real catalog when it is present at the
repo root (PDFs are git-ignored) and is skipped otherwise.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
import shutil

from app.models.product import ProcessingSession
from app.parsers.parser_factory import ParserFactory
from app.parsers.ga_murdock_parser import (
    GAMurdockParser, _Span, _Family,
    FONT_HEADER, FONT_CELL, FONT_PRICE, FONT_TITLE, WHITE,
)

SAMPLE_PDF = Path(__file__).parent.parent / "GAMurdock-Catalog-ListPriceOnly.pdf"


# ─── Fixtures & helpers ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_dir():
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def parser(tmp_dir):
    return GAMurdockParser(tmp_dir / "missing.pdf", tmp_dir / "images")


def header(text, x0, y, width=None):
    return _Span(text, x0, y, x0 + (width or len(text) * 3.5), y + 8, FONT_HEADER, 7.0, WHITE)


def cell(text, x0, y, width=None):
    return _Span(text, x0, y, x0 + (width or len(text) * 3.5), y + 8, FONT_CELL, 7.0, 0)


def price(text, x0, y):
    # Prices render ~0.7 pt above the row text
    return _Span(text, x0, y - 0.7, x0 + 22, y + 6, FONT_PRICE, 6.0, 0)


def title(text, x0, y, size=10.0, font=FONT_TITLE):
    return _Span(text, x0, y, x0 + len(text) * 5, y + 11, font, size, 0)


def ball_valve_table_spans(y=100.0):
    """Header + 3 rows modelled on 'Mur-lok R/O Pal' (page 1 of the catalog)."""
    spans = [
        header("Part Number", 116, y, 44),
        header("Tube ID", 212, y, 25),
        header("Tube OD", 262, y, 27),
        header("Ball Valve End", 318, y, 50),
        header("List", 394, y, 12),
    ]
    rows = [
        ("A0630405", '1/4”', '3/8”', "1/4” Female NPTF", "$18.06"),
        ("A0630425*", '1/4”', '3/8”', "1/4” Mur-lok", "$21.08"),
        ("A0630625", '1/4”', '3/8”', "3/8” Mur-lok", ""),       # no published price
    ]
    for i, (sku, tid, tod, end, list_price) in enumerate(rows):
        ry = y + 10 + i * 9.5
        spans += [cell(sku, 116, ry, 30), cell(tid, 218, ry, 14),
                  cell(tod, 268, ry, 14), cell(end, 315, ry, 55)]
        if list_price:
            spans.append(price(list_price, 390, ry))
    return spans


def parse_spans(parser, spans, families=None):
    tables = parser._find_tables(spans)
    families = families if families is not None else parser._find_families(spans)
    parser._assign_body_spans(spans, tables, families)
    return tables


# ─── Text helpers ────────────────────────────────────────────────────────────

class TestTextHelpers:
    def test_clean_text_separates_glued_trademarks(self):
        assert GAMurdockParser._clean_text("Slim Line®Housings") == "Slim Line Housings"

    def test_clean_text_normalises_inch_quotes(self):
        assert GAMurdockParser._clean_text("1/4”  QC") == '1/4" QC'

    def test_split_known_brand(self):
        assert GAMurdockParser._split_brand("John Guest Check Valves") == ("John Guest", "Check Valves")

    def test_split_unknown_brand_keeps_brand_empty(self):
        assert GAMurdockParser._split_brand("In-line Ball Valves") == ("", "In-line Ball Valves")

    def test_slugify(self):
        assert GAMurdockParser._slugify('"Stubby" Ball Valves') == "stubby-ball-valves"


class TestCategoryResolution:
    def test_keyword_picks_highlighted_tab(self):
        idx = GAMurdockParser._resolve_category("Norgren Pressure Regulators",
                                                {"Valves", "Drain Products", "Regulators"}, 0)
        assert idx == 3  # Regulators

    def test_most_specific_tab_wins(self):
        idx = GAMurdockParser._resolve_category("Faucet Installation Wrench", {"Faucets", "Tools"}, 13)
        assert idx == 14  # Tools, not Faucets

    def test_tankless_is_not_a_tank(self):
        idx = GAMurdockParser._resolve_category("Pentair Tankless RO System",
                                                {"Systems", "Pumps", "Tanks"}, 7)
        assert idx == 7  # Systems

    def test_no_keyword_carries_current_category(self):
        idx = GAMurdockParser._resolve_category("Li Kuan Hot/Cold Dual Flow",
                                                {"Chemicals", "Tools", "Faucets"}, 13)
        assert idx == 13  # stays on Faucets


# ─── Layout detection ────────────────────────────────────────────────────────

class TestTableDetection:
    def test_header_columns_read_dynamically(self, parser):
        tables = parser._find_tables(ball_valve_table_spans())
        assert len(tables) == 1
        assert [c.label for c in tables[0].columns] == [
            "Part Number", "Tube ID", "Tube OD", "Ball Valve End", "List"]

    def test_header_without_list_column_is_ignored(self, parser):
        spans = [header("Fitting Size", 400, 50), header("psi", 460, 50)]
        assert parser._find_tables(spans) == []

    def test_label_split_mid_word_is_merged(self, parser):
        spans = [header("Part #", 116, 50, 21), header("Box Q", 350, 50, 20),
                 header("ty", 371, 50, 6), header("List", 394, 50, 12)]
        labels = [c.label for c in parser._find_tables(spans)[0].columns]
        assert labels == ["Part #", "Box Qty", "List"]

    def test_wrapped_label_second_line_is_merged(self, parser):
        spans = [header("Part Number", 116, 50, 44), header("Dimen-", 250, 50, 24),
                 header("Qty", 360, 50, 12), header("List", 394, 50, 12),
                 header("sions", 251, 58.4, 20)]   # second line, 8.4 pt lower
        tables = parser._find_tables(spans)
        assert len(tables) == 1
        assert tables[0].columns[1].label == "Dimensions"

    def test_sub_header_inherits_previous_columns(self, parser):
        spans = [header("Part #", 116, 50, 21), header("Model", 160, 50, 20),
                 header("Description", 230, 50, 40), header("Qty", 370, 50, 12),
                 header("List", 394, 50, 12),
                 header("Replacement Components", 116, 120, 93),
                 header("Qty", 370, 120, 12), header("List", 394, 120, 12)]
        tables = parser._find_tables(spans)
        assert len(tables) == 2
        assert [c.label for c in tables[1].columns] == ["Part #", "Model", "Description", "Qty", "List"]

    def test_kerned_title_spans_are_merged(self, parser):
        spans = [title("Li", 114, 124.7), title("q", 122.0, 125.2, size=9.49, font="LucidaFax-Demi"),
                 title("uid-Filled Pressure Gauges", 128.2, 124.7)]
        spans[0].x1, spans[1].x1 = 122.0, 128.2
        families = parser._find_families(spans)
        assert [f.title for f in families] == ["Liquid-Filled Pressure Gauges"]


# ─── Row extraction ──────────────────────────────────────────────────────────

class TestRowExtraction:
    def test_rows_become_products(self, parser):
        table = parse_spans(parser, ball_valve_table_spans(), families=[])[0]
        products = [parser._row_to_product(r, table, "Mur-lok® R/O Pal", "Valves", 2)
                    for r in parser._build_rows(table)]
        first = products[0]
        assert first.sku == "A0630405"
        assert first.price_original == pytest.approx(18.06)
        assert first.brand == "Mur-lok"
        assert first.category == "Valves"
        assert first.description == (
            'R/O Pal — Tube ID 1/4", Tube OD 3/8", Ball Valve End 1/4" Female NPTF')

    def test_footnote_marker_is_stripped_and_noted(self, parser):
        table = parse_spans(parser, ball_valve_table_spans(), families=[])[0]
        product = parser._row_to_product(parser._build_rows(table)[1], table, "R/O Pal", "Valves", 2)
        assert product.sku == "A0630425"
        assert "footnote (*)" in product.notes

    def test_row_without_price_is_skipped_and_reported(self, parser):
        table = parse_spans(parser, ball_valve_table_spans(), families=[])[0]
        assert parser._row_to_product(parser._build_rows(table)[2], table, "R/O Pal", "Valves", 2) is None
        assert parser._skipped_products[0]["sku"] == "A0630625"

    def test_wrapped_description_continues_previous_row(self, parser):
        spans = [header("Part #", 116, 50, 21), header("Description", 230, 50, 40),
                 header("Qty", 368, 50, 12), header("List", 394, 50, 12),
                 cell("RK2K1", 116, 60, 22), cell("Starter Kit (64 oz", 154, 60, 80),
                 cell("6", 372, 60, 4), price("$34.67", 388, 60),
                 cell("ResCare)", 154, 68.4, 30)]
        table = parse_spans(parser, spans, families=[])[0]
        rows = parser._build_rows(table)
        assert len(rows) == 1
        product = parser._row_to_product(rows[0], table, "", "Chemicals", 41)
        assert product.description == "Starter Kit (64 oz ResCare)"
        assert product.notes == "Qty: 6"

    def test_sku_qualifier_moves_to_description(self, parser):
        spans = [header("Part Number", 116, 50, 44), header("Volume", 250, 50, 24),
                 header("List", 394, 50, 12),
                 cell("RO122P (plastic)", 116, 60, 60), cell("2.5 Gal.", 252, 60, 26),
                 price("$95.70", 388, 60)]
        table = parse_spans(parser, spans, families=[])[0]
        product = parser._row_to_product(parser._build_rows(table)[0], table, "PA-E RO Storage Tanks",
                                         "Tanks", 24)
        assert product.sku == "RO122P"
        assert product.description == "PA-E RO Storage Tanks — plastic, Volume 2.5 Gal."

    def test_text_below_a_new_title_is_not_absorbed(self, parser):
        spans = ball_valve_table_spans(y=100) + [
            title("Also available:", 126, 140),
            cell("Mur-lok Male Angle Stop Connectors - Page 9", 202, 141.5, 150),
        ]
        families = [_Family("R/O Pal", 80.0), _Family("Also available:", 140.0)]
        table = parse_spans(parser, spans, families=families)[0]
        last = parser._build_rows(table)[-1]
        assert all("Page 9" not in " ".join(v) for v in last["cells"].values())


# ─── Registration & integration ──────────────────────────────────────────────

class TestRegistration:
    def test_parser_is_registered(self):
        assert any(p["name"] == "G.A. Murdock" for p in ParserFactory.list_parsers())


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="supplier PDF not present (git-ignored)")
class TestRealCatalog:
    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("ga_images")
        p = GAMurdockParser(SAMPLE_PDF, out)
        session = ProcessingSession(pdf_path=str(SAMPLE_PDF))
        try:
            products, images = p.run(session)
        finally:
            p._close_doc()
        return products, images, session

    def test_detected_by_factory(self):
        assert ParserFactory.detect(SAMPLE_PDF) is GAMurdockParser

    def test_every_published_price_becomes_a_product(self, result):
        products, _, session = result
        assert session.errors == []
        # 1,318 prices − 17 cross-section duplicates
        assert len(products) == 1301
        assert all(p.price_original > 0 for p in products)
        assert len({p.sku for p in products}) == len(products)

    def test_almost_every_product_has_an_image(self, result):
        products, images, _ = result
        with_image = [p for p in products if p.image_path]
        assert len(with_image) / len(products) > 0.99
        assert all(Path(pi.file_path).exists() for pi in images)
