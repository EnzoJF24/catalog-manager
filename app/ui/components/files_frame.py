"""
FilesFrame: explorador de archivos generados (PDFs y Excels).
Permite abrir o eliminar cualquier archivo sin salir de la aplicación.
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from tkinter import messagebox
import customtkinter as ctk

from app.core.app_controller import AppController
from app.config.settings import settings
from app.ui.theme import (
    BG_BASE, BG_CARD, BG_ELEVATED,
    ACCENT_BLUE, ACCENT_BLUE_H,
    ACCENT_DANGER, ACCENT_DANGER_H,
    BTN_SECONDARY, BTN_SECONDARY_H,
    TEXT_PRIMARY, TEXT_MUTED, TEXT_SUBTLE,
    RADIUS_CARD,
    font_title, font_label, font_small, font_bold,
)


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _open_path(path: Path):
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror("Error al abrir", str(e))


class FileCard(ctk.CTkFrame):
    """Fila compacta que representa un archivo generado."""

    def __init__(self, parent, file_path: Path, on_delete, **kwargs):
        super().__init__(parent, fg_color=BG_ELEVATED, corner_radius=6, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self._path = file_path

        ext   = file_path.suffix.lower()
        icon  = "📄" if ext == ".pdf" else "📗" if ext in (".xlsx", ".xls") else "📁"
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        size  = _human_size(file_path.stat().st_size)

        ctk.CTkLabel(self, text=icon, font=ctk.CTkFont(size=18), width=30).grid(
            row=0, column=0, padx=(10, 6), pady=8
        )

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew", pady=6)
        info.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            info, text=file_path.name,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY, anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            info,
            text=f"{mtime}  ·  {size}",
            font=font_small(), text_color=TEXT_MUTED, anchor="w",
        ).grid(row=1, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=(6, 10), pady=8)

        ctk.CTkButton(
            btn_frame, text="Abrir", width=74, height=28,
            fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_H,
            font=font_small(), corner_radius=6,
            command=lambda: _open_path(file_path),
        ).grid(row=0, column=0, padx=2)

        ctk.CTkButton(
            btn_frame, text="📂 Carpeta", width=90, height=28,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_H,
            font=font_small(), corner_radius=6,
            command=lambda: _open_path(file_path.parent),
        ).grid(row=0, column=1, padx=2)

        ctk.CTkButton(
            btn_frame, text="✕", width=28, height=28,
            fg_color=ACCENT_DANGER, hover_color=ACCENT_DANGER_H,
            font=font_small(), corner_radius=6,
            command=lambda: on_delete(file_path),
        ).grid(row=0, column=2, padx=2)


class FilesFrame(ctk.CTkFrame):
    """
    Muestra todos los PDFs y Excels generados.
    Permite abrir, ir a la carpeta o eliminar individualmente.
    """

    def __init__(self, parent, controller: AppController):
        super().__init__(parent, fg_color=BG_BASE, corner_radius=0)
        self.controller = controller
        self._tab: str  = "pdf"
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Título
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=24, pady=(24, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="Archivos generados",
            font=font_title(), text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header, text="🔄 Actualizar", width=110, height=32,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_H,
            font=font_small(),
            command=self._refresh,
        ).grid(row=0, column=1, sticky="e")

        # Tabs
        tab_row = ctk.CTkFrame(self, fg_color="transparent")
        tab_row.grid(row=1, column=0, padx=24, pady=(8, 0), sticky="w")

        self._tab_pdf = ctk.CTkButton(
            tab_row, text="📄 PDFs generados", width=160, height=34,
            corner_radius=8,
            fg_color=BTN_SECONDARY, hover_color=BTN_SECONDARY_H,
            font=font_label(),
            command=lambda: self._switch_tab("pdf"),
        )
        self._tab_pdf.grid(row=0, column=0, padx=(0, 4))

        self._tab_xls = ctk.CTkButton(
            tab_row, text="📗 Excels generados", width=170, height=34,
            corner_radius=8,
            fg_color="transparent", hover_color=BTN_SECONDARY,
            font=font_label(),
            command=lambda: self._switch_tab("excel"),
        )
        self._tab_xls.grid(row=0, column=1, padx=4)

        # Atajos de carpeta
        short_row = ctk.CTkFrame(self, fg_color="transparent")
        short_row.grid(row=2, column=0, padx=24, pady=(4, 8), sticky="w")

        ctk.CTkButton(
            short_row, text="📂 Abrir carpeta PDFs", width=160, height=28,
            fg_color="transparent", hover_color=BG_CARD,
            text_color=TEXT_MUTED, font=font_small(),
            command=lambda: _open_path(settings.PDFS_DIR),
        ).grid(row=0, column=0, padx=(0, 4))

        ctk.CTkButton(
            short_row, text="📂 Abrir carpeta Excels", width=170, height=28,
            fg_color="transparent", hover_color=BG_CARD,
            text_color=TEXT_MUTED, font=font_small(),
            command=lambda: _open_path(settings.EXCELS_DIR),
        ).grid(row=0, column=1, padx=4)

        # Lista scrollable
        self.list_frame = ctk.CTkScrollableFrame(
            self, fg_color=BG_CARD, corner_radius=RADIUS_CARD,
        )
        self.list_frame.grid(row=3, column=0, padx=24, pady=(0, 16), sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)

    # ── Lógica ────────────────────────────────────────────────────────────────

    def on_show(self):
        self._refresh()

    def on_hide(self):
        pass

    def _switch_tab(self, tab: str):
        self._tab = tab
        active_cfg   = dict(fg_color=BTN_SECONDARY, text_color=TEXT_PRIMARY)
        inactive_cfg = dict(fg_color="transparent", text_color=TEXT_MUTED)
        if tab == "pdf":
            self._tab_pdf.configure(**active_cfg)
            self._tab_xls.configure(**inactive_cfg)
        else:
            self._tab_pdf.configure(**inactive_cfg)
            self._tab_xls.configure(**active_cfg)
        self._refresh()

    def _refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        if self._tab == "pdf":
            folder = settings.PDFS_DIR
            exts   = {".pdf"}
        else:
            folder = settings.EXCELS_DIR
            exts   = {".xlsx", ".xls"}

        files = sorted(
            [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ) if folder.exists() else []

        if not files:
            ctk.CTkLabel(
                self.list_frame,
                text="No hay archivos generados todavía.",
                text_color=TEXT_SUBTLE, font=font_label(),
            ).grid(row=0, column=0, padx=24, pady=40)
            return

        for i, f in enumerate(files):
            card = FileCard(self.list_frame, f, on_delete=self._confirm_delete)
            card.grid(row=i, column=0, padx=4, pady=3, sticky="ew")

    def _confirm_delete(self, path: Path):
        ok = messagebox.askyesno(
            "Eliminar archivo",
            f"¿Eliminar '{path.name}'?\nEsta acción no se puede deshacer.",
        )
        if ok:
            try:
                path.unlink()
                self._refresh()
            except Exception as e:
                messagebox.showerror("Error", str(e))
