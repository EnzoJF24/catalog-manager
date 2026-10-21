"""
Design tokens and small widget factories shared by every screen.

Visual language: neutral dark surfaces separated by 1 px borders, a single
blue accent reserved for the primary action and selection, and muted status
colours used only where a state has to be communicated.
Import from here — never hardcode hex values in individual frames.
"""
from __future__ import annotations
from typing import Callable, Optional

import customtkinter as ctk

# ── Typography ────────────────────────────────────────────────────────────────
FONT_FAMILY   = "Segoe UI"
FONT_SEMIBOLD = "Segoe UI Semibold"
FONT_MONO     = "Cascadia Mono"

# ── Surfaces ──────────────────────────────────────────────────────────────────
BG_BASE      = "#0F1115"   # window background
BG_SIDEBAR   = "#0B0D10"   # navigation rail
BG_CARD      = "#16181D"   # cards and panels
BG_ELEVATED  = "#1E2128"   # inputs, selected rows
BG_HOVER     = "#24272F"   # hover state for ghost controls
BG_DEEPEST   = "#0B0D10"   # log consoles
BG_ROW_ALT   = "#181B20"   # zebra rows (barely visible)

BORDER        = "#262A31"
BORDER_STRONG = "#353A45"

# ── Accent & status ───────────────────────────────────────────────────────────
ACCENT       = "#3B82F6"
ACCENT_H     = "#2563EB"
ACCENT_SOFT  = "#172236"   # selected nav item / pending rows
ACCENT_TEXT  = "#8AB4F8"

SUCCESS      = "#22C55E"
SUCCESS_SOFT = "#11261A"
WARNING      = "#F59E0B"
WARNING_SOFT = "#2A2110"
DANGER       = "#EF4444"
DANGER_SOFT  = "#2B1517"

# ── Text ──────────────────────────────────────────────────────────────────────
TEXT_PRIMARY = "#EDEEF0"
TEXT_HEADING = "#D5D8DD"
TEXT_MUTED   = "#8A919C"
TEXT_SUBTLE  = "#5F6673"
TEXT_LINK    = ACCENT_TEXT
BTN_TEXT_DISABLED = "#6B7280"

# ── Legacy aliases (components that only need "a colour for X") ──────────────
ACCENT_PRIMARY, ACCENT_PRIMARY_H = ACCENT, ACCENT_H
ACCENT_BLUE, ACCENT_BLUE_H       = ACCENT, ACCENT_H
ACCENT_SUCCESS, ACCENT_SUCCESS_H = SUCCESS, SUCCESS
ACCENT_WARNING, ACCENT_WARNING_H = WARNING, WARNING
ACCENT_DANGER, ACCENT_DANGER_H   = DANGER, "#DC2626"
ACCENT_PURPLE, ACCENT_PURPLE_H   = ACCENT, ACCENT_H
BTN_SECONDARY, BTN_SECONDARY_H   = BG_ELEVATED, BG_HOVER
BORDER_COLOR = SEPARATOR_COLOR   = BORDER

# ── Shape ─────────────────────────────────────────────────────────────────────
RADIUS_CARD   = 10
RADIUS_BUTTON = 8
RADIUS_CHIP   = 6
CONTROL_H     = 34
PAGE_PADX     = 28


def apply_global_button_disabled_color() -> None:
    """Readable-but-dimmed text on every disabled CTkButton. Call once at startup."""
    try:
        theme = ctk.ThemeManager.theme
        if "CTkButton" in theme:
            theme["CTkButton"]["text_color_disabled"] = [BTN_TEXT_DISABLED, BTN_TEXT_DISABLED]
    except Exception:
        pass   # never fail at startup because of a cosmetic patch


# ── Fonts (call after the root window exists) ─────────────────────────────────
def font_title()   -> ctk.CTkFont: return ctk.CTkFont(family=FONT_SEMIBOLD, size=22)
def font_heading() -> ctk.CTkFont: return ctk.CTkFont(family=FONT_SEMIBOLD, size=15)
def font_sub()     -> ctk.CTkFont: return ctk.CTkFont(family=FONT_SEMIBOLD, size=13)
def font_body()    -> ctk.CTkFont: return ctk.CTkFont(family=FONT_FAMILY, size=13)
def font_label()   -> ctk.CTkFont: return ctk.CTkFont(family=FONT_FAMILY, size=12)
def font_small()   -> ctk.CTkFont: return ctk.CTkFont(family=FONT_FAMILY, size=11)
def font_bold()    -> ctk.CTkFont: return ctk.CTkFont(family=FONT_SEMIBOLD, size=13)
def font_mono()    -> ctk.CTkFont: return ctk.CTkFont(family=FONT_MONO, size=11)
def font_number(size: int = 26) -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_SEMIBOLD, size=size)
def font_caps()    -> ctk.CTkFont:
    """Small semibold label used for table headers and field captions."""
    return ctk.CTkFont(family=FONT_SEMIBOLD, size=11)


def fmt_int(n) -> str:
    """1301 → '1,301'."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


# ── Widget factories ──────────────────────────────────────────────────────────
def card(parent, **grid_kw) -> ctk.CTkFrame:
    """Bordered surface. Pass grid kwargs to place it immediately."""
    frame = ctk.CTkFrame(
        parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD,
        border_width=1, border_color=BORDER,
    )
    if grid_kw:
        frame.grid(**grid_kw)
    return frame


def section_title(parent, text: str, hint: str = "") -> ctk.CTkFrame:
    """Card heading: semibold title plus an optional muted hint on the right."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(row, text=text, font=font_sub(), text_color=TEXT_PRIMARY,
                 anchor="w").grid(row=0, column=0, sticky="w")
    if hint:
        ctk.CTkLabel(row, text=hint, font=font_small(), text_color=TEXT_SUBTLE,
                     anchor="e").grid(row=0, column=1, sticky="e")
    return row


