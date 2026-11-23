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
import urllib.parse
import hashlib
import math
import uuid
import tempfile
import urllib.error
from io import BytesIO
from reportlab.pdfgen import canvas as reportlab_canvas
from reportlab.graphics.barcode import createBarcodeDrawing
# ReportLab โหลดชนิดบาร์โค้ดบางส่วนแบบ dynamic; import นี้ช่วยให้ PyInstaller
# ตรวจพบ Code128 และรวมโมดูลไว้ใน executable ได้อย่างแน่นอน
from reportlab.graphics.barcode import code128 as reportlab_code128
from reportlab.graphics.barcode import qr as reportlab_qr
from reportlab.graphics import renderPDF
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

# --- Configuration ---
PROGRAM_NAME = "BOWA Smart Processor"
VERSION = "7.3.0"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ICON_PATH = APP_DIR / "bowa.ico"
PORTABLE_FONT_DIR = APP_DIR / "portable_fonts"
# URL ไฟล์ JSON สำหรับตรวจสอบรุ่นล่าสุด เช่น GitHub Raw หรือ Web Server ขององค์กร
# ใช้ "latest" เพื่อให้ลิงก์ชี้ไปที่ update_manifest.json ของ Release ล่าสุดเสมอ (ไม่ผูกกับแท็กเวอร์ชันใดเวอร์ชันหนึ่ง)
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/iudomdet/BOWASmartProcessor/main/update_manifest.json"
UPDATE_CHECK_TIMEOUT = 8
# ฟอนต์ที่รองรับภาษาไทยและมีไฟล์ใช้งานได้จริง: ชื่อ -> (ไฟล์ปกติ, ไฟล์ตัวหนา)
LABEL_FONT_FILES = {
    "Leelawadee UI": (("leelawui.ttf",), ("leelauib.ttf",)),
    "Tahoma": (("tahoma.ttf",), ("tahomabd.ttf",)),
    "TH Sarabun New": (("THSarabunNew.ttf",), ("THSarabunNew Bold.ttf", "THSarabunNewBold.ttf")),
}
DEFAULT_LABEL_FONT = "Leelawadee UI"

# =====================================================================
#  Document & Label Designer — ส่วนประมวลผล (ไม่พึ่ง tkinter)
#  แม่แบบ (dict/JSON) + ข้อมูล CSV  ->  PDF  (ตัวอย่างบนจอใช้ PDF ชุดเดียวกัน)
# =====================================================================
MM = 72.0 / 25.4
PAD_MM = 0.6  # ระยะห่างข้อความจากขอบกรอบ

PAPER_SIZES = {"A4": (210, 297), "A5": (148, 210), "A6": (105, 148), "A3": (297, 420),
               "Letter": (215.9, 279.4), "9×11 นิ้ว (ต่อเนื่อง)": (228.6, 279.4), "กำหนดเอง": None}
ROLL_SIZES = {"100×150": (100, 150), "100×100": (100, 100), "100×75": (100, 75), "80×50": (80, 50),
              "60×40": (60, 40), "50×30": (50, 30), "40×30": (40, 30), "30×20": (30, 20)}
SHEET_PRESETS = {"2×4  (99.1×67.7 มม.)": (2, 4, 99.1, 67.7), "2×7  (99.1×38.1 มม.)": (2, 7, 99.1, 38.1),
                 "3×7  (63.5×38.1 มม.)": (3, 7, 63.5, 38.1), "3×8  (70×37 มม.)": (3, 8, 70, 37),
                 "4×11 (48.5×25.4 มม.)": (4, 11, 48.5, 25.4)}
MODES = [("roll", "ลาเบลม้วน/ความร้อน (1 ดวงต่อหน้า)"), ("sheet", "ลาเบลหลายดวงบนแผ่น (A4 ฯลฯ)"), ("document", "เอกสาร (ใบส่งของ/ใบเสร็จ)")]
COLORS = {"black": ("ดำ", (0, 0, 0)), "dgray": ("เทาเข้ม", (.3, .3, .3)), "gray": ("เทา", (.55, .55, .55)),
          "red": ("แดง", (.8, 0, 0)), "blue": ("น้ำเงิน", (0, 0, .7)), "white": ("ขาว", (1, 1, 1))}
FILLS = {"none": ("ไม่มี", None), "lgray": ("เทาอ่อน", (.92, .92, .92)), "mgray": ("เทา", (.78, .78, .78)),
         "black": ("ดำ", (0, 0, 0)), "yellow": ("เหลืองอ่อน", (1, .96, .7))}
ELEMENT_NAMES = {"text": "ข้อความ", "barcode": "บาร์โค้ด", "qr": "QR Code", "image": "รูปภาพ",
                 "line": "เส้น", "rect": "กรอบ", "table": "ตาราง"}

_FONT_CACHE = {}


def find_font_file(bold=False, family=DEFAULT_LABEL_FONT):
    """หาไฟล์ฟอนต์จาก portable_fonts หรือโฟลเดอร์ฟอนต์ของ Windows"""
    if family not in LABEL_FONT_FILES: family = DEFAULT_LABEL_FONT
    windows_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    portable = [p for p in PORTABLE_FONT_DIR.rglob("*") if p.is_file()] if PORTABLE_FONT_DIR.exists() else []
    for name in [family] + [f for f in LABEL_FONT_FILES if f != family]:
        for filename in LABEL_FONT_FILES[name][1 if bold else 0]:
            match = next((p for p in portable if p.name.lower() == filename.lower()), None)
            if match: return str(match)
            if (windows_dir / filename).is_file(): return str(windows_dir / filename)
    linux = ["/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return next((p for p in linux if Path(p).is_file()), None)


def pdf_font(family, bold):
    """ลงทะเบียนฟอนต์ TTF กับ ReportLab (ไม่พบฟอนต์ -> Helvetica ซึ่งแสดงภาษาไทยไม่ได้)"""
    key = (family, bool(bold))
    if key in _FONT_CACHE: return _FONT_CACHE[key]
    name = "Helvetica-Bold" if bold else "Helvetica"
    path = find_font_file(bool(bold), family)
    if path:
        reg = "BF" + hashlib.md5(path.encode("utf-8", "replace")).hexdigest()[:10]
        try:
            if reg not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont(reg, path))
            name = reg
        except Exception:  # noqa: BLE001 - ไฟล์ฟอนต์เสีย/ไม่รองรับ ให้ถอยไปใช้ฟอนต์พื้นฐาน
            pass
    _FONT_CACHE[key] = name
    return name


def font_available(family, bold=False):
    return pdf_font(family, bold).startswith("BF")


# ---------------------------------------------------------------- ตัวเลข/ข้อความ
def to_float(value):
    try: return float(str(value).replace(",", "").replace("฿", "").strip() or 0)
    except (ValueError, TypeError): return 0.0


_TH_DIGITS = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_TH_POS = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]


