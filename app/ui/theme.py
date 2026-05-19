"""
Unified visual theme for the entire UI.
All colour constants and font specs live here.
Import and use — never hardcode hex values in individual frames.
"""
import customtkinter as ctk

# ── Base palette ──────────────────────────────────────────────────────────────
BG_BASE      = "#1a1a2e"   # main window / frame background
BG_CARD      = "#16213e"   # cards, sections, inner panels
BG_ELEVATED  = "#0f3460"   # elevated surfaces (toolbar, drop-zone)
BG_DEEPEST   = "#0a0a1a"   # log boxes, deepest level

# ── Accent colours ────────────────────────────────────────────────────────────
ACCENT_PRIMARY   = "#C0392B"   # red — primary action, category bars, PDF header
ACCENT_PRIMARY_H = "#a93226"   # red hover

ACCENT_BLUE      = "#2980b9"   # secondary actions (export, links)
ACCENT_BLUE_H    = "#1f618d"

ACCENT_SUCCESS   = "#27ae60"   # success states, active products
ACCENT_SUCCESS_H = "#219a52"

ACCENT_WARNING   = "#f39c12"   # warnings, reimport apply button
ACCENT_WARNING_H = "#d68910"

ACCENT_DANGER    = "#7f1c1c"   # destructive actions (clear, delete)
ACCENT_DANGER_H  = "#6b1010"

ACCENT_PURPLE    = "#8e44ad"   # PDF generation (kept as tertiary only)
ACCENT_PURPLE_H  = "#7d3c98"

# ── Text colours ──────────────────────────────────────────────────────────────
TEXT_PRIMARY = "#ffffff"
TEXT_HEADING = "#ecf0f1"
TEXT_MUTED   = "#7f8c8d"
TEXT_SUBTLE  = "#566573"
TEXT_LINK    = "#3498db"

# Text color for buttons in disabled state — semi-bright off-white that
# stays readable on every saturated bg (green, red, purple, blue).
# Applied globally via apply_global_button_disabled_color() at startup.
BTN_TEXT_DISABLED = "#dfe6e9"


def apply_global_button_disabled_color() -> None:
    """
    Patch CTk's default text_color_disabled for CTkButton, so every disabled
    button across the app shows a readable label on saturated backgrounds
    (green Save, red Delete, etc.). Call ONCE after set_default_color_theme.
    """
    try:
        theme = ctk.ThemeManager.theme
        if "CTkButton" in theme:
            # text_color_disabled is stored as [light, dark] in CTk themes
            theme["CTkButton"]["text_color_disabled"] = [BTN_TEXT_DISABLED, BTN_TEXT_DISABLED]
    except Exception:
        # Never fail at startup just because of a cosmetic patch
        pass

# ── Status colours for product rows ──────────────────────────────────────────
STATUS_ACTIVE_BG   = "#1A6B3C"
STATUS_INACTIVE_BG = "#8B0000"
STATUS_ACTIVE_FG   = "#E8F8E8"
STATUS_INACTIVE_FG = "#F8E8E8"

# ── Border / separator ────────────────────────────────────────────────────────
BORDER_COLOR    = "#0f3460"
SEPARATOR_COLOR = "#0f3460"

# ── Secondary / utility buttons ──────────────────────────────────────────────
# Use for refresh, folder shortcuts, and neutral utility actions.
# Keeps the dark-blue family — distinct from backgrounds but not distracting.
BTN_SECONDARY   = "#1a4a7a"
BTN_SECONDARY_H = "#1f5c99"

# ── Corner radius presets ─────────────────────────────────────────────────────
RADIUS_CARD    = 12
RADIUS_BUTTON  = 10
RADIUS_CHIP    = 8

# ── Font helpers (call after ctk.set_appearance_mode) ────────────────────────
def font_title()   -> ctk.CTkFont: return ctk.CTkFont(size=24, weight="bold")
def font_heading() -> ctk.CTkFont: return ctk.CTkFont(size=16, weight="bold")
def font_sub()     -> ctk.CTkFont: return ctk.CTkFont(size=14, weight="bold")
def font_body()    -> ctk.CTkFont: return ctk.CTkFont(size=13)
def font_small()   -> ctk.CTkFont: return ctk.CTkFont(size=11)
def font_label()   -> ctk.CTkFont: return ctk.CTkFont(size=12)
def font_mono()    -> ctk.CTkFont: return ctk.CTkFont(family="Courier", size=11)
def font_bold()    -> ctk.CTkFont: return ctk.CTkFont(size=13, weight="bold")


# ── Reusable section builder ──────────────────────────────────────────────────
def make_section(parent, title: str, accent: str = ACCENT_PRIMARY) -> ctk.CTkFrame:
    """
    Standard section card with a colored title.
    Returns the frame; caller adds children inside it.
    """
    frame = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=RADIUS_CARD)
    frame.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        frame, text=title,
        font=font_heading(),
        text_color=accent,
    ).grid(row=0, column=0, padx=16, pady=(14, 8), sticky="w")
    return frame
