# Adding a parser for a new supplier

Each supplier's PDF gets its own parser class. Once it's registered, the app recognizes that supplier's PDFs on its own when you import them. The UI and the database don't need any changes.

Rough effort, from my experience with the two parsers in this repo:

- Text only (no photos): 2 to 4 hours
- With photo extraction: 1 to 2 days

## How parsers are picked

1. Each supplier has a class in `app/parsers/` that subclasses `BaseParser`.
2. `app/parsers/parser_factory.py` keeps the list of registered parsers in `REGISTERED_PARSERS`.
3. On import, the factory reads page 1 and checks it against each parser's `DETECTION_KEYWORDS` and `DETECTION_PATTERNS`. The first match wins.
4. The chosen parser's `run()` returns `Product` and `ProductImage` objects, and `ProductService` saves them.

So adding a supplier means writing one class and adding one line to the registry.

## Steps

### 1. Get a sample PDF

Get at least one real PDF from the supplier, ideally two: one to build the parser and another to check it.

It has to be a text PDF. If it's a scan, it needs OCR first, which this guide doesn't cover.

### 2. Look at how the page is laid out

Every word in a PDF has a position, and usually a font. Print them for the first page:

```python
import fitz
doc = fitz.open("path/to/supplier_sample.pdf")
for w in doc[0].get_text("words")[:80]:
    print(f"x={w[0]:6.1f}  y={w[1]:6.1f}  text={w[4]!r}")
```

From that output you can see which x-range each column uses. A typical price list looks something like this:

| Column      | x-range (approx.) |
|-------------|-------------------|
| SKU         | 30 to 100         |
| Brand       | 100 to 220        |
| Description | 220 to 480        |
| Price       | 480 and up        |

Check a few more pages. Some suppliers shift columns slightly on certain pages.

If the columns change from table to table, fixed x-ranges won't work. In that case look at the fonts too, with `page.get_text("dict")`, which gives each span's font name and size. `ga_murdock_parser.py` works this way: it finds each table's header row by its font, reads the column positions from that header, and identifies titles, cells and prices by font instead of position.

### 3. Copy the template

```bash
cp docs/example_parser_template.py app/parsers/<supplier>_parser.py
```

Rename the class, for example `ExampleSupplierParser` to `AcmeWholesaleParser`.

### 4. Fill in the constants

- `SUPPLIER_NAME`: the name shown in the app.
- `DETECTION_KEYWORDS`: text that only appears in this supplier's PDFs.
- `COL_*_MIN_X` / `COL_*_MAX_X`: the column ranges from step 2.
- `SKU_RE`: a regex for the supplier's SKU format.

### 5. Register it

In `app/parsers/parser_factory.py`:

```python
from app.parsers.acme_wholesale_parser import AcmeWholesaleParser

REGISTERED_PARSERS: list[Type[BaseParser]] = [
    MayoristasIParser,
    GAMurdockParser,
    AcmeWholesaleParser,
]
```

### 6. Try it

1. Run the app with `python main.py`.
2. In **Import PDF**, click **Browse…**, pick the supplier's PDF and click **Import**.
3. Read the import log. The second line should say `Parser: <your supplier name>`.

On a first run it's normal for most rows to come out right and a few to be skipped, usually category headers or rows your regex doesn't match. Skipped rows show up as notes in the import log.

Then open **Products** and check SKUs, brands and prices. Fix the parser and import again until it's clean. Writing a few tests with small fake pages (see `tests/test_ga_murdock_parser.py`) is much faster than re-importing the whole PDF every time.

### 7. Photos (optional)

Photos are harder than text because the PDF stores them apart from the text, and you have to match each one to its row by position.

For a first version you can return `[]` from `extract_images()`. Products just won't have a photo, and the dashboard's "Products without an image" check will list them.

When you add photos, look at the two existing parsers:

- `mayoristas_i_parser.py`: `_extract_image_with_bbox()` gets each image with its position, and `best_by_sku` keeps the best-scoring image for each SKU.
- `ga_murdock_parser.py`: `extract_images()` renders one photo per product family and assigns it to every product in that family's tables. It also skips blank placeholder images.

## Things that usually go wrong

**Price formats.** `BaseParser._parse_price()` handles `1,234.56`, `$ 1.234,56` and `1234.56`. If your supplier uses something else, such as spaces as thousands separators or the currency symbol at the end, override it in your parser.

**Categories are headers, not columns.** Most price lists put a category title above a group of products. Keep a `current_category` variable, update it whenever you hit a header (a line with no SKU and no price), and assign it to the products that follow. `mayoristas_i_parser.py` does this in `_try_extract_category()` and `_parse_page()`.

**SKUs with spaces.** If a SKU like `AB 1234` is split into two words, join them before normalizing: `self._normalize_sku(" ".join(w[4] for w in sku_words))`.

**Detection keywords that are too generic.** Words like "PRICE" or "CATALOG" will match other suppliers' PDFs too. Use something only this supplier has: their full company name, their website or an address line.

**Re-imports overwrite some edits.** Re-importing updates products by SKU. `active`, `notes` and `discontinued` are kept (see `upsert_product` in `db_manager.py`), but brand and description are replaced with what's in the new PDF. If you edited a brand by hand, a re-import will undo it.

## Files to look at

- `app/parsers/base_parser.py`: the base class and its helpers (`_parse_price`, `_normalize_sku`, `_normalize_text`).
- `app/parsers/mayoristas_i_parser.py`: position-based parser with photo extraction.
- `app/parsers/ga_murdock_parser.py`: font-based parser for tables whose columns change.
- `app/parsers/parser_factory.py`: the registry and detection.
- `docs/example_parser_template.py`: the template to copy.