def page_header(parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
    """Page title row. Column 1 of the returned frame is free for actions."""
    head = ctk.CTkFrame(parent, fg_color="transparent")
    head.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(head, text=title, font=font_title(), text_color=TEXT_PRIMARY,
                 anchor="w").grid(row=0, column=0, sticky="w")
    if subtitle:
        ctk.CTkLabel(head, text=subtitle, font=font_label(), text_color=TEXT_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(2, 0))
    return head


def _button(parent, text: str, command: Optional[Callable], icon=None,
            width: int = 0, height: int = CONTROL_H, **style) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent, text=text, command=command, image=icon,
        compound="left", width=width or 0, height=height,
        corner_radius=RADIUS_BUTTON, font=font_bold(), **style,
    )


def primary_button(parent, text: str, command=None, icon=None, width: int = 0,
                   height: int = CONTROL_H) -> ctk.CTkButton:
    return _button(parent, text, command, icon, width, height,
                   fg_color=ACCENT, hover_color=ACCENT_H, text_color="#FFFFFF",
                   border_width=0)


def secondary_button(parent, text: str, command=None, icon=None, width: int = 0,
                     height: int = CONTROL_H) -> ctk.CTkButton:
    return _button(parent, text, command, icon, width, height,
                   fg_color="transparent", hover_color=BG_HOVER, text_color=TEXT_HEADING,
                   border_width=1, border_color=BORDER_STRONG)


def ghost_button(parent, text: str, command=None, icon=None, width: int = 0,
                 height: int = CONTROL_H, text_color: str = TEXT_MUTED) -> ctk.CTkButton:
    btn = _button(parent, text, command, icon, width, height,
                  fg_color="transparent", hover_color=BG_HOVER, text_color=text_color,
                  border_width=0)
    btn.configure(font=font_label())
    return btn


def icon_button(parent, icon, command=None, size: int = 32) -> ctk.CTkButton:
    return ctk.CTkButton(
        parent, text="", image=icon, command=command, width=size, height=size,
        corner_radius=RADIUS_BUTTON, fg_color="transparent", hover_color=BG_HOVER,
        border_width=0,
    )


_PILL_STYLES = {
    "success": (SUCCESS_SOFT, SUCCESS),
    "warning": (WARNING_SOFT, WARNING),
    "danger":  (DANGER_SOFT, DANGER),
    "accent":  (ACCENT_SOFT, ACCENT_TEXT),
    "neutral": (BG_ELEVATED, TEXT_MUTED),
}


def pill(parent, text: str = "", kind: str = "neutral") -> ctk.CTkLabel:
    """Small status badge with a tinted background."""
    lbl = ctk.CTkLabel(parent, text=text, font=font_caps(), corner_radius=RADIUS_CHIP,
                       padx=8, pady=1, height=22)
    set_pill(lbl, text, kind)
    return lbl


def set_pill(lbl: ctk.CTkLabel, text: str, kind: str = "neutral") -> None:
    bg, fg = _PILL_STYLES.get(kind, _PILL_STYLES["neutral"])
    lbl.configure(text=text, fg_color=bg if text else "transparent", text_color=fg)


def entry(parent, textvariable=None, width: int = 140, placeholder: str = "",
          height: int = CONTROL_H, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        parent, textvariable=textvariable, width=width, height=height,
        placeholder_text=placeholder, corner_radius=RADIUS_BUTTON,
        fg_color=BG_ELEVATED, border_color=BORDER_STRONG, border_width=1,
        text_color=TEXT_PRIMARY, placeholder_text_color=TEXT_SUBTLE,
        font=font_body(), **kw,
    )


def option_menu(parent, variable, values: list[str], width: int = 140,
                command=None, height: int = CONTROL_H) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(
        parent, variable=variable, values=values, width=width, height=height,
        command=command, corner_radius=RADIUS_BUTTON,
        fg_color=BG_ELEVATED, button_color=BG_ELEVATED, button_hover_color=BG_HOVER,
        text_color=TEXT_PRIMARY, font=font_body(),
        dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_HOVER,
        dropdown_text_color=TEXT_PRIMARY, dropdown_font=font_body(),
    )


def segmented(parent, values: list[str], variable=None, command=None,
              height: int = 32) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(
        parent, values=values, variable=variable, command=command, height=height,
        corner_radius=RADIUS_BUTTON, font=font_label(),
        fg_color=BG_ELEVATED, selected_color=BORDER_STRONG, selected_hover_color=BORDER_STRONG,
        unselected_color=BG_ELEVATED, unselected_hover_color=BG_CARD,
        text_color=TEXT_PRIMARY, border_width=2,
    )


def field_caption(parent, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=font_label(), text_color=TEXT_MUTED, anchor="w")


def divider(parent) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, height=1, fg_color=BORDER, corner_radius=0)


def make_section(parent, title: str, accent: str = TEXT_PRIMARY) -> ctk.CTkFrame:
    """Backwards-compatible helper: bordered card with a heading on row 0."""
    frame = card(parent)
    frame.grid_columnconfigure(0, weight=1)
    section_title(frame, title).grid(row=0, column=0, padx=18, pady=(16, 10), sticky="ew")
    return frame
