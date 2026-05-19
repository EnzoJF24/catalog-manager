# Adding a parser for a new supplier

This guide walks through adding support for a new supplier's PDF price list.
Once implemented, the application will auto-detect the new supplier from any
matching PDF dropped into the Import tab — no UI changes required.

Estimated effort:
- **Basic parser (text only, no images):** 2–4 hours
- **Full parser (with image extraction):** 1–2 days

---

## How the parser system works

The application's PDF parsing follows a **registry + auto-detection** pattern:

1. Every supported supplier has its own parser class in `app/parsers/`,
   subclassing `BaseParser`.
2. The `ParserFactory` (in `app/parsers/parser_factory.py`) holds a list of
   registered parser classes.
3. When a user imports a PDF, the factory reads page 1 and matches its text
   against each parser's `DETECTION_KEYWORDS` and `DETECTION_PATTERNS`. The
   first match wins.
4. The matched parser is instantiated and its `run()` method is called,
   producing a list of `Product` and `ProductImage` objects that the
   `ProductService` persists to the database.

You don't need to touch the factory's matching logic, the database layer, or
the UI. Adding a supplier is purely about writing one parser class and
registering it.

---

## Step-by-step

### Step 1 — Obtain a representative PDF

Get at least one real catalog PDF from the supplier. Ideally two: one for
development and one for validation after the parser is working.

Make sure the PDF is text-based (not a scanned image). If it's scanned, you'd
need to OCR it first — that's outside this guide's scope.

### Step 2 — Discover the PDF's structure

The core technique used by every parser in this project is
**coordinate-based column extraction**: each word in the PDF has an
(x, y) position, and product columns occupy known x-ranges. To find those
ranges, run this snippet against page 1:

```python
import fitz
doc = fitz.open("path/to/supplier_sample.pdf")
for w in doc[0].get_text("words")[:80]:
    print(f"x={w[0]:6.1f}  y={w[1]:6.1f}  text={w[4]!r}")
```

Look at the output and identify which x-ranges correspond to which columns.
A typical wholesale catalog has something like:

| Column      | Approximate x-range |
|-------------|---------------------|
| SKU         | 30 – 100            |
| Brand       | 100 – 220           |
| Description | 220 – 480           |
| Price       | 480 onwards         |

Write these down — you'll plug them into the parser as constants.

### Step 3 — Copy the template

```bash
cp docs/example_parser_template.py app/parsers/<supplier>_parser.py
```

Rename the class inside (e.g. `ExampleSupplierParser` → `AcmeWholesaleParser`).

### Step 4 — Customize the constants

In the new file, replace:

- **`SUPPLIER_NAME`** — human-readable supplier name (shown in the UI).
- **`DETECTION_KEYWORDS`** — strings unique to this supplier's PDFs.
- **`COL_*_MIN_X` / `COL_*_MAX_X`** — column x-ranges from Step 2.
- **`SKU_RE`** — regex describing the supplier's SKU format.

Run the discovery snippet from Step 2 a few more times against other pages
to make sure the column ranges are stable across the catalog. Some
suppliers shift columns slightly on certain pages — handle those edge cases
explicitly if needed.

### Step 5 — Register the parser

Open `app/parsers/parser_factory.py` and add an import + registry entry:

```python
from app.parsers.acme_wholesale_parser import AcmeWholesaleParser

REGISTERED_PARSERS: list[Type[BaseParser]] = [
    MayoristasIParser,
    AcmeWholesaleParser,    # ← new entry
]
```

### Step 6 — Test

1. Launch the app: `python main.py`
2. Open the **Import** tab.
3. Drag in the supplier's PDF.
4. Watch the logs at the bottom of the window.

Expected first run:
- The parser detects the supplier correctly (status shows "Parser: Acme Wholesale")
- Most products extract successfully
- A handful of rows may fail — those are usually category headers or
  exceptional rows your regex skips. They appear in the import session's
  warnings.

Open the **Products** tab to confirm the data looks right (SKUs, brands,
prices). Edit any wrongly-parsed rows inline. Iterate on the parser code as
needed.

### Step 7 — Add image extraction (optional)

Image extraction is significantly more complex than text extraction because
PDFs store images separately from the text stream and you have to correlate
them by bounding box.

For an initial release, returning `[]` from `extract_images()` is fine —
products will simply have no images. The dashboard's "No image" health
check will surface them, and the user can attach images manually if needed.

When you're ready to add image extraction, study the reference
implementation in `app/parsers/mayoristas_i_parser.py`. Look at:

- `_extract_image_with_bbox` — extracts an image and computes its center y
- `_match_image_to_product` — pairs the image with the closest product row
- `best_by_sku` — keeps only the highest-confidence match per SKU

Adapt the pattern to your supplier's image placement.

---

## Common pitfalls

### Price strings vary wildly

`BaseParser._parse_price()` handles the most common formats:
- US: `1,234.56`
- Argentine: `$ 1.234,56`
- Plain: `1234.56`

If your supplier uses a different format (e.g. European spaces as thousand
separators, currency symbols at the end), override `_parse_price()` in your
parser class.

### Categories live in section headers, not product rows

Most catalogs intersperse category headers (e.g. "TOOLS") between product
rows. The header is on its own line and doesn't have a SKU. The standard
approach:

1. Detect category headers as rows whose text matches `^[A-ZÁÉÍÓÚÑ\s]+$`
   and which contain no number-like words.
2. When you see one, store it in a `current_category` variable.
3. Assign `current_category` to each subsequent product until the next
   header.

The `mayoristas_i_parser.py` reference implements this pattern in
`_try_extract_category()` and `_parse_page()`.

### Some SKUs span multiple words

If the supplier's SKU column contains multi-word SKUs like `"AB 1234"`, the
default whitespace-collapsing logic still works:
`self._normalize_sku(" ".join(w[4] for w in sku_words))` produces
`"AB 1234"` → `_normalize_sku()` uppercases and trims.

If the supplier uses internal whitespace as a real character (rare), you
need to handle this explicitly.

### Detection keywords are too broad

If your `DETECTION_KEYWORDS` are common English words ("PRICE", "LIST",
"CATALOG"), the factory may pick your parser for unrelated PDFs. Be
specific: use the supplier's full registered name, an address line,
a website URL, a part number that's clearly theirs.

### Re-imports overwrite edits

By design, re-importing the same supplier PDF updates products by SKU.
The fields `active`, `notes`, and the `discontinued` flag are preserved
across re-imports (see `db_manager.upsert_product`). Brand and description
are overwritten — if the user manually edited a brand and then re-imports,
their edit will be lost. This is intentional but worth knowing.

---

## Reference

- **`app/parsers/base_parser.py`** — abstract base class with helpers
  (`_parse_price`, `_normalize_sku`, `_normalize_text`).
- **`app/parsers/mayoristas_i_parser.py`** — full production-grade parser,
  including image extraction with bounding-box matching.
- **`app/parsers/parser_factory.py`** — registry and auto-detection logic.
- **`docs/example_parser_template.py`** — starting-point template (copy this).

---

## Need a hand?

If you're stuck adapting the parser to a specific supplier, open a
discussion on the repo or contact the author. The PDF-parsing patterns
used here are generalizable — most wholesale-catalog formats are some
variant of the column-based layout described above.
