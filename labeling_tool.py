#!/usr/bin/env python3
"""
Defect Detection Labeling Tool  –  v2
========================================
4 Classes  : BERKARAT | CONDONG | PINTU TIDAK BERKUNCI | VANDALISM
Output     : COCO JSON  (annotations.json)
Severity   : Low / Medium / High  (per annotation)
Draw modes : Bounding Box  |  Polygon / Semantic Segmentation

Controls – BBox mode
---------------------
  Left-click + drag       Draw bounding box
  Right-click on box      Delete that box

Controls – Polygon mode
------------------------
  Left-click              Add vertex
  Right-click             Close polygon  (needs ≥ 3 vertices)
  Escape                  Cancel in-progress polygon
  Enter / Return          Close polygon  (same as right-click)

General
-------
  Save & Next             Commit annotations → annotations.json → next image
  Skip (no defect)        Mark image as reviewed with no annotations
  Prev / Next             Navigate without saving
"""

import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import json
import os
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
FOLDERS = {
    "BERKARAT":             r"C:\Users\Izzat\Downloads\BERKARAT",
    "CONDONG":              r"C:\Users\Izzat\Downloads\CONDONG",
    "PINTU TIDAK BERKUNCI": r"C:\Users\Izzat\Downloads\PINTU TIDAK BERKUNCI",
    "VANDALISM":            r"C:\Users\Izzat\Downloads\VANDALISM",
}

CATEGORIES = [
    {"id": 1, "name": "BERKARAT",             "supercategory": "defect"},
    {"id": 2, "name": "CONDONG",              "supercategory": "defect"},
    {"id": 3, "name": "PINTU TIDAK BERKUNCI", "supercategory": "defect"},
    {"id": 4, "name": "VANDALISM",            "supercategory": "defect"},
]
CAT_NAME_TO_ID = {c["name"]: c["id"] for c in CATEGORIES}

SEVERITIES  = ["Low", "Medium", "High"]
OUTPUT_FILE = r"C:\Users\Izzat\Labelling Folder\annotations.json"
CANVAS_W, CANVAS_H = 900, 650

CLASS_COLORS = {
    "BERKARAT":             "#e67e22",
    "CONDONG":              "#3498db",
    "PINTU TIDAK BERKUNCI": "#9b59b6",
    "VANDALISM":            "#e74c3c",
}
SEV_COLORS = {
    "Low":    "#a6e3a1",
    "Medium": "#f9e2af",
    "High":   "#f38ba8",
}


# ── Geometry helpers ──────────────────────────────────────────────────────────
def poly_bbox(flat_pts: list[float]) -> tuple[float, float, float, float]:
    """[x1,y1,x2,y2,...] → (x, y, w, h) bounding box."""
    xs = flat_pts[0::2]
    ys = flat_pts[1::2]
    x, y = min(xs), min(ys)
    return x, y, max(xs) - x, max(ys) - y


def poly_area(flat_pts: list[float]) -> float:
    """Shoelace formula. flat_pts = [x1,y1,x2,y2,...]."""
    n = len(flat_pts) // 2
    if n < 3:
        return 0.0
    xs, ys = flat_pts[0::2], flat_pts[1::2]
    area = sum(xs[i] * ys[(i + 1) % n] - xs[(i + 1) % n] * ys[i]
               for i in range(n))
    return abs(area) / 2.0


def point_in_bbox(px, py, box: dict) -> bool:
    return (box["x"] <= px <= box["x"] + box["w"] and
            box["y"] <= py <= box["y"] + box["h"])


def canvas_to_img(cx, cy, scale_x, scale_y, img_x0, img_y0):
    return (cx - img_x0) * scale_x, (cy - img_y0) * scale_y


def img_to_canvas(ix, iy, scale_x, scale_y, img_x0, img_y0):
    return ix / scale_x + img_x0, iy / scale_y + img_y0