def _th_int(n):
    if n <= 0: return ""
    if n >= 1_000_000:
        rem = n % 1_000_000
        return _th_int(n // 1_000_000) + "ล้าน" + ("เอ็ด" if rem == 1 else _th_int(rem))
    s = str(n); out = ""
    for i, ch in enumerate(s):
        d = int(ch); pos = len(s) - i - 1
        if d == 0: continue
        if pos == 0 and d == 1 and len(s) > 1: out += "เอ็ด"
        elif pos == 1 and d == 2: out += "ยี่สิบ"
        elif pos == 1 and d == 1: out += "สิบ"
        else: out += _TH_DIGITS[d] + _TH_POS[pos]
    return out


def baht_text(amount):
    """จำนวนเงินเป็นตัวอักษรไทย เช่น 1,250.50 -> หนึ่งพันสองร้อยห้าสิบบาทห้าสิบสตางค์"""
    total = int(round(abs(amount) * 100)); baht, satang = divmod(total, 100)
    text = ("ลบ" if amount < 0 and total else "")
    if baht: text += _th_int(baht) + "บาท"
    elif not satang: return "ศูนย์บาทถ้วน"
    text += (_th_int(satang) + "สตางค์") if satang else "ถ้วน"
    return text


_TOKEN_RE = re.compile(r"\{([^{}]*)\}")
_FUNC_RE = re.compile(r"^(sum|count|avg|bahttext)\((.*)\)$")


def format_number(value, spec, default=",.2f"):
    try: return format(to_float(value), spec or default)
    except (ValueError, TypeError): return str(value)


def _eval_number(expr, ctx):
    """คำนวณ sum(col) / avg(col) / count() / ชื่อคอลัมน์ เป็นตัวเลข"""
    expr = expr.strip(); rows = ctx.get("__rows__") or [ctx]
    m = _FUNC_RE.match(expr)
    if m:
        func, arg = m.group(1), m.group(2).strip()
        if func == "count": return float(len(rows))
        values = [to_float(r.get(arg, "")) for r in rows]
        if func == "sum": return sum(values)
        if func == "avg": return sum(values) / len(values) if values else 0.0
    return to_float(ctx.get(expr, ""))


def expand(template, ctx):
    """แทนที่ {คอลัมน์}, {คอลัมน์:,.2f}, {sum(คอลัมน์)}, {count()}, {bahttext(sum(คอลัมน์))}"""
    if not template or "{" not in template: return template or ""

    def repl(match):
        body = match.group(1); name, _, spec = body.partition(":") if not body.startswith("bahttext(") else (body, "", "")
        name = name.strip(); func = _FUNC_RE.match(name)
        if func:
            kind, arg = func.group(1), func.group(2)
            if kind == "bahttext": return baht_text(_eval_number(arg, ctx))
            number = _eval_number(name, ctx)
            if kind == "count": return format(int(number), spec or "d")
            return format_number(number, spec)
        if name in ctx and not name.startswith("__"):
            return format_number(ctx[name], spec) if spec else str(ctx[name])
        return ""
    return _TOKEN_RE.sub(repl, template)


def referenced_names(template):
    """รายชื่อคอลัมน์ที่อ้างถึงในข้อความแม่แบบ (ไม่รวมฟังก์ชัน)"""
    names = set()
    for body in _TOKEN_RE.findall(template or ""):
        body = body.strip(); name = body.partition(":")[0].strip() if not body.startswith("bahttext(") else body
        func = _FUNC_RE.match(name)
        while func:
            if func.group(1) == "count": name = ""; break
            name = func.group(2).strip(); func = _FUNC_RE.match(name)
        if name: names.add(name)
    return names


BUILTIN_TOKENS = ["page", "pages", "no", "date", "date_th", "time", "record", "copy_label"]


def builtin_context(now=None):
    now = now or datetime.now()
    return {"date": now.strftime("%d/%m/%Y"), "date_th": f"{now.day:02d}/{now.month:02d}/{now.year + 543}", "time": now.strftime("%H:%M")}


# ---------------------------------------------------------------- ตัดบรรทัด (รองรับไทย)
def _is_thai(ch): return "\u0e00" <= ch <= "\u0e7f"
def _no_break_before(ch):
    o = ord(ch); return o in (0x0E2F, 0x0E30, 0x0E31, 0x0E32, 0x0E33, 0x0E45, 0x0E46) or 0x0E34 <= o <= 0x0E3A or 0x0E47 <= o <= 0x0E4E
def _no_break_after(ch): return 0x0E40 <= ord(ch) <= 0x0E44


def wrap_paragraph(text, font, size, max_w):
    sw = pdfmetrics.stringWidth
    if not text or sw(text, font, size) <= max_w: return [text]
    lines = []; start = 0; brk = None; i = 0; n = len(text)
    while i < n:
        if i > start and sw(text[start:i + 1].rstrip(), font, size) > max_w:
            cut = brk if (brk is not None and brk > start) else i
            while cut > start + 1 and cut < n and (_no_break_before(text[cut]) or _no_break_after(text[cut - 1])): cut -= 1
            lines.append(text[start:cut].rstrip()); start = cut
            while start < n and text[start] == " ": start += 1
            i = start; brk = None
            if i < n and sw(text[start:].rstrip(), font, size) <= max_w: lines.append(text[start:].rstrip()); return lines
            continue
        ch = text[i]
        if ch == " " or ch == "-": brk = i + 1
        elif i + 1 < n and _is_thai(ch) and _is_thai(text[i + 1]) and not _no_break_before(text[i + 1]) and not _no_break_after(ch): brk = i + 1
        i += 1
    if start < n: lines.append(text[start:].rstrip())
    return lines or [""]


def line_height(font, size):
    asc = pdfmetrics.getAscent(font, size); desc = -pdfmetrics.getDescent(font, size)
    return min(max(size * 1.2, asc + desc), size * 1.45), asc


def layout_text(text, font, size, w_pt, h_pt, shrink, min_size=5.0):
    """คืน (บรรทัด, ขนาดตัวอักษรที่ใช้)"""
    while True:
        lines = []
        for para in str(text).split("\n"): lines += wrap_paragraph(para, font, size, w_pt)
        lh, _ = line_height(font, size)
        if not shrink or len(lines) * lh <= h_pt + 0.01 or size <= min_size: break
        size = max(min_size, size - 0.5)
    lh, _ = line_height(font, size)
    max_lines = max(1, int((h_pt + 0.01) // lh)) if h_pt > 0 else len(lines)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and pdfmetrics.stringWidth(lines[-1] + "…", font, size) > w_pt and len(lines[-1]) > 1: lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines, size


def fit_single_line(text, font, size, w_pt, min_size=5.0):
    sw = pdfmetrics.stringWidth
    while sw(text, font, size) > w_pt and size > min_size: size = max(min_size, size - 0.5)
    if sw(text, font, size) > w_pt:
        while len(text) > 1 and sw(text + "…", font, size) > w_pt: text = text[:-1]
        text += "…"
    return text, size


# ---------------------------------------------------------------- แม่แบบ
def new_id(): return uuid.uuid4().hex[:8]


def default_element(kind, **kw):
    base = {"id": new_id(), "type": kind, "name": ELEMENT_NAMES[kind], "x": 5.0, "y": 5.0, "w": 40.0, "h": 8.0, "show_on": "all"}
    if kind == "text": base.update(text="ข้อความ", font=DEFAULT_LABEL_FONT, size=11.0, bold=False, align="left", valign="top", color="black", fill="none", border=0.0, shrink=True)
    elif kind == "barcode": base.update(value="{sku}", human=True, h=14.0, w=50.0)
    elif kind == "qr": base.update(value="{sku}", w=25.0, h=25.0)
    elif kind == "image": base.update(path="", fit="contain", w=30.0, h=20.0)
    elif kind == "line": base.update(thickness=0.3, color="black", h=0.0, w=60.0)
    elif kind == "rect": base.update(border=0.3, fill="none", color="black", w=60.0, h=20.0)
    elif kind == "table":
        base.update(w=190.0, h=120.0, font=DEFAULT_LABEL_FONT, size=10.0, row_h=7.0, header_fill="lgray", zebra=False, fill_empty=True, total_label="รวม", border=0.25,
                    columns=[{"title": "ลำดับ", "value": "{no}", "weight": 8, "align": "center", "sum": False},
                             {"title": "รายการ", "value": "{item}", "weight": 60, "align": "left", "sum": False},
                             {"title": "จำนวน", "value": "{qty}", "weight": 15, "align": "right", "sum": False},
                             {"title": "จำนวนเงิน", "value": "{amount:,.2f}", "weight": 25, "align": "right", "sum": True}])
    base.update(kw)
    return base


def new_template(mode="roll"):
    tpl = {"version": 2, "mode": mode, "paper": "A4", "orientation": "portrait", "page_w": 100.0, "page_h": 150.0,
           "cols": 1, "rows": 1, "cell_w": 70.0, "cell_h": 37.0, "margin_left": 0.0, "margin_top": 0.0, "gap_x": 0.0, "gap_y": 0.0,
           "start_cell": 1, "group_col": "", "copies": 1, "copies_col": "", "copy_labels": "", "show_guides": False, "starter": "", "elements": []}
    return tpl


def page_geometry(tpl):
    """ขนาดกระดาษ/ลาเบลจริง (มม.) ตามโหมด"""
    mode = tpl.get("mode", "roll")
    if mode == "roll":
        w, h = float(tpl.get("page_w", 100)), float(tpl.get("page_h", 150))
        return dict(page_w=w, page_h=h, cols=1, rows=1, cell_w=w, cell_h=h, ml=0.0, mt=0.0, gx=0.0, gy=0.0)
    size = PAPER_SIZES.get(tpl.get("paper", "A4")) or (float(tpl.get("page_w", 210)), float(tpl.get("page_h", 297)))
    w, h = size
    if tpl.get("orientation") == "landscape": w, h = h, w
    if mode == "document":
        return dict(page_w=w, page_h=h, cols=1, rows=1, cell_w=w, cell_h=h, ml=0.0, mt=0.0, gx=0.0, gy=0.0)
    return dict(page_w=w, page_h=h, cols=max(1, int(tpl.get("cols", 1))), rows=max(1, int(tpl.get("rows", 1))),
                cell_w=float(tpl.get("cell_w", 70)), cell_h=float(tpl.get("cell_h", 37)),
                ml=float(tpl.get("margin_left", 0)), mt=float(tpl.get("margin_top", 0)),
                gx=float(tpl.get("gap_x", 0)), gy=float(tpl.get("gap_y", 0)))


def table_of(tpl): return next((e for e in tpl.get("elements", []) if e.get("type") == "table"), None)


def table_capacity(el):
    """จำนวนแถวข้อมูลต่อหน้า (หักแถวหัวตาราง และเว้นที่แถวรวมถ้ามีคอลัมน์ผลรวม)"""
    rows_avail = int((float(el["h"]) + 0.001) // max(1.0, float(el.get("row_h", 7))))
    reserve = 1 if any(c.get("sum") for c in el.get("columns", [])) else 0
    return max(1, rows_avail - 1 - reserve)


# ---------------------------------------------------------------- CSV
def read_csv_rows(path):
    """อ่าน CSV เป็นข้อความล้วน (คงเลข 0 นำหน้า) รองรับ UTF-8 / cp874 และตัวคั่น , ; TAB |"""
    for encoding in ("utf-8-sig", "cp874"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                sample = f.read(8192); f.seek(0)
                try: dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error: dialect = csv.excel
                reader = csv.DictReader(f, dialect=dialect)
                columns = [str(c).strip() for c in (reader.fieldnames or [])]
                rows = [{str(k).strip(): (v or "").strip() for k, v in row.items() if k is not None} for row in reader]
            return columns, rows
        except UnicodeDecodeError:
            continue
    raise ValueError("ไม่สามารถอ่านรหัสอักขระของไฟล์ CSV ได้")


# ---------------------------------------------------------------- ตัวสร้างหน้า
class Engine:
    """รวมแม่แบบ + ข้อมูล แล้ววาดลง ReportLab canvas"""
    _image_cache = {}

    def __init__(self, tpl, rows, base_dir=""):
        self.tpl = tpl; self.rows = rows or [{}]; self.base_dir = base_dir
        self.geo = page_geometry(tpl); self.builtin = builtin_context()
        self.table = table_of(tpl); self.mode = tpl.get("mode", "roll")
        self._plan = None

    # ---- วางแผนหน้า
    def label_items(self):
        """รายการลาเบลทั้งหมดหลังคูณจำนวนสำเนา"""
        items = []; col = self.tpl.get("copies_col", ""); fixed = max(1, int(to_float(self.tpl.get("copies", 1)) or 1))
        for idx, row in enumerate(self.rows):
            n = max(0, int(to_float(row.get(col, 1)))) if col else fixed
            items += [(idx, row)] * n
        return items

    def documents(self):
        group = self.tpl.get("group_col", ""); table = self.table
        if group:
            groups = {}
            for row in self.rows: groups.setdefault(row.get(group, ""), []).append(row)
            docs = list(groups.values())
        elif table: docs = [self.rows]
        else: docs = [[r] for r in self.rows]
        cap = table_capacity(table) if table else 10 ** 9
        plans = []
        for grp in docs:
            chunks = [grp[i:i + cap] for i in range(0, len(grp), cap)] if table else [grp]
            plans.append({"rows": grp, "chunks": chunks or [[]]})
        return plans

    def copy_labels(self):
        labels = [s.strip() for s in str(self.tpl.get("copy_labels", "")).split(",") if s.strip()]
        return labels or [""]

    def plan(self):
        if self._plan is not None: return self._plan
        pages = []
        if self.mode == "document":
            docs = self.documents(); self.docs = docs
            for di, doc in enumerate(docs):
                for label in self.copy_labels():
                    for ci in range(len(doc["chunks"])): pages.append(("doc", di, label, ci))
        elif self.mode == "roll":
            pages = [("cell", i) for i in range(len(self.label_items()))]
        else:
            g = self.geo; per = g["cols"] * g["rows"]; start = max(1, int(self.tpl.get("start_cell", 1))) - 1
            total = start + len(self.label_items()); pages = [("sheet", p) for p in range(max(1, math.ceil(total / per)))] if self.label_items() else []
        self._plan = pages
        return pages

    def record_count(self):
        if self.mode == "document":
            self.plan(); return len(self.docs)
        return len(self.label_items())

    def pages_in_record(self, rec):
        if self.mode != "document": return 1
        self.plan(); return len(self.docs[min(rec, len(self.docs) - 1)]["chunks"])

    # ---- วาด
    def make_ctx(self, row, **extra):
        ctx = dict(self.builtin); ctx.update(row); ctx.update(extra); return ctx

    def draw_cell(self, c, ox, oy, ctx, page_no=1, pages=1, chunk=None, doc_rows=None, first=True, last=True, no_start=0, clip=True):
        """วาดแม่แบบหนึ่งชุดที่ตำแหน่ง (ox, oy) มม. จากมุมซ้ายบนของกระดาษ"""
        g = self.geo; page_h_pt = g["page_h"] * MM
        ctx = dict(ctx); ctx.update(page=page_no, pages=pages)
        if doc_rows is not None: ctx["__rows__"] = doc_rows
        c.saveState()
        if clip:
            p = c.beginPath(); p.rect(ox * MM, page_h_pt - (oy + g["cell_h"]) * MM, g["cell_w"] * MM, g["cell_h"] * MM); c.clipPath(p, stroke=0, fill=0)
        for el in self.tpl.get("elements", []):
            show = el.get("show_on", "all")
            if (show == "first" and not first) or (show == "last" and not last): continue
            try: self.draw_element(c, el, ox, oy, ctx, chunk, no_start, last)
            except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:  # องค์ประกอบเดียวผิดพลาดต้องไม่ทำให้ทั้งงานล้ม
                c.setFillColorRGB(.8, 0, 0); c.setFont("Helvetica", 6)
                c.drawString((ox + float(el["x"])) * MM, page_h_pt - (oy + float(el["y"])) * MM - 6, f"[{el.get('name', el.get('type'))}: {type(exc).__name__}]")
        c.restoreState()

    def box(self, el, ox, oy):
        page_h_pt = self.geo["page_h"] * MM
        return (ox + float(el["x"])) * MM, page_h_pt - (oy + float(el["y"]) + float(el["h"])) * MM, float(el["w"]) * MM, float(el["h"]) * MM

    def draw_element(self, c, el, ox, oy, ctx, chunk, no_start, last):
        kind = el["type"]; x, y, w, h = self.box(el, ox, oy)
        if kind == "text": self.draw_text_box(c, el, x, y, w, h, expand(el.get("text", ""), ctx))
        elif kind == "rect":
            fill = FILLS.get(el.get("fill", "none"), FILLS["none"])[1]; bw = float(el.get("border", 0) or 0)
            if fill: c.setFillColorRGB(*fill)
            if bw > 0: c.setLineWidth(bw * MM); c.setStrokeColorRGB(*COLORS.get(el.get("color", "black"), COLORS["black"])[1])
            if fill or bw > 0: c.rect(x, y, w, h, stroke=1 if bw > 0 else 0, fill=1 if fill else 0)
        elif kind == "line":
            c.setLineWidth(max(0.05, float(el.get("thickness", 0.3))) * MM); c.setStrokeColorRGB(*COLORS.get(el.get("color", "black"), COLORS["black"])[1])
            c.line(x, y + h, x + w, y)
        elif kind == "barcode": self.draw_barcode(c, x, y, w, h, expand(el.get("value", ""), ctx).strip(), bool(el.get("human", True)))
        elif kind == "qr": self.draw_qr(c, x, y, w, h, expand(el.get("value", ""), ctx))
        elif kind == "image": self.draw_image(c, el, x, y, w, h, expand(el.get("path", ""), ctx).strip())
        elif kind == "table": self.draw_table(c, el, x, y, w, h, ctx, chunk or [], no_start, last)

    def draw_text_box(self, c, el, x, y, w, h, text):
        fill = FILLS.get(el.get("fill", "none"), FILLS["none"])[1]; bw = float(el.get("border", 0) or 0)
        if fill or bw > 0:
            if fill: c.setFillColorRGB(*fill)
            if bw > 0: c.setLineWidth(bw * MM); c.setStrokeColorRGB(0, 0, 0)
            c.rect(x, y, w, h, stroke=1 if bw > 0 else 0, fill=1 if fill else 0)
        if not text: return
        font = pdf_font(el.get("font", DEFAULT_LABEL_FONT), el.get("bold", False)); pad = PAD_MM * MM
        lines, size = layout_text(text, font, float(el.get("size", 11)), max(1.0, w - 2 * pad), max(1.0, h - 2 * pad) if h > 0 else 0, bool(el.get("shrink", True)))
        lh, asc = line_height(font, size); block = len(lines) * lh
        valign = el.get("valign", "top")
        top = y + h - pad if valign == "top" else (y + h / 2 + block / 2 if valign == "middle" else y + pad + block)
        c.setFillColorRGB(*COLORS.get(el.get("color", "black"), COLORS["black"])[1]); c.setFont(font, size)
        align = el.get("align", "left")
        for k, line in enumerate(lines):
            tw = pdfmetrics.stringWidth(line, font, size)
            tx = x + pad if align == "left" else (x + (w - tw) / 2 if align == "center" else x + w - pad - tw)
            c.drawString(tx, top - k * lh - asc, line)

    def draw_barcode(self, c, x, y, w, h, value, human):
        if not value: return
        text_h = min(9.0, h * 0.3) if human else 0.0
        try:
            d = createBarcodeDrawing("Code128", value=value, humanReadable=False, barHeight=max(4.0, h - text_h), quiet=True)
        except (ValueError, KeyError, TypeError, UnicodeError, AttributeError):
            c.setFillColorRGB(.8, 0, 0); c.setFont("Helvetica", 6); c.drawString(x, y + h / 2, "[Code128: ค่าไม่รองรับ]"); return
        c.saveState(); c.translate(x, y + text_h); c.scale(w / max(d.width, 1), (h - text_h) / max(d.height, 1)); renderPDF.draw(d, c, 0, 0); c.restoreState()
        if human:
            fs = max(5.0, text_h * 0.85); c.setFillColorRGB(0, 0, 0); c.setFont("Helvetica", fs)
            tw = pdfmetrics.stringWidth(value, "Helvetica", fs)
            if tw > w: fs = max(4.0, fs * w / tw); c.setFont("Helvetica", fs); tw = pdfmetrics.stringWidth(value, "Helvetica", fs)
            c.drawString(x + (w - tw) / 2, y + max(0.5, (text_h - fs * 0.7) / 2), value)

    def draw_qr(self, c, x, y, w, h, value):
        if not value: return
        d = createBarcodeDrawing("QR", value=value, barLevel="M"); side = min(w, h); s = side / max(d.width, 1)
        c.saveState(); c.translate(x + (w - side) / 2, y + (h - side) / 2); c.scale(s, s); renderPDF.draw(d, c, 0, 0); c.restoreState()

    def load_image(self, path):
        p = Path(path)
        if not p.is_absolute() and self.base_dir: p = Path(self.base_dir) / p
        if not p.is_file(): return None
        key = (str(p), p.stat().st_mtime_ns)
        if key not in Engine._image_cache:
            if len(Engine._image_cache) > 64: Engine._image_cache.clear()
            with Image.open(p) as im:
                im = ImageOps.exif_transpose(im); im.thumbnail((1600, 1600))
                Engine._image_cache[key] = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        return Engine._image_cache[key]

    def draw_image(self, c, el, x, y, w, h, path):
        if not path: return
        im = self.load_image(path)
        if im is None:
            c.setStrokeColorRGB(.8, 0, 0); c.setLineWidth(.4); c.rect(x, y, w, h); c.setFillColorRGB(.8, 0, 0); c.setFont("Helvetica", 6); c.drawString(x + 2, y + h / 2, "[ไม่พบรูปภาพ]"); return
        iw, ih = im.size; fit = el.get("fit", "contain")
        if fit == "stretch": dw, dh = w, h
        else:
            s = min(w / iw, h / ih) if fit == "contain" else max(w / iw, h / ih); dw, dh = iw * s, ih * s
        c.saveState(); p = c.beginPath(); p.rect(x, y, w, h); c.clipPath(p, stroke=0, fill=0)
        c.drawImage(ImageReader(im), x + (w - dw) / 2, y + (h - dh) / 2, dw, dh, mask="auto"); c.restoreState()

    def draw_table(self, c, el, x, y, w, h, ctx, chunk, no_start, last):
        cols = el.get("columns", [])
        if not cols: return
        row_h = max(1.0, float(el.get("row_h", 7))) * MM; cap = table_capacity(el); has_sum = any(cd.get("sum") for cd in cols)
        font = pdf_font(el.get("font", DEFAULT_LABEL_FONT), False); bold = pdf_font(el.get("font", DEFAULT_LABEL_FONT), True); size = float(el.get("size", 10))
        weights = [max(0.1, float(cd.get("weight", 1))) for cd in cols]; widths = [w * wt / sum(weights) for wt in weights]
        xs = [x]; [xs.append(xs[-1] + cw) for cw in widths]
        top = y + h; line_w = max(0.05, float(el.get("border", 0.25))) * MM
        header_fill = FILLS.get(el.get("header_fill", "lgray"), FILLS["lgray"])[1]
        n_rows = (cap if el.get("fill_empty") else len(chunk)) + (1 if (has_sum and last) else 0)
        total_h = (n_rows + 1) * row_h
        # หัวตาราง
        if header_fill: c.setFillColorRGB(*header_fill); c.rect(x, top - row_h, w, row_h, stroke=0, fill=1)
        if el.get("zebra"):
            c.setFillColorRGB(.96, .96, .96)
            for r in range(1, n_rows + 1, 2): c.rect(x, top - (r + 1) * row_h, w, row_h, stroke=0, fill=1)
        c.setStrokeColorRGB(0, 0, 0); c.setLineWidth(line_w)
        c.rect(x, top - total_h, w, total_h, stroke=1, fill=0)
        for k in range(1, len(cols)): c.line(xs[k], top, xs[k], top - total_h)
        for r in range(1, n_rows + 1): c.setLineWidth(line_w if r == 1 else line_w * .6); c.line(x, top - r * row_h, x + w, top - r * row_h)

        def put(text, col_i, row_i, fnt, align):
            if text == "": return
            text, sz = fit_single_line(str(text), fnt, size, widths[col_i] - 2 * PAD_MM * MM)
            tw = pdfmetrics.stringWidth(text, fnt, sz); lh, asc = line_height(fnt, sz)
            tx = xs[col_i] + PAD_MM * MM if align == "left" else (xs[col_i] + (widths[col_i] - tw) / 2 if align == "center" else xs[col_i + 1] - PAD_MM * MM - tw)
            c.setFillColorRGB(0, 0, 0); c.setFont(fnt, sz); c.drawString(tx, top - row_i * row_h - (row_h - lh) / 2 - asc, text)
        for ci, cd in enumerate(cols): put(expand(cd.get("title", ""), ctx), ci, 0, bold, "center")
        for ri, row in enumerate(chunk, start=1):
            row_ctx = dict(ctx); row_ctx.update(row); row_ctx["no"] = no_start + ri; row_ctx["__rows__"] = [row]
            for ci, cd in enumerate(cols): put(expand(cd.get("value", ""), row_ctx), ci, ri, font, cd.get("align", "left"))
        if has_sum and last:
            ri = n_rows; rows_all = ctx.get("__rows__") or []
            if header_fill: c.setFillColorRGB(*header_fill); c.rect(x, top - (ri + 1) * row_h, w, row_h, stroke=0, fill=1); c.setStrokeColorRGB(0, 0, 0); c.rect(x, top - (ri + 1) * row_h, w, row_h, stroke=1, fill=0)
            first_sum = next(i for i, cd in enumerate(cols) if cd.get("sum"))
            label = expand(el.get("total_label", "รวม"), ctx)
            if first_sum > 0 and label:
                t, sz = fit_single_line(label, bold, size, xs[first_sum] - x - 2 * PAD_MM * MM); lh, asc = line_height(bold, sz)
                c.setFillColorRGB(0, 0, 0); c.setFont(bold, sz); c.drawString(xs[first_sum] - PAD_MM * MM - pdfmetrics.stringWidth(t, bold, sz), top - ri * row_h - (row_h - lh) / 2 - asc, t)
            for ci, cd in enumerate(cols):
                if not cd.get("sum"): continue
                m = re.search(r"\{([^{}:]+)(?::([^{}]*))?\}", cd.get("value", ""))
                if m: put(format_number(sum(to_float(r.get(m.group(1).strip(), "")) for r in rows_all), m.group(2)), ci, ri, bold, "right")

    # ---- ประกอบทั้งงาน
    def draw_page(self, c, desc):
        g = self.geo
        if desc[0] == "doc":
            _, di, label, ci = desc; doc = self.docs[di]; pages = len(doc["chunks"]); cap = table_capacity(self.table) if self.table else 0
            ctx = self.make_ctx(doc["rows"][0] if doc["rows"] else {}, record=di + 1, copy_label=label)
            self.draw_cell(c, 0, 0, ctx, ci + 1, pages, doc["chunks"][ci], doc["rows"], ci == 0, ci == pages - 1, ci * cap, clip=False)
        elif desc[0] == "cell":
            idx, row = self.label_items()[desc[1]]; self.draw_cell(c, 0, 0, self.make_ctx(row, record=idx + 1), desc[1] + 1, len(self.plan()))
        else:
            per = g["cols"] * g["rows"]; start = max(1, int(self.tpl.get("start_cell", 1))) - 1; items = self.label_items(); total_pages = len(self.plan())
            for slot in range(per):
                n = desc[1] * per + slot - start
                cx = g["ml"] + (slot % g["cols"]) * (g["cell_w"] + g["gx"]); cy = g["mt"] + (slot // g["cols"]) * (g["cell_h"] + g["gy"])
                if self.tpl.get("show_guides"):
                    c.saveState(); c.setDash(2, 2); c.setLineWidth(.3); c.setStrokeColorRGB(.6, .6, .6)
                    c.rect(cx * MM, (g["page_h"] - cy - g["cell_h"]) * MM, g["cell_w"] * MM, g["cell_h"] * MM); c.restoreState()
                if 0 <= n < len(items):
                    idx, row = items[n]; self.draw_cell(c, cx, cy, self.make_ctx(row, record=idx + 1), desc[1] + 1, total_pages)

    def render_pdf(self, dest, progress=None):
        pages = self.plan(); g = self.geo; c = reportlab_canvas.Canvas(dest, pagesize=(g["page_w"] * MM, g["page_h"] * MM))
        c.setTitle(PROGRAM_NAME)
        for i, desc in enumerate(pages):
            self.draw_page(c, desc); c.showPage()
            if progress and (i % 20 == 0 or i == len(pages) - 1): progress(i + 1, len(pages))
        if not pages: c.showPage()
        c.save(); return len(pages)

    def render_preview(self, rec=0, page=0, sheet=False):
        """PDF 1 หน้าสำหรับแสดงบนจอ: โหมดออกแบบ = 1 ลาเบล/1 หน้าเอกสาร, sheet=True = ทั้งแผ่น"""
        g = self.geo; buf = BytesIO(); self.plan()
        if self.mode == "document":
            if not self.docs: return None
            rec = min(rec, len(self.docs) - 1); page = min(page, len(self.docs[rec]["chunks"]) - 1)
            desc = ("doc", rec, self.copy_labels()[0], page); size = (g["page_w"], g["page_h"])
            c = reportlab_canvas.Canvas(buf, pagesize=(size[0] * MM, size[1] * MM)); self.draw_page(c, desc)
        elif sheet and self.mode == "sheet":
            pages = self.plan()
            c = reportlab_canvas.Canvas(buf, pagesize=(g["page_w"] * MM, g["page_h"] * MM))
            self.draw_page(c, pages[min(page, len(pages) - 1)] if pages else ("sheet", 0))
        else:
            items = self.label_items(); row = items[min(rec, len(items) - 1)] if items else (0, {})
            c = reportlab_canvas.Canvas(buf, pagesize=(g["cell_w"] * MM, g["cell_h"] * MM))
            saved = self.geo; self.geo = dict(g, page_w=g["cell_w"], page_h=g["cell_h"])
            try: self.draw_cell(c, 0, 0, self.make_ctx(row[1], record=row[0] + 1), 1, 1, clip=True)
            finally: self.geo = saved
        c.showPage(); c.save(); return buf.getvalue()

    # ---- ตรวจแม่แบบ
    def validate(self, columns):
        errors, warnings = [], []; g = self.geo; tpl = self.tpl; cols = set(columns) | set(BUILTIN_TOKENS)
        if not tpl.get("elements"): errors.append("ยังไม่มีองค์ประกอบในแม่แบบ")
        if g["cell_w"] <= 0 or g["cell_h"] <= 0 or g["page_w"] <= 0 or g["page_h"] <= 0: errors.append("ขนาดกระดาษ/ลาเบลต้องมากกว่า 0")
        if self.mode == "sheet":
            need_w = g["ml"] + g["cols"] * g["cell_w"] + (g["cols"] - 1) * g["gx"]; need_h = g["mt"] + g["rows"] * g["cell_h"] + (g["rows"] - 1) * g["gy"]
            if need_w > g["page_w"] + 0.05: errors.append(f"ตารางลาเบลกว้าง {need_w:.1f} มม. เกินความกว้างกระดาษ {g['page_w']:.1f} มม.")
            if need_h > g["page_h"] + 0.05: errors.append(f"ตารางลาเบลสูง {need_h:.1f} มม. เกินความสูงกระดาษ {g['page_h']:.1f} มม.")
        used = set(); thai_font_missing = False; tables = [e for e in tpl.get("elements", []) if e.get("type") == "table"]
        if len(tables) > 1: warnings.append("มีตารางมากกว่า 1 ตาราง: ระบบแบ่งหน้าตามตารางแรกเท่านั้น")
        for el in tpl.get("elements", []):
            name = el.get("name", el.get("type"))
            if float(el.get("x", 0)) < -0.01 or float(el.get("y", 0)) < -0.01 or float(el["x"]) + float(el["w"]) > g["cell_w"] + 0.05 or float(el["y"]) + float(el["h"]) > g["cell_h"] + 0.05:
                warnings.append(f"“{name}” อยู่เกินขอบ{'ลาเบล' if self.mode != 'document' else 'กระดาษ'}")
            texts = [el.get(k, "") for k in ("text", "value", "path")]
            if el["type"] == "table":
                texts += [cd.get("value", "") for cd in el.get("columns", [])] + [cd.get("title", "") for cd in el.get("columns", [])]
                if not el.get("columns"): warnings.append(f"ตาราง “{name}” ยังไม่มีคอลัมน์")
            for t in texts:
                used |= referenced_names(t)
                if re.search(r"[\u0e00-\u0e7f]", t or "") and not font_available(el.get("font", DEFAULT_LABEL_FONT), el.get("bold", False)): thai_font_missing = True
            if el["type"] == "barcode":
                sample = expand(el.get("value", ""), self.make_ctx(self.rows[0]))
                modules = 11 * (len(sample) + 2) + 35
                if sample and float(el["w"]) / modules < 0.19: warnings.append(f"บาร์โค้ด “{name}” แน่นเกินไป (แท่งบางกว่า 0.19 มม.) อาจสแกนไม่ติด: เพิ่มความกว้างหรือใช้ค่าที่สั้นลง")
        missing = sorted(n for n in used if n not in cols and not n.startswith("__"))
        if missing: warnings.append("แม่แบบอ้างถึงคอลัมน์ที่ไม่มีในข้อมูล: " + ", ".join(missing))
        if thai_font_missing: warnings.append("ไม่พบฟอนต์ภาษาไทยในเครื่อง ข้อความไทยใน PDF จะแสดงผิด (ติดตั้ง Leelawadee UI / Tahoma หรือวางไฟล์ฟอนต์ใน portable_fonts)")
        for grp in ("group_col", "copies_col"):
            if tpl.get(grp) and tpl[grp] not in columns: warnings.append(f"คอลัมน์ “{tpl[grp]}” ในการตั้งค่าไม่มีในข้อมูล")
        if self.mode == "document" and not self.table and tpl.get("group_col"): warnings.append("ตั้งค่าจัดกลุ่มเอกสารไว้ แต่แม่แบบไม่มีตาราง")
        return errors, warnings


# ---------------------------------------------------------------- ตรวจ/แปลงแม่แบบจากไฟล์
def _num(value, default, minimum=None):
    try: out = float(value)
    except (TypeError, ValueError): out = default
    return max(minimum, out) if minimum is not None else out


def migrate_v1_template(data):
    """แปลงเทมเพลตของ Label Designer รุ่นก่อน (fields/page) เป็นแม่แบบใหม่"""
    page = data.get("page", {}) or {}; orient = page.get("orientation", "แนวตั้ง")
    if orient == "กำหนดเอง": w, h = _num(page.get("custom_width_mm"), 100, 1), _num(page.get("custom_height_mm"), 150, 1)
    else: w, h = (100.0, 150.0) if orient == "แนวตั้ง" else (150.0, 100.0)
    cols = int(_num(page.get("sheet_columns"), 1, 1)); rows = int(_num(page.get("sheet_rows"), 1, 1)); gx = _num(page.get("sheet_gap_x_mm"), 0, 0); gy = _num(page.get("sheet_gap_y_mm"), 0, 0)
    tpl = new_template("sheet" if cols * rows > 1 else "roll")
    tpl.update(page_w=w, page_h=h, paper="กำหนดเอง", cols=cols, rows=rows, cell_w=w, cell_h=h, gap_x=gx, gap_y=gy)
    if cols * rows > 1: tpl.update(page_w=w * cols + gx * (cols - 1), page_h=h * rows + gy * (rows - 1))
    dx = _num(page.get("margin_left_mm"), 0) + _num(page.get("offset_x_mm"), 0); dy = _num(page.get("margin_top_mm"), 0) + _num(page.get("offset_y_mm"), 0)
    for f in data.get("fields", []):
        if not isinstance(f, dict): continue
        kind = f.get("type", "ข้อความ"); src = f.get("csv", ""); static = src == "__STATIC__"
        value = str(f.get("text", "")) if static else ("{" + src + "}" if src and src != "__IMAGE__" else "")
        geo = dict(x=_num(f.get("x"), 0) + dx, y=_num(f.get("y"), 0) + dy, w=_num(f.get("width"), 20, 1), h=_num(f.get("height"), 8, 1), name=str(f.get("name", "")) or ELEMENT_NAMES["text"])
        if kind == "รูปภาพ": el = default_element("image", path=str(f.get("image", "")), fit={"Cover": "cover", "Stretch": "stretch"}.get(f.get("image_mode"), "contain"), **geo)
        elif kind == "QR Code": el = default_element("qr", value=value, **geo)
        elif kind == "Barcode": el = default_element("barcode", value=value, **geo)
        else:
            family = f.get("font_family", DEFAULT_LABEL_FONT)
            el = default_element("text", text=value, font=family if family in LABEL_FONT_FILES else DEFAULT_LABEL_FONT, size=_num(f.get("size"), 12, 4), bold=bool(f.get("bold")),
                                 align=f.get("align", "left") if f.get("align") in ("left", "center", "right") else "left", **geo)
        tpl["elements"].append(el)
    return tpl


def normalize_template(data):
    """ตรวจและเติมค่าเริ่มต้นให้แม่แบบที่อ่านจากไฟล์ (กันค่าผิดชนิด/ขาดหาย)"""
    if not isinstance(data, dict): raise ValueError("ไฟล์แม่แบบไม่ถูกต้อง")
    if "fields" in data and "elements" not in data: return normalize_template(migrate_v1_template(data))
    tpl = new_template(data.get("mode") if data.get("mode") in ("roll", "sheet", "document") else "roll")
    for k in tpl:
        if k in data and k != "elements": tpl[k] = data[k]
    for k in ("page_w", "page_h", "cell_w", "cell_h"): tpl[k] = _num(tpl[k], 100, 1)
    for k in ("margin_left", "margin_top", "gap_x", "gap_y"): tpl[k] = _num(tpl[k], 0, 0)
    for k in ("cols", "rows", "start_cell", "copies"): tpl[k] = int(_num(tpl[k], 1, 1))
    if tpl["paper"] not in PAPER_SIZES: tpl["paper"] = "A4"
    if tpl["orientation"] not in ("portrait", "landscape"): tpl["orientation"] = "portrait"
    tpl["show_guides"] = bool(tpl["show_guides"]); seen = set(); elements = []
    for el in data.get("elements", []) or []:
        if not isinstance(el, dict) or el.get("type") not in ELEMENT_NAMES: continue
        base = default_element(el["type"]); base.update({k: v for k, v in el.items() if k in base})
        for k in ("x", "y", "w", "h"): base[k] = _num(base[k], 0)
        base["id"] = str(base["id"]) if str(base["id"]) not in seen else new_id(); seen.add(base["id"])
        if base["type"] == "table":
            cols = [c for c in (base.get("columns") or []) if isinstance(c, dict)]
            base["columns"] = [{"title": str(c.get("title", "")), "value": str(c.get("value", "")), "weight": _num(c.get("weight"), 10, 0.1), "align": c.get("align") if c.get("align") in ("left", "center", "right") else "left", "sum": bool(c.get("sum"))} for c in cols]
        elements.append(base)
    tpl["elements"] = elements
    return tpl



# ---------------------------------------------------------------- แม่แบบเริ่มต้น + ข้อมูลตัวอย่าง
def _t(text, x, y, w, h, **kw):
    return default_element("text", text=text, x=x, y=y, w=w, h=h, name=kw.pop("name", "ข้อความ"), **kw)


def starter_template(kind):
    """คืน (แม่แบบ, คอลัมน์, แถวข้อมูลตัวอย่าง)"""
    if kind == "shipping":
        tpl = new_template("roll"); tpl.update(page_w=100.0, page_h=150.0)
        tpl["elements"] = [
            default_element("rect", x=2, y=2, w=96, h=146, border=0.5, name="กรอบนอก"),
            _t("ผู้ส่ง: {sender}", 4, 4, 92, 9, size=9, name="ผู้ส่ง"),
            default_element("line", x=2, y=14, w=96, h=0, name="เส้น"),
            _t("ผู้รับ", 4, 16, 30, 5, size=8, color="gray", name="หัวข้อผู้รับ"),
            _t("{customer}", 4, 21, 92, 10, size=16, bold=True, name="ชื่อผู้รับ"),
            _t("{address}", 4, 32, 92, 30, size=12, name="ที่อยู่"),
            _t("โทร {phone}", 4, 63, 70, 8, size=12, bold=True, name="เบอร์โทร"),
            default_element("line", x=2, y=74, w=96, h=0, name="เส้น"),
            default_element("qr", value="{order_no}", x=4, y=77, w=36, h=36, name="QR คำสั่งซื้อ"),
            default_element("barcode", value="{order_no}", x=44, y=80, w=52, h=24, name="บาร์โค้ดคำสั่งซื้อ"),
            _t("Order: {order_no}", 44, 105, 52, 7, size=9, align="center", name="เลขคำสั่งซื้อ"),
            _t("เก็บเงินปลายทาง {cod:,.2f} บาท", 4, 118, 92, 12, size=16, bold=True, align="center", valign="middle", border=0.5, name="COD"),
            _t("{note}", 4, 132, 92, 14, size=9, color="dgray", name="หมายเหตุ")]
        cols = ["order_no", "customer", "address", "phone", "sender", "cod", "note"]
        rows = [dict(order_no="SO2611001", customer="คุณสมชาย ใจดี", address="99/9 หมู่ 3 ต.บางพูด อ.ปากเกร็ด จ.นนทบุรี 11120", phone="081-234-5678", sender="ร้านตัวอย่าง โทร 02-111-2222", cod="1250", note="กรุณาโทรก่อนส่ง"),
                dict(order_no="SO2611002", customer="บริษัท เอบีซี จำกัด", address="123 ถนนสุขุมวิท แขวงคลองเตย เขตคลองเตย กรุงเทพมหานคร 10110", phone="02-345-6789", sender="ร้านตัวอย่าง โทร 02-111-2222", cod="0", note="ส่งในเวลาทำการ")]
        return tpl, cols, rows
    if kind == "product":
        tpl = new_template("sheet"); tpl.update(paper="A4", orientation="portrait", cols=3, rows=8, cell_w=70.0, cell_h=37.0, copies_col="qty")
        g = page_geometry(tpl); tpl["margin_left"] = round((g["page_w"] - 3 * 70) / 2, 2); tpl["margin_top"] = round((g["page_h"] - 8 * 37) / 2, 2)
        tpl["elements"] = [
            _t("{name}", 2, 1.5, 66, 11, size=11, bold=True, valign="middle", name="ชื่อสินค้า"),
            default_element("barcode", value="{sku}", x=3, y=13, w=64, h=14, name="บาร์โค้ด"),
            _t("{price:,.2f} บาท", 2, 28, 66, 8, size=14, bold=True, align="right", valign="middle", name="ราคา")]
        cols = ["sku", "name", "price", "qty"]
        rows = [dict(sku="8851234500012", name="น้ำดื่มสะอาด 600 มล.", price="7", qty="3"), dict(sku="8851234500029", name="ขนมปังกรอบรสเนย แพ็คใหญ่", price="45.5", qty="2"),
                dict(sku="SKU-00123", name="เสื้อยืดคอกลมสีขาว ไซส์ L", price="299", qty="4")]
        return tpl, cols, rows
    tpl = new_template("document"); tpl.update(paper="A4", orientation="portrait", group_col="doc_no", copy_labels="ต้นฉบับ,สำเนา")
    tbl = default_element("table", x=10, y=62, w=190, h=170, name="ตารางรายการ", fill_empty=True, row_h=7.0,
                          columns=[{"title": "ลำดับ", "value": "{no}", "weight": 9, "align": "center", "sum": False},
                                   {"title": "รายการ", "value": "{item}", "weight": 70, "align": "left", "sum": False},
                                   {"title": "จำนวน", "value": "{qty}", "weight": 14, "align": "right", "sum": False},
                                   {"title": "หน่วย", "value": "{unit}", "weight": 12, "align": "center", "sum": False},
                                   {"title": "ราคา/หน่วย", "value": "{price:,.2f}", "weight": 20, "align": "right", "sum": False},
                                   {"title": "จำนวนเงิน", "value": "{amount:,.2f}", "weight": 22, "align": "right", "sum": True}])
    tpl["elements"] = [
        _t("บริษัท ตัวอย่าง จำกัด", 10, 8, 110, 8, size=15, bold=True, name="ชื่อบริษัท"),
        _t("123 ถนนตัวอย่าง แขวงตัวอย่าง เขตตัวอย่าง กรุงเทพฯ 10000\nโทร 02-123-4567  เลขประจำตัวผู้เสียภาษี 0-1234-56789-01-2", 10, 16, 120, 12, size=9, name="ที่อยู่บริษัท"),
        _t("ใบส่งของ", 130, 8, 70, 9, size=18, bold=True, align="right", name="ชื่อเอกสาร"),
        _t("{copy_label}", 130, 17, 70, 6, size=10, align="right", color="dgray", name="ต้นฉบับ/สำเนา"),
        default_element("rect", x=10, y=30, w=116, h=28, border=0.3, name="กรอบลูกค้า"),
        _t("ลูกค้า: {customer}", 12, 31, 112, 7, size=11, bold=True, name="ลูกค้า"),
        _t("{address}", 12, 38, 112, 18, size=10, name="ที่อยู่ลูกค้า"),
        default_element("rect", x=130, y=30, w=70, h=28, border=0.3, name="กรอบเลขที่"),
        _t("เลขที่: {doc_no}", 132, 32, 66, 7, size=11, bold=True, name="เลขที่"),
        _t("วันที่: {doc_date}", 132, 40, 66, 7, size=11, name="วันที่"),
        default_element("barcode", value="{doc_no}", x=132, y=47, w=66, h=9, human=False, name="บาร์โค้ดเลขที่"),
        tbl,
        _t("({bahttext(sum(amount))})", 10, 234, 190, 8, size=11, bold=True, show_on="last", name="จำนวนเงินตัวอักษร"),
        default_element("line", x=20, y=268, w=55, h=0, show_on="last", name="เส้นลงชื่อ 1"), _t("ผู้รับของ", 20, 269, 55, 6, size=10, align="center", show_on="last", name="ผู้รับของ"),
        default_element("line", x=135, y=268, w=55, h=0, show_on="last", name="เส้นลงชื่อ 2"), _t("ผู้ส่งของ", 135, 269, 55, 6, size=10, align="center", show_on="last", name="ผู้ส่งของ"),
        _t("หน้า {page}/{pages}", 150, 287, 50, 6, size=9, align="right", color="dgray", name="เลขหน้า")]
    cols = ["doc_no", "doc_date", "customer", "address", "item", "qty", "unit", "price", "amount"]
    rows = []
    items = [("กระดาษ A4 80 แกรม", 5, "รีม", 125), ("ปากกาลูกลื่นสีน้ำเงิน", 24, "ด้าม", 6.5), ("แฟ้มสันกว้าง 3 นิ้ว", 12, "เล่ม", 48), ("หมึกพิมพ์สีดำ", 2, "กล่อง", 890), ("เทปใส 1 นิ้ว", 10, "ม้วน", 22.5)]
    for name, qty, unit, price in items:
        rows.append(dict(doc_no="DN-2611-001", doc_date="21/11/2569", customer="บริษัท เอบีซี เทรดดิ้ง จำกัด", address="99 ถนนพระราม 9 แขวงห้วยขวาง เขตห้วยขวาง กรุงเทพมหานคร 10310", item=name, qty=str(qty), unit=unit, price=str(price), amount=f"{qty * price:.2f}"))
    for k in range(1, 31):
        rows.append(dict(doc_no="DN-2611-002", doc_date="21/11/2569", customer="ห้างหุ้นส่วนจำกัด สยามพาณิชย์", address="45/6 ถนนนิมมานเหมินท์ ต.สุเทพ อ.เมือง จ.เชียงใหม่ 50200", item=f"สินค้าตัวอย่างรายการที่ {k}", qty=str(k % 7 + 1), unit="ชิ้น", price="35", amount=f"{(k % 7 + 1) * 35:.2f}"))
    return tpl, cols, rows


# =====================================================================
#  Document & Label Designer — หน้าจอ
# =====================================================================
class ScrollFrame(ttk.Frame):
    """กรอบเลื่อนแนวตั้ง (ใช้กับแผงคุณสมบัติ)"""
    def __init__(self, parent, bg="#FFFFFF"):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True); bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel)); w.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        if self.inner.winfo_height() > self.canvas.winfo_height(): self.canvas.yview_scroll(int(-event.delta / 120), "units")


class DesignerTab:
    PAD = 24
    INSERT_HINTS = [("{page}", "เลขหน้า"), ("{pages}", "จำนวนหน้าทั้งหมด"), ("{no}", "ลำดับแถวในตาราง"), ("{date}", "วันที่วันนี้ (ค.ศ.)"), ("{date_th}", "วันที่วันนี้ (พ.ศ.)"),
                    ("{copy_label}", "ต้นฉบับ/สำเนา"), ("{sum(คอลัมน์)}", "ผลรวมของคอลัมน์"), ("{count()}", "จำนวนรายการ"),
                    ("{bahttext(sum(คอลัมน์))}", "จำนวนเงินตัวอักษร"), ("{คอลัมน์:,.2f}", "แสดงเป็นตัวเลข 2 ทศนิยม")]
    ALIGN = [("left", "ซ้าย"), ("center", "กลาง"), ("right", "ขวา")]
    VALIGN = [("top", "บน"), ("middle", "กลาง"), ("bottom", "ล่าง")]
    SHOW_ON = [("all", "ทุกหน้า"), ("first", "หน้าแรกเท่านั้น"), ("last", "หน้าสุดท้ายเท่านั้น")]
    FITS = [("contain", "พอดี (ไม่ตัดภาพ)"), ("cover", "เต็มกรอบ (ตัดส่วนเกิน)"), ("stretch", "ยืดให้เต็ม")]

    def __init__(self, parent, app):
        self.parent, self.app, self.root = parent, app, app.root
        self.session_path = Path.home() / ".bowa_designer_session.json"
        self.columns, self.rows, self.csv_path, self.is_demo = [], [], "", True
        self.tpl = new_template(); self.sel_id = None
        self.rec = 0; self.page = 0; self.scale = 3.0; self.fit_mode = True; self.photo = None; self.pxmm = 3.0
        self.drag = None; self.page_mm = (100.0, 150.0); self.busy = False; self._loading = False; self._jobs = {}
        self.history, self.hidx = [], -1; self.pvars = {}; self._props_for = None
        self.sheet_view = tk.BooleanVar(value=False); self.snap_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value=""); self.progress_var = tk.DoubleVar(value=0.0); self.info_var = tk.StringVar(value="")
        st = self.app.style; st.configure("D.TCheckbutton", background=self.app.WHITE); st.configure("D.TRadiobutton", background=self.app.WHITE)
        self.build_ui()
        if not self.load_session(): self.apply_starter("shipping", ask=False)

    # ------------------------------------------------------------ ตัวช่วย
    def later(self, key, ms, func):
        if key in self._jobs:
            try: self.root.after_cancel(self._jobs[key])
            except tk.TclError: pass
        self._jobs[key] = self.root.after(ms, func)

    def tip(self, widget, text):
        self.app.add_tooltip(widget, text)

    def sel_el(self):
        return next((e for e in self.tpl["elements"] if e["id"] == self.sel_id), None)

    def engine(self):
        return Engine(self.tpl, self.rows or [{}], str(Path(self.csv_path).parent) if self.csv_path else "")

    def geo(self): return page_geometry(self.tpl)

    def view_size(self):
        g = self.geo()
        if self.tpl["mode"] == "document" or (self.tpl["mode"] == "sheet" and self.sheet_view.get()): return g["page_w"], g["page_h"]
        return g["cell_w"], g["cell_h"]

    def sheet_active(self): return self.tpl["mode"] == "sheet" and self.sheet_view.get()

    # ------------------------------------------------------------ สร้างหน้าจอ
    def build_ui(self):
        W = self.app.WHITE
        bar = ttk.Frame(self.parent); bar.pack(fill="x", padx=6, pady=(6, 3))
        mb = ttk.Menubutton(bar, text="📋 แม่แบบเริ่มต้น ▾"); menu = tk.Menu(mb, tearoff=0)
        for key, label in (("shipping", "ลาเบลจัดส่ง 100×150 (ผู้รับ/ที่อยู่/QR/บาร์โค้ด)"), ("product", "ลาเบลสินค้า A4 3×8 (ชื่อ/บาร์โค้ด/ราคา)"), ("delivery", "ใบส่งของ A4 (ตารางรายการ/รวมเงิน/สำเนา)")):
            menu.add_command(label=label, command=lambda k=key: self.apply_starter(k))
        mb["menu"] = menu; mb.pack(side="left", padx=2)
        for text, cmd, style, tip in (("📥 โหลดแม่แบบ", self.load_template, "TButton", "เปิดไฟล์แม่แบบ .json (รองรับไฟล์จาก Label Designer รุ่นเก่า)"),
                                      ("💾 บันทึกแม่แบบ", self.save_template, "TButton", "บันทึกแม่แบบเป็นไฟล์ .json"),
                                      ("📂 โหลดข้อมูล CSV", self.load_csv, "Accent.TButton", "โหลดข้อมูลที่จะพิมพ์ (CSV ตัวคั่น , ; TAB)"),
                                      ("✔ ตรวจแม่แบบ", self.check_template, "TButton", "ตรวจคอลัมน์ที่อ้างถึง ขนาด ฟอนต์ และความหนาแน่นบาร์โค้ด"),
                                      ("📄 สร้าง PDF", self.create_pdf, "Success.TButton", "สร้างไฟล์ PDF ทั้งหมดจากข้อมูล"),
                                      ("🖨 พิมพ์", self.print_pdf, "Warning.TButton", "สร้าง PDF และส่งเข้าเครื่องพิมพ์")):
            b = ttk.Button(bar, text=text, command=cmd, style=style); b.pack(side="left", padx=2); self.tip(b, tip)
        ttk.Progressbar(bar, variable=self.progress_var, maximum=100, length=130).pack(side="right", padx=4)
        tk.Label(bar, textvariable=self.info_var, fg=self.app.TEXT_LIGHT, font=("Segoe UI", 8)).pack(side="right", padx=6)

        paned = ttk.PanedWindow(self.parent, orient="horizontal"); paned.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        left = tk.Frame(paned, width=315, bg=W); right = tk.Frame(paned, width=300, bg=W); center = ttk.Frame(paned)
        for f in (left, right): f.pack_propagate(False)
        paned.add(left, weight=0); paned.add(center, weight=1); paned.add(right, weight=0)
        self.build_left(left); self.build_center(center); self.build_right(right)

    # ---- ซ้าย: กระดาษ + ข้อมูล
    def build_left(self, parent):
        nb = ttk.Notebook(parent); nb.pack(fill="both", expand=True)
        page_tab = tk.Frame(nb, bg=self.app.WHITE, padx=6, pady=4); data_tab = tk.Frame(nb, bg=self.app.WHITE, padx=6, pady=4)
        nb.add(page_tab, text=" 📄 กระดาษ "); nb.add(data_tab, text=" 📊 ข้อมูล ")
        W = self.app.WHITE; self.pv = {}
        for key in ("mode", "paper", "orientation", "roll_preset", "sheet_preset", "group_col", "copy_labels", "copies_col"): self.pv[key] = tk.StringVar()
        for key in ("page_w", "page_h", "cols", "rows", "cell_w", "cell_h", "margin_left", "margin_top", "gap_x", "gap_y", "start_cell", "copies"): self.pv[key] = tk.StringVar()
        self.pv["show_guides"] = tk.BooleanVar()

        def lab(parent_, text, r, c=0): tk.Label(parent_, text=text, bg=W, anchor="w").grid(row=r, column=c, sticky="w", padx=2, pady=1)
        def ent(parent_, key, r, c, width=7): e = ttk.Entry(parent_, textvariable=self.pv[key], width=width); e.grid(row=r, column=c, sticky="w", padx=2, pady=1); return e

        tk.Label(page_tab, text="ชนิดงาน", bg=W, font=("Segoe UI", 9, "bold"), fg=self.app.PRIMARY).pack(anchor="w")
        self.mode_combo = ttk.Combobox(page_tab, textvariable=self.pv["mode"], values=[m[1] for m in MODES], state="readonly"); self.mode_combo.pack(fill="x", pady=(0, 6))
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_selected)

        # กระดาษ (sheet/document)
        self.f_paper = tk.LabelFrame(page_tab, text="กระดาษ", bg=W, fg=self.app.PRIMARY, padx=4, pady=3)
        lab(self.f_paper, "ขนาด", 0); pc = ttk.Combobox(self.f_paper, textvariable=self.pv["paper"], values=list(PAPER_SIZES), state="readonly", width=20); pc.grid(row=0, column=1, columnspan=3, sticky="w", padx=2); pc.bind("<<ComboboxSelected>>", self.on_paper_selected)
        lab(self.f_paper, "แนว", 1)
        ttk.Radiobutton(self.f_paper, style="D.TRadiobutton", text="ตั้ง", value="portrait", variable=self.pv["orientation"]).grid(row=1, column=1, sticky="w"); ttk.Radiobutton(self.f_paper, style="D.TRadiobutton", text="นอน", value="landscape", variable=self.pv["orientation"]).grid(row=1, column=2, sticky="w")
        self.f_custom = tk.Frame(self.f_paper, bg=W); lab(self.f_custom, "กว้าง", 0); ent(self.f_custom, "page_w", 0, 1); lab(self.f_custom, "สูง", 0, 2); ent(self.f_custom, "page_h", 0, 3); self.f_custom.grid(row=2, column=0, columnspan=4, sticky="w")
        # ลาเบลม้วน
        self.f_roll = tk.LabelFrame(page_tab, text="ขนาดลาเบล (มม.)", bg=W, fg=self.app.PRIMARY, padx=4, pady=3)
        lab(self.f_roll, "สำเร็จรูป", 0); rc = ttk.Combobox(self.f_roll, textvariable=self.pv["roll_preset"], values=list(ROLL_SIZES) + ["กำหนดเอง"], state="readonly", width=12); rc.grid(row=0, column=1, columnspan=3, sticky="w", padx=2); rc.bind("<<ComboboxSelected>>", self.on_roll_preset)
        lab(self.f_roll, "กว้าง", 1); ent(self.f_roll, "page_w", 1, 1); lab(self.f_roll, "สูง", 1, 2); ent(self.f_roll, "page_h", 1, 3)
        b = ttk.Button(self.f_roll, text="⇄ สลับกว้าง/สูง", command=self.swap_roll); b.grid(row=2, column=0, columnspan=4, sticky="w", padx=2, pady=2)
        # แผ่นลาเบล
        self.f_sheet = tk.LabelFrame(page_tab, text="ตารางลาเบลบนแผ่น", bg=W, fg=self.app.PRIMARY, padx=4, pady=3)
        lab(self.f_sheet, "สำเร็จรูป", 0); sc = ttk.Combobox(self.f_sheet, textvariable=self.pv["sheet_preset"], values=list(SHEET_PRESETS), state="readonly", width=17); sc.grid(row=0, column=1, columnspan=3, sticky="w", padx=2); sc.bind("<<ComboboxSelected>>", self.on_sheet_preset)
        for r, (cap, k1, k2) in enumerate((("คอลัมน์ × แถว", "cols", "rows"), ("ลาเบล กว้าง × สูง", "cell_w", "cell_h"), ("ขอบซ้าย / ขอบบน", "margin_left", "margin_top"), ("ช่องห่าง นอน / ตั้ง", "gap_x", "gap_y")), start=1):
            lab(self.f_sheet, cap, r); ent(self.f_sheet, k1, r, 1, 5); tk.Label(self.f_sheet, text="×" if r < 3 else "/", bg=W).grid(row=r, column=2); ent(self.f_sheet, k2, r, 3, 5)
        lab(self.f_sheet, "เริ่มที่ช่องที่", 5); ent(self.f_sheet, "start_cell", 5, 1, 5)
        ttk.Button(self.f_sheet, text="จัดกึ่งกลาง", command=self.center_grid).grid(row=5, column=3, sticky="w", padx=2)
        ttk.Checkbutton(self.f_sheet, style="D.TCheckbutton", text="พิมพ์เส้นประกรอบลาเบล", variable=self.pv["show_guides"]).grid(row=6, column=0, columnspan=4, sticky="w")
        # จำนวนสำเนา (ลาเบล)
        self.f_copies = tk.LabelFrame(page_tab, text="จำนวนดวงต่อรายการ", bg=W, fg=self.app.PRIMARY, padx=4, pady=3)
        lab(self.f_copies, "ตายตัว", 0); ent(self.f_copies, "copies", 0, 1, 5); lab(self.f_copies, "หรือจากคอลัมน์", 1)
        self.copies_combo = ttk.Combobox(self.f_copies, textvariable=self.pv["copies_col"], width=14); self.copies_combo.grid(row=1, column=1, columnspan=3, sticky="w", padx=2)
        # เอกสาร
        self.f_doc = tk.LabelFrame(page_tab, text="เอกสาร", bg=W, fg=self.app.PRIMARY, padx=4, pady=3)
        lab(self.f_doc, "จัดกลุ่มตามคอลัมน์", 0); self.group_combo = ttk.Combobox(self.f_doc, textvariable=self.pv["group_col"], width=16); self.group_combo.grid(row=1, column=0, columnspan=2, sticky="w", padx=2)
        lab(self.f_doc, "ชุดสำเนา (คั่นด้วย ,)", 2); ttk.Entry(self.f_doc, textvariable=self.pv["copy_labels"], width=24).grid(row=3, column=0, columnspan=2, sticky="w", padx=2)
        tk.Label(self.f_doc, text="1 กลุ่ม = 1 ใบ (ตารางต่อหน้าถัดไปให้เอง)\nเว้นว่าง = ทุกแถวอยู่ในเอกสารเดียว", bg=W, fg=self.app.TEXT_LIGHT, justify="left", font=("Segoe UI", 8)).grid(row=4, column=0, columnspan=2, sticky="w")
        for key, var in self.pv.items():
            if key in ("mode", "paper", "roll_preset", "sheet_preset"): continue
            var.trace_add("write", lambda *_a: self.on_page_var())

        # แท็บข้อมูล
        tk.Label(data_tab, textvariable=self.info_var, bg=W, fg=self.app.TEXT_DARK, wraplength=240, justify="left").pack(anchor="w")
        ttk.Button(data_tab, text="📂 โหลด CSV…", command=self.load_csv).pack(anchor="w", pady=3)
        ttk.Button(data_tab, text="↺ กลับไปใช้ข้อมูลตัวอย่าง", command=self.use_demo_data).pack(anchor="w")
        tk.Label(data_tab, text="คอลัมน์ในข้อมูล (ดับเบิลคลิกเพื่อแทรก)", bg=W, font=("Segoe UI", 9, "bold"), fg=self.app.PRIMARY).pack(anchor="w", pady=(8, 2))
        f = tk.Frame(data_tab, bg=W); f.pack(fill="both", expand=True)
        self.col_list = tk.Listbox(f, height=8, exportselection=False); sb = ttk.Scrollbar(f, command=self.col_list.yview); self.col_list.configure(yscrollcommand=sb.set)
        self.col_list.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.col_list.bind("<Double-Button-1>", lambda _e: self.insert_token_from(self.col_list, lambda t: "{" + t + "}"))
        tk.Label(data_tab, text="ตัวแปร/ฟังก์ชันพิเศษ", bg=W, font=("Segoe UI", 9, "bold"), fg=self.app.PRIMARY).pack(anchor="w", pady=(8, 2))
        f2 = tk.Frame(data_tab, bg=W); f2.pack(fill="both", expand=True)
        self.hint_list = tk.Listbox(f2, height=8, exportselection=False); sb2 = ttk.Scrollbar(f2, command=self.hint_list.yview); self.hint_list.configure(yscrollcommand=sb2.set)
        for token, cap in self.INSERT_HINTS: self.hint_list.insert("end", f"{token}  —  {cap}")
        self.hint_list.pack(side="left", fill="both", expand=True); sb2.pack(side="right", fill="y")
        self.hint_list.bind("<Double-Button-1>", lambda _e: self.insert_token_from(self.hint_list, lambda t: t.split("  —  ")[0]))

    # ---- กลาง: แคนวาส
    def build_center(self, parent):
        W = self.app.WHITE
        t1 = ttk.Frame(parent); t1.pack(fill="x", pady=(0, 2))
        for kind, text in (("text", "T ข้อความ"), ("barcode", "▥ บาร์โค้ด"), ("qr", "▦ QR"), ("image", "🖼 รูปภาพ"), ("line", "─ เส้น"), ("rect", "▭ กรอบ"), ("table", "▤ ตาราง")):
            b = ttk.Button(t1, text=text, command=lambda k=kind: self.add_element(k)); b.pack(side="left", padx=1); self.tip(b, f"เพิ่ม{ELEMENT_NAMES[kind]}")
        ttk.Separator(t1, orient="vertical").pack(side="left", fill="y", padx=4)
        for text, cmd, tip in (("↶", self.undo, "ย้อนกลับ (Ctrl+Z)"), ("↷", self.redo, "ทำซ้ำ (Ctrl+Y)"), ("⧉", self.duplicate_element, "ทำสำเนา (Ctrl+D)"), ("✕", self.delete_element, "ลบ (Delete)"),
                               ("▲", lambda: self.move_element(1), "ยกขึ้นด้านหน้า"), ("▼", lambda: self.move_element(-1), "ส่งไปด้านหลัง")):
            b = ttk.Button(t1, text=text, width=3, command=cmd); b.pack(side="left", padx=1); self.tip(b, tip)
        t2 = ttk.Frame(parent); t2.pack(fill="x", pady=(0, 3))
        for text, cmd in (("−", lambda: self.zoom_by(1 / 1.25)), ("+", lambda: self.zoom_by(1.25)), ("พอดี", self.fit)): ttk.Button(t2, text=text, width=4 if len(text) < 3 else 5, command=cmd).pack(side="left", padx=1)
        ttk.Checkbutton(t2, text="ยึดกริด 0.5 มม.", variable=self.snap_var, style="D.TCheckbutton").pack(side="left", padx=6)
        self.sheet_check = ttk.Checkbutton(t2, text="ดูทั้งแผ่น", variable=self.sheet_view, command=self.on_view_toggle, style="D.TCheckbutton"); self.sheet_check.pack(side="left", padx=2)
        frame = ttk.Frame(parent); frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, bg="#8A94A6", highlightthickness=0, cursor="arrow")
        hs = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview); vs = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        hs.pack(side="bottom", fill="x"); vs.pack(side="right", fill="y"); self.canvas.pack(side="left", fill="both", expand=True)
        c = self.canvas
        c.bind("<Button-1>", self.on_press); c.bind("<B1-Motion>", self.on_motion); c.bind("<ButtonRelease-1>", self.on_release); c.bind("<Motion>", self.on_hover)
        c.bind("<Button-3>", self.on_context); c.bind("<Configure>", lambda _e: self.later("fit", 120, self.on_canvas_resize))
        c.bind("<MouseWheel>", self.on_wheel); c.bind("<Button-4>", lambda e: self.on_wheel(e, 120)); c.bind("<Button-5>", lambda e: self.on_wheel(e, -120))
        c.bind("<Key>", self.on_key); c.bind("<Control-z>", lambda _e: self.undo()); c.bind("<Control-y>", lambda _e: self.redo()); c.bind("<Control-d>", lambda _e: self.duplicate_element())
        c.bind("<Delete>", lambda _e: self.delete_element())
        bottom = ttk.Frame(parent); bottom.pack(fill="x", pady=(2, 0))
        self.page_nav = ttk.Frame(bottom); self.page_nav.pack(side="right")
        ttk.Button(self.page_nav, text="◀", width=3, command=lambda: self.nav_page(-1)).pack(side="left"); self.page_label = tk.Label(self.page_nav, text="หน้า 1/1", width=9); self.page_label.pack(side="left"); ttk.Button(self.page_nav, text="▶", width=3, command=lambda: self.nav_page(1)).pack(side="left")
        self.rec_nav = ttk.Frame(bottom); self.rec_nav.pack(side="right", padx=8)
        ttk.Button(self.rec_nav, text="◀", width=3, command=lambda: self.nav_rec(-1)).pack(side="left"); self.rec_label = tk.Label(self.rec_nav, text="รายการ 1/1", width=13); self.rec_label.pack(side="left"); ttk.Button(self.rec_nav, text="▶", width=3, command=lambda: self.nav_rec(1)).pack(side="left")
        tk.Label(bottom, textvariable=self.status_var, anchor="w", fg=self.app.TEXT_LIGHT, font=("Segoe UI", 8)).pack(side="left", fill="x", expand=True)
        self.menu = tk.Menu(self.root, tearoff=0)
        for label, cmd in (("ทำสำเนา", self.duplicate_element), ("ยกขึ้นด้านหน้า", lambda: self.move_element(1)), ("ส่งไปด้านหลัง", lambda: self.move_element(-1)), ("ลบ", self.delete_element)): self.menu.add_command(label=label, command=cmd)

    # ---- ขวา: รายการองค์ประกอบ + คุณสมบัติ
    def build_right(self, parent):
        W = self.app.WHITE
        tk.Label(parent, text="องค์ประกอบ (ล่าง → บน)", bg=W, font=("Segoe UI", 9, "bold"), fg=self.app.PRIMARY).pack(anchor="w", padx=4, pady=(4, 0))
        f = tk.Frame(parent, bg=W); f.pack(fill="x", padx=4)
        self.tree = ttk.Treeview(f, columns=("name", "type"), show="headings", height=6, selectmode="browse")
        self.tree.heading("name", text="ชื่อ"); self.tree.heading("type", text="ชนิด"); self.tree.column("name", width=180); self.tree.column("type", width=80, anchor="center")
        sb = ttk.Scrollbar(f, command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set); self.tree.pack(side="left", fill="x", expand=True); sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        tk.Label(parent, text="คุณสมบัติ", bg=W, font=("Segoe UI", 9, "bold"), fg=self.app.PRIMARY).pack(anchor="w", padx=4, pady=(6, 0))
        self.props = ScrollFrame(parent, bg=W); self.props.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.props_inner = self.props.inner

    # ------------------------------------------------------------ แสดงค่าลงฟอร์มกระดาษ
    def mode_label(self, key): return next(lbl for k, lbl in MODES if k == key)
    def mode_key(self, label): return next((k for k, lbl in MODES if lbl == label), "roll")

    def load_page_vars(self):
        self._loading = True
        try:
            t = self.tpl; pv = self.pv
            pv["mode"].set(self.mode_label(t["mode"])); pv["paper"].set(t["paper"]); pv["orientation"].set(t["orientation"])
            pv["page_w"].set(f"{t['page_w']:g}"); pv["page_h"].set(f"{t['page_h']:g}")
            for k in ("cols", "rows", "start_cell", "copies"): pv[k].set(str(t[k]))
            for k in ("cell_w", "cell_h", "margin_left", "margin_top", "gap_x", "gap_y"): pv[k].set(f"{t[k]:g}")
            pv["group_col"].set(t["group_col"]); pv["copy_labels"].set(t["copy_labels"]); pv["copies_col"].set(t["copies_col"]); pv["show_guides"].set(bool(t["show_guides"]))
            pv["roll_preset"].set(next((k for k, v in ROLL_SIZES.items() if abs(v[0] - t["page_w"]) < .01 and abs(v[1] - t["page_h"]) < .01), "กำหนดเอง"))
            pv["sheet_preset"].set(next((k for k, v in SHEET_PRESETS.items() if v[0] == t["cols"] and v[1] == t["rows"] and abs(v[2] - t["cell_w"]) < .01 and abs(v[3] - t["cell_h"]) < .01), ""))
        finally: self._loading = False
        self.update_page_visibility()

    def update_page_visibility(self):
        mode = self.tpl["mode"]
        for f in (self.f_paper, self.f_roll, self.f_sheet, self.f_copies, self.f_doc): f.pack_forget()
        if mode == "roll": self.f_roll.pack(fill="x", pady=3); self.f_copies.pack(fill="x", pady=3)
        elif mode == "sheet": self.f_paper.pack(fill="x", pady=3); self.f_sheet.pack(fill="x", pady=3); self.f_copies.pack(fill="x", pady=3)
        else: self.f_paper.pack(fill="x", pady=3); self.f_doc.pack(fill="x", pady=3)
        if self.tpl["paper"] == "กำหนดเอง" and mode != "roll": self.f_custom.grid()
        else: self.f_custom.grid_remove()
        if mode == "sheet": self.sheet_check.pack(side="left", padx=2)
        else: self.sheet_check.pack_forget(); self.sheet_view.set(False)
        names = [""] + list(self.columns)
        self.group_combo["values"] = names; self.copies_combo["values"] = names

    def on_page_var(self):
        if self._loading: return
        self.later("page", 300, self.commit_page)

    def commit_page(self):
        t = self.tpl; pv = self.pv; changed = json.dumps(t, sort_keys=True)
        t["orientation"] = pv["orientation"].get() or "portrait"
        for k, lo in (("page_w", 1), ("page_h", 1), ("cell_w", 1), ("cell_h", 1), ("margin_left", 0), ("margin_top", 0), ("gap_x", 0), ("gap_y", 0)):
            try: t[k] = max(lo, float(pv[k].get()))
            except ValueError: pass
        for k in ("cols", "rows", "start_cell", "copies"):
            try: t[k] = max(1, int(float(pv[k].get())))
            except ValueError: pass
        t["group_col"] = pv["group_col"].get().strip(); t["copies_col"] = pv["copies_col"].get().strip(); t["copy_labels"] = pv["copy_labels"].get(); t["show_guides"] = bool(pv["show_guides"].get())
        if json.dumps(t, sort_keys=True) != changed: self.after_change(page=True)

    def on_mode_selected(self, _e=None):
        new = self.mode_key(self.pv["mode"].get())
        if new == self.tpl["mode"]: return
        t = self.tpl; old = t["mode"]; t["mode"] = new
        if new == "roll":
            t["page_w"], t["page_h"] = (t["cell_w"], t["cell_h"]) if old == "sheet" else (100.0, 150.0)
        elif new == "sheet":
            if t["paper"] == "กำหนดเอง": t["paper"] = "A4"
            t["page_w"], t["page_h"] = PAPER_SIZES.get(t["paper"], (210, 297))
            if t["cols"] * t["rows"] <= 1: t.update(cols=3, rows=8, cell_w=70.0, cell_h=37.0)
            self.center_grid(push=False)
        elif old == "roll" and t["paper"] == "กำหนดเอง": t["paper"] = "A4"
        self.load_page_vars(); self.after_change(page=True)

    def on_paper_selected(self, _e=None):
        t = self.tpl; old = self.geo(); t["paper"] = self.pv["paper"].get()
        size = PAPER_SIZES.get(t["paper"])
        if size: t["page_w"], t["page_h"] = size
        else: t["page_w"], t["page_h"] = old["page_w"], old["page_h"]
        self.load_page_vars(); self.after_change(page=True)

    def on_roll_preset(self, _e=None):
        size = ROLL_SIZES.get(self.pv["roll_preset"].get())
        if size: self.tpl["page_w"], self.tpl["page_h"] = size; self.load_page_vars(); self.after_change(page=True)

    def swap_roll(self):
        t = self.tpl; t["page_w"], t["page_h"] = t["page_h"], t["page_w"]; self.load_page_vars(); self.after_change(page=True)

    def on_sheet_preset(self, _e=None):
        v = SHEET_PRESETS.get(self.pv["sheet_preset"].get())
        if v: self.tpl.update(cols=v[0], rows=v[1], cell_w=v[2], cell_h=v[3], gap_x=0.0, gap_y=0.0); self.center_grid(push=False); self.load_page_vars(); self.after_change(page=True)

    def center_grid(self, push=True):
        t = self.tpl; size = PAPER_SIZES.get(t["paper"]) or (t["page_w"], t["page_h"]); w, h = size
        if t["orientation"] == "landscape": w, h = h, w
        t["margin_left"] = round(max(0.0, (w - t["cols"] * t["cell_w"] - (t["cols"] - 1) * t["gap_x"]) / 2), 2)
        t["margin_top"] = round(max(0.0, (h - t["rows"] * t["cell_h"] - (t["rows"] - 1) * t["gap_y"]) / 2), 2)
        if push: self.load_page_vars(); self.after_change(page=True)

    # ------------------------------------------------------------ ประวัติ Undo/Redo
    def snapshot(self): return json.dumps(self.tpl, sort_keys=True, ensure_ascii=False)

    def push_history(self):
        s = self.snapshot()
        if self.hidx >= 0 and self.history[self.hidx] == s: return
        del self.history[self.hidx + 1:]; self.history.append(s); self.hidx = len(self.history) - 1
        if len(self.history) > 200: self.history.pop(0); self.hidx -= 1

    def undo(self):
        if self.hidx > 0: self.hidx -= 1; self.restore(self.history[self.hidx])

    def redo(self):
        if self.hidx < len(self.history) - 1: self.hidx += 1; self.restore(self.history[self.hidx])

    def restore(self, s):
        self.tpl = json.loads(s); self._props_for = None
        if self.sel_el() is None: self.sel_id = None
        self.refresh_all()

    def after_change(self, page=False, props=False):
        """เรียกหลังแก้แม่แบบ: บันทึกประวัติ + วาดใหม่"""
        self.push_history(); self.clamp_nav()
        if page: self.update_page_visibility()
        if props: self.fill_geometry_vars()
        self.render(); self.later("save", 1500, self.save_session)

    def refresh_all(self):
        self.load_page_vars(); self.refresh_tree(); self.sync_selection(); self.clamp_nav(); self.fit() if self.fit_mode else self.render()

    # ------------------------------------------------------------ รายการองค์ประกอบ
    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for el in self.tpl["elements"]: self.tree.insert("", "end", iid=el["id"], values=(el.get("name", ""), ELEMENT_NAMES[el["type"]]))
        if self.sel_id and self.tree.exists(self.sel_id): self.tree.selection_set(self.sel_id)

    def on_tree_select(self, _e=None):
        sel = self.tree.selection()
        if sel and sel[0] != self.sel_id: self.select(sel[0])

    def select(self, el_id):
        self.sel_id = el_id
        if el_id and self.tree.exists(el_id): self.tree.selection_set(el_id); self.tree.see(el_id)
        elif not el_id: self.tree.selection_remove(self.tree.selection())
        self.sync_selection()

    def sync_selection(self):
        el = self.sel_el(); key = (el["id"], el["type"], self.tpl["mode"]) if el else None
        if key != self._props_for: self.build_props(el)
        elif el: self.fill_geometry_vars()
        self.draw_overlay()

    # ------------------------------------------------------------ คุณสมบัติ
    def prop_specs(self, el):
        k = el["type"]; specs = []
        if k == "text":
            specs = [("text", "ข้อความ", "text", None), ("font", "ฟอนต์", "choice", [(f, f) for f in LABEL_FONT_FILES]), ("size", "ขนาด (pt)", "num", None), ("bold", "ตัวหนา", "bool", None),
                     ("align", "จัดแนวนอน", "choice", self.ALIGN), ("valign", "จัดแนวตั้ง", "choice", self.VALIGN), ("color", "สีตัวอักษร", "choice", [(a, b[0]) for a, b in COLORS.items()]),
                     ("fill", "สีพื้น", "choice", [(a, b[0]) for a, b in FILLS.items()]), ("border", "เส้นกรอบ (มม.)", "num", None), ("shrink", "ย่อตัวอักษรให้พอดีกรอบ", "bool", None)]
        elif k == "barcode": specs = [("value", "ค่า (Code128)", "str", None), ("human", "แสดงตัวเลขใต้บาร์โค้ด", "bool", None)]
        elif k == "qr": specs = [("value", "ค่า", "str", None)]
        elif k == "image": specs = [("path", "ไฟล์รูป", "path", None), ("fit", "การจัดวาง", "choice", self.FITS)]
        elif k == "line": specs = [("thickness", "ความหนา (มม.)", "num", None), ("color", "สี", "choice", [(a, b[0]) for a, b in COLORS.items()])]
        elif k == "rect": specs = [("border", "เส้นกรอบ (มม.)", "num", None), ("color", "สีเส้น", "choice", [(a, b[0]) for a, b in COLORS.items()]), ("fill", "สีพื้น", "choice", [(a, b[0]) for a, b in FILLS.items()])]
        elif k == "table":
            specs = [("columns", "คอลัมน์ตาราง", "button", None), ("font", "ฟอนต์", "choice", [(f, f) for f in LABEL_FONT_FILES]), ("size", "ขนาด (pt)", "num", None), ("row_h", "ความสูงแถว (มม.)", "num", None),
                     ("header_fill", "สีหัวตาราง", "choice", [(a, b[0]) for a, b in FILLS.items()]), ("border", "เส้นตาราง (มม.)", "num", None), ("zebra", "สลับสีแถว", "bool", None),
                     ("fill_empty", "เติมแถวว่างให้เต็มกรอบ", "bool", None), ("total_label", "ข้อความแถวรวม", "str", None)]
        return specs

    def build_props(self, el):
        for w in self.props_inner.winfo_children(): w.destroy()
        self.pvars = {}; self._props_for = None
        if not el:
            tk.Label(self.props_inner, text="เลือกองค์ประกอบบนกระดาษ หรือกดปุ่มด้านบนเพื่อเพิ่ม\n\nเคล็ดลับ\n• ลากเพื่อย้าย ลากมุมขวาล่างเพื่อปรับขนาด\n• ลูกศรบนคีย์บอร์ด = ขยับ 0.5 มม. (Shift = 5 มม.)\n• ใส่ {ชื่อคอลัมน์} ในข้อความเพื่อดึงข้อมูลจาก CSV\n• ดับเบิลคลิกคอลัมน์ในแท็บ “ข้อมูล” เพื่อแทรก",
                     bg=self.app.WHITE, fg=self.app.TEXT_LIGHT, justify="left", wraplength=270, anchor="nw").pack(fill="x", padx=4, pady=6)
            return
        self._loading = True; W = self.app.WHITE; p = self.props_inner
        def row(): r = tk.Frame(p, bg=W); r.pack(fill="x", padx=4, pady=1); return r
        r = row(); tk.Label(r, text="ชื่อ", width=13, anchor="w", bg=W).pack(side="left"); v = tk.StringVar(value=el.get("name", "")); ttk.Entry(r, textvariable=v).pack(side="left", fill="x", expand=True); self.pvars["name"] = ("str", v, None); v.trace_add("write", lambda *_a: self.on_prop_change())
        for pair in (("x", "X (มม.)", "y", "Y (มม.)"), ("w", "กว้าง (มม.)", "h", "สูง (มม.)")):
            r = row()
            for key, cap in ((pair[0], pair[1]), (pair[2], pair[3])):
                tk.Label(r, text=cap, bg=W, anchor="w", width=10 if key in "xw" else 9).pack(side="left"); v = tk.StringVar(); e = ttk.Entry(r, textvariable=v, width=7); e.pack(side="left", padx=(0, 4)); self.pvars[key] = ("num", v, None); v.trace_add("write", lambda *_a: self.on_prop_change())
        if self.tpl["mode"] == "document":
            self.add_choice(row(), "show_on", "แสดงที่", self.SHOW_ON, el)
        for key, cap, ft, opt in self.prop_specs(el):
            r = row()
            if ft == "bool":
                v = tk.BooleanVar(value=bool(el.get(key, False))); ttk.Checkbutton(r, style="D.TCheckbutton", text=cap, variable=v).pack(anchor="w"); self.pvars[key] = ("bool", v, None); v.trace_add("write", lambda *_a: self.on_prop_change())
            elif ft == "choice": self.add_choice(r, key, cap, opt, el)
            elif ft == "text":
                tk.Label(r, text=cap, bg=W, anchor="nw", width=13).pack(side="left", anchor="n"); t = tk.Text(r, height=5, width=22, wrap="word", font=("Segoe UI", 9), undo=True); t.insert("1.0", str(el.get(key, ""))); t.pack(side="left", fill="both", expand=True)
                t.bind("<KeyRelease>", lambda _e: self.on_prop_change()); self.pvars[key] = ("text", t, None)
                self.app.add_right_click_menu(t)
            elif ft == "button":
                ttk.Button(r, text="✎ แก้ไขคอลัมน์ตาราง…", command=self.edit_table_columns).pack(anchor="w")
            else:
                tk.Label(r, text=cap, bg=W, anchor="w", width=13).pack(side="left"); v = tk.StringVar(value=(f"{el.get(key, 0):g}" if ft == "num" and isinstance(el.get(key), (int, float)) else str(el.get(key, ""))))
                ttk.Entry(r, textvariable=v, width=10 if ft == "num" else 20).pack(side="left", fill="x", expand=(ft != "num")); self.pvars[key] = (ft, v, None); v.trace_add("write", lambda *_a: self.on_prop_change())
                if ft == "path": ttk.Button(r, text="…", width=3, command=self.browse_image).pack(side="left", padx=2)
        self._props_for = (el["id"], el["type"], self.tpl["mode"]); self._loading = False
        self.fill_geometry_vars()

    def add_choice(self, row, key, cap, options, el):
        tk.Label(row, text=cap, bg=self.app.WHITE, anchor="w", width=13).pack(side="left")
        labels = [lbl for _v, lbl in options]; current = next((lbl for v, lbl in options if v == el.get(key)), labels[0])
        var = tk.StringVar(value=current); cb = ttk.Combobox(row, textvariable=var, values=labels, state="readonly", width=18); cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", lambda _e: self.on_prop_change()); self.pvars[key] = ("choice", var, options)

    def fill_geometry_vars(self):
        el = self.sel_el()
        if not el or not self.pvars: return
        self._loading = True
        try:
            for k in ("x", "y", "w", "h"):
                if k in self.pvars: self.pvars[k][1].set(f"{float(el[k]):.2f}".rstrip("0").rstrip("."))
        finally: self._loading = False

    def on_prop_change(self):
        if self._loading: return
        self.later("props", 250, self.commit_props)

    def commit_props(self):
        el = self.sel_el()
        if not el or not self.pvars: return
        before = json.dumps(el, sort_keys=True); old_name = el.get("name")
        for key, (ft, obj, opt) in self.pvars.items():
            try:
                if ft == "text": el[key] = obj.get("1.0", "end-1c")
                elif ft == "num":
                    val = float(obj.get().replace(",", "").strip()); el[key] = max({"size": 1.0, "row_h": 1.0}.get(key, 0.0), val)
                elif ft == "bool": el[key] = bool(obj.get())
                elif ft == "choice": el[key] = next((v for v, lbl in opt if lbl == obj.get()), el.get(key))
                else: el[key] = obj.get()
            except (ValueError, tk.TclError): continue
        if json.dumps(el, sort_keys=True) != before:
            if el.get("name") != old_name and self.tree.exists(el["id"]): self.tree.item(el["id"], values=(el.get("name", ""), ELEMENT_NAMES[el["type"]]))
            self.after_change()

    def browse_image(self):
        path = filedialog.askopenfilename(filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("ทุกไฟล์", "*.*")])
        if path and "path" in self.pvars: self.pvars["path"][1].set(path)

    # ---- ตัวแก้คอลัมน์ตาราง
    def edit_table_columns(self):
        el = self.sel_el()
        if not el or el["type"] != "table": return
        cols = [dict(c) for c in el["columns"]]; W = self.app.WHITE
        dlg = tk.Toplevel(self.root); dlg.title("คอลัมน์ตาราง"); dlg.transient(self.root); dlg.grab_set(); dlg.configure(bg=W)
        tree = ttk.Treeview(dlg, columns=("title", "value", "weight", "align", "sum"), show="headings", height=9)
        for k, t, w in (("title", "หัวคอลัมน์", 110), ("value", "ค่า (แม่แบบ)", 170), ("weight", "สัดส่วนกว้าง", 80), ("align", "จัดแนว", 60), ("sum", "รวมยอด", 60)): tree.heading(k, text=t); tree.column(k, width=w, anchor="center" if k in ("weight", "align", "sum") else "w")
        tree.grid(row=0, column=0, columnspan=6, padx=8, pady=8, sticky="nsew")
        align_lbl = dict(self.ALIGN)
        def refresh(select=None):
            tree.delete(*tree.get_children())
            for i, c in enumerate(cols): tree.insert("", "end", iid=str(i), values=(c["title"], c["value"], f"{c['weight']:g}", align_lbl.get(c["align"], ""), "✔" if c["sum"] else ""))
            if select is not None and 0 <= select < len(cols): tree.selection_set(str(select))
        form = {"title": tk.StringVar(), "value": tk.StringVar(), "weight": tk.StringVar(value="10"), "align": tk.StringVar(value="ซ้าย"), "sum": tk.BooleanVar()}
        for i, (cap, key, w) in enumerate((("หัวคอลัมน์", "title", 14), ("ค่า", "value", 22), ("สัดส่วนกว้าง", "weight", 6))):
            tk.Label(dlg, text=cap, bg=W).grid(row=1, column=i * 2 if i < 2 else 4, sticky="e", padx=2)
        ttk.Entry(dlg, textvariable=form["title"], width=14).grid(row=1, column=1, sticky="w"); ttk.Entry(dlg, textvariable=form["value"], width=22).grid(row=1, column=3, sticky="w"); ttk.Entry(dlg, textvariable=form["weight"], width=6).grid(row=1, column=5, sticky="w", padx=(2, 8))
        tk.Label(dlg, text="จัดแนว", bg=W).grid(row=2, column=0, sticky="e"); ttk.Combobox(dlg, textvariable=form["align"], values=[l for _v, l in self.ALIGN], state="readonly", width=8).grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(dlg, style="D.TCheckbutton", text="รวมยอดคอลัมน์นี้ (แสดงในแถวรวมหน้าสุดท้าย)", variable=form["sum"]).grid(row=2, column=2, columnspan=4, sticky="w")
        def on_select(_e=None):
            sel = tree.selection()
            if not sel: return
            c = cols[int(sel[0])]; form["title"].set(c["title"]); form["value"].set(c["value"]); form["weight"].set(f"{c['weight']:g}"); form["align"].set(align_lbl.get(c["align"], "ซ้าย")); form["sum"].set(c["sum"])
        tree.bind("<<TreeviewSelect>>", on_select)
        def read_form():
            try: wt = max(0.1, float(form["weight"].get()))
            except ValueError: wt = 10.0
            return {"title": form["title"].get(), "value": form["value"].get(), "weight": wt, "align": next((v for v, l in self.ALIGN if l == form["align"].get()), "left"), "sum": bool(form["sum"].get())}
        def add(): cols.append(read_form()); refresh(len(cols) - 1)
        def update():
            sel = tree.selection()
            if sel: cols[int(sel[0])] = read_form(); refresh(int(sel[0]))
        def delete():
            sel = tree.selection()
            if sel: del cols[int(sel[0])]; refresh(max(0, int(sel[0]) - 1))
        def shift(d):
            sel = tree.selection()
            if sel:
                i = int(sel[0]); j = i + d
                if 0 <= j < len(cols): cols[i], cols[j] = cols[j], cols[i]; refresh(j)
        def from_csv():
            have = {referenced for c in cols for referenced in referenced_names(c["value"])}
            for name in self.columns:
                if name not in have: cols.append({"title": name, "value": "{" + name + "}", "weight": 15.0, "align": "left", "sum": False})
            refresh()
        bar = tk.Frame(dlg, bg=W); bar.grid(row=3, column=0, columnspan=6, pady=6)
        for text, cmd in (("＋ เพิ่ม", add), ("✔ อัปเดตแถวที่เลือก", update), ("ลบ", delete), ("▲", lambda: shift(-1)), ("▼", lambda: shift(1)), ("เติมจากคอลัมน์ CSV", from_csv)): ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=2)
        def ok():
            el["columns"] = cols; dlg.destroy(); self.after_change()
        bar2 = tk.Frame(dlg, bg=W); bar2.grid(row=4, column=0, columnspan=6, pady=(0, 8)); ttk.Button(bar2, text="ตกลง", style="Success.TButton", command=ok).pack(side="left", padx=4); ttk.Button(bar2, text="ยกเลิก", command=dlg.destroy).pack(side="left")
        refresh(0); on_select()

    # ------------------------------------------------------------ แก้ไของค์ประกอบ
    def add_element(self, kind):
        if kind == "table":
            if self.tpl["mode"] != "document": messagebox.showinfo("ตาราง", "ตารางใช้ได้ในโหมด “เอกสาร” เท่านั้น (เปลี่ยนชนิดงานในแท็บกระดาษ)"); return
            if table_of(self.tpl): messagebox.showinfo("ตาราง", "มีตารางอยู่แล้ว 1 ตาราง (รองรับตารางเดียวต่อเอกสาร)"); return
        g = self.geo(); first = self.columns[0] if self.columns else ""
        el = default_element(kind)
        if kind == "text": el["text"] = "{" + first + "}" if first else "ข้อความ"
        elif kind in ("barcode", "qr"): el["value"] = "{" + first + "}" if first else "123456789"
        n = len(self.tpl["elements"]); el["x"] = 4.0 + (n % 5) * 2; el["y"] = 4.0 + (n % 5) * 2
        el["w"] = min(el["w"], max(5.0, g["cell_w"] - el["x"] - 2)); el["h"] = min(el["h"], max(3.0, g["cell_h"] - el["y"] - 2)) if kind != "line" else 0.0
        if kind == "table": el["x"], el["y"] = 10.0, 62.0; el["w"] = min(el["w"], g["cell_w"] - 20); el["h"] = min(el["h"], g["cell_h"] - 72)
        if self.sheet_active(): self.sheet_view.set(False); self.on_view_toggle(render=False)
        self.tpl["elements"].append(el); self.refresh_tree(); self.select(el["id"]); self.after_change()

    def delete_element(self):
        el = self.sel_el()
        if not el: return
        self.tpl["elements"].remove(el); self.sel_id = None; self.refresh_tree(); self.sync_selection(); self.after_change()

    def duplicate_element(self):
        el = self.sel_el()
        if not el or el["type"] == "table": return
        new = json.loads(json.dumps(el)); new["id"] = new_id(); new["name"] = el.get("name", "") + " (สำเนา)"; new["x"] += 3; new["y"] += 3
        self.tpl["elements"].insert(self.tpl["elements"].index(el) + 1, new); self.refresh_tree(); self.select(new["id"]); self.after_change()

    def move_element(self, step):
        el = self.sel_el()
        if not el: return
        els = self.tpl["elements"]; i = els.index(el); j = i + step
        if 0 <= j < len(els): els[i], els[j] = els[j], els[i]; self.refresh_tree(); self.after_change()

    def insert_token_from(self, listbox, convert):
        sel = listbox.curselection()
        if not sel: return
        token = convert(listbox.get(sel[0])); el = self.sel_el()
        target = next((k for k in ("text", "value", "path") if k in self.pvars), None) if el else None
        if el and target:
            ft, obj, _ = self.pvars[target]
            if ft == "text": obj.insert("insert", token); self.commit_props()
            else: obj.set(obj.get() + token)
        else:
            self.add_element("text")
            el = self.sel_el()
            if el and "text" in self.pvars: self.pvars["text"][1].delete("1.0", "end"); self.pvars["text"][1].insert("1.0", token); self.commit_props()

    # ------------------------------------------------------------ มุมมอง/วาด
    def clamp_nav(self):
        try: eng = self.engine(); n = max(1, eng.record_count()); self.rec = min(self.rec, n - 1)
        except (ValueError, KeyError, TypeError): n = 1
        self.rec_label.config(text=f"รายการ {self.rec + 1}/{n}" if self.tpl["mode"] != "document" else f"เอกสาร {self.rec + 1}/{n}")
        pages = 1
        try:
            if self.tpl["mode"] == "document": pages = eng.pages_in_record(self.rec)
            elif self.sheet_active(): pages = max(1, len(eng.plan()))
        except (ValueError, KeyError, TypeError, UnboundLocalError): pass
        self.page = min(self.page, pages - 1); self.page_label.config(text=f"หน้า {self.page + 1}/{pages}"); self._pages = pages; self._records = n

    def nav_rec(self, d):
        self.clamp_nav(); self.rec = max(0, min(self._records - 1, self.rec + d)); self.page = 0; self.clamp_nav(); self.render()

    def nav_page(self, d):
        self.clamp_nav(); self.page = max(0, min(self._pages - 1, self.page + d)); self.clamp_nav(); self.render()

    def on_view_toggle(self, render=True):
        self.page = 0; self.rec = 0 if not self.sheet_view.get() else self.rec; self.fit_mode = True
        if render: self.fit()

    def on_canvas_resize(self):
        if self.fit_mode: self.fit()

    def fit(self):
        self.canvas.update_idletasks(); cw, ch = max(200, self.canvas.winfo_width()), max(150, self.canvas.winfo_height()); w, h = self.view_size()
        self.scale = max(0.6, min(14.0, (cw - 2 * self.PAD) / w, (ch - 2 * self.PAD) / h)); self.fit_mode = True; self.render()

    def zoom_by(self, f):
        self.scale = max(0.6, min(16.0, self.scale * f)); self.fit_mode = False; self.render()

    def render(self):
        c = self.canvas; self.clamp_nav()
        try:
            eng = self.engine(); pdf = eng.render_preview(self.rec, self.page, self.sheet_active())
            if pdf is None: c.delete("all"); return
            doc = fitz.open(stream=pdf, filetype="pdf"); pg = doc[0]; wpt, hpt = pg.rect.width, pg.rect.height
            z = self.scale / MM
            while wpt * z * hpt * z > 9_000_000: z *= 0.8
            pix = pg.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False); doc.close()
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples); self.pxmm = pix.width / (wpt / MM)
            self.photo = ImageTk.PhotoImage(img); self.page_mm = (wpt / MM, hpt / MM)
        except Exception as exc:  # noqa: BLE001 - แสดงข้อผิดพลาดบนจอแทนที่จะทำให้โปรแกรมค้าง
            c.delete("all"); c.create_text(20, 20, anchor="nw", fill="white", text=f"แสดงตัวอย่างไม่ได้: {exc}", font=("Segoe UI", 10)); return
        c.delete("all"); P = self.PAD
        c.create_rectangle(P + 3, P + 3, P + pix.width + 3, P + pix.height + 3, fill="#5C6478", outline="")
        c.create_image(P, P, anchor="nw", image=self.photo, tags="page")
        c.create_rectangle(P, P, P + pix.width, P + pix.height, outline="#B0B8C8")
        c.configure(scrollregion=(0, 0, pix.width + 2 * P, pix.height + 2 * P))
        self.draw_overlay()
        info = "ข้อมูลตัวอย่าง" if self.is_demo else Path(self.csv_path).name
        self.info_var.set(f"{info} • {len(self.rows)} แถว")

    def draw_overlay(self):
        c = self.canvas; c.delete("ov"); el = self.sel_el()
        if not el or self.sheet_active(): return
        self.draw_box((float(el["x"]), float(el["y"]), float(el["w"]), float(el["h"])))

    def draw_box(self, box):
        c = self.canvas; P = self.PAD; k = self.pxmm; x, y, w, h = box
        x0, y0, x1, y1 = P + x * k, P + y * k, P + (x + w) * k, P + (y + h) * k
        c.delete("ov"); c.create_rectangle(x0, y0, x1, y1, outline="#1976D2", width=2, dash=(5, 3), tags="ov")
        for hx, hy in self.handles((x0, y0, x1, y1)).values(): c.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4, fill="white", outline="#1976D2", width=2, tags="ov")

    @staticmethod
    def handles(b):
        x0, y0, x1, y1 = b
        return {"br": (x1, y1), "r": (x1, (y0 + y1) / 2), "b": ((x0 + x1) / 2, y1)}

    # ------------------------------------------------------------ เมาส์/คีย์บอร์ด
    def to_mm(self, e): return (self.canvas.canvasx(e.x) - self.PAD) / self.pxmm, (self.canvas.canvasy(e.y) - self.PAD) / self.pxmm

    def snap(self, v): return round(v / 0.5) * 0.5 if self.snap_var.get() else round(v, 2)

    def hit_test(self, mx, my):
        tol = 3.0 / self.pxmm
        for el in reversed(self.tpl["elements"]):
            if float(el["x"]) - tol <= mx <= float(el["x"]) + float(el["w"]) + tol and float(el["y"]) - tol <= my <= float(el["y"]) + float(el["h"]) + tol: return el
        return None

    def on_press(self, e):
        self.canvas.focus_set()
        if self.sheet_active(): return
        el = self.sel_el(); cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y); P = self.PAD; k = self.pxmm; mx, my = self.to_mm(e); self.drag = None
        if el:
            b = (P + float(el["x"]) * k, P + float(el["y"]) * k, P + (float(el["x"]) + float(el["w"])) * k, P + (float(el["y"]) + float(el["h"])) * k)
            for name, (hx, hy) in self.handles(b).items():
                if abs(cx - hx) <= 7 and abs(cy - hy) <= 7:
                    self.drag = {"mode": name, "start": (mx, my), "orig": (float(el["x"]), float(el["y"]), float(el["w"]), float(el["h"])), "el": el, "moved": False}; return
        hit = self.hit_test(mx, my)
        if hit:
            if hit["id"] != self.sel_id: self.select(hit["id"])
            self.drag = {"mode": "move", "start": (mx, my), "orig": (float(hit["x"]), float(hit["y"]), float(hit["w"]), float(hit["h"])), "el": hit, "moved": False}
        else: self.select(None)

    def drag_box(self, e):
        d = self.drag; mx, my = self.to_mm(e); dx, dy = mx - d["start"][0], my - d["start"][1]; x, y, w, h = d["orig"]
        if d["mode"] == "move": x, y = self.snap(x + dx), self.snap(y + dy)
        else:
            if d["mode"] in ("br", "r"): w = max(0.0 if d["el"]["type"] == "line" else 1.0, self.snap(w + dx))
            if d["mode"] in ("br", "b"): h = max(0.0 if d["el"]["type"] == "line" else 1.0, self.snap(h + dy))
        return x, y, w, h

    def on_motion(self, e):
        if not self.drag: return
        box = self.drag_box(e); self.drag["box"] = box; self.drag["moved"] = True; self.draw_box(box)
        self.status_var.set(f"X {box[0]:.1f}  Y {box[1]:.1f}  กว้าง {box[2]:.1f}  สูง {box[3]:.1f} มม.")

    def on_release(self, e):
        d = self.drag; self.drag = None
        if not d or not d["moved"]: return
        box = d.get("box")
        if box: d["el"]["x"], d["el"]["y"], d["el"]["w"], d["el"]["h"] = box
        self.after_change(props=True)

    def on_hover(self, e):
        if self.drag or self.sheet_active(): return
        mx, my = self.to_mm(e); el = self.sel_el(); cursor = "arrow"
        if el:
            P, k = self.PAD, self.pxmm; cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
            b = (P + float(el["x"]) * k, P + float(el["y"]) * k, P + (float(el["x"]) + float(el["w"])) * k, P + (float(el["y"]) + float(el["h"])) * k)
            if any(abs(cx - hx) <= 7 and abs(cy - hy) <= 7 for hx, hy in self.handles(b).values()): cursor = "sizing"
        if cursor == "arrow" and self.hit_test(mx, my): cursor = "fleur"
        self.canvas.configure(cursor=cursor); self.status_var.set(f"ตำแหน่งเมาส์ X {mx:.1f}  Y {my:.1f} มม.   |   กระดาษ {self.page_mm[0]:.1f} × {self.page_mm[1]:.1f} มม.")

    def on_context(self, e):
        if self.sheet_active(): return
        hit = self.hit_test(*self.to_mm(e))
        if hit: self.select(hit["id"]); self.menu.tk_popup(e.x_root, e.y_root)

    def on_wheel(self, e, delta=None):
        d = delta if delta is not None else e.delta
        if e.state & 0x4: self.zoom_by(1.12 if d > 0 else 1 / 1.12)
        elif e.state & 0x1: self.canvas.xview_scroll(-1 if d > 0 else 1, "units")
        else: self.canvas.yview_scroll(-1 if d > 0 else 1, "units")

    def on_key(self, e):
        el = self.sel_el()
        if not el or e.keysym not in ("Left", "Right", "Up", "Down"): return
        step = 5.0 if e.state & 0x1 else (0.1 if e.state & 0x4 else 0.5)
        dx = {"Left": -step, "Right": step}.get(e.keysym, 0.0); dy = {"Up": -step, "Down": step}.get(e.keysym, 0.0)
        el["x"] = round(float(el["x"]) + dx, 2); el["y"] = round(float(el["y"]) + dy, 2); self.later("nudge", 150, lambda: self.after_change(props=True)); self.draw_overlay(); self.fill_geometry_vars(); return "break"

    # ------------------------------------------------------------ ข้อมูล CSV
    def set_data(self, columns, rows, path="", demo=False):
        self.columns, self.rows, self.csv_path, self.is_demo = list(columns), list(rows), path, demo
        self.rec = 0; self.page = 0
        for k in ("group_col", "copies_col"):
            if self.tpl.get(k) and self.tpl[k] not in self.columns: self.tpl[k] = ""
        self.col_list.delete(0, "end")
        for name in self.columns: self.col_list.insert("end", name)
        self.update_page_visibility(); self.load_page_vars(); self.render()

    def load_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv *.txt"), ("ทุกไฟล์", "*.*")], title="เลือกไฟล์ข้อมูล CSV")
        if not path: return
        try: columns, rows = read_csv_rows(path)
        except (OSError, ValueError, csv.Error) as exc: messagebox.showerror("อ่าน CSV ไม่สำเร็จ", str(exc)); return
        if not columns or not rows: messagebox.showwarning("CSV ว่าง", "ไม่พบหัวคอลัมน์หรือข้อมูลในไฟล์"); return
        self.set_data(columns, rows, path)
        eng = self.engine(); _errs, warns = eng.validate(self.columns); miss = [w for w in warns if "คอลัมน์ที่ไม่มีในข้อมูล" in w]
        msg = f"โหลดข้อมูล {len(rows)} แถว {len(columns)} คอลัมน์แล้ว"
        if miss: msg += "\n\n" + miss[0] + "\nแก้ข้อความในองค์ประกอบให้ตรงกับชื่อคอลัมน์ในไฟล์ (ดับเบิลคลิกคอลัมน์ในแท็บ “ข้อมูล” เพื่อแทรก)"
        messagebox.showinfo("โหลดข้อมูลแล้ว", msg)

    def demo_kind(self):
        k = self.tpl.get("starter")
        return k if k in ("shipping", "product", "delivery") else {"roll": "shipping", "sheet": "product", "document": "delivery"}[self.tpl["mode"]]

    def use_demo_data(self):
        _t, cols, rows = starter_template(self.demo_kind()); self.set_data(cols, rows, "", demo=True)

    # ------------------------------------------------------------ แม่แบบ
    def apply_starter(self, kind, ask=True):
        if ask and self.tpl["elements"] and not messagebox.askyesno("แม่แบบเริ่มต้น", "แม่แบบปัจจุบันจะถูกแทนที่ (ยังย้อนกลับด้วย Undo ได้)\nและใช้ข้อมูลตัวอย่างแทน CSV ที่โหลดอยู่\n\nดำเนินการต่อหรือไม่?"): return
        tpl, cols, rows = starter_template(kind); tpl["starter"] = kind; self.tpl = tpl; self.sel_id = None; self.fit_mode = True
        self.set_data(cols, rows, "", demo=True); self.refresh_tree(); self.build_props(None); self.push_history(); self.fit()

    def save_template(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("แม่แบบ JSON", "*.json")], initialfile="template.json", title="บันทึกแม่แบบ")
        if not path: return
        try: Path(path).write_text(json.dumps({"application": PROGRAM_NAME, "template": self.tpl}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc: messagebox.showerror("บันทึกไม่สำเร็จ", str(exc)); return
        self.status_var.set(f"บันทึกแม่แบบแล้ว: {path}")

    def load_template(self):
        path = filedialog.askopenfilename(filetypes=[("แม่แบบ JSON", "*.json"), ("ทุกไฟล์", "*.*")], title="เลือกไฟล์แม่แบบ")
        if not path: return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig")); tpl = normalize_template(data["template"] if isinstance(data, dict) and "template" in data else data)
        except (OSError, ValueError, KeyError, TypeError) as exc: messagebox.showerror("โหลดแม่แบบไม่สำเร็จ", str(exc)); return
        self.tpl = tpl; self.sel_id = None; self.fit_mode = True; self.refresh_tree(); self.build_props(None); self.load_page_vars(); self.push_history(); self.fit()
        self.status_var.set(f"โหลดแม่แบบแล้ว: {Path(path).name}")

    def save_session(self):
        try:
            data = {"template": self.tpl, "csv_path": self.csv_path if (self.csv_path and Path(self.csv_path).is_file()) else ""}
            self.session_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError, ValueError): pass

    def load_session(self):
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8")); tpl = normalize_template(data["template"])
        except (OSError, ValueError, KeyError, TypeError): return False
        if not tpl["elements"]: return False
        self.tpl = tpl; _t, cols, rows = starter_template(self.demo_kind())
        path = data.get("csv_path", "")
        if path and Path(path).is_file():
            try: cols, rows = read_csv_rows(path); self.set_data(cols, rows, path)
            except (OSError, ValueError, csv.Error): self.set_data(cols, rows, "", demo=True)
        else: self.set_data(cols, rows, "", demo=True)
        self.refresh_tree(); self.build_props(None); self.push_history(); self.fit_mode = True; self.root.after(300, self.fit)
        return True

    # ------------------------------------------------------------ ตรวจ / PDF / พิมพ์
    def check_template(self):
        errors, warnings = self.engine().validate(self.columns)
        if self.is_demo: warnings.insert(0, "กำลังใช้ข้อมูลตัวอย่าง (ยังไม่ได้โหลด CSV)")
        if not errors and len(warnings) <= (1 if self.is_demo else 0): messagebox.showinfo("ตรวจแม่แบบ", "ไม่พบปัญหา ✔"); return
        text = ("ข้อผิดพลาด:\n" + "\n".join("✖ " + e for e in errors) + "\n\n" if errors else "") + ("คำเตือน:\n" + "\n".join("• " + w for w in warnings) if warnings else "")
        (messagebox.showerror if errors else messagebox.showwarning)("ตรวจแม่แบบ", text.strip())

    def prepare_job(self, title):
        if self.busy: messagebox.showinfo("กำลังทำงาน", "กำลังสร้าง PDF อยู่ กรุณารอสักครู่"); return None
        eng = self.engine(); errors, warnings = eng.validate(self.columns)
        if errors: messagebox.showerror(title, "\n".join("✖ " + e for e in errors)); return None
        if not self.rows: messagebox.showwarning(title, "ยังไม่มีข้อมูล กรุณาโหลด CSV ก่อน"); return None
        notes = (["กำลังใช้ข้อมูลตัวอย่าง (ยังไม่ได้โหลด CSV)"] if self.is_demo else []) + warnings
        if notes and not messagebox.askyesno(title, "\n".join("• " + w for w in notes) + "\n\nดำเนินการต่อหรือไม่?"): return None
        return eng

    def run_job(self, eng, path, done):
        """สร้าง PDF ในเธรดแยก โดยเธรดหลักคอยอ่านความคืบหน้า (ไม่เรียก tkinter จากเธรดงาน)"""
        self.busy = True; self.app.is_busy = True; self.progress_var.set(0); self.status_var.set("กำลังสร้าง PDF…")
        state = {"i": 0, "n": 1, "done": False, "pages": 0, "err": None}
        def progress(i, n): state["i"], state["n"] = i, n
        def worker():
            try: state["pages"] = eng.render_pdf(path, progress)
            except Exception as exc:  # noqa: BLE001 - แจ้งผู้ใช้ทุกข้อผิดพลาดของการสร้างไฟล์
                state["err"] = str(exc) or type(exc).__name__
            state["done"] = True
        def poll():
            self.progress_var.set(100.0 * state["i"] / max(1, state["n"]))
            if not state["done"]: self.root.after(120, poll); return
            self.busy = False; self.app.is_busy = False; self.progress_var.set(100 if not state["err"] else 0)
            if state["err"]: self.status_var.set("สร้าง PDF ไม่สำเร็จ"); messagebox.showerror("สร้าง PDF ไม่สำเร็จ", state["err"])
            else: self.status_var.set(f"สร้าง PDF แล้ว {state['pages']} หน้า"); done(state["pages"])
        threading.Thread(target=worker, daemon=True).start(); self.root.after(120, poll)

    def create_pdf(self):
        eng = self.prepare_job("สร้าง PDF")
        if eng is None: return
        name = {"document": "document", "sheet": "labels", "roll": "labels"}[self.tpl["mode"]] + datetime.now().strftime("_%Y%m%d_%H%M") + ".pdf"
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")], initialfile=name, title="บันทึก PDF")
        if not path: return
        def done(pages):
            self.last_pdf = path
            if messagebox.askyesno("สร้าง PDF สำเร็จ", f"สร้างแล้ว {pages} หน้า\n{path}\n\nเปิดไฟล์เลยหรือไม่?"): self.open_file(path)
        self.run_job(eng, path, done)

    def print_pdf(self):
        eng = self.prepare_job("พิมพ์")
        if eng is None: return
        folder = Path(tempfile.gettempdir()) / "BOWA_print"
        try: folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc: messagebox.showerror("พิมพ์ไม่สำเร็จ", str(exc)); return
        path = str(folder / ("print_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf"))
        def done(pages):
            if os.name == "nt":
                ok, error = self.app._send_file_to_windows_printer(path)
                if ok: self.status_var.set(f"ส่งพิมพ์ {pages} หน้าแล้ว")
                else: messagebox.showerror("พิมพ์ไม่สำเร็จ", f"{error}\n\nไฟล์ PDF อยู่ที่:\n{path}")
            elif shutil.which("lp"):
                try: subprocess.run(["lp", path], check=True, capture_output=True, text=True); self.status_var.set(f"ส่งพิมพ์ {pages} หน้าแล้ว")
                except (OSError, subprocess.SubprocessError) as exc: messagebox.showerror("พิมพ์ไม่สำเร็จ", str(exc))
            else: self.open_file(path); messagebox.showinfo("เปิดไฟล์แล้ว", "ไม่พบคำสั่งพิมพ์อัตโนมัติ จึงเปิด PDF ให้สั่งพิมพ์เอง")
        self.run_job(eng, path, done)

    @staticmethod
    def open_file(path):
        try:
            if os.name == "nt": os.startfile(path)
            elif sys.platform == "darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
        except OSError as exc: messagebox.showerror("เปิดไฟล์ไม่สำเร็จ", str(exc))


# --- Auto Rename: ประวัติและย้อนกลับ ---
HISTORY_DIR = Path.home() / ".bowa_rename_history"
MAX_HISTORY_RUNS = 50


class RenameHistory:
    """เก็บประวัติการเปลี่ยนชื่อ/ย้ายไฟล์ของ Auto Rename รอบละ 1 ไฟล์ JSON เพื่อย้อนกลับได้"""

    def __init__(self, folder=None):
        self.dir = Path(folder) if folder else HISTORY_DIR

    def save_run(self, target_dir, moves, include_subfolders=False):
        if not moves:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = self.dir / f"rename_{now:%Y%m%d_%H%M%S}.json"
        n = 1
        while path.exists():
            path = self.dir / f"rename_{now:%Y%m%d_%H%M%S}_{n}.json"; n += 1
        data = {"version": 1, "time": now.isoformat(timespec="seconds"), "folder": str(target_dir),
                "subfolders": bool(include_subfolders), "moves": moves, "undone_at": None}
        self._write(path, data)
        self.prune()
        return path

    @staticmethod
    def _write(path, data):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def prune(self):
        files = sorted(self.dir.glob("rename_*.json"))
        for old in files[:-MAX_HISTORY_RUNS]:
            try: old.unlink()
            except OSError: pass

    def load(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def list_runs(self):
        """คืนรายการจากใหม่ไปเก่า: dict(path, time, folder, renamed, unreadable, undone_at)"""
        runs = []
        if not self.dir.exists():
            return runs
        for f in sorted(self.dir.glob("rename_*.json"), reverse=True):
            try:
                d = self.load(f)
                moves = d.get("moves", [])
                runs.append({"path": f, "time": d.get("time", ""), "folder": d.get("folder", ""),
                             "renamed": sum(1 for m in moves if m.get("kind") == "rename"),
                             "unreadable": sum(1 for m in moves if m.get("kind") == "unreadable"),
                             "undone_at": d.get("undone_at")})
            except (OSError, ValueError):
                continue
        return runs

    def delete(self, path):
        try: Path(path).unlink()
        except OSError: pass

    def undo(self, path):
        """ย้อนกลับทั้งรอบ (จากท้ายไปต้น) คืน (restored, skipped[(old, new, reason)])"""
        path = Path(path)
        data = self.load(path)
        if data.get("undone_at"):
            raise ValueError("รอบนี้ถูกย้อนกลับไปแล้ว")
        restored, skipped = 0, []
        for m in reversed(data.get("moves", [])):
            src, dst = Path(m["new"]), Path(m["old"])
            if not src.exists():
                skipped.append((m["old"], m["new"], "ไม่พบไฟล์ปัจจุบัน (ถูกย้ายหรือลบไปแล้ว)")); continue
            if dst.exists():
                try: same = os.path.samefile(src, dst)
                except OSError: same = False
                if not same:
                    skipped.append((m["old"], m["new"], "มีไฟล์ชื่อเดิมอยู่แล้ว")); continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                restored += 1
            except OSError as e:
                skipped.append((m["old"], m["new"], f"ผิดพลาด: {e}"))
        for m in data.get("moves", []):
            if m.get("kind") == "unreadable":
                try: Path(m["new"]).parent.rmdir()
                except OSError: pass
        data["undone_at"] = datetime.now().isoformat(timespec="seconds")
        data["undo_restored"] = restored
        data["undo_skipped"] = len(skipped)
        self._write(path, data)
        return restored, skipped


class BowaApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{PROGRAM_NAME} v{VERSION}")
        try:
            self.root.iconbitmap(default=str(ICON_PATH))
        except tk.TclError:
            # เปิดโปรแกรมได้แม้ไม่พบไฟล์ไอคอนหรือระบบไม่รองรับ ICO
            pass
        # ขนาดเริ่มต้น กว้าง 28 ซม. x สูง 15 ซม. (แปลงตาม DPI ของหน้าจอ) และไม่เกินพื้นที่หน้าจอ
        px_cm = self.root.winfo_fpixels("1c")
        start_w = min(int(round(28 * px_cm)), self.root.winfo_screenwidth() - 40)
        start_h = min(int(round(15 * px_cm)), self.root.winfo_screenheight() - 80)
        self.root.geometry(f"{start_w}x{start_h}")
        self.root.minsize(min(start_w, 1000), min(start_h, 540))
        self.root.configure(bg="#F0F2F5")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_busy = False
        self.history = RenameHistory()

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
        if getattr(self, "_update_in_progress", False): return
        self.update_button.configure(state="disabled")
        def worker():
            result = None; error = None
            try:
                # เติม query เวลาเพื่อเลี่ยงแคชของ raw.githubusercontent.com (แคชราว 5 นาที)
                url = f"{UPDATE_MANIFEST_URL}?t={int(time.time())}" if "raw.githubusercontent.com" in UPDATE_MANIFEST_URL else UPDATE_MANIFEST_URL
                request = urllib.request.Request(url, headers={"User-Agent": f"{PROGRAM_NAME}/{VERSION}", "Cache-Control": "no-cache"})
                with urllib.request.urlopen(request, timeout=UPDATE_CHECK_TIMEOUT) as response:
                    if response.status != 200: raise OSError(f"HTTP {response.status}")
                    result = json.loads(response.read().decode("utf-8-sig"))
            except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
                error = str(exc)
            self.root.after(0, lambda: self.finish_update_check(result, error, silent))
        threading.Thread(target=worker, daemon=True).start()

    def finish_update_check(self, manifest, error, silent):
        self.update_button.configure(state="normal")
        if error:
            if not silent: messagebox.showwarning("ตรวจสอบอัปเดตไม่สำเร็จ", f"ไม่สามารถเชื่อมต่อแหล่งข้อมูลอัปเดตได้\n{error}")
            return
        if not isinstance(manifest, dict):
            if not silent: messagebox.showwarning("ตรวจสอบอัปเดตไม่สำเร็จ", "รูปแบบไฟล์ข้อมูลอัปเดตไม่ถูกต้อง")
            return
        latest = str(manifest.get("version", "")).strip()
        if not latest or self.normalize_version(latest) <= self.normalize_version(VERSION):
            if not silent: messagebox.showinfo("ตรวจสอบอัปเดต", f"คุณกำลังใช้เวอร์ชันล่าสุด v{VERSION}")
            return
        notes = str(manifest.get("notes", "")).strip()
        download_url = str(manifest.get("url", "")).strip()
        sha256 = str(manifest.get("sha256", "")).strip()
        text = f"พบเวอร์ชันใหม่ v{latest} (ปัจจุบัน v{VERSION})" + (f"\n\n{notes}" if notes else "")
        # อัปเดตอัตโนมัติได้เฉพาะ exe ที่ build แล้ว, URL เป็น https .exe และมี SHA-256 ครบถ้วนเท่านั้น
        auto = (getattr(sys, "frozen", False) and download_url.lower().startswith("https://")
                and urllib.parse.urlparse(download_url).path.lower().endswith(".exe")
                and re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is not None)
        if auto:
            if self.is_busy:
                messagebox.showinfo("มีเวอร์ชันใหม่", text + "\n\nกำลังประมวลผลอยู่ กรุณาอัปเดตหลังงานเสร็จ")
                return
            if messagebox.askyesno("มีเวอร์ชันใหม่", text + "\n\nดาวน์โหลดและอัปเดตอัตโนมัติตอนนี้หรือไม่?\n(โปรแกรมจะปิดและเปิดใหม่เอง)"):
                self.start_auto_update(download_url, sha256, latest)
        elif download_url.lower().startswith(("https://", "http://")):
            if messagebox.askyesno("มีเวอร์ชันใหม่", text + "\n\nเปิดหน้าดาวน์โหลดหรือไม่?"):
                webbrowser.open(download_url)
        else:
            messagebox.showinfo("มีเวอร์ชันใหม่", text)

    @staticmethod
    def download_verified(url, part_path, sha256, progress=None, cancel=None):
        """ดาวน์โหลดไฟล์ พร้อมตรวจ SHA-256 ระหว่างโหลด คืนขนาดไฟล์ (ไบต์)
        ถ้า hash ไม่ตรงหรือถูกยกเลิก จะลบไฟล์ชั่วคราวและยก ValueError"""
        digest = hashlib.sha256(); done = 0
        try:
            request = urllib.request.Request(url, headers={"User-Agent": f"{PROGRAM_NAME}/{VERSION}"})
            with urllib.request.urlopen(request, timeout=30) as response, open(part_path, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                while True:
                    if cancel is not None and cancel.is_set(): raise ValueError("ยกเลิกการดาวน์โหลด")
                    chunk = response.read(256 * 1024)
                    if not chunk: break
                    out.write(chunk); digest.update(chunk); done += len(chunk)
                    if progress: progress(done, total)
            if done == 0: raise ValueError("ไฟล์ที่ดาวน์โหลดว่างเปล่า")
            if digest.hexdigest().lower() != sha256.lower():
                raise ValueError("ค่า SHA-256 ของไฟล์ไม่ตรงกับที่ประกาศไว้ ไฟล์อาจเสียหายหรือถูกแก้ไข จึงไม่ติดตั้ง")
            return done
        except BaseException:
            try: Path(part_path).unlink()
            except OSError: pass
            raise

    def start_auto_update(self, url, sha256, latest):
        current_exe = Path(sys.executable).resolve()
        filename = Path(urllib.parse.urlparse(url).path).name
        if not re.fullmatch(r"[\w.\- ]+\.exe", filename, re.IGNORECASE):
            filename = f"BOWASmartProcessor{latest}.exe"
        dest = current_exe.parent / filename
        staged = dest.with_name(dest.name + ".new")
        work_dir = Path(tempfile.gettempdir()) / "BOWA_update"
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            probe = current_exe.parent / ".bowa_write_test"; probe.write_text("x"); probe.unlink()
        except OSError:
            messagebox.showerror("อัปเดตอัตโนมัติไม่ได้", "ไม่มีสิทธิ์เขียนไฟล์ในโฟลเดอร์ของโปรแกรม\nจะเปิดหน้าดาวน์โหลดให้ติดตั้งด้วยตนเอง")
            webbrowser.open(url); return
        part = work_dir / (filename + ".part")
        cancel = threading.Event()
        self._update_in_progress = True; self.is_busy = True
        dialog = tk.Toplevel(self.root); dialog.title("กำลังอัปเดต"); dialog.transient(self.root); dialog.grab_set(); dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", cancel.set)
        frame = tk.Frame(dialog, bg=self.WHITE, padx=16, pady=14); frame.pack()
        tk.Label(frame, text=f"กำลังดาวน์โหลด v{latest}", bg=self.WHITE, fg=self.PRIMARY, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        bar = ttk.Progressbar(frame, length=320, mode="determinate", maximum=100); bar.pack(pady=8)
        status = tk.Label(frame, text="กำลังเชื่อมต่อ...", bg=self.WHITE, fg=self.TEXT_LIGHT); status.pack(anchor="w")
        ttk.Button(frame, text="ยกเลิก", command=cancel.set).pack(anchor="e", pady=(8, 0))

        def update_ui(done, total):
            if not dialog.winfo_exists(): return
            if total: bar["value"] = done * 100 / total
            status.config(text=f"{done / 1048576:.1f} / {total / 1048576:.1f} MB" if total else f"{done / 1048576:.1f} MB")
        def fail(message):
            self._update_in_progress = False; self.is_busy = False
            if dialog.winfo_exists(): dialog.destroy()
            if message: messagebox.showerror("อัปเดตไม่สำเร็จ", message)
        def succeed():
            try:
                self.launch_updater(staged, dest, current_exe)
            except (OSError, subprocess.SubprocessError) as exc:
                fail(f"เริ่มตัวติดตั้งอัปเดตไม่สำเร็จ:\n{exc}")
        def worker():
            try:
                self.download_verified(url, part, sha256, lambda d, t: self.root.after(0, lambda: update_ui(d, t)), cancel)
                shutil.move(str(part), str(staged))
                self.root.after(0, succeed)
            except (OSError, ValueError, shutil.Error) as exc:
                message = None if cancel.is_set() else str(exc)
                try: staged.unlink()
                except OSError: pass
                self.root.after(0, lambda: fail(message))
        threading.Thread(target=worker, daemon=True).start()

    def launch_updater(self, staged, dest, old_exe):
        """สร้างสคริปต์ .bat ที่รอให้โปรแกรมปิด แล้วแทนที่ไฟล์ exe และเปิดโปรแกรมใหม่"""
        esc = lambda value: str(value).replace("%", "%%")
        # หมายเหตุ: ใช้ ping เป็นตัวหน่วงเวลา เพราะ "timeout" ใช้ไม่ได้เมื่อไม่มีคอนโซล (จะจบทันทีโดยไม่รอ)
        wait = "ping -n 2 127.0.0.1 >nul"
        script = "\r\n".join([
            "@echo off", "chcp 65001 >nul",
            f'set "NEW={esc(staged)}"', f'set "DEST={esc(dest)}"', f'set "OLD={esc(old_exe)}"', 'set "LOG=%TEMP%\\BOWA_update\\update.log"',
            'echo [%date% %time%] start>>"%LOG%"', "set /a n=0", ":move",
            'move /Y "%NEW%" "%DEST%" >nul 2>&1', "if not errorlevel 1 goto moved",
            "set /a n+=1", "if %n% geq 60 goto fail", wait, "goto move",
            ":moved", 'echo [%date% %time%] replaced>>"%LOG%"', 'if /I "%DEST%"=="%OLD%" goto run', "set /a m=0", ":delold",
            'del /F /Q "%OLD%" >nul 2>&1', 'if not exist "%OLD%" goto run',
            "set /a m+=1", "if %m% geq 30 goto run", wait, "goto delold",
            ":run", wait, 'start "" "%DEST%"', 'echo [%date% %time%] launched>>"%LOG%"', '(goto) 2>nul & del "%~f0"',
            ":fail", 'echo [%date% %time%] FAILED to replace exe>>"%LOG%"', 'start "" "%OLD%"', "exit /b 1", ""])
        bat = Path(tempfile.gettempdir()) / "BOWA_update" / "apply_update.bat"
        bat.write_text(script, encoding="utf-8")
        # ล้างตัวแปรของ PyInstaller เพื่อให้ exe ใหม่แตกไฟล์ของตัวเอง ไม่ใช้โฟลเดอร์ชั่วคราวของตัวเก่า
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI", "_MEIPASS"))}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(["cmd.exe", "/c", str(bat)], env=env, creationflags=flags, close_fds=True)
        self.designer.save_session()
        self.root.destroy()

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
        self.designer = DesignerTab(self.tab4, self)

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

        hist_frame = ttk.LabelFrame(container, text=" ประวัติและย้อนกลับ (Undo) ", padding=10)
        hist_frame.pack(fill="x", pady=(12, 0))
        self.history_info = tk.Label(hist_frame, text="", font=("Segoe UI", 8), bg=self.WHITE, fg=self.TEXT_DARK, justify="left", anchor="w")
        self.history_info.pack(fill="x", pady=(0, 8))
        btns = tk.Frame(hist_frame, bg=self.WHITE)
        btns.pack(anchor="w")
        self.undo_btn = ttk.Button(btns, text="↩ ย้อนกลับครั้งล่าสุด", style="Warning.TButton", command=self.undo_last_rename)
        self.undo_btn.pack(side="left", ipadx=10, ipady=3)
        self.hist_btn = ttk.Button(btns, text="📜 ดูประวัติทั้งหมด", command=self.show_rename_history)
        self.hist_btn.pack(side="left", padx=8, ipadx=10, ipady=3)
        self.refresh_history_info()

    def refresh_history_info(self):
        runs = self.history.list_runs()
        last = next((r for r in runs if not r["undone_at"]), None)
        if last:
            self.history_info.config(text=f"ครั้งล่าสุดที่ย้อนกลับได้: {last['time'].replace('T', ' ')}  |  เปลี่ยนชื่อ {last['renamed']} ไฟล์, ย้ายไฟล์ที่อ่านไม่ได้ {last['unreadable']} ไฟล์\nโฟลเดอร์: {last['folder']}")
            self.undo_btn.config(state=tk.NORMAL if not self.is_busy else tk.DISABLED)
        else:
            self.history_info.config(text="ยังไม่มีประวัติที่ย้อนกลับได้ (ระบบจะบันทึกอัตโนมัติทุกครั้งที่เปลี่ยนชื่อ)")
            self.undo_btn.config(state=tk.DISABLED)

    def confirm_and_undo(self, run, parent=None):
        if self.is_busy:
            messagebox.showwarning("แจ้งเตือน", "ระบบกำลังทำงานอยู่ กรุณารอให้เสร็จก่อน", parent=parent); return False
        if run["undone_at"]:
            messagebox.showinfo("แจ้งเตือน", "รอบนี้ถูกย้อนกลับไปแล้ว", parent=parent); return False
        if not messagebox.askyesno("ยืนยันการย้อนกลับ",
                f"ย้อนกลับการทำงานเมื่อ {run['time'].replace('T', ' ')}\n\nคืนชื่อเดิม {run['renamed']} ไฟล์ และนำไฟล์ที่อ่านไม่ได้ {run['unreadable']} ไฟล์กลับตำแหน่งเดิม\nโฟลเดอร์: {run['folder']}\n\nดำเนินการต่อหรือไม่?", parent=parent):
            return False
        self.root.config(cursor="watch"); self.root.update_idletasks()
        try:
            restored, skipped = self.history.undo(run["path"])
        except (OSError, ValueError) as e:
            self.root.config(cursor="")
            messagebox.showerror("ย้อนกลับไม่สำเร็จ", str(e), parent=parent); return False
        self.root.config(cursor="")
        msg = f"ย้อนกลับสำเร็จ {restored} ไฟล์"
        if skipped:
            msg += f"\nข้าม {len(skipped)} ไฟล์:\n" + "\n".join(f"• {Path(o).name}: {why}" for o, _n, why in skipped[:8])
            if len(skipped) > 8: msg += f"\n… และอีก {len(skipped) - 8} ไฟล์"
        messagebox.showinfo("ผลการย้อนกลับ", msg, parent=parent)
        self.refresh_history_info()
        return True

    def undo_last_rename(self):
        last = next((r for r in self.history.list_runs() if not r["undone_at"]), None)
        if last: self.confirm_and_undo(last)
        else: self.refresh_history_info()

    def show_rename_history(self):
        win = tk.Toplevel(self.root)
        win.title("ประวัติ Auto Rename"); win.geometry("900x420"); win.transient(self.root); win.configure(bg=self.WHITE)
        cols = ("time", "folder", "renamed", "unreadable", "status")
        tree = ttk.Treeview(win, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a in (("time", "วันเวลา", 140, "w"), ("folder", "โฟลเดอร์", 300, "w"), ("renamed", "เปลี่ยนชื่อ", 80, "center"), ("unreadable", "อ่านไม่ได้", 80, "center"), ("status", "สถานะ", 220, "w")):
            tree.heading(c, text=t); tree.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(win, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=sb.set)
        bar = tk.Frame(win, bg=self.WHITE); bar.pack(side="bottom", fill="x", padx=8, pady=8)
        sb.pack(side="right", fill="y"); tree.pack(side="top", fill="both", expand=True, padx=(8, 0), pady=(8, 0))
        runs = {}

        def fill():
            tree.delete(*tree.get_children()); runs.clear()
            for r in self.history.list_runs():
                iid = str(r["path"]); runs[iid] = r
                status = f"ย้อนกลับแล้ว {r['undone_at'].replace('T', ' ')}" if r["undone_at"] else "ย้อนกลับได้"
                tree.insert("", "end", iid=iid, values=(r["time"].replace("T", " "), r["folder"], r["renamed"], r["unreadable"], status))

        def selected():
            sel = tree.selection()
            if not sel: messagebox.showinfo("แจ้งเตือน", "กรุณาเลือกรายการก่อน", parent=win); return None
            return runs[sel[0]]

        def do_undo():
            r = selected()
            if r and self.confirm_and_undo(r, parent=win): fill()

        def do_export():
            r = selected()
            if not r: return
            dest = filedialog.asksaveasfilename(parent=win, defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"rename_log_{r['time'][:10]}.csv")
            if not dest: return
            try:
                data = self.history.load(r["path"])
                with open(dest, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f); w.writerow(["Type", "Old Path", "New Path"])
                    for m in data.get("moves", []): w.writerow(["rename" if m.get("kind") == "rename" else "unreadable", m["old"], m["new"]])
                messagebox.showinfo("สำเร็จ", "ส่งออกประวัติเรียบร้อย", parent=win)
            except OSError as e:
                messagebox.showerror("ผิดพลาด", str(e), parent=win)

        def do_delete():
            r = selected()
            if r and messagebox.askyesno("ลบประวัติ", "ลบประวัติรอบนี้? (ไม่กระทบไฟล์จริง แต่จะย้อนกลับไม่ได้อีก)", parent=win):
                self.history.delete(r["path"]); fill(); self.refresh_history_info()

        ttk.Button(bar, text="↩ ย้อนกลับรอบที่เลือก", style="Warning.TButton", command=do_undo).pack(side="left", ipadx=8)
        ttk.Button(bar, text="📊 ส่งออก CSV", command=do_export).pack(side="left", padx=6, ipadx=8)
        ttk.Button(bar, text="🗑 ลบประวัติ", command=do_delete).pack(side="left", ipadx=8)
        ttk.Button(bar, text="ปิด", command=win.destroy).pack(side="right", ipadx=8)
        fill()

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
        content_split.add(table_container, stretch="always", minsize=300)

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
        content_split.add(self.preview_panel, stretch="never", minsize=200)
        # แผงพรีวิวกว้างประมาณ 1 ใน 3 ของพื้นที่ และคงสัดส่วนนี้เมื่อย่อ/ขยายหน้าต่าง
        # จนกว่าผู้ใช้จะลากเส้นแบ่งปรับเอง
        self._preview_sash_user = False

        def place_preview_sash(_e=None):
            total = content_split.winfo_width()
            if self._preview_sash_user or total < 600 or not content_split.winfo_ismapped(): return
            want = int(total * 2 / 3)
            try:
                if abs(content_split.sash_coord(0)[0] - want) > 2:
                    content_split.sash_place(0, want, 0)
            except tk.TclError:
                pass
        content_split.bind("<Configure>", lambda e: content_split.after(60, place_preview_sash))
        content_split.bind("<Map>", lambda e: content_split.after(120, place_preview_sash))
        content_split.bind("<ButtonRelease-1>", lambda e: setattr(self, "_preview_sash_user", True))
        self.preview_panel.pack_propagate(False)

        preview_header = tk.Frame(self.preview_panel, bg="#F8F9FA")
        preview_header.pack(fill="x", pady=(2, 0))
        tk.Label(preview_header, text="Interactive Preview", font=("Segoe UI", 8, "bold"), bg="#F8F9FA", fg=self.PRIMARY).pack(side="left", padx=5)
        reset_btn = tk.Button(preview_header, text="Reset", font=("Segoe UI", 8), command=self.reset_preview, bg="#E0E0E0", relief="flat")
        reset_btn.pack(side="right", padx=5)
        # คำแนะนำแยกเป็นบรรทัดของตัวเอง และตัดบรรทัดอัตโนมัติตามความกว้างของแผง ไม่ให้ข้อความถูกตัด
        hint = tk.Label(self.preview_panel, text="เลื่อนล้อเมาส์ = ซูม  |  ลาก = เลื่อนภาพ", font=("Segoe UI", 7), bg="#F8F9FA", fg=self.TEXT_LIGHT, justify="left", anchor="w")
        hint.pack(fill="x", padx=6, pady=(0, 2))
        self.preview_panel.bind("<Configure>", lambda e, l=hint: l.config(wraplength=max(60, e.width - 14)))

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
        grid = tk.Frame(container, bg=self.WHITE)
        grid.pack(fill="both", expand=True, pady=2)
        for col in range(4):
            grid.columnconfigure(col, weight=1, uniform="tools")
        # แถว 1: 2 การ์ด (กว้างการ์ดละ 2 ช่อง) | แถว 2-3: แถวละ 4 การ์ด
        rows = [
            [("✂️ PDF Splitter", "แยกไฟล์ PDF ขนาดใหญ่ให้เป็นไฟล์ละ 1 หน้าอัตโนมัติ\nตั้งชื่อตามไฟล์ต้นทางและเลขหน้า", "เลือกไฟล์เพื่อแยกหน้า", self.ACCENT, self.split_pdf_logic),
             ("➕ PDF Merger", "รวมไฟล์ PDF หลายไฟล์เข้าด้วยกันเป็นไฟล์เดียว\nเรียงลำดับตามชื่อไฟล์อัตโนมัติ", "เลือกไฟล์เพื่อรวมร่าง", self.SUCCESS, self.merge_pdf_logic)],
            [("🔄 PDF Rotator", "หมุนทุกหน้า 90, 180 หรือ 270 องศา\nเหมาะสำหรับเอกสารสแกนผิดแนว", "เลือกไฟล์เพื่อหมุน", self.WARNING, self.rotate_pdf_logic),
             ("🧹 Remove Blank Pages", "ตรวจหาและลบหน้าว่างที่ไม่มีข้อความหรือรูปภาพ\nสร้างไฟล์ใหม่โดยไม่แก้ต้นฉบับ", "ลบหน้าว่าง", self.PURPLE, self.remove_blank_pages_logic),
             ("✂️ Extract Pages", "แยกหน้าที่ต้องการ เช่น 1-3,5,8-10\nสร้างเป็น PDF ใหม่", "แยกหน้าที่เลือก", self.SUCCESS, self.extract_pages_logic),
             ("🖨️ PDF 2-up / Booklet", "จัด 2 หน้าบนกระดาษแนวนอน 1 แผ่น\nเหมาะสำหรับพิมพ์ประหยัดกระดาษ", "จัดหน้า 2-up", self.PURPLE, self.two_up_pdf_logic)],
            [("🔒 PDF Protect", "ตั้งรหัสผ่านเปิดไฟล์และจำกัดการแก้ไข\nไฟล์ต้นฉบับจะไม่ถูกแก้ไข", "ป้องกันด้วยรหัสผ่าน", self.WARNING, self.protect_pdf_logic),
             ("🔓 PDF Unlock", "เปิด PDF ด้วยรหัสผ่านที่ถูกต้อง\nบันทึกเป็นไฟล์ปลดล็อกใหม่", "ปลดล็อก PDF", self.DANGER, self.unlock_pdf_logic),
             ("🖼️ Image to PDF", "รวมรูปภาพหลายไฟล์เป็น PDF เดียว\nเรียงตามลำดับที่เลือก", "รวมภาพเป็น PDF", self.ACCENT, self.images_to_pdf_logic),
             ("📄 PDF Page to Image", "แปลงทุกหน้า PDF เป็นไฟล์ PNG\nเลือกโฟลเดอร์ปลายทางและ DPI ได้", "แปลง PDF เป็นรูปภาพ", self.SUCCESS, self.pdf_pages_to_images_logic)],
        ]
        for r, cards in enumerate(rows):
            span = 4 // len(cards)
            for c, spec in enumerate(cards):
                self.create_tool_card(grid, *spec).grid(row=r, column=c * span, columnspan=span, sticky="nsew", padx=4, pady=3)

    def create_tool_card(self, parent, title, desc, btn_text, color, command):
        card = tk.Frame(parent, bg=self.WHITE, highlightthickness=1, highlightbackground="#EEEEEE", padx=10, pady=10)
        tk.Label(card, text=title, font=("Segoe UI", 10, "bold"), fg=color, bg=self.WHITE).pack(anchor="w")
        desc_label = tk.Label(card, text=desc, font=("Segoe UI", 8), fg=self.TEXT_LIGHT, bg=self.WHITE, justify="left", anchor="w")
        desc_label.pack(anchor="w", fill="x", pady=6)
        card.bind("<Configure>", lambda e, d=desc_label: d.config(wraplength=max(100, e.width - 26)))
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
        self.undo_btn.config(state=tk.DISABLED)
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
        moves = []
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
                    moves.append({"kind": "unreadable", "old": str(file_path), "new": str(unreadable_target)})
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
                moves.append({"kind": "rename", "old": str(file_path), "new": str(new_path)})
                success += 1
                self.root.after(0, lambda s=success: self.update_stat("Success", str(s)))
            except OSError:
                error += 1
                self.root.after(0, lambda e=error: self.update_stat("Unreadable", str(e)))
        try:
            self.history.save_run(target_dir, moves, include_subfolders)
        except OSError:
            pass
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
        self.refresh_history_info()
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
        self.designer.save_session()
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
