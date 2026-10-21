"""
Catalog Manager — Entry point.
Run: python main.py
"""
import sys
import traceback
from pathlib import Path

# Ensure project root is in path when run directly
sys.path.insert(0, str(Path(__file__).parent))


def _show_error_dialog(title: str, message: str):
    """Best-effort fallback dialog; never raises."""
    try:
        from tkinter import Tk, messagebox
        root = Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        # If even Tk fails, fall back to stderr (will be visible if launched from a terminal)
        print(f"\n❌ {title}\n{message}\n", file=sys.stderr)


def main():
    try:
        from app.core.app_controller import AppController
        from app.ui.main_window import MainWindow

    except ImportError as e:
        _show_error_dialog(
            "Missing dependency",
            f"A required module could not be imported:\n\n{e}\n\n"
            f"Make sure the dependencies are installed:\n"
            f"    pip install -r requirements.txt",
        )
        sys.exit(1)

    try:
        controller = AppController()
        app = MainWindow(controller)
        app.mainloop()

    except Exception as e:
        tb = traceback.format_exc()
        # Log the full traceback to stderr for debugging
        print(tb, file=sys.stderr)
        _show_error_dialog(
            "Startup error",
            f"An unexpected error occurred:\n\n{e}\n\n"
            f"Check the log file in the 'logs/' folder "
            f"for details.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