# ── Main Application ──────────────────────────────────────────────────────────
class LabelingTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Defect Detection Labeling Tool  –  v2  (BBox + Segmentation)")
        self.geometry("1500x820")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)

        # ── Persistent state ───────────────────────────────────────────────
        self.images: list[tuple[str, str]] = []   # (abs_path, class_name)
        self.current_idx: int = 0
        self.coco: dict = self._init_coco()
        self.labeled_paths: set[str] = set()

        # ── Per-image annotation state ─────────────────────────────────────
        # Each box dict:
        #   mode        : "bbox" | "polygon"
        #   severity    : "Low" | "Medium" | "High"
        #   x,y,w,h     : bounding box in original image coords
        #   segmentation: [] for bbox mode; [x1,y1,...] for polygon mode
        self.current_boxes: list[dict] = []

        # ── Drawing state ──────────────────────────────────────────────────
        self.mode_var     = tk.StringVar(value="bbox")
        self.severity_var = tk.StringVar(value="Low")

        # bbox
        self.rect_id  = None
        self.start_x  = self.start_y = 0

        # polygon
        self.poly_pts:        list[float] = []   # canvas coords [x1,y1,x2,y2,...]
        self.poly_dot_ids:    list[int]   = []   # circle item IDs
        self.poly_line_ids:   list[int]   = []   # segment item IDs
        self.rubber_line_id:  int | None  = None # live rubber-band segment

        # image transform
        self.scale_x = self.scale_y = 1.0
        self.img_x0  = self.img_y0  = 0
        self.tk_img  = None

        self._load_image_list()
        self._build_ui()
        self._bind_canvas_events()
        self._load_existing_annotations()
        if self.images:
            self._show_image(self.current_idx)

    # ── COCO skeleton ─────────────────────────────────────────────────────
    def _init_coco(self) -> dict:
        return {
            "info": {
                "description":  "Defect Detection Dataset",
                "version":      "1.0",
                "date_created": datetime.now().isoformat(),
            },
            "licenses":   [],
            "categories": CATEGORIES,
            "images":     [],
        }

    # ── Image list loading ─────────────────────────────────────────────────
    def _load_image_list(self):
        for class_name, folder in FOLDERS.items():
            if not os.path.isdir(folder):
                print(f"[WARN] Folder not found: {folder}")
                continue
            for fname in sorted(os.listdir(folder)):
                if fname.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                    self.images.append((os.path.join(folder, fname), class_name))
        if not self.images:
            messagebox.showerror("Error", "No images found in any folder!")
            self.destroy()

    # ── Persist ───────────────────────────────────────────────────────────
    def _load_existing_annotations(self):
        if not os.path.exists(OUTPUT_FILE):
            return
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # ── Migrate old flat format → embedded annotations ─────────────
            if "annotations" in data:
                id_to_img = {img["id"]: img for img in data.get("images", [])}
                for ann in data.pop("annotations", []):
                    img = id_to_img.get(ann.get("image_id"))
                    if img is not None:
                        ann_copy = {k: v for k, v in ann.items() if k != "image_id"}
                        img.setdefault("annotations", []).append(ann_copy)
            for img in data.get("images", []):
                img.setdefault("annotations", [])
            # ──────────────────────────────────────────────────────────────

            self.coco = data
            self.labeled_paths = {img["file_name"] for img in data.get("images", [])}

            # Jump to first unlabeled image
            for i, (path, _) in enumerate(self.images):
                if path not in self.labeled_paths:
                    self.current_idx = i
                    break

            # Refresh listbox markers
            for i, (path, _) in enumerate(self.images):
                if path in self.labeled_paths:
                    self.listbox.delete(i)
                    self.listbox.insert(i, f"✓ {os.path.basename(path)[:26]}")
                    self.listbox.itemconfig(i, fg="#a6e3a1")

            self._update_stats()
        except Exception as exc:
            messagebox.showwarning("Load Warning",
                                   f"Could not load existing annotations:\n{exc}\n"
                                   "Starting fresh.")

    def _write_json(self):
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.coco, f, indent=2, ensure_ascii=False)

    def _get_image_id(self, path: str):
        for img in self.coco["images"]:
            if img["file_name"] == path:
                return img["id"]
        return None

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Toolbar ────────────────────────────────────────────────────
        toolbar = tk.Frame(self, bg="#2d2d3f", pady=7, padx=12)
        toolbar.pack(fill="x", side="top")

        self.progress_lbl = tk.Label(toolbar, text="", bg="#2d2d3f", fg="#cdd6f4",
                                      font=("Segoe UI", 10))
        self.progress_lbl.pack(side="left", padx=8)

        self.class_badge = tk.Label(toolbar, text="", bg="#2d2d3f", fg="white",
                                     font=("Segoe UI", 11, "bold"), padx=12, pady=3)
        self.class_badge.pack(side="left", padx=12)

        btn = dict(font=("Segoe UI", 10), relief="flat", padx=12, pady=5, cursor="hand2")

        tk.Button(toolbar, text="◀ Prev",         command=self._prev,
                  bg="#585b70", fg="white", activebackground="#7f849c", **btn
                  ).pack(side="left", padx=3)
        tk.Button(toolbar, text="Next ▶",         command=self._next,
                  bg="#585b70", fg="white", activebackground="#7f849c", **btn
                  ).pack(side="left", padx=3)
        tk.Button(toolbar, text="💾 Save & Next",  command=self._save_and_next,
                  bg="#a6e3a1", fg="#1e1e2e", activebackground="#c3f0c0",
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(side="left", padx=10)
        tk.Button(toolbar, text="⊘ Skip (no defect)", command=self._skip_no_defect,
                  bg="#f9e2af", fg="#1e1e2e", activebackground="#fce6b5", **btn
                  ).pack(side="left", padx=3)

        # ── Main area ──────────────────────────────────────────────────
        main = tk.Frame(self, bg="#1e1e2e")
        main.pack(fill="both", expand=True)

        # Left panel – image list
        left = tk.Frame(main, bg="#181825", width=230)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="All Images", bg="#181825", fg="#cdd6f4",
                 font=("Segoe UI", 11, "bold")).pack(pady=(10, 4))

        sb = ttk.Scrollbar(left, orient="vertical")
        sb.pack(side="right", fill="y")
        self.listbox = tk.Listbox(
            left, yscrollcommand=sb.set,
            bg="#181825", fg="#cdd6f4",
            selectbackground="#585b70", selectforeground="white",
            font=("Consolas", 8), borderwidth=0, highlightthickness=0,
            activestyle="none")
        self.listbox.pack(fill="both", expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)
        for path, _ in self.images:
            self.listbox.insert("end", f"○ {os.path.basename(path)[:26]}")

        # Center – canvas + mode bar
        center = tk.Frame(main, bg="#1e1e2e")
        center.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        # Mode toggle bar (above canvas)
        mode_bar = tk.Frame(center, bg="#2d2d3f", pady=5)
        mode_bar.pack(fill="x", pady=(0, 6))

        tk.Label(mode_bar, text="Draw mode:", bg="#2d2d3f", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(side="left", padx=(10, 6))

        self.btn_bbox = tk.Button(
            mode_bar, text="⬜  Bounding Box",
            command=lambda: self._set_mode("bbox"),
            bg="#89b4fa", fg="#1e1e2e",
            font=("Segoe UI", 10, "bold"), relief="flat",
            padx=12, pady=4, cursor="hand2")
        self.btn_bbox.pack(side="left", padx=4)

        self.btn_poly = tk.Button(
            mode_bar, text="⬡  Polygon / Segmentation",
            command=lambda: self._set_mode("polygon"),
            bg="#585b70", fg="#cdd6f4",
            font=("Segoe UI", 10), relief="flat",
            padx=12, pady=4, cursor="hand2")
        self.btn_poly.pack(side="left", padx=4)

        self.mode_hint = tk.Label(
            mode_bar, text="", bg="#2d2d3f", fg="#6c7086",
            font=("Segoe UI", 9))
        self.mode_hint.pack(side="left", padx=16)
        self._update_mode_hint()

        self.canvas = tk.Canvas(
            center, width=CANVAS_W, height=CANVAS_H,
            bg="#313244", cursor="crosshair",
            highlightthickness=1, highlightbackground="#585b70")
        self.canvas.pack()

        # Right panel – controls
        right = tk.Frame(main, bg="#181825", width=280)
        right.pack(side="right", fill="y", padx=(0, 8), pady=8)
        right.pack_propagate(False)

        # Severity
        tk.Label(right, text="Severity", bg="#181825", fg="#cdd6f4",
                 font=("Segoe UI", 13, "bold")).pack(pady=(18, 6))
        for sev in SEVERITIES:
            tk.Radiobutton(
                right, text=f"  {sev}", variable=self.severity_var, value=sev,
                bg="#181825", fg=SEV_COLORS[sev], selectcolor="#313244",
                activebackground="#181825",
                font=("Segoe UI", 12, "bold"), cursor="hand2",
            ).pack(anchor="w", padx=24, pady=4)

        tk.Frame(right, bg="#45475a", height=1).pack(fill="x", padx=10, pady=12)

        # Annotations list
        tk.Label(right, text="Annotations on this image",
                 bg="#181825", fg="#cdd6f4",
                 font=("Segoe UI", 11, "bold")).pack(pady=(0, 6))

        ann_sb = ttk.Scrollbar(right, orient="vertical")
        ann_sb.pack(side="right", fill="y", padx=(0, 4))
        self.ann_listbox = tk.Listbox(
            right, yscrollcommand=ann_sb.set,
            bg="#313244", fg="#cdd6f4", height=8,
            font=("Consolas", 9), borderwidth=0, highlightthickness=0,
            activestyle="none")
        self.ann_listbox.pack(fill="x", padx=(10, 0))
        ann_sb.config(command=self.ann_listbox.yview)

        tk.Button(right, text="🗑  Delete Selected",
                  command=self._delete_selected,
                  bg="#45475a", fg="#f38ba8",
                  font=("Segoe UI", 10), relief="flat",
                  padx=8, pady=4, cursor="hand2").pack(pady=8)

        tk.Frame(right, bg="#45475a", height=1).pack(fill="x", padx=10, pady=6)

        # Stats
        tk.Label(right, text="Progress", bg="#181825", fg="#cdd6f4",
                 font=("Segoe UI", 11, "bold")).pack(pady=(0, 4))
        self.stats_lbl = tk.Label(right, text="", bg="#181825", fg="#a6adc8",
                                   font=("Consolas", 9), justify="left")
        self.stats_lbl.pack(padx=14, anchor="w")

        self._update_stats()

    # ── Canvas event binding ───────────────────────────────────────────────
    def _bind_canvas_events(self):
        self.canvas.bind("<ButtonPress-1>",   self._on_left_press)
        self.canvas.bind("<B1-Motion>",       self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<Button-3>",        self._on_right_click)
        self.canvas.bind("<Motion>",          self._on_mouse_move)
        self.bind("<Escape>",  lambda _: self._poly_cancel())
        self.bind("<Return>",  lambda _: self._poly_close())

    # ── Mode switching ─────────────────────────────────────────────────────
    def _set_mode(self, mode: str):
        self._poly_cancel()   # discard any in-progress polygon
        self.mode_var.set(mode)
        active   = "#89b4fa"
        inactive = "#585b70"
        active_fg   = "#1e1e2e"
        inactive_fg = "#cdd6f4"
        if mode == "bbox":
            self.btn_bbox.config(bg=active,   fg=active_fg,   font=("Segoe UI", 10, "bold"))
            self.btn_poly.config(bg=inactive, fg=inactive_fg, font=("Segoe UI", 10))
        else:
            self.btn_poly.config(bg=active,   fg=active_fg,   font=("Segoe UI", 10, "bold"))
            self.btn_bbox.config(bg=inactive, fg=inactive_fg, font=("Segoe UI", 10))
        self._update_mode_hint()

    def _update_mode_hint(self):
        if self.mode_var.get() == "bbox":
            self.mode_hint.config(
                text="Left-drag: draw box   Right-click on box: delete")
        else:
            self.mode_hint.config(
                text="Left-click: add vertex   Right-click / Enter: close   Esc: cancel")

    # ── Canvas event handlers ──────────────────────────────────────────────
    def _on_left_press(self, event):
        if self.mode_var.get() == "bbox":
            self.start_x, self.start_y = event.x, event.y
            self.rect_id = self.canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline="#89b4fa", width=2, dash=(5, 3), tags="drawing")
        else:
            self._poly_add_point(event.x, event.y)

    def _on_left_drag(self, event):
        if self.mode_var.get() == "bbox" and self.rect_id:
            self.canvas.coords(self.rect_id,
                                self.start_x, self.start_y, event.x, event.y)

    def _on_left_release(self, event):
        if self.mode_var.get() != "bbox" or not self.rect_id:
            return
        x1 = min(self.start_x, event.x)
        y1 = min(self.start_y, event.y)
        x2 = max(self.start_x, event.x)
        y2 = max(self.start_y, event.y)
        self.canvas.delete(self.rect_id)
        self.rect_id = None
        if (x2 - x1) < 6 or (y2 - y1) < 6:
            return

        ox = max(0.0, (x1 - self.img_x0) * self.scale_x)
        oy = max(0.0, (y1 - self.img_y0) * self.scale_y)
        ow = (x2 - x1) * self.scale_x
        oh = (y2 - y1) * self.scale_y

        self.current_boxes.append({
            "mode":        "bbox",
            "severity":    self.severity_var.get(),
            "x": ox, "y": oy, "w": ow, "h": oh,
            "segmentation": [],
        })
        self._redraw_annotations()
        self._refresh_ann_list()

    def _on_right_click(self, event):
        if self.mode_var.get() == "polygon":
            # Right-click in polygon mode = close polygon
            self._poly_close()
            return
        # BBox mode: delete box under cursor
        px = (event.x - self.img_x0) * self.scale_x
        py = (event.y - self.img_y0) * self.scale_y
        for i, box in enumerate(self.current_boxes):
            if point_in_bbox(px, py, box):
                self.current_boxes.pop(i)
                self._redraw_annotations()
                self._refresh_ann_list()
                return

    def _on_mouse_move(self, event):
        """Update rubber-band line while drawing polygon."""
        if self.mode_var.get() != "polygon" or len(self.poly_pts) < 2:
            return
        if self.rubber_line_id:
            self.canvas.delete(self.rubber_line_id)
        lx, ly = self.poly_pts[-2], self.poly_pts[-1]
        self.rubber_line_id = self.canvas.create_line(
            lx, ly, event.x, event.y,
            fill="#89b4fa", width=1, dash=(4, 3), tags="drawing")

    # ── Polygon drawing logic ──────────────────────────────────────────────
    def _poly_add_point(self, cx: float, cy: float):
        """Add one vertex to the in-progress polygon."""
        self.poly_pts.extend([cx, cy])
        n = len(self.poly_pts) // 2

        # Draw a dot at the vertex
        dot = self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                                       fill="#89b4fa", outline="white",
                                       width=1, tags="drawing")
        self.poly_dot_ids.append(dot)

        # Draw segment from previous vertex
        if n >= 2:
            px, py = self.poly_pts[-4], self.poly_pts[-3]
            seg = self.canvas.create_line(px, py, cx, cy,
                                          fill="#89b4fa", width=2, tags="drawing")
            self.poly_line_ids.append(seg)

    def _poly_close(self):
        """Finalise the in-progress polygon (need ≥ 3 vertices)."""
        n = len(self.poly_pts) // 2
        if n < 3:
            messagebox.showinfo("Polygon",
                                "Need at least 3 vertices to close a polygon.\n"
                                "Press Escape to cancel.")
            return

        # Build original-image-coord flat list
        seg_orig: list[float] = []
        for j in range(0, len(self.poly_pts), 2):
            ox, oy = canvas_to_img(self.poly_pts[j], self.poly_pts[j + 1],
                                    self.scale_x, self.scale_y,
                                    self.img_x0, self.img_y0)
            seg_orig.extend([round(max(0.0, ox), 2), round(max(0.0, oy), 2)])

        bx, by, bw, bh = poly_bbox(seg_orig)
        self.current_boxes.append({
            "mode":        "polygon",
            "severity":    self.severity_var.get(),
            "x": bx, "y": by, "w": bw, "h": bh,
            "segmentation": seg_orig,
        })

        self._poly_cancel()        # clear drawing state
        self._redraw_annotations()
        self._refresh_ann_list()

    def _poly_cancel(self):
        """Discard an in-progress polygon without saving."""
        self.canvas.delete("drawing")
        if self.rubber_line_id:
            self.canvas.delete(self.rubber_line_id)
            self.rubber_line_id = None
        self.poly_pts.clear()
        self.poly_dot_ids.clear()
        self.poly_line_ids.clear()

    # ── Redraw all saved annotations ───────────────────────────────────────
    def _redraw_annotations(self):
        self.canvas.delete("ann")

        for i, box in enumerate(self.current_boxes):
            sev   = box.get("severity", "Low")
            color = SEV_COLORS.get(sev, "#cdd6f4")
            mode  = box.get("mode", "bbox")

            if mode == "polygon" and box.get("segmentation"):
                seg = box["segmentation"]
                # Convert to canvas coords
                cpts: list[float] = []
                for j in range(0, len(seg), 2):
                    cx, cy = img_to_canvas(seg[j], seg[j + 1],
                                           self.scale_x, self.scale_y,
                                           self.img_x0, self.img_y0)
                    cpts.extend([cx, cy])
                # Filled polygon with stipple for semi-transparency
                self.canvas.create_polygon(
                    cpts, outline=color, fill=color,
                    stipple="gray25", width=2, tags="ann")
                # Vertex dots
                for j in range(0, len(cpts), 2):
                    self.canvas.create_oval(
                        cpts[j] - 3, cpts[j + 1] - 3,
                        cpts[j] + 3, cpts[j + 1] + 3,
                        fill=color, outline="white", width=1, tags="ann")
                # Label near first vertex
                self.canvas.create_text(
                    cpts[0] + 5, cpts[1] - 8, anchor="nw",
                    text=f"#{i + 1} SEG {sev[:1]}",
                    fill=color, font=("Segoe UI", 9, "bold"), tags="ann")

            else:
                # Bounding box
                x1 = box["x"] / self.scale_x + self.img_x0
                y1 = box["y"] / self.scale_y + self.img_y0
                x2 = x1 + box["w"] / self.scale_x
                y2 = y1 + box["h"] / self.scale_y
                self.canvas.create_rectangle(
                    x1, y1, x2, y2, outline=color, width=2, tags="ann")
                self.canvas.create_text(
                    x1 + 4, y1 + 2, anchor="nw",
                    text=f"#{i + 1} BOX {sev[:1]}",
                    fill=color, font=("Segoe UI", 9, "bold"), tags="ann")

    def _refresh_ann_list(self):
        self.ann_listbox.delete(0, "end")
        for i, box in enumerate(self.current_boxes):
            sev  = box.get("severity", "Low")
            mode = box.get("mode", "bbox")
            if mode == "polygon":
                pts = len(box["segmentation"]) // 2
                entry = f"#{i+1}  [SEG]  [{sev}]  {pts} pts"
            else:
                entry = f"#{i+1}  [BOX]  [{sev}]  {int(box['w'])}×{int(box['h'])} px"
            self.ann_listbox.insert("end", entry)
            self.ann_listbox.itemconfig(i, fg=SEV_COLORS.get(sev, "#cdd6f4"))

    def _delete_selected(self):
        sel = self.ann_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.current_boxes):
            self.current_boxes.pop(idx)
            self._redraw_annotations()
            self._refresh_ann_list()

    # ── Image display ─────────────────────────────────────────────────────
    def _show_image(self, idx: int):
        if not (0 <= idx < len(self.images)):
            return
        self._poly_cancel()
        self.current_idx = idx
        path, class_name = self.images[idx]

        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror("Image Error", f"Cannot open:\n{path}\n\n{exc}")
            return

        orig_w, orig_h = img.size
        scale = min(CANVAS_W / orig_w, CANVAS_H / orig_h, 1.0)
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))

        self.scale_x = orig_w / new_w
        self.scale_y = orig_h / new_h
        self.img_x0  = (CANVAS_W - new_w) // 2
        self.img_y0  = (CANVAS_H - new_h) // 2

        img = img.resize((new_w, new_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.create_image(self.img_x0, self.img_y0,
                                  anchor="nw", image=self.tk_img, tags="bg")

        # Restore saved annotations for this image
        self.current_boxes = []
        for img_entry in self.coco["images"]:
            if img_entry["file_name"] == path:
                for ann in img_entry.get("annotations", []):
                    x, y, w, h = ann["bbox"]
                    seg = ann.get("segmentation", [])
                    # COCO stores segmentation as list of polygons; take first
                    flat_seg = seg[0] if (seg and isinstance(seg[0], list)) else seg
                    mode = "polygon" if flat_seg else "bbox"
                    self.current_boxes.append({
                        "mode":        mode,
                        "severity":    ann.get("severity", "Low"),
                        "x": x, "y": y, "w": w, "h": h,
                        "segmentation": flat_seg,
                    })
                break

        self._redraw_annotations()

        color = CLASS_COLORS.get(class_name, "#cdd6f4")
        self.class_badge.config(text=f"  {class_name}  ", bg=color)
        self.progress_lbl.config(
            text=f"[{idx + 1} / {len(self.images)}]   {os.path.basename(path)}")

        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.see(idx)

        self._refresh_ann_list()
        self._update_stats()

    # ── Navigation ────────────────────────────────────────────────────────
    def _prev(self):
        if self.current_idx > 0:
            self._show_image(self.current_idx - 1)

    def _next(self):
        if self.current_idx < len(self.images) - 1:
            self._show_image(self.current_idx + 1)

    def _save_and_next(self):
        self._commit_annotations()
        self._write_json()
        self._next()

    def _skip_no_defect(self):
        path, class_name = self.images[self.current_idx]
        if self._get_image_id(path) is None:
            try:
                w, h = Image.open(path).size
            except Exception:
                w, h = 0, 0
            self.coco["images"].append({
                "id":            len(self.coco["images"]) + 1,
                "file_name":     path,
                "width":         w,
                "height":        h,
                "class":         class_name,
                "severity":      "None",
                "no_defect":     True,
                "date_captured": "",
                "annotations":   [],
            })
            self.labeled_paths.add(path)
        self._update_listbox_marker(self.current_idx, labeled=True, no_defect=True)
        self._write_json()
        self._next()

    def _on_listbox_select(self, event):
        sel = self.listbox.curselection()
        if not sel or sel[0] == self.current_idx:
            return
        self._show_image(sel[0])

    # ── Commit to COCO ────────────────────────────────────────────────────
    def _commit_annotations(self):
        path, class_name = self.images[self.current_idx]
        cat_id = CAT_NAME_TO_ID.get(class_name, 1)

        img_id = self._get_image_id(path)
        if img_id is None:
            try:
                w, h = Image.open(path).size
            except Exception:
                w, h = 0, 0
            img_id = len(self.coco["images"]) + 1
            self.coco["images"].append({
                "id":            img_id,
                "file_name":     path,
                "width":         w,
                "height":        h,
                "class":         class_name,
                "date_captured": "",
                "annotations":   [],
            })
            self.labeled_paths.add(path)

        # Overall severity = worst box on this image
        sev_rank = {"Low": 0, "Medium": 1, "High": 2}
        overall  = max(
            (b["severity"] for b in self.current_boxes),
            key=lambda s: sev_rank.get(s, 0),
            default="Low"
        ) if self.current_boxes else "Low"

        # Find the image entry, update metadata, and replace its annotations
        img_entry = next(e for e in self.coco["images"] if e["id"] == img_id)
        img_entry["severity"]    = overall
        img_entry["no_defect"]   = (len(self.current_boxes) == 0)
        img_entry["annotations"] = []   # clear old annotations for this image

        # Global ann_id = max across all embedded annotations + 1
        ann_id = max(
            (ann["id"] for img in self.coco["images"]
             for ann in img.get("annotations", [])),
            default=0
        ) + 1

        for box in self.current_boxes:
            seg = box.get("segmentation", [])

            if seg:
                area     = poly_area(seg)
                coco_seg = [seg]          # COCO: list of polygons
            else:
                area     = box["w"] * box["h"]
                coco_seg = []

            img_entry["annotations"].append({
                "id":           ann_id,
                "category_id":  cat_id,
                "bbox":         [round(box["x"], 2), round(box["y"], 2),
                                 round(box["w"], 2), round(box["h"], 2)],
                "segmentation": coco_seg,
                "area":         round(area, 2),
                "iscrowd":      0,
                "severity":     box["severity"],
                "ann_mode":     box.get("mode", "bbox"),
            })
            ann_id += 1

        self._update_listbox_marker(self.current_idx, labeled=True)
        self._update_stats()

    def _update_listbox_marker(self, idx: int,
                                labeled: bool = False, no_defect: bool = False):
        path = self.images[idx][0]
        icon = "⊘" if no_defect else ("✓" if labeled else "○")
        col  = "#6c7086" if no_defect else ("#a6e3a1" if labeled else "#cdd6f4")
        self.listbox.delete(idx)
        self.listbox.insert(idx, f"{icon} {os.path.basename(path)[:26]}")
        self.listbox.itemconfig(idx, fg=col)

    # ── Stats ─────────────────────────────────────────────────────────────
    def _update_stats(self):
        labeled = len(self.labeled_paths)
        total   = len(self.images)
        pct     = (labeled / total * 100) if total else 0
        anns    = [ann for img in self.coco["images"]
                   for ann in img.get("annotations", [])]
        n_anns  = len(anns)
        n_box   = sum(1 for a in anns if a.get("ann_mode") != "polygon")
        n_seg   = sum(1 for a in anns if a.get("ann_mode") == "polygon")
        low     = sum(1 for a in anns if a.get("severity") == "Low")
        med     = sum(1 for a in anns if a.get("severity") == "Medium")
        high    = sum(1 for a in anns if a.get("severity") == "High")

        per_cls = {cls: sum(1 for img in self.coco["images"]
                            if cls in img["file_name"] or img.get("class") == cls)
                   for cls in FOLDERS}

        lines = [
            f"Labeled  : {labeled}/{total}",
            f"Progress : {pct:.1f}%",
            "",
            f"Annotations: {n_anns}",
            f"  BBox   : {n_box}",
            f"  Seg    : {n_seg}",
            "",
            f"Severity breakdown:",
            f"  Low    : {low}",
            f"  Medium : {med}",
            f"  High   : {high}",
            "",
            "── Per class ──",
        ]
        for cls, n in per_cls.items():
            short = (cls[:9] + "…") if len(cls) > 10 else cls
            lines.append(f"  {short:<10}: {n}")

        self.stats_lbl.config(text="\n".join(lines))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = LabelingTool()
    app.mainloop()
