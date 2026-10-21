"""
Line icons drawn as inline SVG (24 × 24 grid, 2 px stroke, round caps) and
rasterised with PyMuPDF — no image files or extra dependencies.

    from app.ui.icons import icon
    btn = ctk.CTkButton(..., image=icon("download", TEXT_MUTED))
"""
from __future__ import annotations
import io
from functools import lru_cache

import customtkinter as ctk
import fitz  # PyMuPDF
from PIL import Image

# SVG element bodies on a 24 × 24 grid
_ICONS: dict[str, str] = {
    "logo":          '<path d="M12 2l10 5-10 5L2 7z"/><path d="M2 12l10 5 10-5"/><path d="M2 17l10 5 10-5"/>',
    "dashboard":     '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/>'
                     '<rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "upload":        '<path d="M12 15V3"/><path d="M7 8l5-5 5 5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    "download":      '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    "package":       '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
    "book":          '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    "folder":        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "sliders":       '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/>'
                     '<path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
    "info":          '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "search":        '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "refresh":       '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>',
    "file":          '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
    "file_text":     '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>'
                     '<path d="M8 13h8"/><path d="M8 17h5"/>',
    "sheet":         '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/>',
    "save":          '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8"/><path d="M7 21v-7h10v7"/>',
    "x":             '<path d="M18 6L6 18"/><path d="M6 6l12 12"/>',
    "check":         '<path d="M20 6L9 17l-5-5"/>',
    "check_circle":  '<circle cx="12" cy="12" r="10"/><path d="M8 12l3 3 5-6"/>',
    "alert":         '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
                     '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "chevron_left":  '<path d="M15 18l-6-6 6-6"/>',
    "chevron_right": '<path d="M9 18l6-6-6-6"/>',
    "chevrons_left": '<path d="M11 17l-5-5 5-5"/><path d="M18 17l-5-5 5-5"/>',
    "chevrons_right":'<path d="M13 17l5-5-5-5"/><path d="M6 17l5-5-5-5"/>',
    "external":      '<path d="M15 3h6v6"/><path d="M10 14L21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "trash":         '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
                     '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    "clock":         '<circle cx="12" cy="12" r="10"/><path d="M12 7v5l3 2"/>',
    "image":         '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
    "edit":          '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "percent":       '<path d="M19 5L5 19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
    "code":          '<path d="M16 18l6-6-6-6"/><path d="M8 6l-6 6 6 6"/>',
    "history":       '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "palette":       '<circle cx="12" cy="12" r="10"/><circle cx="8" cy="10" r="1.2"/><circle cx="12" cy="7.5" r="1.2"/>'
                     '<circle cx="16" cy="10" r="1.2"/><path d="M12 22a3 3 0 0 1 0-6h1.5a2.5 2.5 0 0 0 2.5-2.5"/>',
    "layers":        '<path d="M12 2l10 5-10 5L2 7z"/><path d="M2 12l10 5 10-5"/>',
    "mail":          '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 6l-10 7L2 6"/>',
}

_RENDER_SCALE = 3   # rasterise at 3× so icons stay crisp on high-DPI screens


@lru_cache(maxsize=256)
def _render(name: str, color: str, px: int) -> Image.Image:
    body = _ICONS[name]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{px}" height="{px}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{body}</svg>'
    )
    doc = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
    pix = doc[0].get_pixmap(alpha=True)
    doc.close()
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")


@lru_cache(maxsize=256)
def icon(name: str, color: str, size: int = 16) -> ctk.CTkImage:
    """CTkImage of a line icon in the given colour, displayed at `size` px."""
    img = _render(name, color, size * _RENDER_SCALE)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
