"""
Excel service v3:
  Hoja 1 "Productos"  — editable por el usuario.
                         Precio Final es un VALOR numérico (no fórmula),
                         calculado por apply_margin() y guardado en DB.
                         El usuario puede editar Margen%/IVA%/Precio Final
                         directamente; al reimportar se recalcula con apply_margin().
  Hoja 2 "Sistema"    — datos internos: imagen↔SKU, metadatos, configuración.
  Reimport            — recalcula precio_final con apply_margin() usando los
                         round_to/suffix persistidos en DB (fuente única de verdad).
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side,
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app.database.db_manager import DatabaseManager
from app.logging_config.logger import get_logger
from app.config.branding import APP_NAME, APP_VERSION, APP_AUTHOR, EXCEL_SYSTEM_LABEL
from app.config.settings import settings

log = get_logger("excel_service")

TRUTHY = {"si", "sí", "yes", "true", "1", "activo", "x"}

# ── Column map for Sheet 1 ────────────────────────────────────────────────────
COL_ACTIVO  = 1
COL_SKU     = 2
COL_MARCA   = 3
COL_DESC    = 4
COL_CAT     = 5
COL_ORIG    = 6
COL_MARGEN  = 7
COL_IVA     = 8
COL_FINAL   = 9   # ← numeric value (pre-calculated), no formula
COL_OBS     = 10

HEADERS_USER = [
    "Activo", "SKU", "Marca", "Descripción", "Categoría",
    "Precio Original", "Margen %", "IVA %", "Precio Final",
    "Observaciones",
]

# ── Palette (mirrors app/ui/theme.py for Excel consistency) ──────────────────
_RED        = "C0392B"
_DARK_BLUE  = "16213E"
_DEEP_BLUE  = "0F1E36"
_LIGHT      = "F5F5F5"
_GREEN_BG   = "E8F8E8"
_RED_BG     = "F8E8E8"
_BLUE_BG    = "EBF5FB"   # Precio Final column
_GREY_TAB   = "95A5A6"
_SYS_HDR    = "2C3E50"
_SYS_SEC    = "1A252F"

_BANNER_BG  = "FCF3CF"   # soft yellow — staleness warning banner
_BANNER_TXT = "7D6608"   # dark gold — banner text

_FILL_HEADER   = PatternFill("solid", fgColor=_RED)
_FILL_BANNER   = PatternFill("solid", fgColor=_BANNER_BG)
_FILL_ACTIVE   = PatternFill("solid", fgColor=_GREEN_BG)
_FILL_INACTIVE = PatternFill("solid", fgColor=_RED_BG)
_FILL_ALT      = PatternFill("solid", fgColor=_LIGHT)
_FILL_FINAL    = PatternFill("solid", fgColor=_BLUE_BG)
_FILL_SYS_HDR  = PatternFill("solid", fgColor=_SYS_HDR)
_FILL_SYS_SEC  = PatternFill("solid", fgColor=_SYS_SEC)

_FONT_HEADER = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
_FONT_BANNER = Font(bold=True, name="Calibri", size=11, color=_BANNER_TXT)
_FONT_DATA   = Font(name="Calibri", size=10)
_FONT_BOLD   = Font(bold=True, name="Calibri", size=10)
_FONT_FINAL  = Font(bold=True, name="Calibri", size=10, color="154360")
_FONT_SYS    = Font(name="Consolas", size=9, color="BDC3C7")
_FONT_SYS_H  = Font(bold=True, name="Calibri", size=11, color="FFFFFF")
_FONT_SYS_S  = Font(bold=True, name="Calibri", size=10, color="3498DB")
_FONT_NOTE   = Font(italic=True, name="Calibri", size=9, color="7F8C8D")

_ALIGN_C = Alignment(horizontal="center", vertical="center", wrap_text=True)
_ALIGN_L = Alignment(horizontal="left",   vertical="center", wrap_text=True)
_ALIGN_R = Alignment(horizontal="right",  vertical="center")
_BORDER  = Border(
    bottom=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin",  color="DDDDDD"),
)


def _cell(ws, row: int, col: int):
    return ws.cell(row=row, column=col)


class ExcelService:

    def __init__(self, db: DatabaseManager, output_dir: Path):
        self.db = db
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Generation ────────────────────────────────────────────────────────────

    def generate_excel(
        self,
        filename: Optional[str] = None,
        active_only: bool = False,
        include_discontinued: bool = False,
        round_to: int = 0,
        suffix: str = "",
    ) -> Path:
        rows = self.db.get_all_products(include_inactive=True)
        if not rows:
            raise ValueError("No hay productos en la base de datos.")

        if active_only:
            rows = [r for r in rows if r.get("active")]
        if not include_discontinued:
            rows = [r for r in rows if not r.get("discontinued")]
        if not rows:
            raise ValueError("No hay productos que cumplan los criterios de filtro.")

        rows.sort(key=lambda r: (r.get("category") or "", r.get("sku") or ""))

        if filename:
            out_path = self.output_dir / filename
        else:
            base     = f"catalogo_{datetime.now().strftime('%Y-%m-%d')}"
            out_path = self.output_dir / f"{base}.xlsx"
            # If a file with that date already exists, append _2, _3, … to avoid overwrite
            n = 2
            while out_path.exists():
                out_path = self.output_dir / f"{base}_{n}.xlsx"
                n += 1

        wb = Workbook()
        ws1 = wb.active
        ws1.title = "Productos"
        self._write_products_sheet(ws1, rows)

        ws2 = wb.create_sheet("Sistema")
        ws2.sheet_properties.tabColor = _GREY_TAB
        self._write_system_sheet(ws2, rows, round_to, suffix)

        wb.save(str(out_path))
        log.info(f"Excel generado: {out_path} ({len(rows)} filas)")
        return out_path

    # ── Sheet 1 ───────────────────────────────────────────────────────────────

    def _write_products_sheet(self, ws, rows: list[dict]):
        # ── Row 1: staleness banner (merged across all columns) ──────────────
        gen_str = datetime.now().strftime("%d/%m/%Y a las %H:%M")
        banner  = _cell(ws, 1, 1)
        banner.value = (
            f"⚠  Catálogo generado el {gen_str}. "
            "Si hubo modificaciones posteriores en el sistema, NO están reflejadas aquí. "
            "Para datos actualizados, generá un Excel nuevo desde la aplicación."
        )
        banner.fill      = _FILL_BANNER
        banner.font      = _FONT_BANNER
        banner.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=COL_OBS
        )
        ws.row_dimensions[1].height = 38

        # ── Row 2: headers ────────────────────────────────────────────────────
        for col, h in enumerate(HEADERS_USER, 1):
            c            = _cell(ws, 2, col)
            c.value      = h
            c.fill       = _FILL_HEADER
            c.font       = _FONT_HEADER
            c.alignment  = _ALIGN_C
            c.border     = _BORDER

        # Dropdown for "Activo" column
        dv = DataValidation(type="list", formula1='"SI,NO"', allow_blank=False)
        dv.error       = "Usá SI o NO"
        dv.errorTitle  = "Valor inválido"
        dv.prompt      = "SI = activo, NO = inactivo"
        dv.promptTitle = "Estado del producto"
        ws.add_data_validation(dv)

        # ── Row 3+: data ──────────────────────────────────────────────────────
        for row_i, r in enumerate(rows, start=3):
            is_active = r.get("active", True)

            # A — Activo
            c           = _cell(ws, row_i, COL_ACTIVO)
            c.value     = "SI" if is_active else "NO"
            c.fill      = _FILL_ACTIVE if is_active else _FILL_INACTIVE
            c.font      = Font(bold=True, name="Calibri", size=10,
                               color="1A6B3C" if is_active else "8B0000")
            c.alignment = _ALIGN_C
            c.border    = _BORDER
            dv.add(c)

            # B-E — text
            for col, val in [
                (COL_SKU,   r.get("sku", "")),
                (COL_MARCA, r.get("brand") or ""),
                (COL_DESC,  r.get("description") or ""),
                (COL_CAT,   r.get("category") or ""),
            ]:
                c           = _cell(ws, row_i, col)
                c.value     = val
                c.font      = _FONT_DATA
                c.alignment = _ALIGN_L
                c.border    = _BORDER
                if row_i % 2 == 0 and col != COL_SKU:
                    c.fill = _FILL_ALT

            # F — Precio Original
            c               = _cell(ws, row_i, COL_ORIG)
            c.value         = round(r.get("price_original", 0.0) or 0.0, 2)
            c.font          = _FONT_DATA
            c.alignment     = _ALIGN_R
            c.border        = _BORDER
            c.number_format = '"$ "#,##0.00'

            # G — Margen %
            c               = _cell(ws, row_i, COL_MARGEN)
            c.value         = round(r.get("margin_pct", 0.0) or 0.0, 2)
            c.font          = _FONT_DATA
            c.alignment     = _ALIGN_R
            c.border        = _BORDER
            c.number_format = '0.00"%"'

            # H — IVA %
            c               = _cell(ws, row_i, COL_IVA)
            c.value         = round(r.get("iva_pct", 0.0) or 0.0, 2)
            c.font          = _FONT_DATA
            c.alignment     = _ALIGN_R
            c.border        = _BORDER
            c.number_format = '0.00"%"'

            # I — Precio Final (numeric, pre-calculated — no live formula)
            c               = _cell(ws, row_i, COL_FINAL)
            c.value         = round(r.get("price_final", 0.0) or 0.0, 2)
            c.font          = _FONT_FINAL
            c.fill          = _FILL_FINAL
            c.alignment     = _ALIGN_R
            c.border        = _BORDER
            c.number_format = '"$ "#,##0.00'

            # J — Observaciones
            c           = _cell(ws, row_i, COL_OBS)
            c.value     = r.get("notes") or ""
            c.font      = _FONT_DATA
            c.alignment = _ALIGN_L
            c.border    = _BORDER

        # Column widths
        for col, w in {
            COL_ACTIVO: 8, COL_SKU: 13, COL_MARCA: 18,
            COL_DESC: 46, COL_CAT: 22, COL_ORIG: 17,
            COL_MARGEN: 10, COL_IVA: 8, COL_FINAL: 17, COL_OBS: 30,
        }.items():
            ws.column_dimensions[get_column_letter(col)].width = w

        # Nota explicativa debajo de los datos (data starts at row 3 now)
        help_row = len(rows) + 4
        note = _cell(ws, help_row, COL_FINAL - 2)
        note.value     = (
            "ℹ  Precio Final es el valor calculado por el sistema. "
            "Para recalcular usá 'Re-aplicar Margen' en Configuración."
        )
        note.font      = _FONT_NOTE
        note.alignment = _ALIGN_L
        ws.merge_cells(
            start_row=help_row, start_column=COL_FINAL - 2,
            end_row=help_row,   end_column=COL_OBS
        )

        # Freeze under headers (row 2), filter on header row, set row heights
        ws.freeze_panes    = "A3"
        ws.auto_filter.ref = f"A2:{get_column_letter(COL_OBS)}2"
        ws.row_dimensions[2].height = 22
        for r_i in range(3, len(rows) + 3):
            ws.row_dimensions[r_i].height = 20

    # ── Sheet 2 ───────────────────────────────────────────────────────────────

    def _write_system_sheet(self, ws, rows: list[dict], round_to: int, suffix: str):
        def _section_title(row: int, text: str):
            c           = _cell(ws, row, 1)
            c.value     = f"  {text}"
            c.fill      = _FILL_SYS_SEC
            c.font      = _FONT_SYS_S
            c.alignment = _ALIGN_L
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)

        def _kv(row: int, key: str, val):
            k           = _cell(ws, row, 1)
            k.value     = key
            k.font      = Font(bold=True, name="Calibri", size=10, color="7F8C8D")
            k.alignment = _ALIGN_R
            v           = _cell(ws, row, 2)
            v.value     = str(val)
            v.font      = Font(name="Calibri", size=10, color="FFFFFF")
            v.alignment = _ALIGN_L

        # Global header
        c           = _cell(ws, 1, 1)
        c.value     = EXCEL_SYSTEM_LABEL
        c.fill      = _FILL_SYS_HDR
        c.font      = _FONT_SYS_H
        c.alignment = _ALIGN_L
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=8)
        ws.row_dimensions[1].height = 24

        c2           = _cell(ws, 2, 1)
        c2.value     = (
            f"  Generado por {APP_AUTHOR}  ·  {APP_NAME} v{APP_VERSION}  "
            "— Esta hoja es de uso interno del sistema. No modificar."
        )
        c2.font      = _FONT_NOTE
        c2.alignment = _ALIGN_L
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=8)

        # Generation metadata
        _section_title(4, "METADATOS DE GENERACIÓN")
        _kv(5, "Fecha de generación:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        _kv(6, "Total productos:",     len(rows))
        sessions = self.db.get_sessions(limit=1)
        if sessions:
            s = sessions[0]
            _kv(7, "Última sesión ID:",  s.get("session_id", "—"))
            _kv(8, "Proveedor:",         s.get("supplier_name", "—"))
            _kv(9, "Parser:",            s.get("parser_name", "—"))

        # Applied config
        _section_title(11, "CONFIGURACIÓN APLICADA")
        sample = rows[0] if rows else {}
        _kv(12, "Margen %:",         f"{sample.get('margin_pct', 0):.2f}")
        _kv(13, "IVA %:",            f"{sample.get('iva_pct', 0):.2f}")
        _kv(14, "Redondear a:",      round_to if round_to else "Sin redondeo")
        _kv(15, "Sufijo de precio:", suffix if suffix else "Ninguno")
        _kv(16, "Precio Final:",     "Valor precalculado por el sistema (no fórmula)")

        # SKU ↔ image table
        _section_title(18, "TABLA IMAGEN ↔ PRODUCTO")
        img_headers = [
            "SKU", "Ruta de Imagen", "Imagen existe",
            "Marca", "Categoría", "Primera vez visto",
            "Última importación", "ID Sesión",
        ]
        for col, h in enumerate(img_headers, 1):
            c           = _cell(ws, 19, col)
            c.value     = h
            c.fill      = _FILL_SYS_HDR
            c.font      = _FONT_SYS_H
            c.alignment = _ALIGN_C
            c.border    = _BORDER

        img_alt = PatternFill("solid", fgColor="1A252F")
        for row_i, r in enumerate(rows, start=20):
            img_path = r.get("image_path") or ""
            if not img_path:
                img_ok = "— sin imagen"
            elif settings.resolve_path(img_path).exists():
                img_ok = "✓"
            else:
                img_ok = "⚠ archivo no encontrado"

            vals = [
                r.get("sku", ""),
                img_path,
                img_ok,
                r.get("brand", ""),
                r.get("category", ""),
                str(r.get("first_seen", ""))[:16],
                str(r.get("last_seen",  ""))[:16],
                r.get("processing_id", ""),
            ]
            for col, val in enumerate(vals, 1):
                c           = _cell(ws, row_i, col)
                c.value     = val
                c.font      = _FONT_SYS
                c.alignment = _ALIGN_L
                c.border    = _BORDER
                if row_i % 2 == 0:
                    c.fill = img_alt

        for col, w in {1: 14, 2: 60, 3: 20, 4: 20, 5: 22, 6: 18, 7: 18, 8: 14}.items():
            ws.column_dimensions[get_column_letter(col)].width = w
        ws.freeze_panes = "A20"

    # ── Reimport ──────────────────────────────────────────────────────────────

    def reimport_excel(self, excel_path: Path) -> dict:
        """
        Read an edited Excel and update the DB.
        Price recalculation uses apply_margin() with the persisted round_to / suffix
        from each product's DB row — single source of truth (C1 fix).
        """
        log.info(f"Reimportando Excel: {excel_path}")
        results = {
            "processed": 0, "updated": 0,
            "not_found": [], "duplicates": [], "errors": [], "warnings": [],
        }

        try:
            wb = load_workbook(str(excel_path), data_only=True)
        except Exception as e:
            results["errors"].append(f"Error abriendo Excel: {e}")
            return results

        ws = wb.worksheets[0]
        # Headers may live on row 1 (legacy) or row 2 (after staleness banner).
        # Detect by looking for "SKU" in the first two rows.
        header_row_idx = 1
        for candidate in (1, 2):
            row_vals = [c.value for c in ws[candidate]]
            if "SKU" in row_vals:
                header_row_idx = candidate
                break

        header_row = [c.value for c in ws[header_row_idx]]
        col_map    = {h: i + 1 for i, h in enumerate(header_row) if h}

        required = {"SKU", "Activo"}
        missing  = required - set(col_map)
        if missing:
            results["errors"].append(f"Columnas requeridas faltantes: {missing}")
            return results

        all_rows: list[dict] = []
        for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
            def _get(col_name, default=None):
                idx = col_map.get(col_name)
                return row[idx - 1] if idx else default

            sku = str(_get("SKU") or "").strip().upper()
            if not sku:
                continue
            all_rows.append({
                "sku":           sku,
                "activo":        str(_get("Activo", "SI") or "SI"),
                "marca":         _get("Marca"),
                "descripcion":   _get("Descripción"),
                "observaciones": _get("Observaciones"),
                "precio_orig":   _get("Precio Original"),
                "margen_pct":    _get("Margen %"),
                "iva_pct":       _get("IVA %"),
                "precio_final":  _get("Precio Final"),
                "categoria":     _get("Categoría"),
            })

        # Dedup
        seen: dict[str, int] = {}
        for d in all_rows:
            seen[d["sku"]] = seen.get(d["sku"], 0) + 1
        dupes = [s for s, c in seen.items() if c > 1]
        if dupes:
            results["duplicates"] = dupes
            results["warnings"].append(
                f"SKUs duplicados (primera aparición usada): {dupes}"
            )
            unique: dict[str, dict] = {}
            for d in all_rows:
                if d["sku"] not in unique:
                    unique[d["sku"]] = d
            all_rows = list(unique.values())

        for d in all_rows:
            results["processed"] += 1
            sku       = d["sku"]
            is_active = d["activo"].strip().lower() in TRUTHY

            existing = self.db.get_product(sku)
            if not existing:
                results["not_found"].append(sku)
                continue

            update_row: dict = {"sku": sku, "active": is_active}

            # Text fields
            for key, db_col in [
                ("marca",         "brand"),
                ("descripcion",   "description"),
                ("observaciones", "notes"),
                ("categoria",     "category"),
            ]:
                val = d.get(key)
                if val is not None and str(val).strip():
                    update_row[db_col] = str(val).strip()

            def _to_float(v) -> Optional[float]:
                if v is None:
                    return None
                try:
                    return float(str(v).replace(",", ".").strip())
                except (ValueError, TypeError):
                    return None

            orig   = _to_float(d["precio_orig"])
            margen = _to_float(d["margen_pct"])
            iva    = _to_float(d["iva_pct"])

            if orig   is not None: update_row["price_original"] = orig
            if margen is not None: update_row["margin_pct"]     = margen
            if iva    is not None: update_row["iva_pct"]        = iva

            # Recalculate price_final with apply_margin() using persisted round_to/suffix
            # This is the C1 fix: one code path for price calculation, always.
            from app.models.product import Product
            _orig   = orig   if orig   is not None else (existing.get("price_original") or 0.0)
            _margen = margen if margen is not None else (existing.get("margin_pct")     or 0.0)
            _iva    = iva    if iva    is not None else (existing.get("iva_pct")        or 0.0)
            _rnd    = existing.get("round_to_nearest") or 0
            _sfx    = existing.get("price_suffix") or ""

            p = Product(
                sku=sku, brand="", description="", price_original=_orig, category=""
            )
            p.apply_margin(_margen, _iva, _rnd, _sfx)
            update_row["price_final"]      = p.price_final
            update_row["round_to_nearest"] = p.round_to_nearest
            update_row["price_suffix"]     = p.price_suffix

            try:
                self.db.upsert_product(update_row)
                self.db.set_product_active(sku, is_active)
                results["updated"] += 1
            except Exception as e:
                results["errors"].append(f"Error actualizando {sku}: {e}")

        log.info(
            f"Reimport: procesados={results['processed']} "
            f"actualizados={results['updated']} "
            f"no_encontrados={len(results['not_found'])}"
        )
        return results
