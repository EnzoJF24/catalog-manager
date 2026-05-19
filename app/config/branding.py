"""
Single source of truth for all user-visible identity strings.
Import from here — never hardcode these in UI, PDF, or Excel files.
"""

APP_NAME    = "Sistema Gestión de Catálogo"
APP_VERSION = "2.0.0"
APP_AUTHOR  = "Enzo Javier Fulcheri"

# Default branding injected into generated PDFs and the catalog config screen.
# The user can override these via the Catálogo UI.
COMPANY_NAME    = "Sample Company"
COMPANY_SLOGAN  = "Catálogo de Productos"
PRIMARY_COLOR   = "#C0392B"   # Red — headers, category bars, accent
SECONDARY_COLOR = "#2C3E50"   # Dark blue/grey — footer, secondary text

# Window title shown in the OS title-bar
WINDOW_TITLE = f"{APP_NAME} v{APP_VERSION}"

# Footer line shown in the sidebar
SIDEBAR_FOOTER = f"{APP_NAME}  ·  v{APP_VERSION}\n© {APP_AUTHOR}"

# Label shown in the "Sistema" sheet of generated Excel files
EXCEL_SYSTEM_LABEL = (
    f"  ⚙  DATOS INTERNOS — {APP_NAME} v{APP_VERSION}"
)

# Footer string written into PDF metadata / cover
PDF_FOOTER_LABEL = APP_NAME
