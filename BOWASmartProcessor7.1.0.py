from pathlib import Path
import fitz  # PyMuPDF
from pyzbar import pyzbar
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
from PIL import Image, ImageTk, ImageOps
import shutil
import threading
import os
import csv
from datetime import datetime
import time
import re
import json
import subprocess
import sys
import webbrowser
import urllib.request
import urllib.error
from io import BytesIO
from reportlab.pdfgen import canvas as reportlab_canvas
from reportlab.graphics.barcode import createBarcodeDrawing
# ReportLab โหลดชนิดบาร์โค้ดบางส่วนแบบ dynamic; import นี้ช่วยให้ PyInstaller
# ตรวจพบ Code128 และรวมโมดูลไว้ใน executable ได้อย่างแน่นอน
from reportlab.graphics.barcode import code128 as reportlab_code128
from reportlab.graphics.barcode import qr as reportlab_qr
from reportlab.graphics import renderPDF

# --- Configuration ---
PROGRAM_NAME = "BOWA Smart Processor"
VERSION = "7.1.0"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ICON_PATH = APP_DIR / "bowa.ico"
PORTABLE_FONT_DIR = APP_DIR / "portable_fonts"
# URL ไฟล์ JSON สำหรับตรวจสอบรุ่นล่าสุด เช่น GitHub Raw หรือ Web Server ขององค์กร
UPDATE_MANIFEST_URL = "https://freshapp.rf.gd/bowa/update_manifest.json"
UPDATE_CHECK_TIMEOUT = 5
# ฟอนต์ที่รองรับภาษาไทยและมีไฟล์ใช้งานได้จริง: ชื่อ -> (ไฟล์ปกติ, ไฟล์ตัวหนา)
LABEL_FONT_FILES = {
    "Leelawadee UI": (("leelawui.ttf",), ("leelauib.ttf",)),
    "Tahoma": (("tahoma.ttf",), ("tahomabd.ttf",)),
    "TH Sarabun New": (("THSarabunNew.ttf",), ("THSarabunNew Bold.ttf", "THSarabunNewBold.ttf")),
}
DEFAULT_LABEL_FONT = "Leelawadee UI"

class BowaApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{PROGRAM_NAME} v{VERSION}")
        try:
            self.root.iconbitmap(default=str(ICON_PATH))
        except tk.TclError:
            # เปิดโปรแกรมได้แม้ไม่พบไฟล์ไอคอนหรือระบบไม่รองรับ ICO
            pass
        self.root.geometry("900x620")
        self.root.configure(bg="#F0F2F5")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_busy = False

        # --- Modern Style Definition ---
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Colors
        self.PRIMARY = "#1A237E"
        self.ACCENT = "#2196F3"
        self.SUCCESS = "#4CAF50"
        self.DANGER = "#F44336"
        self.WARNING = "#FF9800"
        self.PURPLE = "#673AB7"
        self.BG_LIGHT = "#F0F2F5"
        self.WHITE = "#FFFFFF"
        self.TEXT_DARK = "#2C3E50"
        self.TEXT_LIGHT = "#7F8C8D"

        # Preview State
        self.current_preview_img = None
        self.zoom_level = 1.0
        self.img_pos_x = 0
        self.img_pos_y = 0
        self.drag_start_x = 0
        self.drag_start_y = 0

        # Configure Styles
        self.style.configure("TNotebook", background=self.BG_LIGHT, borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#E0E0E0", padding=[10, 4], font=('Segoe UI', 8))
        self.style.map("TNotebook.Tab", background=[("selected", self.PRIMARY)], foreground=[("selected", self.WHITE)])
        self.style.configure("TButton", font=('Segoe UI', 8), padding=4)
        self.style.configure("Accent.TButton", foreground=self.WHITE, background=self.ACCENT, borderwidth=0)
        self.style.map("Accent.TButton", background=[("active", "#1976D2")])
        self.style.configure("Success.TButton", foreground=self.WHITE, background=self.SUCCESS, borderwidth=0)
        self.style.map("Success.TButton", background=[("active", "#388E3C")])
        self.style.configure("Warning.TButton", foreground=self.WHITE, background=self.WARNING, borderwidth=0)
        self.style.map("Warning.TButton", background=[("active", "#F57C00")])
        self.style.configure("Purple.TButton", foreground=self.WHITE, background=self.PURPLE, borderwidth=0)
        self.style.map("Purple.TButton", background=[("active", "#5E35B1")])
        self.style.configure("TLabelframe", background=self.WHITE, bordercolor="#E0E0E0", relief="flat")
        self.style.configure("TLabelframe.Label", background=self.WHITE, font=('Segoe UI', 9, 'bold'), foreground=self.PRIMARY)
        self.style.configure("Treeview", font=('Segoe UI', 8), rowheight=18, borderwidth=0)
        self.style.configure("Treeview.Heading", font=('Segoe UI', 8, 'bold'), background="#F8F9FA", foreground=self.TEXT_DARK)

        # --- Main Layout ---
        self.header = tk.Frame(self.root, bg=self.PRIMARY, height=60)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)
        
        header_content = tk.Frame(self.header, bg=self.PRIMARY)
        header_content.pack(side="left", padx=12, pady=8)
        tk.Label(header_content, text="BOWA SMART PROCESSOR", font=("Segoe UI", 14, "bold"), fg=self.WHITE, bg=self.PRIMARY).pack(anchor="w")
        tk.Label(header_content, text="Enterprise Document Automation Solution", font=("Segoe UI", 8), fg="#C5CAE9", bg=self.PRIMARY).pack(anchor="w")
        self.update_button = ttk.Button(self.header, text="ตรวจสอบอัปเดต", command=self.check_for_updates_manual)
        self.update_button.pack(side="right", padx=(4, 8))
        tk.Label(self.header, text=f"v{VERSION}", font=("Segoe UI", 9, "bold"), fg=self.WHITE, bg=self.PRIMARY, padx=8, pady=2).pack(side="right", padx=10)

        self.main_container = tk.Frame(self.root, bg=self.BG_LIGHT)
        self.main_container.pack(expand=True, fill="both", padx=8, pady=8)

        self.notebook = ttk.Notebook(self.main_container)
        self.notebook.pack(expand=True, fill="both")

        self.tab1 = ttk.Frame(self.notebook)
        self.tab2 = ttk.Frame(self.notebook)
        self.tab3 = ttk.Frame(self.notebook)
        self.tab4 = ttk.Frame(self.notebook)

        self.notebook.add(self.tab1, text="  🔄  Auto Rename  ")
        self.notebook.add(self.tab2, text="  🔍  Search & Print  ")
        self.notebook.add(self.tab3, text="  📄  PDF Tools  ")
        self.notebook.add(self.tab4, text="  🏷️  Label Designer  ")

        self.setup_tab1()
        self.setup_tab2()
        self.setup_tab3()
        self.setup_tab4()
        self.root.after(1500, self.check_for_updates_silent)

    @staticmethod
    def normalize_version(value):
        parts = re.findall(r"\d+", str(value or "0"))
        return tuple(int(p) for p in (parts + [0, 0, 0])[:3])

    def check_for_updates_manual(self):
        self.check_for_updates(silent=False)

    def check_for_updates_silent(self):
        self.check_for_updates(silent=True)

    def check_for_updates(self, silent=True):
        if not UPDATE_MANIFEST_URL:
            if not silent: messagebox.showinfo("ตรวจสอบอัปเดต", "ยังไม่ได้กำหนด UPDATE_MANIFEST_URL ในโค้ดโปรแกรม")
            return
        self.update_button.configure(state="disabled")
        def worker():
            result = None; error = None
            try:
                request = urllib.request.Request(UPDATE_MANIFEST_URL, headers={"User-Agent": f"{PROGRAM_NAME}/{VERSION}"})
                with urllib.request.urlopen(request, timeout=UPDATE_CHECK_TIMEOUT) as response:
                    if response.status != 200: raise OSError(f"HTTP {response.status}")
                    result = json.loads(response.read().decode("utf-8"))
            except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
                error = str(exc)
            self.root.after(0, lambda: self.finish_update_check(result, error, silent))
        threading.Thread(target=worker, daemon=True).start()

    def finish_update_check(self, manifest, error, silent):
        self.update_button.configure(state="normal")
        if error:
            if not silent: messagebox.showwarning("ตรวจสอบอัปเดตไม่สำเร็จ", f"ไม่สามารถเชื่อมต่อแหล่งข้อมูลอัปเดตได้\n{error}")
            return
        latest = str(manifest.get("version", "")).strip() if isinstance(manifest, dict) else ""
        if not latest or self.normalize_version(latest) <= self.normalize_version(VERSION):
            if not silent: messagebox.showinfo("ตรวจสอบอัปเดต", f"คุณกำลังใช้เวอร์ชันล่าสุด v{VERSION}")
            return
        notes = str(manifest.get("notes", "")).strip() if isinstance(manifest, dict) else ""
        download_url = str(manifest.get("url", "")).strip() if isinstance(manifest, dict) else ""
        text = f"พบเวอร์ชันใหม่ v{latest}\n\n{notes}" if notes else f"พบเวอร์ชันใหม่ v{latest}"
        if messagebox.askyesno("มีเวอร์ชันใหม่", text + "\n\nเปิดหน้าดาวน์โหลดหรือไม่?") and download_url:
            webbrowser.open(download_url)

    def add_right_click_menu(self, widget):
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="ตัด (Cut)", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="คัดลอก (Copy)", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="วาง (Paste)", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="เลือกทั้งหมด (Select All)", command=lambda: widget.tag_add("sel", "1.0", "end"))
        widget.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def add_tooltip(self, widget, text):
        tip = [None]
        def show(_event):
            if tip[0] is not None: return
            tip[0] = tk.Toplevel(widget); tip[0].wm_overrideredirect(True); tip[0].attributes("-topmost", True)
            tk.Label(tip[0], text=text, bg="#263238", fg="white", padx=6, pady=3, font=("Segoe UI", 8)).pack()
            tip[0].wm_geometry(f"+{widget.winfo_rootx()+widget.winfo_width()+4}+{widget.winfo_rooty()+widget.winfo_height()+4}")
        def hide(_event):
            if tip[0] is not None: tip[0].destroy(); tip[0] = None
        widget.bind("<Enter>", show); widget.bind("<Leave>", hide)

    # --- TAB 4: LABEL DESIGNER ---
    def setup_tab4(self):
        self.label_fields, self.label_columns, self.label_sample = [], [], {}
        self.label_rows, self.label_row_index = [], 0
        self.label_orientation = tk.StringVar(value="แนวตั้ง")
        self.label_custom_width = tk.DoubleVar(value=100.0); self.label_custom_height = tk.DoubleVar(value=150.0)
        self.label_margin_left = tk.DoubleVar(value=0.0); self.label_margin_top = tk.DoubleVar(value=0.0)
        self.label_offset_x = tk.DoubleVar(value=0.0); self.label_offset_y = tk.DoubleVar(value=0.0)
        self.label_selected_index = None
        self.label_grid_var = tk.BooleanVar(value=True)
        self.label_zoom_var = tk.DoubleVar(value=1.0)
        self._preview_drag_index = None
        self._preview_drag_start = None
        self._preview_drag_snapshot = None
        self._label_undo_stack = []
        self._label_redo_stack = []
        self.label_sheet_rows = tk.IntVar(value=1)
        self.label_sheet_columns = tk.IntVar(value=1)
        self.label_sheet_gap_x = tk.DoubleVar(value=0.0)
        self.label_sheet_gap_y = tk.DoubleVar(value=0.0)
        self.label_settings_path = Path.home() / ".bowa_smart_processor_label_settings.json"
        self.label_progress_var = tk.DoubleVar(value=0.0)
        self.label_progress_text = tk.StringVar(value="พร้อมทำงาน")
        self.label_print_status = tk.StringVar(value="คิวพิมพ์: ยังไม่มีงาน")
        container = tk.Frame(self.tab4, bg=self.WHITE, padx=8, pady=4)
        container.pack(fill="both", expand=True)
        title = tk.Frame(container, bg=self.WHITE); title.pack(fill="x")
        tk.Label(title, text="Label Template Designer", font=("Segoe UI", 12, "bold"), fg=self.PRIMARY, bg=self.WHITE).pack(side="left")
        self.label_size_text = tk.Label(title, text="ขนาดลาเบล 100 × 150 มม.", font=("Segoe UI", 8), fg=self.TEXT_LIGHT, bg=self.WHITE); self.label_size_text.pack(side="right")
        toolbar = tk.Frame(container, bg=self.WHITE); toolbar.pack(fill="x", pady=(5, 4))
        def tool_button(parent, icon, tip, command, style=None):
            button = ttk.Button(parent, text=icon, width=3, command=command, style=style or "TButton")
            button.pack(side="left", padx=2); self.add_tooltip(button, tip); return button
        data_group = tk.LabelFrame(toolbar, text="ข้อมูล", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=3, pady=2); data_group.pack(side="left", padx=(0, 5))
        tool_button(data_group, "📂", "โหลดข้อมูล CSV", self.load_label_csv, "Accent.TButton")
        tool_button(data_group, "📥", "โหลดเทมเพลต JSON", self.load_label_template)
        tool_button(data_group, "💾", "บันทึกเทมเพลต JSON", self.save_label_template, "Success.TButton")
        edit_group = tk.LabelFrame(toolbar, text="ฟิลด์", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=3, pady=2); edit_group.pack(side="left", padx=5)
        tool_button(edit_group, "＋", "เพิ่มฟิลด์จาก CSV", self.add_label_field)
        tool_button(edit_group, "T+", "เพิ่มข้อความคงที่", self.add_static_label_field)
        tool_button(edit_group, "🖼", "เพิ่มรูปภาพลงในลาเบล", self.add_image_label_field)
        tool_button(edit_group, "⧉", "ทำสำเนาฟิลด์ที่เลือก", self.duplicate_label_field)
        tool_button(edit_group, "↑", "เลื่อนฟิลด์ขึ้น", lambda: self.move_label_field(-1))
        tool_button(edit_group, "↓", "เลื่อนฟิลด์ลง", lambda: self.move_label_field(1))
        tool_button(edit_group, "−", "ลบฟิลด์ที่เลือก", self.delete_label_field)
        tool_button(edit_group, "⌫", "ล้างฟิลด์ทั้งหมด", self.clear_label_fields)
        tool_button(edit_group, "↶", "Undo การลากวัตถุ", self.undo_label_move)
        tool_button(edit_group, "↷", "Redo การลากวัตถุ", self.redo_label_move)
        output_group = tk.LabelFrame(toolbar, text="ส่งออก", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=3, pady=2); output_group.pack(side="left", padx=5)
        tool_button(output_group, "PDF", "สร้าง PDF จาก CSV", self.create_label_pdf, "Success.TButton")
        tool_button(output_group, "🖨", "พิมพ์ลาเบล", self.print_labels, "Warning.TButton")
        tool_button(output_group, "⚙", "ตั้งค่าระยะขอบและ Offset", self.open_label_print_settings)
        tool_button(output_group, "▦", "ตั้งค่าพิมพ์หลายแถว/หลายคอลัมน์", self.open_multirow_settings)
        orient_group = tk.LabelFrame(toolbar, text="หน้า", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=3, pady=2); orient_group.pack(side="left", padx=5)
        tool_button(orient_group, "📐", "กำหนดขนาดกระดาษเอง", self.open_custom_size_dialog)
        orientation_box = ttk.Combobox(orient_group, textvariable=self.label_orientation, values=("แนวตั้ง", "แนวนอน"), state="readonly", width=9)
        orientation_box.pack(side="left", padx=2); orientation_box.bind("<<ComboboxSelected>>", lambda _e: self.on_label_orientation_change())
        view_group = tk.LabelFrame(toolbar, text="มุมมอง", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=3, pady=2); view_group.pack(side="left", padx=5)
        ttk.Checkbutton(view_group, text="กริด", variable=self.label_grid_var, command=self.draw_label_preview).pack(side="left", padx=2)
        ttk.Button(view_group, text="−", width=3, command=lambda: self.change_label_zoom(-0.1)).pack(side="left")
        ttk.Button(view_group, text="100%", width=5, command=self.reset_label_zoom).pack(side="left")
        ttk.Button(view_group, text="+", width=3, command=lambda: self.change_label_zoom(0.1)).pack(side="left")
        body = tk.PanedWindow(container, orient=tk.HORIZONTAL, sashwidth=6, bg="#D0D7DE", opaqueresize=True); body.pack(fill="both", expand=True)
        left, right = tk.Frame(body, bg=self.WHITE, padx=4), tk.Frame(body, bg="#F8F9FA", padx=8)
        body.add(left, stretch="always", minsize=360); body.add(right, stretch="never", minsize=360)
        tk.Label(left, text="ฟิลด์ในเทมเพลต", font=("Segoe UI", 9, "bold"), fg=self.PRIMARY, bg=self.WHITE).pack(anchor="w")
        cols = ("field", "csv", "x", "y", "size", "align")
        self.label_tree = ttk.Treeview(left, columns=cols, show="headings", height=6)
        headings = {"field":"ชื่อฟิลด์", "csv":"คอลัมน์ CSV", "x":"X", "y":"Y", "size":"ขนาด", "align":"จัดแนว"}
        widths = {"field":90, "csv":105, "x":45, "y":45, "size":48, "align":65}
        for col in cols: self.label_tree.heading(col, text=headings[col]); self.label_tree.column(col, width=widths[col], anchor="center")
        self.label_tree.pack(fill="both", expand=True, pady=4); self.label_tree.bind("<<TreeviewSelect>>", self.select_label_field)
        editor = tk.LabelFrame(left, text="แก้ไขฟิลด์", bg=self.WHITE, fg=self.PRIMARY, padx=3, pady=2); editor.pack(fill="x", pady=2)
        self.label_vars = {k: tk.StringVar() for k in ("name", "csv", "text", "x", "y", "width", "height", "size", "align")}
        self.label_bold_var = tk.BooleanVar(value=False); self.label_italic_var = tk.BooleanVar(value=False); self.label_underline_var = tk.BooleanVar(value=False)
        self.label_image_mode_var = tk.StringVar(value="Contain"); self.label_font_family_var = tk.StringVar(value=DEFAULT_LABEL_FONT); self.label_type_var = tk.StringVar(value="ข้อความ")
        identity = tk.LabelFrame(editor, text="ข้อมูลฟิลด์", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=2, pady=1); identity.pack(fill="x", pady=(0, 1))
        for col in (1, 3): identity.columnconfigure(col, weight=1)
        tk.Label(identity, text="ชื่อ", bg=self.WHITE).grid(row=0, column=0, sticky="w", padx=2); tk.Entry(identity, textvariable=self.label_vars["name"], width=12).grid(row=0, column=1, sticky="ew", padx=2)
        tk.Label(identity, text="CSV", bg=self.WHITE).grid(row=0, column=2, sticky="w", padx=2); self.label_csv_combo = ttk.Combobox(identity, textvariable=self.label_vars["csv"], state="readonly", width=12); self.label_csv_combo.grid(row=0, column=3, sticky="ew", padx=2)
        tk.Label(identity, text="ชนิด", bg=self.WHITE).grid(row=1, column=0, sticky="w", padx=2); ttk.Combobox(identity, textvariable=self.label_type_var, values=("ข้อความ", "Barcode", "QR Code", "รูปภาพ"), state="readonly", width=12).grid(row=1, column=1, sticky="w", padx=2)
        tk.Label(identity, text="ข้อความ", bg=self.WHITE).grid(row=1, column=2, sticky="w", padx=2); tk.Entry(identity, textvariable=self.label_vars["text"], width=12).grid(row=1, column=3, sticky="ew", padx=2)
        layout = tk.LabelFrame(editor, text="ตำแหน่งและขนาด (มม.)", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=2, pady=1); layout.pack(fill="x", pady=1)
        layout_items = (("X", "x"), ("Y", "y"), ("กว้าง", "width"), ("สูง", "height"))
        for idx, (caption, key) in enumerate(layout_items):
            col = idx * 2; tk.Label(layout, text=caption, bg=self.WHITE).grid(row=0, column=col, sticky="w", padx=2); tk.Entry(layout, textvariable=self.label_vars[key], width=7).grid(row=0, column=col+1, sticky="w", padx=2)
        style = tk.LabelFrame(editor, text="รูปแบบข้อความ", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=2, pady=1); style.pack(fill="x", pady=1)
        tk.Label(style, text="ฟอนต์", bg=self.WHITE).grid(row=0, column=0, sticky="w", padx=2); ttk.Combobox(style, textvariable=self.label_font_family_var, values=tuple(LABEL_FONT_FILES), state="readonly", width=14).grid(row=0, column=1, sticky="w", padx=2)
        tk.Label(style, text="ขนาด", bg=self.WHITE).grid(row=0, column=2, sticky="w", padx=2); ttk.Combobox(style, textvariable=self.label_vars["size"], values=tuple(str(n) for n in range(6, 73)), state="normal", width=6).grid(row=0, column=3, sticky="w", padx=2)
        tk.Label(style, text="จัดแนว", bg=self.WHITE).grid(row=0, column=4, sticky="w", padx=2); ttk.Combobox(style, textvariable=self.label_vars["align"], values=("left", "center", "right"), state="readonly", width=8).grid(row=0, column=5, sticky="w", padx=2)
        ttk.Checkbutton(style, text="หนา", variable=self.label_bold_var).grid(row=1, column=0, sticky="w", padx=2); ttk.Checkbutton(style, text="เอียง", variable=self.label_italic_var).grid(row=1, column=1, sticky="w", padx=2); ttk.Checkbutton(style, text="ขีดเส้นใต้", variable=self.label_underline_var).grid(row=1, column=2, columnspan=2, sticky="w", padx=2)
        image = tk.LabelFrame(editor, text="รูปภาพ", bg=self.WHITE, fg=self.TEXT_LIGHT, padx=2, pady=1); image.pack(fill="x", pady=1)
        tk.Label(image, text="การจัดวาง", bg=self.WHITE).pack(side="left", padx=2); ttk.Combobox(image, textvariable=self.label_image_mode_var, values=("Contain", "Cover"), state="readonly", width=10).pack(side="left", padx=2)
        tk.Label(right, text="ตัวอย่างลาเบล", font=("Segoe UI", 9, "bold"), fg=self.PRIMARY, bg="#F8F9FA").pack(anchor="w")
        self.label_preview = tk.Canvas(right, width=300, height=280, bg="white", highlightthickness=1, highlightbackground="#BDBDBD"); self.label_preview.pack(pady=(3, 2))
        self.label_preview.bind("<Button-1>", self.preview_drag_start)
        self.label_preview.bind("<B1-Motion>", self.preview_drag_motion)
        self.label_preview.bind("<ButtonRelease-1>", self.preview_drag_end)
        preview_nav = tk.Frame(right, bg="#F8F9FA"); preview_nav.pack(fill="x", pady=(0, 2))
        ttk.Button(preview_nav, text="◀ ก่อนหน้า", command=self.previous_label_row).pack(side="left")
        self.label_row_status = tk.Label(preview_nav, text="แถว 0 / 0", bg="#F8F9FA", fg=self.TEXT_DARK); self.label_row_status.pack(side="left", expand=True)
        ttk.Button(preview_nav, text="ถัดไป ▶", command=self.next_label_row).pack(side="right")
        progress_frame = tk.Frame(right, bg="#F8F9FA"); progress_frame.pack(fill="x", pady=(3, 0))
        self.label_progress_bar = ttk.Progressbar(progress_frame, variable=self.label_progress_var, maximum=100, mode="determinate")
        self.label_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(progress_frame, textvariable=self.label_progress_text, bg="#F8F9FA", fg=self.TEXT_LIGHT, width=24, anchor="w").pack(side="right")
        print_status = tk.Frame(right, bg="#F8F9FA"); print_status.pack(fill="x", pady=(2, 0))
        tk.Label(print_status, textvariable=self.label_print_status, bg="#F8F9FA", fg=self.TEXT_DARK, anchor="w").pack(side="left", fill="x", expand=True)
        self.setup_live_preview_traces()
        self.load_last_label_settings()
        self.draw_label_preview()

    def save_last_label_settings(self):
        try:
            width, height = self.get_label_dimensions()
            data = {"version": 1, "page": {"width_mm": width, "height_mm": height, "orientation": self.label_orientation.get(), "custom_width_mm": self.label_custom_width.get(), "custom_height_mm": self.label_custom_height.get(), "margin_left_mm": self.label_margin_left.get(), "margin_top_mm": self.label_margin_top.get(), "offset_x_mm": self.label_offset_x.get(), "offset_y_mm": self.label_offset_y.get()}, "fields": self.label_fields}
            self.label_settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    def load_last_label_settings(self):
        if not self.label_settings_path.exists(): return
        try:
            data = json.loads(self.label_settings_path.read_text(encoding="utf-8")); page = data.get("page", {}); fields = data.get("fields", [])
            orientation = page.get("orientation", "แนวตั้ง")
            if orientation in ("แนวตั้ง", "แนวนอน", "กำหนดเอง"): self.label_orientation.set(orientation)
            for var, key in ((self.label_custom_width, "custom_width_mm"), (self.label_custom_height, "custom_height_mm"), (self.label_margin_left, "margin_left_mm"), (self.label_margin_top, "margin_top_mm"), (self.label_offset_x, "offset_x_mm"), (self.label_offset_y, "offset_y_mm")):
                try: var.set(float(page.get(key, var.get())))
                except (TypeError, ValueError): pass
            if isinstance(fields, list): self.label_fields = fields
            self.refresh_label_tree(); self.on_label_orientation_change()
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def setup_live_preview_traces(self):
        variables = list(self.label_vars.values()) + [self.label_bold_var, self.label_italic_var, self.label_underline_var, self.label_image_mode_var, self.label_font_family_var, self.label_type_var]
        for variable in variables:
            variable.trace_add("write", lambda *_args: self.schedule_live_preview())

    def schedule_live_preview(self):
        if getattr(self, "_live_preview_after", None):
            try: self.root.after_cancel(self._live_preview_after)
            except (tk.TclError, ValueError): pass
        self._live_preview_after = self.root.after(80, self.apply_live_preview)

    def apply_live_preview(self):
        self._live_preview_after = None
        if self.label_selected_index is None or self.label_selected_index >= len(self.label_fields): return
        field = dict(self.label_fields[self.label_selected_index])
        for key in ("name", "csv", "text", "align"):
            field[key] = self.label_vars[key].get()
        for key in ("x", "y", "width", "height", "size"):
            try: field[key] = float(self.label_vars[key].get())
            except (TypeError, ValueError): return
        field.update({"type": self.label_type_var.get() or "ข้อความ", "font_family": self.label_font_family_var.get() or DEFAULT_LABEL_FONT, "image_mode": self.label_image_mode_var.get() or "Contain", "bold": bool(self.label_bold_var.get()), "italic": bool(self.label_italic_var.get()), "underline": bool(self.label_underline_var.get())})
        self.label_fields[self.label_selected_index] = field
        self.draw_label_preview()

    @staticmethod
    def read_csv_rows(path):
        """อ่าน CSV เป็นข้อความล้วน (คงเลข 0 นำหน้า) รองรับ UTF-8 และ cp874"""
        for encoding in ("utf-8-sig", "cp874"):
            try:
                with open(path, newline="", encoding=encoding) as f:
                    reader = csv.DictReader(f)
                    columns = [str(c) for c in (reader.fieldnames or [])]
                    rows = [{str(k): (v or "") for k, v in row.items() if k is not None} for row in reader]
                return columns, rows
            except UnicodeDecodeError:
                continue
        raise ValueError("ไม่สามารถอ่านรหัสอักขระของไฟล์ CSV ได้")

    def load_label_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")], title="เลือกไฟล์ CSV")
        if not path: return
        try:
            self.label_columns, self.label_rows = self.read_csv_rows(path)
            self.label_row_index = 0
            self.label_sample = self.label_rows[0] if self.label_rows else {}
            self.label_csv_combo["values"] = self.label_columns
            if not self.label_fields:
                for i, col in enumerate(self.label_columns[:4]): self.label_fields.append({"name": col, "csv": col, "text": "", "type": "ข้อความ", "bold": False, "italic": False, "underline": False, "border": True, "x": 8, "y": 10+i*18, "width": 84, "height": 12, "size": 12, "align": "left"})
                self.refresh_label_tree(); self.draw_label_preview()
            messagebox.showinfo("สำเร็จ", f"โหลด CSV แล้ว {len(self.label_columns)} คอลัมน์")
        except (OSError, ValueError, csv.Error) as e: messagebox.showerror("ข้อผิดพลาด", f"อ่าน CSV ไม่สำเร็จ:\n{e}")

    def refresh_label_tree(self):
        self.label_tree.delete(*self.label_tree.get_children())
        for i, f in enumerate(self.label_fields): self.label_tree.insert("", "end", iid=str(i), values=(f.get("name", ""), f.get("csv", ""), f.get("x", 0), f.get("y", 0), f.get("size", 0), f.get("align", "left")))

    def add_label_field(self):
        col = self.label_columns[0] if self.label_columns else "เลือกคอลัมน์"; i = len(self.label_fields)
        self.label_fields.append({"name": col, "csv": col, "text": "", "type": "ข้อความ", "bold": False, "italic": False, "underline": False, "border": True, "x": 8, "y": 10+i*18, "width": 84, "height": 12, "size": 12, "align": "left"}); self.refresh_label_tree(); self.draw_label_preview()

    def add_static_label_field(self):
        i = len(self.label_fields)
        self.label_fields.append({"name": "ข้อความคงที่", "csv": "__STATIC__", "text": "ข้อความของฉัน", "type": "ข้อความ", "bold": False, "italic": False, "underline": False, "border": True, "x": 8, "y": 10+i*18, "width": 84, "height": 12, "size": 12, "align": "left"})
        self.refresh_label_tree(); self.draw_label_preview()

    def add_image_label_field(self):
        path = filedialog.askopenfilename(filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All files", "*.*")], title="เลือกรูปภาพสำหรับลาเบล")
        if not path: return
        i = len(self.label_fields)
        self.label_fields.append({"name": Path(path).stem, "csv": "__IMAGE__", "image": path, "image_mode": "Contain", "text": "", "type": "รูปภาพ", "bold": False, "italic": False, "underline": False, "x": 8, "y": 10+i*18, "width": 40, "height": 30, "size": 12, "align": "center"})
        self.refresh_label_tree(); self.draw_label_preview()

    def open_custom_size_dialog(self):
        dialog = tk.Toplevel(self.root); dialog.title("กำหนดขนาดลาเบล"); dialog.transient(self.root); dialog.grab_set(); dialog.resizable(False, False)
        frame = tk.Frame(dialog, bg=self.WHITE, padx=14, pady=12); frame.pack()
        tk.Label(frame, text="กำหนดขนาดเป็นมิลลิเมตร (mm)", bg=self.WHITE, fg=self.TEXT_LIGHT).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for row, (caption, var) in enumerate((("กว้าง", self.label_custom_width), ("สูง", self.label_custom_height)), 1):
            tk.Label(frame, text=caption, bg=self.WHITE).grid(row=row, column=0, sticky="w", padx=4, pady=3); tk.Entry(frame, textvariable=var, width=12).grid(row=row, column=1, padx=4, pady=3)
        def apply():
            try:
                width, height = float(self.label_custom_width.get()), float(self.label_custom_height.get())
                if width <= 0 or height <= 0 or width > 1000 or height > 1000: raise ValueError
                self.label_orientation.set("กำหนดเอง"); self.label_size_text.config(text=f"ขนาดลาเบล {width:g} × {height:g} มม."); self.draw_label_preview(); dialog.destroy()
            except (TypeError, ValueError): messagebox.showerror("ข้อมูลไม่ถูกต้อง", "กรุณาระบุขนาดมากกว่า 0 และไม่เกิน 1000 มม.", parent=dialog)
        ttk.Button(frame, text="ตกลง", command=apply).grid(row=3, column=1, sticky="e", pady=(8, 0))

    def previous_label_row(self):
        if self.label_rows:
            self.label_row_index = max(0, self.label_row_index - 1); self.label_sample = self.label_rows[self.label_row_index]; self.draw_label_preview()

    def next_label_row(self):
        if self.label_rows:
            self.label_row_index = min(len(self.label_rows) - 1, self.label_row_index + 1); self.label_sample = self.label_rows[self.label_row_index]; self.draw_label_preview()

    def duplicate_label_field(self):
        if self.label_selected_index is None or self.label_selected_index >= len(self.label_fields):
            messagebox.showinfo("เลือกฟิลด์ก่อน", "กรุณาเลือกฟิลด์ที่ต้องการทำสำเนา")
            return
        field = dict(self.label_fields[self.label_selected_index])
        field["name"] = f"{field.get('name', 'ฟิลด์')} สำเนา"
        field["x"] = float(field.get("x", 0)) + 3
        field["y"] = float(field.get("y", 0)) + 3
        self.label_fields.insert(self.label_selected_index + 1, field)
        self.label_selected_index += 1
        self.refresh_label_tree(); self.label_tree.selection_set(str(self.label_selected_index)); self.draw_label_preview()

    def move_label_field(self, step):
        if self.label_selected_index is None or not self.label_fields: return
        old_index = self.label_selected_index; new_index = old_index + int(step)
        if not 0 <= new_index < len(self.label_fields): return
        self.label_fields[old_index], self.label_fields[new_index] = self.label_fields[new_index], self.label_fields[old_index]
        self.label_selected_index = new_index
        self.refresh_label_tree(); self.label_tree.selection_set(str(new_index)); self.draw_label_preview()

    def clear_label_fields(self):
        if not self.label_fields: return
        if messagebox.askyesno("ล้างฟิลด์ทั้งหมด", "ต้องการลบฟิลด์ทั้งหมดออกจากเทมเพลตหรือไม่?"):
            self.label_fields.clear(); self.label_selected_index = None; self.refresh_label_tree(); self.draw_label_preview()

    def change_label_zoom(self, delta):
        self.label_zoom_var.set(max(0.5, min(2.0, self.label_zoom_var.get() + float(delta))))
        self.draw_label_preview()

    def reset_label_zoom(self):
        self.label_zoom_var.set(1.0); self.draw_label_preview()

    def _copy_label_fields(self):
        return [dict(field) for field in self.label_fields]

    def undo_label_move(self):
        if not self._label_undo_stack: return
        self._label_redo_stack.append(self._copy_label_fields())
        self.label_fields = self._label_undo_stack.pop()
        self.label_selected_index = min(self.label_selected_index or 0, len(self.label_fields) - 1) if self.label_fields else None
        self.refresh_label_tree(); self.draw_label_preview()
        if self.label_selected_index is not None: self.label_tree.selection_set(str(self.label_selected_index)); self.select_label_field()

    def redo_label_move(self):
        if not self._label_redo_stack: return
        self._label_undo_stack.append(self._copy_label_fields())
        self.label_fields = self._label_redo_stack.pop()
        self.label_selected_index = min(self.label_selected_index or 0, len(self.label_fields) - 1) if self.label_fields else None
        self.refresh_label_tree(); self.draw_label_preview()
        if self.label_selected_index is not None: self.label_tree.selection_set(str(self.label_selected_index)); self.select_label_field()

    def _preview_field_at(self, event):
        page_w, page_h = self.get_label_dimensions(); base = min(300 / page_w, 280 / page_h) * self.label_zoom_var.get()
        for index in range(len(self.label_fields) - 1, -1, -1):
            field = self.label_fields[index]
            try:
                x = (float(field.get("x", 0)) + self.label_margin_left.get() + self.label_offset_x.get()) * base
                y = (float(field.get("y", 0)) + self.label_margin_top.get() + self.label_offset_y.get()) * base
                w = float(field.get("width", 0)) * base; h = float(field.get("height", 0)) * base
                if x <= event.x <= x + w and y <= event.y <= y + h: return index, base
            except (TypeError, ValueError): continue
        return None, base

    def preview_drag_start(self, event):
        index, _base = self._preview_field_at(event)
        self._preview_drag_index = index
        self._preview_drag_start = (event.x, event.y)
        self._preview_drag_snapshot = self._copy_label_fields() if index is not None else None
        if index is not None:
            self.label_selected_index = index
            self.label_tree.selection_set(str(index)); self.label_tree.see(str(index)); self.select_label_field()

    def preview_drag_motion(self, event):
        if self._preview_drag_index is None or self._preview_drag_start is None: return
        page_w, page_h = self.get_label_dimensions(); base = min(300 / page_w, 280 / page_h) * self.label_zoom_var.get()
        if base <= 0: return
        field = self.label_fields[self._preview_drag_index]
        dx = (event.x - self._preview_drag_start[0]) / base
        dy = (event.y - self._preview_drag_start[1]) / base
        page_w, page_h = self.get_label_dimensions()
        field["x"] = max(0.0, min(page_w - float(field.get("width", 0)), float(field.get("x", 0)) + dx))
        field["y"] = max(0.0, min(page_h - float(field.get("height", 0)), float(field.get("y", 0)) + dy))
        self._preview_drag_start = (event.x, event.y)
        self.label_vars["x"].set(f"{field['x']:.2f}"); self.label_vars["y"].set(f"{field['y']:.2f}")
        self.draw_label_preview()

    def preview_drag_end(self, _event):
        if self._preview_drag_index is not None:
            if self._preview_drag_snapshot is not None and self._preview_drag_snapshot != self.label_fields:
                self._label_undo_stack.append(self._preview_drag_snapshot)
                self._label_redo_stack.clear()
            self.refresh_label_tree(); self.label_tree.selection_set(str(self._preview_drag_index))
        self._preview_drag_index = None; self._preview_drag_start = None; self._preview_drag_snapshot = None

    def select_preview_field(self, event):
        for index, field in enumerate(self.label_fields):
            try:
                page_w, page_h = self.get_label_dimensions(); base = min(300 / page_w, 280 / page_h) * self.label_zoom_var.get()
                x = (float(field.get("x", 0)) + self.label_margin_left.get() + self.label_offset_x.get()) * base
                y = (float(field.get("y", 0)) + self.label_margin_top.get() + self.label_offset_y.get()) * base
                w = float(field.get("width", 0)) * base; h = float(field.get("height", 0)) * base
                if x <= event.x <= x + w and y <= event.y <= y + h:
                    self.label_selected_index = index; self.label_tree.selection_set(str(index)); self.label_tree.see(str(index)); return
            except (TypeError, ValueError): continue

    def delete_label_field(self):
        if self.label_selected_index is not None and self.label_selected_index < len(self.label_fields): self.label_fields.pop(self.label_selected_index); self.label_selected_index = None; self.refresh_label_tree(); self.draw_label_preview()

    def select_label_field(self, _event=None):
        selected = self.label_tree.selection()
        if selected:
            self.label_selected_index = int(selected[0]); field = self.label_fields[self.label_selected_index]
            for key in self.label_vars: self.label_vars[key].set(str(field.get(key, "")))
            self.label_bold_var.set(bool(field.get("bold", False)))
            self.label_type_var.set(field.get("type", "ข้อความ")); self.label_italic_var.set(bool(field.get("italic", False)))
            self.label_underline_var.set(bool(field.get("underline", False)))
            self.label_image_mode_var.set(field.get("image_mode", "Contain"))
            family = field.get("font_family", DEFAULT_LABEL_FONT)
            self.label_font_family_var.set(family if family in LABEL_FONT_FILES else DEFAULT_LABEL_FONT)

    def update_label_field(self):
        if self.label_selected_index is None: return
        try:
            field = {"name": self.label_vars["name"].get().strip(), "csv": self.label_vars["csv"].get().strip(), "text": self.label_vars["text"].get(), "type": self.label_type_var.get() or "ข้อความ", "image": self.label_fields[self.label_selected_index].get("image", ""), "image_mode": self.label_image_mode_var.get() or "Contain", "font_family": self.label_font_family_var.get() or DEFAULT_LABEL_FONT, "bold": bool(self.label_bold_var.get()), "italic": bool(self.label_italic_var.get()), "underline": bool(self.label_underline_var.get()), "x": float(self.label_vars["x"].get()), "y": float(self.label_vars["y"].get()), "width": float(self.label_vars["width"].get()), "height": float(self.label_vars["height"].get()), "size": float(self.label_vars["size"].get()), "align": self.label_vars["align"].get() or "left"}
            if not field["name"] or min(field["x"], field["y"]) < 0 or min(field["width"], field["height"], field["size"]) <= 0: raise ValueError("ค่าฟิลด์ไม่ถูกต้อง")
            self.label_fields[self.label_selected_index] = field; self.refresh_label_tree(); self.label_tree.selection_set(str(self.label_selected_index)); self.draw_label_preview()
        except ValueError as e: messagebox.showerror("ข้อมูลไม่ถูกต้อง", str(e))

    def save_label_template(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON template", "*.json")], initialfile="label_template.json")
        if path:
            try:
                width, height = self.get_label_dimensions()
                page_data = {"width_mm": width, "height_mm": height, "orientation": self.label_orientation.get(), "custom_width_mm": self.label_custom_width.get(), "custom_height_mm": self.label_custom_height.get(), "margin_left_mm": self.label_margin_left.get(), "margin_top_mm": self.label_margin_top.get(), "offset_x_mm": self.label_offset_x.get(), "offset_y_mm": self.label_offset_y.get(), "grid_visible": bool(self.label_grid_var.get()), "zoom": self.label_zoom_var.get(), "sheet_rows": self.label_sheet_rows.get(), "sheet_columns": self.label_sheet_columns.get(), "sheet_gap_x_mm": self.label_sheet_gap_x.get(), "sheet_gap_y_mm": self.label_sheet_gap_y.get()}
                template = {"template_version": 2, "name": Path(path).stem, "application": PROGRAM_NAME, "page": page_data, "fields": [dict(field) for field in self.label_fields]}
                Path(path).write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
                messagebox.showinfo("สำเร็จ", "บันทึกเทมเพลตเรียบร้อยแล้ว")
            except OSError as e: messagebox.showerror("ข้อผิดพลาด", f"บันทึกไม่สำเร็จ:\n{e}")

    def load_label_template(self):
        path = filedialog.askopenfilename(filetypes=[("JSON template", "*.json")], title="เลือกเทมเพลตลาเบล")
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8")); fields = data.get("fields", [])
                page_data = data.get("page", {})
                orientation = page_data.get("orientation", "แนวตั้ง")
                try: self.label_custom_width.set(float(page_data.get("custom_width_mm", page_data.get("width_mm", 100)))) ; self.label_custom_height.set(float(page_data.get("custom_height_mm", page_data.get("height_mm", 150))))
                except (TypeError, ValueError): pass
                for var, key in ((self.label_margin_left, "margin_left_mm"), (self.label_margin_top, "margin_top_mm"), (self.label_offset_x, "offset_x_mm"), (self.label_offset_y, "offset_y_mm"), (self.label_sheet_gap_x, "sheet_gap_x_mm"), (self.label_sheet_gap_y, "sheet_gap_y_mm")):
                    try: var.set(float(page_data.get(key, 0)))
                    except (TypeError, ValueError): var.set(0.0)
                try: self.label_sheet_rows.set(max(1, int(page_data.get("sheet_rows", 1)))); self.label_sheet_columns.set(max(1, int(page_data.get("sheet_columns", 1))))
                except (TypeError, ValueError): self.label_sheet_rows.set(1); self.label_sheet_columns.set(1)
                try: self.label_grid_var.set(bool(page_data.get("grid_visible", True))); self.label_zoom_var.set(max(0.5, min(2.0, float(page_data.get("zoom", 1.0)))))
                except (TypeError, ValueError): self.label_grid_var.set(True); self.label_zoom_var.set(1.0)
                if orientation in ("แนวตั้ง", "แนวนอน", "กำหนดเอง"):
                    self.label_orientation.set(orientation)
                    self.on_label_orientation_change()
                if not isinstance(fields, list): raise ValueError("รูปแบบเทมเพลตไม่ถูกต้อง")
                self.label_fields = [dict(field) for field in fields if isinstance(field, dict)]; self.label_selected_index = None; self.last_label_pdf = ""; self.refresh_label_tree(); self.draw_label_preview()
            except (OSError, ValueError, json.JSONDecodeError) as e: messagebox.showerror("ข้อผิดพลาด", f"โหลดไม่สำเร็จ:\n{e}")

    def open_label_print_settings(self):
        dialog = tk.Toplevel(self.root); dialog.title("ตั้งค่าระยะขอบและ Offset"); dialog.transient(self.root); dialog.grab_set(); dialog.resizable(False, False)
        frame = tk.Frame(dialog, padx=12, pady=10, bg=self.WHITE); frame.pack(fill="both", expand=True)
        tk.Label(frame, text="หน่วยเป็นมิลลิเมตร (mm)", bg=self.WHITE, fg=self.TEXT_LIGHT).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        vars_ = [("ระยะขอบซ้าย", self.label_margin_left), ("ระยะขอบบน", self.label_margin_top), ("Offset แกน X", self.label_offset_x), ("Offset แกน Y", self.label_offset_y)]
        for row, (caption, var) in enumerate(vars_, 1):
            tk.Label(frame, text=caption, bg=self.WHITE).grid(row=row, column=0, sticky="w", padx=4, pady=3)
            tk.Entry(frame, textvariable=var, width=12).grid(row=row, column=1, sticky="e", padx=4, pady=3)
        tk.Label(frame, text="ค่า Offset ใช้ชดเชยตำแหน่งพิมพ์ที่เหลื่อมจากเครื่องจริง", bg=self.WHITE, fg=self.TEXT_LIGHT, wraplength=280, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=6)
        ttk.Button(frame, text="ตกลง", command=lambda: (self.draw_label_preview(), dialog.destroy())).grid(row=6, column=1, sticky="e", pady=(4, 0))

    def get_sheet_layout(self):
        label_w, label_h = self.get_label_dimensions()
        rows = max(1, int(self.label_sheet_rows.get())); columns = max(1, int(self.label_sheet_columns.get()))
        gap_x = max(0.0, float(self.label_sheet_gap_x.get())); gap_y = max(0.0, float(self.label_sheet_gap_y.get()))
        return rows, columns, gap_x, gap_y, label_w * columns + gap_x * (columns - 1), label_h * rows + gap_y * (rows - 1)

    def open_multirow_settings(self):
        dialog = tk.Toplevel(self.root); dialog.title("พิมพ์สติกเกอร์หลายแถว"); dialog.transient(self.root); dialog.grab_set(); dialog.resizable(False, False)
        frame = tk.Frame(dialog, bg=self.WHITE, padx=14, pady=12); frame.pack()
        tk.Label(frame, text="กำหนดจำนวนตำแหน่งบนกระดาษ/แผ่น (หน่วย mm)", bg=self.WHITE, fg=self.TEXT_LIGHT).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        items = (("จำนวนแถว", self.label_sheet_rows), ("จำนวนคอลัมน์", self.label_sheet_columns), ("ระยะห่างแนวนอน", self.label_sheet_gap_x), ("ระยะห่างแนวตั้ง", self.label_sheet_gap_y))
        for row, (caption, variable) in enumerate(items, 1):
            tk.Label(frame, text=caption, bg=self.WHITE).grid(row=row, column=0, sticky="w", padx=4, pady=3)
            tk.Entry(frame, textvariable=variable, width=12).grid(row=row, column=1, sticky="e", padx=4, pady=3)
        summary = tk.StringVar()
        tk.Label(frame, textvariable=summary, bg=self.WHITE, fg=self.PRIMARY).grid(row=5, column=0, columnspan=2, sticky="w", padx=4, pady=6)
        def update_summary(*_args):
            try:
                _r, _c, _gx, _gy, sw, sh = self.get_sheet_layout(); summary.set(f"ขนาดกระดาษรวมประมาณ {sw:g} × {sh:g} มม.")
            except (TypeError, ValueError, tk.TclError): summary.set("กรุณาระบุค่าตัวเลขที่ถูกต้อง")
        for variable in (self.label_sheet_rows, self.label_sheet_columns, self.label_sheet_gap_x, self.label_sheet_gap_y): variable.trace_add("write", update_summary)
        update_summary()
        def apply():
            try:
                if int(self.label_sheet_rows.get()) < 1 or int(self.label_sheet_columns.get()) < 1 or float(self.label_sheet_gap_x.get()) < 0 or float(self.label_sheet_gap_y.get()) < 0: raise ValueError
                self.last_label_pdf = ""; self.label_print_status.set("คิวพิมพ์: ต้องสร้าง PDF ใหม่ตามรูปแบบหลายแถว"); dialog.destroy()
            except (TypeError, ValueError, tk.TclError): messagebox.showerror("ข้อมูลไม่ถูกต้อง", "จำนวนแถว/คอลัมน์ต้องมากกว่า 0 และระยะห่างต้องไม่ติดลบ", parent=dialog)
        ttk.Button(frame, text="ตกลง", command=apply).grid(row=6, column=1, sticky="e", pady=(4, 0))

    def validate_label_layout(self):
        page_w, page_h = self.get_label_dimensions(); problems = []
        for index, field in enumerate(self.label_fields, 1):
            try:
                x, y = float(field.get("x", 0)), float(field.get("y", 0))
                w, h = float(field.get("width", 0)), float(field.get("height", 0))
                if min(w, h) <= 0: problems.append(f"ฟิลด์ที่ {index}: ขนาดต้องมากกว่า 0")
                elif x < 0 or y < 0 or x + w > page_w or y + h > page_h:
                    problems.append(f"ฟิลด์ที่ {index} ({field.get('name', '')}): อยู่นอกขอบลาเบล")
                if field.get("type") == "รูปภาพ" and field.get("image") and not Path(field.get("image")).exists():
                    problems.append(f"ฟิลด์ที่ {index}: ไม่พบไฟล์รูปภาพ")
            except (TypeError, ValueError):
                problems.append(f"ฟิลด์ที่ {index}: ค่าตำแหน่งหรือขนาดไม่ถูกต้อง")
        if problems:
            messagebox.showwarning("ตรวจสอบเทมเพลต", "พบรายการที่ควรแก้ไข:\n\n" + "\n".join(problems[:8]) + ("\n..." if len(problems) > 8 else ""))
            return False
        return True

    def create_label_pdf(self):
        if not self.label_rows:
            messagebox.showwarning("ยังไม่มีข้อมูล", "กรุณาโหลดไฟล์ CSV ก่อนสร้าง PDF")
            return
        if not self.label_fields:
            messagebox.showwarning("ยังไม่มีฟิลด์", "กรุณาเพิ่มฟิลด์ในเทมเพลตก่อนสร้าง PDF")
            return
        if not self.validate_label_layout(): return
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], initialfile="labels.pdf", title="บันทึกไฟล์ลาเบล PDF")
        if not path: return
        try:
            self.set_label_progress(0, len(self.label_rows), "กำลังเริ่มสร้าง PDF")
            self.render_label_pdf(path, self.label_rows, self.update_label_progress)
            self.last_label_pdf = path
            self.set_label_progress(len(self.label_rows), len(self.label_rows), f"สร้าง PDF เสร็จ {len(self.label_rows)} / {len(self.label_rows)} หน้า")
            messagebox.showinfo("สร้าง PDF สำเร็จ", f"สร้างลาเบลจำนวน {len(self.label_rows)} รายการแล้ว\n{path}")
        except (OSError, ValueError, RuntimeError) as e:
            messagebox.showerror("สร้าง PDF ไม่สำเร็จ", str(e))

    def get_label_fontfile(self, bold=False, family=DEFAULT_LABEL_FONT):
        """หาไฟล์ฟอนต์จาก portable_fonts หรือโฟลเดอร์ฟอนต์ของ Windows"""
        if family not in LABEL_FONT_FILES: family = DEFAULT_LABEL_FONT
        windows_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        portable = [p for p in PORTABLE_FONT_DIR.rglob("*") if p.is_file()] if PORTABLE_FONT_DIR.exists() else []
        order = [family] + [f for f in LABEL_FONT_FILES if f != family]
        for name in order:
            for filename in LABEL_FONT_FILES[name][1 if bold else 0]:
                match = next((p for p in portable if p.name.lower() == filename.lower()), None)
                if match: return str(match)
                if (windows_dir / filename).is_file(): return str(windows_dir / filename)
        linux = ["/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        return next((p for p in linux if Path(p).is_file()), None)

    def make_barcode_pdf(self, value, width, height):
        drawing = createBarcodeDrawing("Code128", value=str(value), barHeight=max(12, height * 0.72), humanReadable=True)
        buffer = BytesIO(); c = reportlab_canvas.Canvas(buffer, pagesize=(width, height)); c.saveState(); c.scale(width / max(drawing.width, 1), height / max(drawing.height, 1)); renderPDF.draw(drawing, c, 0, 0); c.restoreState(); c.showPage(); c.save(); return buffer.getvalue()

    def make_qr_pdf(self, value, side):
        drawing = createBarcodeDrawing("QR", value=str(value), barLevel="M")
        buffer = BytesIO(); c = reportlab_canvas.Canvas(buffer, pagesize=(side, side)); c.saveState()
        c.scale(side / max(drawing.width, 1), side / max(drawing.height, 1)); renderPDF.draw(drawing, c, 0, 0)
        c.restoreState(); c.showPage(); c.save(); return buffer.getvalue()

    def prepare_label_image(self, path, target_px, mode):
        image = Image.open(path).convert("RGB")
        if mode == "Cover":
            return ImageOps.fit(image, target_px, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        image.thumbnail(target_px, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", target_px, "white")
        canvas.paste(image, ((target_px[0] - image.width) // 2, (target_px[1] - image.height) // 2))
        return canvas

    def set_label_progress(self, current, total, text=None):
        total = max(1, int(total)); current = max(0, min(int(current), total)); self.label_progress_var.set(current * 100 / total)
        if text is not None: self.label_progress_text.set(text)
        if hasattr(self, "root"): self.root.update_idletasks()

    def update_label_progress(self, current, total):
        self.set_label_progress(current, total, f"กำลังสร้าง {current} / {total} หน้า ({current * 100 / max(1, total):.1f}%)")

    def render_label_pdf(self, output_path, rows, progress_callback=None):
        label_w_mm, label_h_mm = self.get_label_dimensions(); mm = 72 / 25.4
        sheet_rows, sheet_columns, gap_x, gap_y, page_w_mm, page_h_mm = self.get_sheet_layout()
        doc = fitz.open()
        try:
            total_rows = len(rows)
            per_page = sheet_rows * sheet_columns
            total_pages = (total_rows + per_page - 1) // per_page
            for page_index in range(total_pages):
                page = doc.new_page(width=page_w_mm * mm, height=page_h_mm * mm)
                page_rows = rows[page_index * per_page:(page_index + 1) * per_page]
                for slot, row in enumerate(page_rows):
                    slot_row, slot_column = divmod(slot, sheet_columns)
                    origin_x = slot_column * (label_w_mm + gap_x) * mm
                    origin_y = slot_row * (label_h_mm + gap_y) * mm
                    for field in self.label_fields:
                        try:
                            x = origin_x + (float(field.get("x", 0)) + self.label_margin_left.get() + self.label_offset_x.get()) * mm; y = origin_y + (float(field.get("y", 0)) + self.label_margin_top.get() + self.label_offset_y.get()) * mm
                            w = float(field.get("width", 0)) * mm; h = float(field.get("height", 0)) * mm
                            if w <= 0 or h <= 0: continue
                            csv_name = field.get("csv", ""); value = field.get("text", "") if csv_name == "__STATIC__" else str(row.get(csv_name, "")); kind = field.get("type", "ข้อความ")
                            rect = fitz.Rect(x, y, x+w, y+h)
                            if kind == "รูปภาพ":
                                image_path = field.get("image", "")
                                if image_path and Path(image_path).exists():
                                    target_px = (max(1, int(w * 2.5)), max(1, int(h * 2.5)))
                                    prepared = self.prepare_label_image(image_path, target_px, field.get("image_mode", "Contain")); buffer = BytesIO(); prepared.save(buffer, format="PNG"); page.insert_image(rect, stream=buffer.getvalue(), keep_proportion=False)
                            elif kind == "QR Code":
                                if value:
                                    side = min(w, h); qr_doc = fitz.open(stream=self.make_qr_pdf(value, side), filetype="pdf")
                                    page.show_pdf_page(fitz.Rect(x + (w - side) / 2, y + (h - side) / 2, x + (w + side) / 2, y + (h + side) / 2), qr_doc, 0); qr_doc.close()
                            elif kind == "Barcode":
                                barcode_doc = fitz.open(stream=self.make_barcode_pdf(value, w, h), filetype="pdf"); page.show_pdf_page(rect, barcode_doc, 0); barcode_doc.close()
                            else:
                                align = {"left": 0, "center": 1, "right": 2}.get(field.get("align", "left"), 0); bold = bool(field.get("bold", False)); italic = bool(field.get("italic", False)); fontfile = self.get_label_fontfile(bold, field.get("font_family", DEFAULT_LABEL_FONT)); fontsize = max(5, min(144, float(field.get("size", 12)))); kwargs = {"fontsize": fontsize, "align": align, "color": (0, 0, 0), "lineheight": 1.1}
                                if fontfile: kwargs.update(fontname="F" + re.sub(r"[^A-Za-z0-9]", "", str(abs(hash(fontfile)))), fontfile=fontfile)
                                else: kwargs.update(fontname="hebo" if bold else "helv")
                                page.insert_textbox(rect, value, **kwargs)
                                if field.get("underline", False): page.draw_line((x, y+h-2), (x+w, y+h-2), color=(0, 0, 0), width=0.7)
                        except (TypeError, ValueError, RuntimeError): continue
                    if progress_callback: progress_callback(min((page_index * per_page) + slot + 1, total_rows), total_rows)
            doc.save(output_path, garbage=4, deflate=True)
        finally: doc.close()

    def print_labels(self):
        pdf_path = getattr(self, "last_label_pdf", "")
        if not pdf_path or not Path(pdf_path).exists():
            if not self.label_rows:
                messagebox.showwarning("ยังไม่มีข้อมูล", "กรุณาโหลด CSV ก่อนพิมพ์ลาเบล")
                return
            if not self.label_fields:
                messagebox.showwarning("ยังไม่มีฟิลด์", "กรุณาเพิ่มฟิลด์ในเทมเพลตก่อนพิมพ์ลาเบล")
                return
            if not self.validate_label_layout(): return
            pdf_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], initialfile="labels.pdf", title="สร้าง PDF ก่อนพิมพ์")
            if not pdf_path: return
            try:
                self.set_label_progress(0, len(self.label_rows), "กำลังเริ่มสร้าง PDF")
                self.render_label_pdf(pdf_path, self.label_rows, self.update_label_progress); self.last_label_pdf = pdf_path
            except (OSError, ValueError, RuntimeError) as e:
                messagebox.showerror("สร้าง PDF ไม่สำเร็จ", str(e)); return
        try:
            if os.name == "nt":
                os.startfile(pdf_path, "print"); self.label_print_status.set("คิวพิมพ์: ส่งงานเข้าระบบแล้ว")
            elif shutil.which("lp"):
                result = subprocess.run(["lp", pdf_path], check=True, capture_output=True, text=True); job = result.stdout.strip(); self.label_print_status.set(f"คิวพิมพ์: {job or 'ส่งงานแล้ว'}")
            else:
                self.open_file(pdf_path)
                self.label_print_status.set("คิวพิมพ์: ไม่พบระบบคิวอัตโนมัติ"); messagebox.showinfo("เปิดไฟล์ PDF แล้ว", "ไม่พบคำสั่งพิมพ์อัตโนมัติ จึงเปิด PDF ให้สั่งพิมพ์ด้วยตนเอง")
        except (OSError, subprocess.SubprocessError) as e:
            messagebox.showerror("พิมพ์ไม่สำเร็จ", f"ไม่สามารถส่งไฟล์ไปยังเครื่องพิมพ์ได้:\n{e}")

    def open_print_queue(self):
        try:
            if os.name == "nt":
                subprocess.Popen(["rundll32", "printui.dll,PrintUIEntry", "/o"])
                self.label_print_status.set("คิวพิมพ์: เปิดหน้าต่างเครื่องพิมพ์แล้ว")
            elif shutil.which("lpstat"):
                result = subprocess.run(["lpstat", "-o"], check=False, capture_output=True, text=True)
                jobs = [line for line in result.stdout.splitlines() if line.strip()]
                self.label_print_status.set(f"คิวพิมพ์: มี {len(jobs)} งานรอพิมพ์")
                if shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", "http://localhost:631/jobs"])
            elif shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", "http://localhost:631/jobs"])
                self.label_print_status.set("คิวพิมพ์: เปิดหน้าจัดการคิวแล้ว")
            else:
                messagebox.showinfo("คิวพิมพ์", "ไม่พบเครื่องมือเปิดคิวพิมพ์ของระบบ")
        except (OSError, subprocess.SubprocessError) as e:
            messagebox.showerror("เปิดคิวพิมพ์ไม่สำเร็จ", str(e))

    def open_file(self, path):
        if os.name == "nt": os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else: subprocess.Popen(["xdg-open", path])

    def get_label_dimensions(self):
        if self.label_orientation.get() == "กำหนดเอง": return (float(self.label_custom_width.get()), float(self.label_custom_height.get()))
        return (100, 150) if self.label_orientation.get() == "แนวตั้ง" else (150, 100)

    def on_label_orientation_change(self):
        width, height = self.get_label_dimensions()
        self.label_size_text.config(text=f"ขนาดลาเบล {width} × {height} มม.")
        self.draw_label_preview()

    def draw_label_preview(self):
        if not hasattr(self, "label_preview"): return
        self.label_preview.delete("all")
        self._label_preview_images = []
        page_w, page_h = self.get_label_dimensions(); scale = min(300 / page_w, 280 / page_h) * self.label_zoom_var.get()
        preview_w, preview_h = page_w * scale, page_h * scale
        self.label_preview.config(scrollregion=(0, 0, preview_w, preview_h))
        self.label_preview.create_rectangle(1, 1, preview_w-1, preview_h-1, fill="white", outline="#607D8B", width=2)
        if self.label_grid_var.get():
            grid_step = max(5, 10 * scale)
            for gx in range(1, max(1, int(preview_w / grid_step)) + 1):
                px = gx * grid_step
                self.label_preview.create_line(px, 0, px, preview_h, fill="#E8EEF2")
            for gy in range(1, max(1, int(preview_h / grid_step)) + 1):
                py = gy * grid_step
                self.label_preview.create_line(0, py, preview_w, py, fill="#E8EEF2")
        if hasattr(self, "label_row_status"):
            self.label_row_status.config(text=f"แถว {self.label_row_index + 1 if self.label_rows else 0} / {len(self.label_rows)}")
        for index, field in enumerate(self.label_fields):
            try:
                x, y, w, h = [(float(field.get(k, 0)) + (self.label_margin_left.get() + self.label_offset_x.get() if k == "x" else self.label_margin_top.get() + self.label_offset_y.get() if k == "y" else 0)) * scale for k in ("x", "y", "width", "height")]
                text = field.get("text", "") if field.get("csv") == "__STATIC__" else self.label_sample.get(field.get("csv", ""), "{"+field.get("name", "field")+"}"); kind = field.get("type", "ข้อความ")
                if index == self.label_selected_index:
                    self.label_preview.create_rectangle(x, y, x+w, y+h, outline="#1976D2", width=2, dash=(4, 2))
                if kind == "รูปภาพ":
                    image_path = field.get("image", "")
                    if image_path and Path(image_path).exists():
                        try:
                            image = self.prepare_label_image(image_path, (max(1, int(w)), max(1, int(h))), field.get("image_mode", "Contain"))
                            photo = ImageTk.PhotoImage(image); self._label_preview_images.append(photo); self.label_preview.create_image(x+w/2, y+h/2, image=photo)
                        except (OSError, ValueError): self.label_preview.create_text(x+w/2, y+h/2, text="รูปภาพอ่านไม่ได้", fill="#B71C1C")
                elif kind == "QR Code":
                    self.label_preview.create_rectangle(x+3, y+3, x+w-3, y+h-3, fill="white", outline="#263238")
                    for gx in range(3):
                        for gy in range(3): self.label_preview.create_rectangle(x+7+gx*max(4,(w-20)/3), y+7+gy*max(4,(h-20)/3), x+10+gx*max(4,(w-20)/3), y+10+gy*max(4,(h-20)/3), fill="#263238", outline="")
                elif kind == "Barcode":
                    for n in range(18):
                        if n % 3 != 1: self.label_preview.create_rectangle(x+4+n*(w-8)/18, y+4, x+4+(n+1)*(w-8)/18, y+h-8, fill="#263238", outline="")
                    self.label_preview.create_text(x+w/2, y+h-4, text=text, anchor="s", font=("Segoe UI", 7), fill="#263238")
                else:
                    align = field.get("align", "left"); anchor = {"left":"w", "center":"center", "right":"e"}.get(align, "w"); tx = x if align == "left" else x+w/2 if align == "center" else x+w
                    weight = "bold" if field.get("bold", False) else "normal"; slant = "italic" if field.get("italic", False) else "roman"; self.label_preview.create_text(tx, y+h/2, text=text, anchor=anchor, font=(field.get("font_family", "Segoe UI"), max(7, int(float(field.get("size", 12))*0.7)), weight, slant), fill="#263238")
                    if field.get("underline", False): self.label_preview.create_line(x, y+h-2, x+w, y+h-2, fill="#263238")
            except (TypeError, ValueError): continue

    # --- TAB 1: AUTO RENAME ---
    def setup_tab1(self):
        container = tk.Frame(self.tab1, bg=self.WHITE, padx=15, pady=15)
        container.pack(fill="both", expand=True)
        title_frame = tk.Frame(container, bg=self.WHITE)
        title_frame.pack(fill="x", pady=(0, 12))
        tk.Label(title_frame, text="Auto Renamer Dashboard", font=("Segoe UI", 12, "bold"), fg=self.PRIMARY, bg=self.WHITE).pack(side="left")
        
        stats_frame = tk.Frame(container, bg=self.WHITE)
        stats_frame.pack(fill="x", pady=4)
        self.create_stat_card(stats_frame, "Total Files", "0", self.ACCENT).pack(side="left", expand=True, fill="both", padx=2)
        self.success_card = self.create_stat_card(stats_frame, "Success", "0", self.SUCCESS)
        self.success_card.pack(side="left", expand=True, fill="both", padx=2)
        self.error_card = self.create_stat_card(stats_frame, "Unreadable", "0", self.DANGER)
        self.error_card.pack(side="left", expand=True, fill="both", padx=2)

        action_frame = ttk.LabelFrame(container, text=" Quick Actions ", padding=10)
        action_frame.pack(fill="x", pady=10)
        tk.Label(action_frame, text="เลือกโฟลเดอร์ที่ต้องการให้ระบบอ่าน Barcode และเปลี่ยนชื่อไฟล์อัตโนมัติ", font=("Segoe UI", 8), bg=self.WHITE, fg=self.TEXT_DARK).pack(pady=(0, 8))
        self.select_btn = ttk.Button(action_frame, text="📂 เลือกโฟลเดอร์และเริ่มทำงานทันที", style="Accent.TButton", command=self.start_rename_thread)
        self.select_btn.pack(ipadx=15, ipady=5)

        progress_container = tk.Frame(container, bg=self.WHITE)
        progress_container.pack(fill="x", pady=8)
        self.status_label = tk.Label(progress_container, text="สถานะ: พร้อมใช้งาน", font=("Segoe UI", 8), bg=self.WHITE, fg=self.TEXT_LIGHT)
        self.status_label.pack(side="left")
        self.percent_label = tk.Label(progress_container, text="0%", font=("Segoe UI", 8, "bold"), bg=self.WHITE, fg=self.PRIMARY)
        self.percent_label.pack(side="right")
        self.progress = ttk.Progressbar(container, orient=tk.HORIZONTAL, mode='determinate')
        self.progress.pack(fill="x", pady=2)

    def create_stat_card(self, parent, title, value, color):
        card = tk.Frame(parent, bg=self.WHITE, highlightthickness=1, highlightbackground="#EEEEEE", padx=8, pady=6)
        tk.Label(card, text=title, font=("Segoe UI", 8), fg=self.TEXT_LIGHT, bg=self.WHITE).pack(anchor="w")
        val_label = tk.Label(card, text=value, font=("Segoe UI", 14, "bold"), fg=color, bg=self.WHITE)
        val_label.pack(anchor="w")
        card.val_label = val_label
        return card

    # --- TAB 2: SEARCH & PRINT (WITH SUBFOLDER SEARCH & COPY/PASTE & COPY TO FOLDER & MERGE) ---
    def setup_tab2(self):
        main_frame = tk.Frame(self.tab2, bg=self.WHITE, padx=12, pady=12)
        main_frame.pack(expand=True, fill="both")

        # Top Section: Search Input (resizable vertically)
        search_split = tk.PanedWindow(
            main_frame, orient=tk.VERTICAL, sashwidth=7, sashrelief="raised",
            bg="#D0D7DE", bd=0, relief="flat", opaqueresize=True
        )
        search_split.pack(fill="both", expand=True)
        search_top = tk.Frame(search_split, bg=self.WHITE)
        search_split.add(search_top, stretch="never", minsize=115)

        input_frame = tk.Frame(search_top, bg=self.WHITE)
        input_frame.pack(fill="x")
        tk.Label(input_frame, text="รายการเลขเอกสารที่ต้องการค้นหา (รองรับการ Copy/Paste และคลิกขวา)", font=("Segoe UI", 9, "bold"), bg=self.WHITE, fg=self.PRIMARY).pack(anchor="w")
        tk.Label(input_frame, text="ลากเส้นแบ่งระหว่างตารางกับ Preview เพื่อปรับขนาดพื้นที่", font=("Segoe UI", 7), bg=self.WHITE, fg=self.TEXT_LIGHT).pack(anchor="w")
        
        self.search_list_text = tk.Text(search_top, height=3, font=("Consolas", 8), undo=True, relief="flat", bg="#F8F9FA", borderwidth=1, highlightthickness=1, highlightcolor=self.ACCENT)
        self.search_list_text.pack(fill="both", expand=True, pady=4)
        self.add_right_click_menu(self.search_list_text) # เพิ่มเมนูคลิกขวา

        # Toolbar
        toolbar = tk.Frame(search_top, bg=self.WHITE)
        toolbar.pack(fill="x", pady=4)
        ttk.Button(toolbar, text="🔍 เริ่มค้นหาไฟล์ (รวมโฟลเดอร์ย่อย)", style="Accent.TButton", command=self.start_search_thread).pack(side="left", padx=2)
        ttk.Button(toolbar, text="✅ เลือกทั้งหมด", command=self.toggle_selection).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🖨️ สั่งพิมพ์รายการที่เลือก", command=self.print_selected).pack(side="left", padx=2)
        ttk.Button(toolbar, text="📂 Copy to Folder", style="Warning.TButton", command=self.copy_selected_to_folder).pack(side="left", padx=2)
        ttk.Button(toolbar, text="➕ Merge Selected PDFs", style="Purple.TButton", command=self.merge_selected_pdfs).pack(side="left", padx=2)
        ttk.Button(toolbar, text="📊 ส่งออกรายงาน CSV", command=self.export_to_csv).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🗑️ ล้างข้อมูล", command=self.clear_search_data).pack(side="right", padx=2)

        # Bottom Section: Table + Preview Panel
        content_split = tk.PanedWindow(
            search_split, orient=tk.HORIZONTAL, sashwidth=7, sashrelief="raised",
            bg="#D0D7DE", bd=0, relief="flat", opaqueresize=True
        )
        search_split.add(content_split, stretch="always", minsize=240)

        # Left: Results Table
        table_container = tk.Frame(content_split, bg=self.WHITE, highlightthickness=1, highlightbackground="#EEEEEE")
        content_split.add(table_container, stretch="always", minsize=320)

        cols = ("select", "search_name", "status", "found_name", "full_path")
        self.result_tree = ttk.Treeview(table_container, columns=cols, show="headings")
        headings = {"select": "เลือก", "search_name": "คำค้นหา", "status": "สถานะ", "found_name": "ชื่อไฟล์ที่พบ", "full_path": "ที่อยู่ไฟล์"}
        for col in cols: self.result_tree.heading(col, text=headings[col])
        self.result_tree.column("select", width=30, anchor="center")
        self.result_tree.column("search_name", width=70)
        self.result_tree.column("status", width=60, anchor="center")
        self.result_tree.column("found_name", width=110)
        self.result_tree.column("full_path", width=160)
        
        self.result_tree.tag_configure("not_found", background="#FFEBEE", foreground="#C62828")
        self.result_tree.tag_configure("found_multiple", background="#E3F2FD", foreground="#1565C0")
        self.result_tree.tag_configure("found", background="#E8F5E9", foreground="#2E7D32")

        vsb = ttk.Scrollbar(table_container, orient="vertical", command=self.result_tree.yview)
        hsb = ttk.Scrollbar(table_container, orient="horizontal", command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.result_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        table_container.grid_columnconfigure(0, weight=1)
        table_container.grid_rowconfigure(0, weight=1)

        # Right: Interactive Preview Panel
        self.preview_panel = tk.Frame(content_split, bg="#F8F9FA", width=240, highlightthickness=1, highlightbackground="#EEEEEE")
        content_split.add(self.preview_panel, stretch="never", minsize=180)
        self.preview_panel.pack_propagate(False)

        preview_header = tk.Frame(self.preview_panel, bg="#F8F9FA")
        preview_header.pack(fill="x", pady=2)
        tk.Label(preview_header, text="Interactive Preview", font=("Segoe UI", 8, "bold"), bg="#F8F9FA", fg=self.PRIMARY).pack(side="left", padx=5)
        tk.Label(preview_header, text="(Scroll: Zoom | Drag: Move)", font=("Segoe UI", 7), bg="#F8F9FA", fg=self.TEXT_LIGHT).pack(side="left")
        
        reset_btn = tk.Button(preview_header, text="Reset", font=("Segoe UI", 8), command=self.reset_preview, bg="#E0E0E0", relief="flat")
        reset_btn.pack(side="right", padx=5)

        self.preview_canvas = tk.Canvas(self.preview_panel, bg="white", highlightthickness=0, cursor="fleur")
        self.preview_canvas.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        self.preview_msg = tk.Label(self.preview_canvas, text="คลิกที่รายการในตาราง\nเพื่อดูตัวอย่างเอกสาร", font=("Segoe UI", 8), fg=self.TEXT_LIGHT, bg="white")
        self.preview_msg.place(relx=0.5, rely=0.5, anchor="center")

        # Bind events
        self.result_tree.bind("<ButtonRelease-1>", self.on_tree_click)
        self.result_tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.preview_canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.preview_canvas.bind("<Button-4>", self.on_mouse_wheel)
        self.preview_canvas.bind("<Button-5>", self.on_mouse_wheel)
        self.preview_canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.preview_canvas.bind("<B1-Motion>", self.on_drag_motion)
        self.preview_canvas.bind("<Double-Button-1>", lambda e: self.reset_preview())

    # --- TAB 3: PDF TOOLS ---
    def setup_tab3(self):
        container = tk.Frame(self.tab3, bg=self.WHITE, padx=12, pady=8)
        container.pack(fill="both", expand=True)
        tk.Label(container, text="PDF Management Center", font=("Segoe UI", 12, "bold"), fg=self.PRIMARY, bg=self.WHITE).pack(anchor="w", pady=(0, 6))
        tools_grid = tk.Frame(container, bg=self.WHITE)
        tools_grid.pack(fill="x", pady=2)
        self.create_tool_card(tools_grid, "✂️ PDF Splitter", "แยกไฟล์ PDF ขนาดใหญ่ให้เป็นไฟล์ละ 1 หน้าอัตโนมัติ\nตั้งชื่อตามไฟล์ต้นทางและเลขหน้า", "เลือกไฟล์เพื่อแยกหน้า", self.ACCENT, self.split_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)
        self.create_tool_card(tools_grid, "➕ PDF Merger", "รวมไฟล์ PDF หลายไฟล์เข้าด้วยกันเป็นไฟล์เดียว\nเรียงลำดับตามชื่อไฟล์อัตโนมัติ", "เลือกไฟล์เพื่อรวมร่าง", self.SUCCESS, self.merge_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)

        tools_grid2 = tk.Frame(container, bg=self.WHITE)
        tools_grid2.pack(fill="x", pady=(6, 2))
        self.create_tool_card(tools_grid2, "🔄 PDF Rotator", "หมุนทุกหน้า 90, 180 หรือ 270 องศา\nเหมาะสำหรับเอกสารสแกนผิดแนว", "เลือกไฟล์เพื่อหมุน", self.WARNING, self.rotate_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)
        self.create_tool_card(tools_grid2, "🧹 Remove Blank Pages", "ตรวจหาและลบหน้าว่างที่ไม่มีข้อความหรือรูปภาพ\nสร้างไฟล์ใหม่โดยไม่แก้ต้นฉบับ", "ลบหน้าว่าง", self.PURPLE, self.remove_blank_pages_logic).pack(side="left", expand=True, fill="both", padx=5)
        self.create_tool_card(tools_grid2, "✂️ Extract Pages", "แยกหน้าที่ต้องการ เช่น 1-3,5,8-10\nสร้างเป็น PDF ใหม่", "แยกหน้าที่เลือก", self.SUCCESS, self.extract_pages_logic).pack(side="left", expand=True, fill="both", padx=5)

        tools_grid3 = tk.Frame(container, bg=self.WHITE)
        tools_grid3.pack(fill="x", pady=(6, 2))
        self.create_tool_card(tools_grid3, "🖨️ PDF 2-up / Booklet", "จัด 2 หน้าบนกระดาษแนวนอน 1 แผ่น\nเหมาะสำหรับพิมพ์ประหยัดกระดาษ", "จัดหน้า 2-up", self.PURPLE, self.two_up_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)
        self.create_tool_card(tools_grid3, "🔒 PDF Protect", "ตั้งรหัสผ่านเปิดไฟล์และจำกัดการแก้ไข\nไฟล์ต้นฉบับจะไม่ถูกแก้ไข", "ป้องกันด้วยรหัสผ่าน", self.WARNING, self.protect_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)
        self.create_tool_card(tools_grid3, "🔓 PDF Unlock", "เปิด PDF ด้วยรหัสผ่านที่ถูกต้อง\nบันทึกเป็นไฟล์ปลดล็อกใหม่", "ปลดล็อก PDF", self.DANGER, self.unlock_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)

        tools_grid4 = tk.Frame(container, bg=self.WHITE)
        tools_grid4.pack(fill="x", pady=(6, 2))
        self.create_tool_card(tools_grid4, "🖼️ Image to PDF", "รวมรูปภาพหลายไฟล์เป็น PDF เดียว\nเรียงตามลำดับที่เลือก", "รวมภาพเป็น PDF", self.ACCENT, self.images_to_pdf_logic).pack(side="left", expand=True, fill="both", padx=5)
        self.create_tool_card(tools_grid4, "📄 PDF Page to Image", "แปลงทุกหน้า PDF เป็นไฟล์ PNG\nเลือกโฟลเดอร์ปลายทางและ DPI ได้", "แปลง PDF เป็นรูปภาพ", self.SUCCESS, self.pdf_pages_to_images_logic).pack(side="left", expand=True, fill="both", padx=5)

    def create_tool_card(self, parent, title, desc, btn_text, color, command):
        card = tk.Frame(parent, bg=self.WHITE, highlightthickness=1, highlightbackground="#EEEEEE", padx=12, pady=12)
        tk.Label(card, text=title, font=("Segoe UI", 11, "bold"), fg=color, bg=self.WHITE).pack(anchor="w")
        tk.Label(card, text=desc, font=("Segoe UI", 8), fg=self.TEXT_LIGHT, bg=self.WHITE, justify="left").pack(anchor="w", pady=6)
        btn = ttk.Button(card, text=btn_text, style="Accent.TButton" if color == self.ACCENT else "Success.TButton", command=command)
        btn.pack(fill="x", ipady=4)
        return card

    def images_to_pdf_logic(self):
        files = filedialog.askopenfilenames(title="เลือกรูปภาพเพื่อรวมเป็น PDF", filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"), ("All files", "*.*")])
        if not files: return
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], initialfile="images.pdf", title="บันทึก PDF จากรูปภาพ")
        if not save_path: return
        images = []
        try:
            for file_path in files:
                with Image.open(file_path) as source:
                    images.append(source.convert("RGB"))
            if not images: raise ValueError("ไม่พบรูปภาพที่ใช้งานได้")
            images[0].save(save_path, "PDF", save_all=True, append_images=images[1:], resolution=150.0)
            for image in images: image.close()
            messagebox.showinfo("สำเร็จ", f"รวมรูปภาพ {len(files)} ไฟล์เป็น PDF แล้ว\n{save_path}")
        except (OSError, ValueError) as exc:
            for image in images:
                try: image.close()
                except Exception: pass
            messagebox.showerror("แปลงไม่สำเร็จ", str(exc))

    def pdf_pages_to_images_logic(self):
        file_path = filedialog.askopenfilename(title="เลือก PDF เพื่อแปลงเป็นรูปภาพ", filetypes=[("PDF files", "*.pdf")])
        if not file_path: return
        output_dir = filedialog.askdirectory(title="เลือกโฟลเดอร์บันทึกรูปภาพ")
        if not output_dir: return
        dpi = simpledialog.askinteger("ความละเอียดภาพ", "ระบุ DPI (แนะนำ 150 หรือ 300):", initialvalue=150, minvalue=36, maxvalue=600, parent=self.root)
        if not dpi: return
        try:
            source = Path(file_path); output_path = Path(output_dir); matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            with fitz.open(file_path) as doc:
                total = len(doc)
                for page_number, page in enumerate(doc, 1):
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    pix.save(str(output_path / f"{source.stem}_page_{page_number:03d}.png"))
            messagebox.showinfo("สำเร็จ", f"แปลง PDF จำนวน {total} หน้าเป็น PNG แล้ว\n{output_dir}")
        except (OSError, ValueError, fitz.FileDataError) as exc:
            messagebox.showerror("แปลงไม่สำเร็จ", str(exc))

    # --- LOGIC SECTIONS ---
    def load_image(self, file_path: Path):
        """โหลดภาพหรือหน้าแรกของ PDF เป็นภาพเทา (PIL) สำหรับอ่านบาร์โค้ด"""
        try:
            if file_path.suffix.lower() == ".pdf":
                with fitz.open(file_path) as doc:
                    if len(doc) == 0: return None
                    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csGRAY, alpha=False)
                    return Image.frombytes("L", (pix.width, pix.height), pix.samples)
            with Image.open(file_path) as img:
                return ImageOps.exif_transpose(img).convert("L")
        except (OSError, ValueError, fitz.FileDataError, Image.DecompressionBombError):
            return None

    def extract_top_barcode(self, image):
        if image is None: return None
        try:
            found = []
            for candidate in (image, image.point(lambda p: 255 if p > 127 else 0)):
                for bc in pyzbar.decode(candidate):
                    data = bc.data.decode("utf-8", errors="replace").strip()
                    if data: found.append({"data": data, "top": bc.rect.top})
                if found: break
            if not found: return None
            found.sort(key=lambda x: x["top"])
            return found[0]["data"]
        except (UnicodeError, ValueError):
            return None

    def start_rename_thread(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        include_subfolders = messagebox.askyesno(
            "ขอบเขตการทำงาน",
            "ต้องการประมวลผลไฟล์ในโฟลเดอร์ย่อยด้วยหรือไม่?"
        )
        self.select_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.update_stat("Success", "0")
        self.update_stat("Unreadable", "0")
        self.is_busy = True
        threading.Thread(
            target=self.process_files,
            args=(Path(folder), include_subfolders),
            daemon=True,
        ).start()

    def process_files(self, target_dir, include_subfolders=False):
        if include_subfolders:
            all_files = [
                f for f in target_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                and "_unreadable_files" not in f.parts
            ]
        else:
            all_files = [
                f for f in target_dir.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
            ]
        all_files.sort(key=lambda p: str(p).lower())
        total = len(all_files)
        if total == 0:
            self.root.after(0, lambda: messagebox.showwarning("แจ้งเตือน", "ไม่พบไฟล์ที่รองรับในโฟลเดอร์นี้"))
            self.root.after(0, lambda: self.select_btn.config(state=tk.NORMAL))
            self.is_busy = False
            return
        self.root.after(0, lambda: self.update_stat("Total Files", str(total)))
        error_dir = target_dir / "_unreadable_files"
        success, error = 0, 0
        for i, file_path in enumerate(all_files):
            percent = int(((i + 1) / total) * 100)
            self.root.after(0, lambda p=percent, n=file_path.name, idx=i+1: self.update_progress(p, n, idx, total))
            image = self.load_image(file_path)
            barcode = self.extract_top_barcode(image)
            if not barcode:
                error_dir.mkdir(exist_ok=True)
                try:
                    unreadable_target = error_dir / file_path.name
                    counter = 1
                    while unreadable_target.exists():
                        unreadable_target = error_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                        counter += 1
                    shutil.move(str(file_path), str(unreadable_target))
                except OSError:
                    pass
                error += 1
                self.root.after(0, lambda e=error: self.update_stat("Unreadable", str(e)))
                continue
            clean_name = re.sub(r"[^\w-]+", "_", barcode, flags=re.UNICODE).strip(" _")
            if not clean_name: clean_name = "unnamed"
            new_path = target_dir / f"{clean_name}{file_path.suffix}"
            if new_path == file_path:
                success += 1
                self.root.after(0, lambda s=success: self.update_stat("Success", str(s)))
                continue
            counter = 1
            while new_path.exists():
                new_path = target_dir / f"{clean_name}_{counter}{file_path.suffix}"
                counter += 1
            try:
                file_path.rename(new_path)
                success += 1
                self.root.after(0, lambda s=success: self.update_stat("Success", str(s)))
            except OSError:
                error += 1
                self.root.after(0, lambda e=error: self.update_stat("Unreadable", str(e)))
        self.root.after(0, lambda: self.finish_process(success, error))

    def update_stat(self, title, value):
        if title == "Success": self.success_card.val_label.config(text=value)
        elif title == "Unreadable": self.error_card.val_label.config(text=value)

    def update_progress(self, percent, filename, current, total):
        self.progress['value'] = percent
        self.percent_label.config(text=f"{percent}% ({current}/{total})")
        self.status_label.config(text=f"กำลังประมวลผล: {filename}")

    def finish_process(self, success, error):
        self.status_label.config(text="สถานะ: ประมวลผลเสร็จสิ้น")
        self.select_btn.config(state=tk.NORMAL)
        self.is_busy = False
        messagebox.showinfo("สรุปผลการทำงาน", f"ดำเนินการสำเร็จ: {success} ไฟล์\nไม่สามารถอ่านได้: {error} ไฟล์")
        self.progress['value'] = 0
        self.percent_label.config(text="0%")

    def start_search_thread(self):
        folder = filedialog.askdirectory()
        if not folder: return
        items = list(dict.fromkeys(
            i.strip() for i in self.search_list_text.get("1.0", tk.END).splitlines() if i.strip()
        ))
        if not items: 
            messagebox.showwarning("แจ้งเตือน", "กรุณาใส่เลขเอกสารที่ต้องการค้นหา")
            return
        threading.Thread(target=self.search_files_recursive, args=(Path(folder), items), daemon=True).start()

    def search_files_recursive(self, target_dir, items):
        self.root.after(0, lambda: [self.result_tree.delete(i) for i in self.result_tree.get_children()])
        all_files = []
        for root_dir, dirs, files in os.walk(target_dir):
            dirs[:] = sorted(d for d in dirs if d != "_unreadable_files")
            for file in files:
                if Path(file).suffix.lower() in SUPPORTED_EXTENSIONS:
                    all_files.append(Path(root_dir) / file)
        
        for item in items:
            matches = [f for f in all_files if item.lower() in f.name.lower()]
            if not matches:
                self.root.after(0, lambda it=item: self.result_tree.insert("", tk.END, values=("---", it, "❌ ไม่พบไฟล์", "-", "-"), tags=("not_found",)))
            else:
                for idx, mf in enumerate(matches):
                    tag = "found_multiple" if len(matches) > 1 else "found"
                    status = f"✅ พบ ({idx+1}/{len(matches)})" if len(matches) > 1 else "✅ พบไฟล์"
                    self.root.after(0, lambda it=item, st=status, fn=mf.name, fp=str(mf), t=tag: 
                                   self.result_tree.insert("", tk.END, values=("[ ]", it, st, fn, fp), tags=(t,)))

    def on_tree_click(self, event):
        item_id = self.result_tree.identify_row(event.y)
        column = self.result_tree.identify_column(event.x)
        if item_id and column == "#1":
            vals = list(self.result_tree.item(item_id, "values"))
            if vals[0] != "---":
                vals[0] = "[X]" if vals[0] == "[ ]" else "[ ]"
                self.result_tree.item(item_id, values=vals)

    def on_tree_select(self, event):
        selected = self.result_tree.selection()
        if not selected: return
        item_id = selected[0]
        vals = self.result_tree.item(item_id, "values")
        file_path = vals[4]
        if file_path != "-" and os.path.exists(file_path):
            threading.Thread(target=self.load_preview_image, args=(file_path,), daemon=True).start()

    def load_preview_image(self, file_path):
        try:
            path = Path(file_path)
            img = None
            if path.suffix.lower() == ".pdf":
                with fitz.open(file_path) as doc:
                    if len(doc) > 0:
                        page = doc[0]
                        pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5))
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            elif path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                img = Image.open(file_path)
            if img:
                self.current_preview_img = img
                self.root.after(0, self.reset_preview)
        except (OSError, ValueError, fitz.FileDataError):
            self.root.after(0, lambda: self.preview_msg.config(text="ไม่สามารถเปิดตัวอย่างไฟล์นี้ได้"))

    def reset_preview(self):
        if not self.current_preview_img: return
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        if canvas_w < 10: canvas_w = 230
        if canvas_h < 10: canvas_h = 300
        img_w, img_h = self.current_preview_img.size
        ratio = min(canvas_w / img_w, canvas_h / img_h)
        self.zoom_level = ratio
        self.img_pos_x = canvas_w // 2
        self.img_pos_y = canvas_h // 2
        self.render_preview()

    def render_preview(self):
        if not self.current_preview_img: return
        new_w = int(self.current_preview_img.width * self.zoom_level)
        new_h = int(self.current_preview_img.height * self.zoom_level)
        if new_w < 10 or new_h < 10: return
        resized_img = self.current_preview_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized_img)
        self.preview_msg.place_forget()
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(self.img_pos_x, self.img_pos_y, image=photo, anchor="center")
        self.preview_canvas.image = photo

    def on_mouse_wheel(self, event):
        if not self.current_preview_img: return
        if event.num == 4 or event.delta > 0: self.zoom_level *= 1.1
        else: self.zoom_level /= 1.1
        self.zoom_level = max(0.05, min(self.zoom_level, 5.0))
        self.render_preview()

    def on_drag_start(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag_motion(self, event):
        if not self.current_preview_img: return
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        self.img_pos_x += dx
        self.img_pos_y += dy
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.render_preview()

    def toggle_selection(self):
        items = self.result_tree.get_children()
        if not items: return
        any_unselected = any(self.result_tree.item(i, "values")[0] == "[ ]" for i in items if self.result_tree.item(i, "values")[0] != "---")
        target = "[X]" if any_unselected else "[ ]"
        for i in items:
            v = list(self.result_tree.item(i, "values"))
            if v[0] != "---":
                v[0] = target
                self.result_tree.item(i, values=v)

    def export_to_csv(self):
        items = self.result_tree.get_children()
        if not items: return
        try:
            fn = f"BOWA_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
            sp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")], initialfile=fn)
            if not sp: return
            with open(sp, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Search Term", "Status", "Found Filename", "Full Path"])
                for it_id in items:
                    v = self.result_tree.item(it_id, "values")
                    writer.writerow([v[1], v[2], v[3], v[4]])
            messagebox.showinfo("สำเร็จ", "ส่งออกข้อมูลเรียบร้อยแล้ว!")
        except Exception as e: messagebox.showerror("ข้อผิดพลาด", str(e))

    def copy_selected_to_folder(self):
        selected_paths = [self.result_tree.item(i, "values")[4] for i in self.result_tree.get_children() if self.result_tree.item(i, "values")[0] == "[X]"]
        if not selected_paths:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกไฟล์ที่ต้องการคัดลอก")
            return
        dest_folder = filedialog.askdirectory(title="เลือกโฟลเดอร์ปลายทาง")
        if not dest_folder: return
        dest_path = Path(dest_folder)
        success, error = 0, 0
        for src_file in selected_paths:
            try:
                src_p = Path(src_file)
                if not src_p.exists(): error += 1; continue
                target_p = dest_path / src_p.name
                counter = 1
                while target_p.exists():
                    target_p = dest_path / f"{src_p.stem}_{counter}{src_p.suffix}"
                    counter += 1
                shutil.copy2(src_file, target_p)
                success += 1
            except (OSError, shutil.Error):
                error += 1
        messagebox.showinfo("สรุปการคัดลอก", f"คัดลอกสำเร็จ: {success} ไฟล์\nผิดพลาด: {error} ไฟล์")

    def merge_selected_pdfs(self):
        selected_paths = [self.result_tree.item(i, "values")[4] for i in self.result_tree.get_children() if self.result_tree.item(i, "values")[0] == "[X]"]
        pdf_files = [p for p in selected_paths if p.lower().endswith(".pdf")]
        if not pdf_files:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกไฟล์ PDF อย่างน้อย 1 ไฟล์เพื่อรวมร่าง")
            return
        
        # ถามผู้ใช้เรื่องการเรียงลำดับ
        do_sort = messagebox.askyesno("การเรียงลำดับ", "คุณต้องการเรียงลำดับไฟล์ตามชื่อ (A-Z) หรือไม่?\n(หากตอบ 'ไม่' ระบบจะเรียงตามลำดับที่คุณเลือกในตาราง)")
        
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", title="ตั้งชื่อไฟล์ที่รวมเสร็จแล้ว")
        if not save_path: return
        
        try:
            files_to_merge = sorted(pdf_files) if do_sort else pdf_files
            with fitz.open() as merged:
                for f in files_to_merge:
                    with fitz.open(f) as doc: merged.insert_pdf(doc)
                merged.save(save_path, garbage=4, deflate=True)
            messagebox.showinfo("สำเร็จ", "รวมไฟล์ PDF ที่เลือกเรียบร้อยแล้ว!")
        except Exception as e: messagebox.showerror("ข้อผิดพลาด", str(e))

    def split_pdf_logic(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")], title="เลือกไฟล์ PDF")
        if not file_path: return
        try:
            with fitz.open(file_path) as src_doc:
                original_name = Path(file_path).stem
                output_dir = Path(file_path).parent / f"split_{original_name}"
                if not output_dir.exists(): output_dir.mkdir()
                total_pages = len(src_doc)
                for i in range(total_pages):
                    new_doc = fitz.open()
                    new_doc.insert_pdf(src_doc, from_page=i, to_page=i)
                    new_filename = f"{original_name}_Page_{i+1}.pdf"
                    new_doc.save(str(output_dir / new_filename), garbage=4, deflate=True)
                    new_doc.close()
            messagebox.showinfo("สำเร็จ", f"แยกไฟล์เรียบร้อยแล้ว {total_pages} หน้า")
        except Exception as e: messagebox.showerror("ข้อผิดพลาด", str(e))

    def merge_pdf_logic(self):
        files = filedialog.askopenfilenames(filetypes=[("PDF Files", "*.pdf")], title="เลือกไฟล์ PDF")
        if not files: return
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", title="ตั้งชื่อไฟล์")
        if not save_path: return
        try:
            with fitz.open() as merged:
                for f in sorted(list(files)):
                    with fitz.open(f) as doc: merged.insert_pdf(doc)
                merged.save(save_path, garbage=4, deflate=True)
            messagebox.showinfo("สำเร็จ", "รวมไฟล์ PDF เรียบร้อยแล้ว!")
        except Exception as e: messagebox.showerror("ข้อผิดพลาด", str(e))

    def rotate_pdf_logic(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("PDF Files", "*.pdf")], title="เลือกไฟล์ PDF ที่ต้องการหมุน"
        )
        if not file_path:
            return
        angle = simpledialog.askinteger(
            "องศาการหมุน", "ระบุองศา (90, 180 หรือ 270):", initialvalue=90,
            minvalue=90, maxvalue=270
        )
        if angle not in (90, 180, 270):
            if angle is not None:
                messagebox.showwarning("ข้อมูลไม่ถูกต้อง", "กรุณาระบุ 90, 180 หรือ 270 องศา")
            return
        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf", title="บันทึก PDF ที่หมุนแล้ว",
            initialfile=f"{Path(file_path).stem}_rotated.pdf"
        )
        if not save_path:
            return
        try:
            with fitz.open(file_path) as doc:
                page_count = len(doc)
                for page in doc:
                    page.set_rotation((page.rotation + angle) % 360)
                doc.save(save_path, garbage=4, deflate=True)
            messagebox.showinfo("สำเร็จ", f"หมุนเอกสารจำนวน {page_count} หน้าเรียบร้อยแล้ว")
        except (OSError, fitz.FileDataError, ValueError) as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถหมุน PDF ได้:\n{e}")

    def remove_blank_pages_logic(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("PDF Files", "*.pdf")], title="เลือกไฟล์ PDF เพื่อลบหน้าว่าง"
        )
        if not file_path:
            return
        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf", title="บันทึก PDF ที่ลบหน้าว่างแล้ว",
            initialfile=f"{Path(file_path).stem}_no_blank.pdf"
        )
        if not save_path:
            return
        try:
            with fitz.open(file_path) as src:
                kept_pages = []
                for index, page in enumerate(src):
                    has_text = bool(page.get_text("text").strip())
                    has_images = bool(page.get_images(full=True))
                    if has_text or has_images:
                        kept_pages.append(index)
                if not kept_pages:
                    messagebox.showwarning("ไม่พบหน้าที่มีเนื้อหา", "เอกสารนี้ไม่มีหน้าที่ตรวจพบข้อความหรือรูปภาพ")
                    return
                with fitz.open() as output:
                    for index in kept_pages:
                        output.insert_pdf(src, from_page=index, to_page=index)
                    output.save(save_path, garbage=4, deflate=True)
                total_pages = len(src)
            removed = total_pages - len(kept_pages)
            messagebox.showinfo("สำเร็จ", f"ลบหน้าว่างแล้ว {removed} หน้า\nคงเหลือ {len(kept_pages)} หน้า")
        except (OSError, fitz.FileDataError, ValueError) as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถลบหน้าว่างได้:\n{e}")

    def parse_page_spec(self, spec, page_count):
        """แปลงรายการหน้า เช่น 1-3,5,8-10 เป็นดัชนีหน้าแบบ zero-based"""
        pages = []
        for token in spec.replace(" ", "").split(","):
            if not token:
                continue
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                start, end = int(start_text), int(end_text)
                if start > end:
                    start, end = end, start
                pages.extend(range(start - 1, end))
            else:
                pages.append(int(token) - 1)
        if not pages or any(page < 0 or page >= page_count for page in pages):
            raise ValueError(f"หมายเลขหน้าต้องอยู่ระหว่าง 1 ถึง {page_count}")
        return pages

    def _ask_pdf_and_save(self, open_title, save_title, initial_suffix):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")], title=open_title)
        if not file_path:
            return None, None
        save_path = filedialog.asksaveasfilename(
            defaultextension=".pdf", title=save_title,
            initialfile=f"{Path(file_path).stem}{initial_suffix}"
        )
        return file_path, save_path or None

    def extract_pages_logic(self):
        file_path, save_path = self._ask_pdf_and_save("เลือก PDF เพื่อแยกหน้า", "บันทึกหน้าที่เลือก", "_extracted.pdf")
        if not file_path or not save_path:
            return
        try:
            with fitz.open(file_path) as src:
                spec = simpledialog.askstring("หน้าที่ต้องการ", f"ระบุช่วงหน้า เช่น 1-3,5,8-10 (มี {len(src)} หน้า):")
                if not spec:
                    return
                pages = self.parse_page_spec(spec, len(src))
                with fitz.open() as out:
                    for page_index in pages:
                        out.insert_pdf(src, from_page=page_index, to_page=page_index)
                    out.save(save_path, garbage=4, deflate=True)
            messagebox.showinfo("สำเร็จ", f"แยกหน้าออกมาแล้ว {len(pages)} หน้า")
        except (OSError, ValueError, fitz.FileDataError) as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถแยกหน้าได้:\n{e}")

    def protect_pdf_logic(self):
        file_path, save_path = self._ask_pdf_and_save("เลือก PDF เพื่อป้องกัน", "บันทึก PDF ที่ป้องกันแล้ว", "_protected.pdf")
        if not file_path or not save_path:
            return
        user_password = simpledialog.askstring("รหัสผ่านเปิดไฟล์", "ตั้งรหัสผ่านสำหรับเปิด PDF:", show="*")
        if not user_password:
            return
        owner_password = simpledialog.askstring("รหัสผ่านเจ้าของ", "ตั้งรหัสผ่านเจ้าของเอกสาร:", show="*") or user_password
        try:
            permissions = fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY
            with fitz.open(file_path) as doc:
                doc.save(save_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_password, owner_pw=owner_password, permissions=permissions, garbage=4, deflate=True)
            messagebox.showinfo("สำเร็จ", "ป้องกัน PDF ด้วยรหัสผ่านเรียบร้อยแล้ว")
        except (OSError, ValueError, fitz.FileDataError) as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถป้องกัน PDF ได้:\n{e}")

    def unlock_pdf_logic(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")], title="เลือก PDF ที่ต้องการปลดล็อก")
        if not file_path:
            return
        password = simpledialog.askstring("รหัสผ่าน PDF", "กรอกรหัสผ่านที่ถูกต้อง:", show="*")
        if password is None:
            return
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", title="บันทึก PDF ที่ปลดล็อกแล้ว", initialfile=f"{Path(file_path).stem}_unlocked.pdf")
        if not save_path:
            return
        try:
            with fitz.open(file_path) as doc:
                if doc.needs_pass and not doc.authenticate(password):
                    raise ValueError("รหัสผ่านไม่ถูกต้อง")
                doc.save(save_path, encryption=fitz.PDF_ENCRYPT_NONE, garbage=4, deflate=True)
            messagebox.showinfo("สำเร็จ", "ปลดล็อก PDF เรียบร้อยแล้ว")
        except (OSError, ValueError, fitz.FileDataError) as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถปลดล็อก PDF ได้:\n{e}")

    def two_up_pdf_logic(self):
        file_path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")], title="เลือก PDF เพื่อจัดหน้า 2-up")
        if not file_path:
            return
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", title="บันทึก PDF แบบ 2-up", initialfile=f"{Path(file_path).stem}_2up.pdf")
        if not save_path:
            return
        try:
            with fitz.open(file_path) as src, fitz.open() as out:
                page_width, page_height = 842, 595
                half_width = page_width / 2
                for index in range(0, len(src), 2):
                    target = out.new_page(width=page_width, height=page_height)
                    target.show_pdf_page(fitz.Rect(0, 0, half_width, page_height), src, index, keep_proportion=True)
                    if index + 1 < len(src):
                        target.show_pdf_page(fitz.Rect(half_width, 0, page_width, page_height), src, index + 1, keep_proportion=True)
                out.save(save_path, garbage=4, deflate=True)
                output_pages = len(out)
            messagebox.showinfo("สำเร็จ", f"จัดหน้า 2-up แล้ว\nสร้างเอกสารใหม่ {output_pages} หน้า")
        except (OSError, ValueError, fitz.FileDataError) as e:
            messagebox.showerror("ข้อผิดพลาด", f"ไม่สามารถจัดหน้า 2-up ได้:\n{e}")

    def clear_search_data(self):
        if messagebox.askyesno("ยืนยัน", "ต้องการล้างข้อมูลทั้งหมดใช่หรือไม่?"):
            for i in self.result_tree.get_children(): self.result_tree.delete(i)
            self.search_list_text.delete("1.0", tk.END)
            self.preview_canvas.delete("all")
            self.preview_msg.place(relx=0.5, rely=0.5, anchor="center")
            self.current_preview_img = None

    def on_close(self):
        self.save_last_label_settings()
        if self.is_busy:
            if not messagebox.askyesno("ยืนยันการปิดโปรแกรม", "กำลังประมวลผลอยู่ ต้องการปิดโปรแกรมหรือไม่?"):
                return
        self.root.destroy()

    def _send_file_to_windows_printer(self, file_path):
        """ส่งไฟล์ไปยังคำสั่ง Print ของโปรแกรมเริ่มต้นใน Windows

        os.startfile เป็นวิธีมาตรฐานของ Windows แต่บางโปรแกรมอ่าน PDF ไม่มี
        Print verb จึงมี PowerShell เป็น fallback และคืนข้อความผิดพลาดให้ผู้ใช้
        แทนการเงียบหายเหมือนรุ่นเดิม
        """
        path = Path(file_path)
        if not path.is_file():
            return False, "ไม่พบไฟล์หรือไฟล์ถูกย้ายแล้ว"
        if os.name != "nt":
            return False, "รองรับการส่งพิมพ์อัตโนมัติเฉพาะ Windows"
        try:
            os.startfile(str(path), "print")
            return True, ""
        except (AttributeError, OSError) as first_error:
            # ใช้ ShellExecute ผ่าน PowerShell เป็นทางเลือกสำหรับ Windows
            # ที่ os.startfile ไม่สามารถเรียก Print verb ของไฟล์ชนิดนั้นได้
            try:
                escaped = str(path).replace("'", "''")
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                     f"Start-Process -LiteralPath '{escaped}' -Verb Print -ErrorAction Stop"],
                    check=False, capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    return True, ""
                detail = (result.stderr or result.stdout).strip()
                return False, detail or str(first_error)
            except (OSError, subprocess.SubprocessError) as fallback_error:
                return False, str(fallback_error)

    def print_selected(self):
        selected = [
            self.result_tree.item(item_id, "values")[4]
            for item_id in self.result_tree.get_children()
            if self.result_tree.item(item_id, "values")[0] == "[X]"
        ]
        if not selected:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกไฟล์ที่ต้องการพิมพ์")
            return
        if not messagebox.askyesno("ยืนยันการพิมพ์", f"ต้องการส่งไฟล์จำนวน {len(selected)} ไฟล์ไปยังเครื่องพิมพ์?"):
            return
        if os.name != "nt":
            messagebox.showwarning("ไม่รองรับบนระบบนี้", "ฟังก์ชันสั่งพิมพ์อัตโนมัติรองรับเฉพาะ Windows")
            return

        sent, failed = 0, 0
        errors = []
        for file_path in selected:
            ok, error = self._send_file_to_windows_printer(file_path)
            if ok:
                sent += 1
            else:
                failed += 1
                errors.append(f"{Path(file_path).name}: {error}")
            # เว้นช่วงเล็กน้อยให้ ShellExecute สร้างงานในคิวพิมพ์ก่อนรายการถัดไป
            if ok:
                time.sleep(0.5)

        summary = f"ส่งเข้าคิวสำเร็จ: {sent} ไฟล์\nผิดพลาด: {failed} ไฟล์"
        if errors:
            summary += "\n\nรายละเอียด:\n" + "\n".join(errors[:8])
            if len(errors) > 8:
                summary += f"\n… และอีก {len(errors) - 8} รายการ"
            summary += "\n\nตรวจสอบว่าได้ติดตั้งโปรแกรมอ่าน PDF/รูปภาพและตั้งค่าเครื่องพิมพ์เริ่มต้นแล้ว"
        messagebox.showinfo("สรุปการพิมพ์", summary)

if __name__ == "__main__":
    root = tk.Tk()
    app = BowaApp(root)
    root.mainloop()
