from __future__ import annotations

import json
import math
import os
import sys
import tkinter as tk
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Callable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageGrab, ImageOps, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
    BaseTk = TkinterDnD.Tk
except (ImportError, RuntimeError):
    DND_FILES = None
    DND_AVAILABLE = False
    BaseTk = tk.Tk

APP_NAME = "QuickFX Editor"
PRESET_ACTIONS = ("Adjustments", "Auto Enhance", "Grayscale", "Invert", "Blur", "Pixelate", "Mosaic", "Vignette", "Glow", "Posterize", "Sketch", "Cinematic Look")
SUPPORTED_OPEN = [
    ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif"),
    ("PNG", "*.png"),
    ("JPEG", "*.jpg *.jpeg"),
    ("WebP", "*.webp"),
    ("All files", "*.*"),
]
SUPPORTED_SAVE = [
    ("PNG", "*.png"),
    ("JPEG", "*.jpg"),
    ("WebP", "*.webp"),
    ("BMP", "*.bmp"),
    ("TIFF", "*.tiff"),
]


@dataclass
class Selection:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def copy(self) -> "Selection":
        return Selection(self.left, self.top, self.right, self.bottom)


@dataclass
class HistoryState:
    image: Image.Image
    selection: Optional[Selection]
    focus_zones: list[Selection]
    lasso_points: list[tuple[int, int]]


@dataclass
class DocumentState:
    document_id: str
    image: Image.Image
    original_image: Image.Image
    current_path: Optional[Path]
    dirty: bool
    undo_stack: list[HistoryState]
    redo_stack: list[HistoryState]
    selection: Optional[Selection]
    focus_zones: list[Selection]
    lasso_points: list[tuple[int, int]]
    zoom: float = 1.0


class QuickFXEditor(BaseTk):
    MAX_HISTORY = 30

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1420x880")
        self.minsize(1080, 680)
        self.configure(bg="#17191d")

        self.image: Optional[Image.Image] = None
        self.original_image: Optional[Image.Image] = None
        self.preview_photo: Optional[ImageTk.PhotoImage] = None
        self.current_path: Optional[Path] = None
        self.dirty = False

        self.zoom = 1.0
        self.fit_zoom = 1.0
        self.image_origin = (0.0, 0.0)
        self.selection: Optional[Selection] = None
        self.focus_zones: list[Selection] = []
        self.focus_preview: Optional[Selection] = None
        self.lasso_points: list[tuple[int, int]] = []
        self.lasso_preview: list[tuple[int, int]] = []
        self.shape_preview: Optional[Selection] = None
        self.mask_drag_action: Optional[str] = None
        self.mask_drag_index: Optional[int] = None
        self.mask_drag_original: Optional[Selection] = None
        self.mask_drag_start: Optional[tuple[int, int]] = None
        self.drag_start_canvas: Optional[tuple[float, float]] = None
        self.tool_start_image: Optional[tuple[int, int]] = None
        self.tool_end_image: Optional[tuple[int, int]] = None
        self.draw_mode = tk.StringVar(value="selection")

        self.preview_image: Optional[Image.Image] = None
        self.brush_before: Optional[Image.Image] = None
        self.brush_source: Optional[Image.Image] = None
        self.brush_last: Optional[tuple[int, int]] = None
        self.clone_source: Optional[tuple[int, int]] = None
        self.clone_offset: Optional[tuple[int, int]] = None

        self.undo_stack: list[HistoryState] = []
        self.redo_stack: list[HistoryState] = []
        self.brush_state_before: Optional[HistoryState] = None

        self.blur_radius = tk.DoubleVar(value=8.0)
        self.pixel_size = tk.IntVar(value=16)
        self.mosaic_size = tk.IntVar(value=22)
        self.brightness = tk.IntVar(value=0)
        self.contrast = tk.IntVar(value=0)
        self.saturation = tk.IntVar(value=0)
        self.sharpness = tk.IntVar(value=0)
        self.creative_strength = tk.IntVar(value=40)
        self.brush_size = tk.IntVar(value=60)
        self.sticker_size = tk.IntVar(value=96)
        self.sticker_choice = tk.StringVar(value="😀")
        self.shape_width = tk.IntVar(value=8)
        self.shape_color = tk.StringVar(value="#ff3030")
        self.area_effect = tk.StringVar(value="Blur")
        self.preset_action = tk.StringVar(value="Adjustments")
        self.preset_choice = tk.StringVar(value="Strong blur")
        self.show_before = tk.BooleanVar(value=False)
        self.before_hold_previous = False
        self.compare_mode = tk.BooleanVar(value=False)
        self.compare_split = tk.IntVar(value=50)
        self.selected_face_index: Optional[int] = None
        self.status_text = tk.StringVar(value="Open an image to begin")
        self.zoom_text = tk.StringVar(value="100%")

        self.presets_path = Path.home() / ".quickfx_presets.json"
        self.recovery_dir = Path.home() / ".quickfx_recovery"
        self.user_presets: dict[str, dict[str, object]] = {}
        self.documents: dict[str, DocumentState] = {}
        self.document_tab_frames: dict[str, ttk.Frame] = {}
        self.tab_to_document: dict[str, str] = {}
        self.active_document_id: Optional[str] = None
        self._switching_documents = False
        self._setup_style()
        self._load_presets()
        self._build_ui()
        self.draw_mode.trace_add("write", self._on_tool_changed)
        self.area_effect.trace_add("write", self._on_area_effect_changed)
        self._refresh_tool_options()
        self._bind_shortcuts()
        self._setup_drag_and_drop()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.blur_radius.trace_add("write", self._refresh_effect_preview)
        self.pixel_size.trace_add("write", self._refresh_effect_preview)
        self.mosaic_size.trace_add("write", self._refresh_effect_preview)
        self.compare_split.trace_add("write", lambda *_args: self._render_image())

        self.after(100, self._draw_empty_state)
        self.after(400, self._offer_recovery)
        self.after(30000, self._autosave_tick)

    # --------------------------- Presets ---------------------------
    def _default_presets(self) -> dict[str, dict[str, object]]:
        return {
            "Strong blur": {"action": "Blur", "blur_radius": 18.0},
            "Strong pixelate": {"action": "Pixelate", "pixel_size": 32},
            "Manga mosaic": {"action": "Mosaic", "mosaic_size": 20},
            "Clean enhance": {"action": "Auto Enhance"},
            "Cinematic look": {"action": "Cinematic Look", "brightness": 4, "contrast": 16, "saturation": -4, "sharpness": 12, "creative_strength": 32},
        }

    def _all_presets(self) -> dict[str, dict[str, object]]:
        presets = self._default_presets().copy()
        presets.update(self.user_presets)
        return presets

    def _load_presets(self) -> None:
        self.user_presets = {}
        try:
            if self.presets_path.exists():
                payload = json.loads(self.presets_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("user_presets"), dict):
                    self.user_presets = payload["user_presets"]
        except Exception:
            self.user_presets = {}

    def _save_presets(self) -> None:
        try:
            self.presets_path.write_text(json.dumps({"user_presets": self.user_presets}, indent=2), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save presets.\n\n{exc}")

    def _preset_snapshot(self) -> dict[str, object]:
        return {
            "action": self.preset_action.get(),
            "brightness": int(self.brightness.get()),
            "contrast": int(self.contrast.get()),
            "saturation": int(self.saturation.get()),
            "sharpness": int(self.sharpness.get()),
            "blur_radius": float(self.blur_radius.get()),
            "pixel_size": int(self.pixel_size.get()),
            "mosaic_size": int(self.mosaic_size.get()),
            "creative_strength": int(self.creative_strength.get()),
        }

    def _refresh_preset_combobox(self) -> None:
        if hasattr(self, "preset_combo"):
            names = tuple(self._all_presets().keys())
            self.preset_combo.configure(values=names)
            if names and self.preset_choice.get() not in names:
                self.preset_choice.set(names[0])

    def _load_preset_into_controls(self, preset: dict[str, object]) -> None:
        self.preset_action.set(str(preset.get("action", "Adjustments")))
        self.brightness.set(int(preset.get("brightness", self.brightness.get())))
        self.contrast.set(int(preset.get("contrast", self.contrast.get())))
        self.saturation.set(int(preset.get("saturation", self.saturation.get())))
        self.sharpness.set(int(preset.get("sharpness", self.sharpness.get())))
        self.blur_radius.set(float(preset.get("blur_radius", self.blur_radius.get())))
        self.pixel_size.set(int(preset.get("pixel_size", self.pixel_size.get())))
        self.mosaic_size.set(int(preset.get("mosaic_size", self.mosaic_size.get())))
        self.creative_strength.set(int(preset.get("creative_strength", self.creative_strength.get())))

    def load_selected_preset(self) -> None:
        name = self.preset_choice.get()
        preset = self._all_presets().get(name)
        if not preset:
            messagebox.showinfo(APP_NAME, "Choose a preset first.")
            return
        self._load_preset_into_controls(preset)
        self._set_status(f"Loaded preset: {name}")

    def save_current_preset(self) -> None:
        name = simpledialog.askstring(APP_NAME, "Save current settings as preset", parent=self)
        if not name:
            return
        clean_name = name.strip()
        if not clean_name:
            return
        if clean_name in self._default_presets():
            messagebox.showinfo(APP_NAME, "That name is reserved for a built-in preset. Choose a different name.")
            return
        self.user_presets[clean_name] = self._preset_snapshot()
        self._save_presets()
        self._refresh_preset_combobox()
        self.preset_choice.set(clean_name)
        self._set_status(f"Saved preset: {clean_name}")

    def delete_selected_preset(self) -> None:
        name = self.preset_choice.get()
        if name in self._default_presets():
            messagebox.showinfo(APP_NAME, "Built-in presets cannot be deleted.")
            return
        if name not in self.user_presets:
            messagebox.showinfo(APP_NAME, "Choose a saved preset first.")
            return
        if not messagebox.askyesno(APP_NAME, f"Delete preset '{name}'?"):
            return
        del self.user_presets[name]
        self._save_presets()
        self._refresh_preset_combobox()
        self._set_status(f"Deleted preset: {name}")

    def apply_selected_preset(self) -> None:
        if self.image is None:
            return
        name = self.preset_choice.get()
        preset = self._all_presets().get(name)
        if not preset:
            messagebox.showinfo(APP_NAME, "Choose a preset first.")
            return
        self.cancel_preview(render=False)
        result = self._apply_preset_to_image(self.image.copy(), preset)
        self._load_preset_into_controls(preset)
        self._commit_edit(result, f"Applied preset: {name}")

    def batch_process_images(self) -> None:
        preset = self._all_presets().get(self.preset_choice.get())
        if not preset:
            messagebox.showinfo(APP_NAME, "Choose a preset first.")
            return
        filenames = filedialog.askopenfilenames(title="Choose images for batch processing", filetypes=SUPPORTED_OPEN)
        if not filenames:
            return
        output_dir = filedialog.askdirectory(title="Choose output folder")
        if not output_dir:
            return
        out_path = Path(output_dir)
        success = 0
        failures: list[str] = []
        total = len(filenames)
        for index, filename in enumerate(filenames, start=1):
            path = Path(filename)
            try:
                self._set_status(f"Batch {index}/{total}: {path.name}")
                src = self._read_image_file(path)
                out = self._apply_preset_to_image(src, preset)
                target = out_path / f"{path.stem}_qfx{path.suffix}"
                self._save_image_object(out, target)
                success += 1
            except Exception as exc:
                failures.append(f"{path.name}: {exc}")
        self._set_status(f"Batch finished: {success}/{total} saved")
        details = "\n".join(failures[:12])
        if failures:
            messagebox.showwarning(APP_NAME, f"Batch finished with {success} success and {len(failures)} failures.\n\n{details}")
        else:
            messagebox.showinfo(APP_NAME, f"Batch finished successfully. {success} image(s) saved to:\n{out_path}")

    # --------------------------- UI setup ---------------------------
    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background="#17191d")
        style.configure("Panel.TFrame", background="#202329")
        style.configure("Top.TFrame", background="#111318")
        style.configure(
            "TButton",
            background="#2b2f37",
            foreground="#f3f5f7",
            borderwidth=0,
            focusthickness=0,
            padding=(10, 7),
        )
        style.map(
            "TButton",
            background=[("active", "#3a404b"), ("disabled", "#24272d")],
            foreground=[("disabled", "#777c86")],
        )
        style.configure(
            "Accent.TButton",
            background="#5b7cfa",
            foreground="#ffffff",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#6f8bfd")])
        style.configure(
            "Danger.TButton",
            background="#743d48",
            foreground="#ffffff",
        )
        style.map("Danger.TButton", background=[("active", "#8a4a57")])
        style.configure(
            "Section.TLabel",
            background="#202329",
            foreground="#f4f5f7",
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background="#202329",
            foreground="#aeb4bf",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Status.TLabel",
            background="#111318",
            foreground="#aeb4bf",
            padding=(10, 4),
        )
        style.configure(
            "TScale",
            background="#202329",
            troughcolor="#343842",
        )
        style.configure("TSeparator", background="#333740")
        style.configure(
            "TCombobox",
            fieldbackground="#2b2f37",
            background="#2b2f37",
            foreground="#f3f5f7",
            arrowcolor="#f3f5f7",
            borderwidth=0,
            padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#2b2f37")],
            foreground=[("readonly", "#f3f5f7")],
            selectbackground=[("readonly", "#5b7cfa")],
            selectforeground=[("readonly", "#ffffff")],
        )
        style.configure("TNotebook", background="#202329", borderwidth=0, tabmargins=(8, 8, 8, 0))
        style.configure(
            "TNotebook.Tab",
            background="#2b2f37",
            foreground="#c5cad3",
            padding=(11, 8),
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#5b7cfa"), ("active", "#3a404b")],
            foreground=[("selected", "#ffffff")],
        )
        style.configure("Card.TFrame", background="#252931")
        style.configure("Card.TLabel", background="#252931", foreground="#f4f5f7", font=("Segoe UI", 10, "bold"))
        style.configure("CardMuted.TLabel", background="#252931", foreground="#aeb4bf", font=("Segoe UI", 9))
        style.configure("TRadiobutton", background="#202329", foreground="#e8ebef")
        style.map("TRadiobutton", background=[("active", "#202329")], foreground=[("disabled", "#777c86")])
        style.configure("TCheckbutton", background="#202329", foreground="#e8ebef")
        style.map("TCheckbutton", background=[("active", "#202329")], foreground=[("disabled", "#777c86")])

    def _build_ui(self) -> None:
        self._build_menu()

        root = ttk.Frame(self, style="App.TFrame")
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root, style="Top.TFrame")
        top.pack(fill="x")
        self._toolbar_button(top, "Open", self.open_image).pack(side="left", padx=(10, 4), pady=8)
        self._toolbar_button(top, "Paste", self.paste_image_from_clipboard).pack(side="left", padx=4, pady=8)
        self._toolbar_button(top, "Save", self.save_image).pack(side="left", padx=4, pady=8)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8, pady=9)
        self.undo_button = self._toolbar_button(top, "Undo", self.undo)
        self.undo_button.pack(side="left", padx=4, pady=8)
        self.redo_button = self._toolbar_button(top, "Redo", self.redo)
        self.redo_button.pack(side="left", padx=4, pady=8)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8, pady=9)
        self._toolbar_button(top, "Fit", self.fit_to_window).pack(side="left", padx=4, pady=8)
        ttk.Checkbutton(top, text="Before", variable=self.show_before, command=self._toggle_before_after).pack(side="left", padx=(8, 4), pady=8)
        ttk.Checkbutton(top, text="Compare", variable=self.compare_mode, command=self._render_image).pack(side="left", padx=4, pady=8)
        self.compare_scale = tk.Scale(top, variable=self.compare_split, from_=5, to=95, orient="horizontal", showvalue=False, length=120, bg="#111318", troughcolor="#343842", highlightthickness=0, bd=0)
        self.compare_scale.pack(side="left", padx=(0, 8), pady=8)
        ttk.Label(top, text="Hold B: original", style="Status.TLabel").pack(side="right", padx=(0, 4))
        ttk.Label(top, textvariable=self.zoom_text, style="Status.TLabel").pack(side="right", padx=8)

        body = ttk.Frame(root, style="App.TFrame")
        body.pack(fill="both", expand=True)

        sidebar_holder = ttk.Frame(body, style="Panel.TFrame", width=352)
        sidebar_holder.pack(side="left", fill="y")
        sidebar_holder.pack_propagate(False)

        sidebar = ttk.Frame(sidebar_holder, style="Panel.TFrame")
        sidebar.pack(fill="both", expand=True)
        self._build_sidebar(sidebar)

        canvas_wrap = ttk.Frame(body, style="App.TFrame")
        canvas_wrap.pack(side="left", fill="both", expand=True)

        self.document_notebook = ttk.Notebook(canvas_wrap)
        self.document_notebook.pack(fill="x", padx=6, pady=(6, 0))
        self.document_notebook.bind("<<NotebookTabChanged>>", self._on_document_tab_changed)

        self.canvas = tk.Canvas(
            canvas_wrap,
            bg="#13151a",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self._selection_start)
        self.canvas.bind("<B1-Motion>", self._selection_drag)
        self.canvas.bind("<ButtonRelease-1>", self._selection_end)
        self.canvas.bind("<MouseWheel>", self._mousewheel_zoom)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at_cursor(1.12, e.x, e.y))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at_cursor(1 / 1.12, e.x, e.y))
        self.canvas.bind("<Button-3>", lambda _e: self.clear_selection())

        status = ttk.Frame(root, style="Top.TFrame")
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_text, style="Status.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(status, text="Drop image files here • Ctrl+V pastes clipboard images", style="Status.TLabel").pack(side="right")

        self._update_button_states()

    def _build_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open…", command=self.open_image, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_image, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As…", command=self.save_image_as, accelerator="Ctrl+Shift+S")
        file_menu.add_command(label="Close Tab", command=self.close_current_document, accelerator="Ctrl+W")
        file_menu.add_separator()
        file_menu.add_command(label="Batch process…", command=self.batch_process_images)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Paste image from clipboard", command=self.paste_image_from_clipboard, accelerator="Ctrl+V")
        edit_menu.add_command(label="Show original / before", command=self.toggle_before_after, accelerator="B")
        edit_menu.add_separator()
        edit_menu.add_command(label="Clear selection", command=self.clear_selection, accelerator="Esc")
        edit_menu.add_command(label="Reset to original", command=self.reset_to_original)
        menu.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Fit to window", command=self.fit_to_window, accelerator="F")
        view_menu.add_command(label="Actual size (100%)", command=lambda: self.set_zoom(1.0), accelerator="1")
        view_menu.add_command(label="Zoom in", command=lambda: self.set_zoom(self.zoom * 1.2), accelerator="+")
        view_menu.add_command(label="Zoom out", command=lambda: self.set_zoom(self.zoom / 1.2), accelerator="-")
        menu.add_cascade(label="View", menu=view_menu)

        self.config(menu=menu)

    def _toolbar_button(self, parent: tk.Widget, text: str, command: Callable[[], None]) -> ttk.Button:
        return ttk.Button(parent, text=text, command=command)

    def _section(self, parent: tk.Widget, title: str) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.pack(fill="x", padx=14, pady=(14, 4))
        ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        return frame

    def _build_sidebar(self, parent: tk.Widget) -> None:
        header = ttk.Frame(parent, style="Panel.TFrame")
        header.pack(fill="x", padx=14, pady=(14, 6))
        ttk.Label(
            header,
            text="QUICKFX",
            background="#202329",
            foreground="#7e9aff",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left")
        ttk.Label(header, text="Simple mode", style="Muted.TLabel").pack(side="right", pady=(5, 0))

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.censor_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        self.annotate_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        self.adjust_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))
        self.transform_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=(10, 10))

        self.notebook.add(self.censor_tab, text="Censor")
        self.notebook.add(self.annotate_tab, text="Annotate")
        self.notebook.add(self.adjust_tab, text="Adjust")
        self.notebook.add(self.transform_tab, text="Transform")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_censor_tab()
        self._build_annotate_tab()
        self._build_adjust_tab()
        self._build_transform_tab()

    def _card(self, parent: tk.Widget, title: str, description: str = "") -> ttk.Frame:
        card = ttk.Frame(parent, style="Panel.TFrame")
        card.pack(fill="x", pady=(0, 12))
        ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        if description:
            ttk.Label(
                card,
                text=description,
                wraplength=305,
                justify="left",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(0, 8))
        return card

    def _tool_grid(self, parent: tk.Widget, tools: tuple[tuple[str, str], ...]) -> None:
        grid = ttk.Frame(parent, style="Panel.TFrame")
        grid.pack(fill="x")
        for index, (label, value) in enumerate(tools):
            row, column = divmod(index, 2)
            button = tk.Radiobutton(
                grid,
                text=label,
                variable=self.draw_mode,
                value=value,
                indicatoron=False,
                bg="#2b2f37",
                fg="#f3f5f7",
                selectcolor="#5b7cfa",
                activebackground="#3a404b",
                activeforeground="#ffffff",
                disabledforeground="#777c86",
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=6,
                pady=9,
                font=("Segoe UI", 9, "bold"),
            )
            button.grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 4, 4 if column == 0 else 0), pady=3)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

    def _build_censor_tab(self) -> None:
        tools = self._card(self.censor_tab, "Choose a tool", "Pick one tool, then use only the options shown below.")
        self._tool_grid(
            tools,
            (
                ("Select area", "selection"),
                ("Lasso area", "lasso"),
                ("Protect faces", "face"),
                ("Blur brush", "blur_brush"),
                ("Pixel brush", "pixel_brush"),
                ("Mosaic brush", "mosaic_brush"),
                ("Black brush", "black_brush"),
                ("Clone", "clone"),
                ("Heal", "heal"),
            ),
        )

        ttk.Separator(self.censor_tab).pack(fill="x", pady=(0, 10))
        ttk.Label(self.censor_tab, text="Tool options", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        self.censor_options_frame = ttk.Frame(self.censor_tab, style="Panel.TFrame")
        self.censor_options_frame.pack(fill="both", expand=True)

    def _build_annotate_tab(self) -> None:
        tools = self._card(self.annotate_tab, "Choose a tool", "Click or drag directly on the image.")
        self._tool_grid(
            tools,
            (
                ("Text", "text"),
                ("Sticker", "sticker"),
                ("Arrow", "arrow"),
                ("Box", "box"),
            ),
        )

        ttk.Separator(self.annotate_tab).pack(fill="x", pady=(0, 10))
        ttk.Label(self.annotate_tab, text="Tool options", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        self.annotate_options_frame = ttk.Frame(self.annotate_tab, style="Panel.TFrame")
        self.annotate_options_frame.pack(fill="both", expand=True)

    def _build_adjust_tab(self) -> None:
        adjust = self._card(self.adjust_tab, "Image adjustments", "A selection limits the edit. Without one, the whole image changes.")
        self._slider(adjust, "Brightness", self.brightness, -100, 100, resolution=1)
        self._slider(adjust, "Contrast", self.contrast, -100, 100, resolution=1)
        self._slider(adjust, "Saturation", self.saturation, -100, 100, resolution=1)
        self._slider(adjust, "Sharpness", self.sharpness, -100, 200, resolution=1)
        row = ttk.Frame(adjust, style="Panel.TFrame")
        row.pack(fill="x", pady=(2, 0))
        ttk.Button(row, text="Apply", command=self.apply_adjustments, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="Reset sliders", command=self.reset_adjustment_sliders).pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(adjust, text="Auto Enhance", command=self.auto_enhance).pack(fill="x", pady=(8, 0))

        creative = self._card(self.adjust_tab, "Creative effects")
        self._slider(creative, "Strength", self.creative_strength, 5, 100, resolution=1)
        grid = ttk.Frame(creative, style="Panel.TFrame")
        grid.pack(fill="x")
        actions = (
            ("Vignette", self.apply_vignette),
            ("Glow", self.apply_glow),
            ("Posterize", self.apply_posterize),
            ("Sketch", self.apply_sketch),
        )
        for index, (label, command) in enumerate(actions):
            row_index, column = divmod(index, 2)
            ttk.Button(grid, text=label, command=command).grid(
                row=row_index,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 4, 4 if column == 0 else 0),
                pady=4,
            )
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        filters = self._card(self.adjust_tab, "Quick filters")
        row = ttk.Frame(filters, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Grayscale", command=self.grayscale).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="Invert", command=self.invert_colors).pack(side="left", fill="x", expand=True, padx=(4, 0))

        presets = self._card(self.adjust_tab, "Presets and batch", "Load a preset into the controls, apply it to the current image, or run it on many images at once.")
        ttk.Label(presets, text="Preset", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        self.preset_combo = ttk.Combobox(presets, textvariable=self.preset_choice, state="readonly")
        self.preset_combo.pack(fill="x", pady=(0, 8))
        self._refresh_preset_combobox()
        ttk.Label(presets, text="Preset action", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        ttk.Combobox(presets, textvariable=self.preset_action, values=PRESET_ACTIONS, state="readonly").pack(fill="x", pady=(0, 8))
        row = ttk.Frame(presets, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Load", command=self.load_selected_preset).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="Apply", command=self.apply_selected_preset, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Save Current", command=self.save_current_preset).pack(side="left", fill="x", expand=True, padx=(4, 0))
        row2 = ttk.Frame(presets, style="Panel.TFrame")
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text="Delete Preset", command=self.delete_selected_preset).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row2, text="Batch Process…", command=self.batch_process_images, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_transform_tab(self) -> None:
        transform = self._card(self.transform_tab, "Rotate and flip")
        grid = ttk.Frame(transform, style="Panel.TFrame")
        grid.pack(fill="x")
        ttk.Button(grid, text="Rotate left", command=lambda: self.rotate(90)).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(grid, text="Rotate right", command=lambda: self.rotate(-90)).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=4)
        ttk.Button(grid, text="Flip horizontal", command=self.flip_horizontal).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=4)
        ttk.Button(grid, text="Flip vertical", command=self.flip_vertical).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=4)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        ttk.Button(transform, text="Resize image…", command=self.resize_image, style="Accent.TButton").pack(fill="x", pady=(8, 0))

        crop = self._card(self.transform_tab, "Crop", "Choose the area first, then crop.")
        row = ttk.Frame(crop, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Button(row, text="Select crop area", command=lambda: self.draw_mode.set("selection")).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(row, text="Crop now", command=self.crop_to_selection, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(crop, text="Clear selection", command=self.clear_selection).pack(fill="x", pady=(8, 0))

        bars = self._card(self.transform_tab, "Cinematic bars")
        ttk.Button(bars, text="Add top and bottom bars…", command=self.add_cinematic_bars).pack(fill="x")

        reset = self._card(self.transform_tab, "Reset")
        ttk.Button(reset, text="Reset to original image", command=self.reset_to_original, style="Danger.TButton").pack(fill="x")

    def _on_tab_changed(self, _event: Optional[tk.Event] = None) -> None:
        selected = self.notebook.select()
        if not selected:
            return
        widget = self.nametowidget(selected)
        mode = self.draw_mode.get()
        censor_modes = {"selection", "lasso", "face", "blur_brush", "pixel_brush", "mosaic_brush", "black_brush", "clone", "heal"}
        annotate_modes = {"text", "sticker", "arrow", "box"}
        if widget == self.censor_tab and mode not in censor_modes:
            self.draw_mode.set("selection")
        elif widget == self.annotate_tab and mode not in annotate_modes:
            self.draw_mode.set("text")
        elif widget in {self.adjust_tab, self.transform_tab} and mode not in {"selection", "face"}:
            self.draw_mode.set("selection")

    def _on_tool_changed(self, *_args: object) -> None:
        self.cancel_preview()
        self.shape_preview = None
        self.tool_start_image = None
        self.tool_end_image = None
        self.brush_before = None
        self.brush_source = None
        self.brush_last = None
        self._refresh_tool_options()
        mode = self.draw_mode.get()
        cursor = "crosshair"
        if mode in {"text", "sticker"}:
            cursor = "hand2"
        elif mode in {"blur_brush", "pixel_brush", "mosaic_brush", "black_brush", "clone", "heal"}:
            cursor = "pencil"
        if hasattr(self, "canvas"):
            self.canvas.configure(cursor=cursor)

    def _on_area_effect_changed(self, *_args: object) -> None:
        self.cancel_preview()
        if self.draw_mode.get() in {"selection", "lasso", "face"}:
            self._refresh_tool_options()

    def _apply_selected_area_effect(self) -> None:
        effect = self.area_effect.get()
        if effect == "Blur":
            self.apply_blur()
        elif effect == "Pixelate":
            self.apply_pixelate()
        elif effect == "Mosaic":
            self.apply_mosaic()
        else:
            self.add_black_bar_to_selection()

    def _apply_selected_outside_effect(self) -> None:
        effect = self.area_effect.get()
        if effect == "Blur":
            self.blur_outside_faces()
        elif effect == "Pixelate":
            self.pixelate_outside_faces()
        elif effect == "Mosaic":
            self.mosaic_outside_faces()
        else:
            self.blackout_outside_faces()

    @staticmethod
    def _clear_children(frame: tk.Widget) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _refresh_tool_options(self) -> None:
        if not hasattr(self, "censor_options_frame") or not hasattr(self, "annotate_options_frame"):
            return
        self._clear_children(self.censor_options_frame)
        self._clear_children(self.annotate_options_frame)
        mode = self.draw_mode.get()
        self._build_censor_options(mode)
        self._build_annotate_options(mode)

    def _hint(self, parent: tk.Widget, text: str) -> None:
        ttk.Label(parent, text=text, wraplength=305, justify="left", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))

    def _build_effect_preview_controls(self, frame: tk.Widget, outside_faces: bool = False) -> None:
        ttk.Label(frame, text="Outside effect" if outside_faces else "Effect", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        ttk.Combobox(
            frame,
            textvariable=self.area_effect,
            state="readonly",
            values=("Blur", "Pixelate", "Mosaic", "Black"),
        ).pack(fill="x", pady=(0, 10))
        effect = self.area_effect.get()
        if effect == "Blur":
            self._slider(frame, "Blur radius", self.blur_radius, 0.5, 50, resolution=0.5)
        elif effect == "Pixelate":
            self._slider(frame, "Pixel block size", self.pixel_size, 2, 100, resolution=1)
        elif effect == "Mosaic":
            self._slider(frame, "Mosaic tile size", self.mosaic_size, 4, 120, resolution=1)
        else:
            self._hint(frame, "Black preview is fully reversible until you press Apply.")
        preview = ttk.Frame(frame, style="Panel.TFrame")
        preview.pack(fill="x", pady=(2, 0))
        ttk.Button(preview, text="Preview", command=self.preview_selected_effect).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(preview, text="Apply", command=self.apply_effect_preview, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(preview, text="Cancel", command=self.cancel_preview).pack(side="left", fill="x", expand=True, padx=(3, 0))
        self._hint(frame, "After Preview, move the size slider freely. The masks stay in place after Apply and Undo.")

    def _build_censor_options(self, mode: str) -> None:
        frame = self.censor_options_frame
        if mode in {"selection", "lasso"}:
            if mode == "selection":
                self._hint(frame, "Drag a rectangle. Drag inside it to move it, or drag a corner handle to resize it.")
                row = ttk.Frame(frame, style="Panel.TFrame")
                row.pack(fill="x", pady=(0, 8))
                ttk.Button(row, text="Crop", command=self.crop_to_selection).pack(side="left", fill="x", expand=True, padx=(0, 4))
                ttk.Button(row, text="Clear", command=self.clear_selection).pack(side="left", fill="x", expand=True, padx=(4, 0))
            else:
                self._hint(frame, "Draw a freehand shape around the area. Effects stay inside the lasso.")
                row = ttk.Frame(frame, style="Panel.TFrame")
                row.pack(fill="x", pady=(0, 8))
                ttk.Button(row, text="Crop Lasso", command=self.crop_to_selection).pack(side="left", fill="x", expand=True, padx=(0, 4))
                ttk.Button(row, text="Clear Lasso", command=self.clear_selection).pack(side="left", fill="x", expand=True, padx=(4, 0))
            self._build_effect_preview_controls(frame, outside_faces=False)
            return

        if mode == "face":
            self._hint(frame, "Draw circles around the faces to keep visible. Click or drag an existing circle to select and move it; use its corner handles to resize.")
            ttk.Button(frame, text="Clear face circles", command=self.clear_focus_zones).pack(fill="x", pady=(0, 8))
            if self.focus_zones:
                ttk.Label(frame, text="Face masks", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
                self.face_listbox = tk.Listbox(frame, height=min(5, max(2, len(self.focus_zones))), exportselection=False, bg="#15181d", fg="#f3f5f7", selectbackground="#5b7cfa", relief="flat")
                self.face_listbox.pack(fill="x", pady=(0, 6))
                for idx, zone in enumerate(self.focus_zones, start=1):
                    self.face_listbox.insert("end", f"Face {idx}: {zone.width}×{zone.height}")
                if self.selected_face_index is None:
                    self.selected_face_index = 0
                if 0 <= self.selected_face_index < len(self.focus_zones):
                    self.face_listbox.selection_set(self.selected_face_index)
                    self.face_listbox.activate(self.selected_face_index)
                self.face_listbox.bind("<<ListboxSelect>>", self._on_face_list_select)
                actions = ttk.Frame(frame, style="Panel.TFrame")
                actions.pack(fill="x", pady=(0, 8))
                ttk.Button(actions, text="Duplicate", command=self.duplicate_selected_face).pack(side="left", fill="x", expand=True, padx=(0, 4))
                ttk.Button(actions, text="Delete", command=self.delete_selected_face).pack(side="left", fill="x", expand=True, padx=(4, 0))
            self._build_effect_preview_controls(frame, outside_faces=True)
            return

        if mode in {"blur_brush", "pixel_brush", "mosaic_brush", "black_brush"}:
            names = {
                "blur_brush": "Blur brush",
                "pixel_brush": "Pixel brush",
                "mosaic_brush": "Mosaic brush",
                "black_brush": "Black brush",
            }
            self._hint(frame, f"{names[mode]} is active. Paint directly on the image; each stroke is one undo step.")
            self._slider(frame, "Brush size", self.brush_size, 5, 400, resolution=1)
            if mode == "blur_brush":
                self._slider(frame, "Blur radius", self.blur_radius, 0.5, 50, resolution=0.5)
            elif mode == "pixel_brush":
                self._slider(frame, "Pixel block size", self.pixel_size, 2, 100, resolution=1)
            elif mode == "mosaic_brush":
                self._slider(frame, "Mosaic tile size", self.mosaic_size, 4, 120, resolution=1)
            return

        if mode in {"clone", "heal"}:
            label = "Clone" if mode == "clone" else "Heal"
            self._hint(frame, f"{label}: click once to set the source, then click and drag where you want to paint.")
            self._slider(frame, "Brush size", self.brush_size, 5, 400, resolution=1)
            ttk.Button(frame, text="Reset source point", command=self.reset_clone_source).pack(fill="x", pady=(4, 0))
            return

        self._hint(frame, "Choose a censor tool above.")

    def _build_annotate_options(self, mode: str) -> None:
        frame = self.annotate_options_frame
        if mode == "text":
            self._hint(frame, "Click the image where the text should begin. A small dialog will ask for the text, size, color, and shadow.")
            ttk.Label(frame, text="Tip: multiline text is supported.", style="Muted.TLabel").pack(anchor="w")
            return

        if mode == "sticker":
            self._hint(frame, "Choose a sticker, set its size, then click the image to place it.")
            ttk.Label(frame, text="Sticker", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
            ttk.Combobox(
                frame,
                textvariable=self.sticker_choice,
                state="readonly",
                values=("😀", "😎", "😂", "❤️", "⭐", "🔥", "❗", "✅", "❌", "💥", "👀", "🔒"),
            ).pack(fill="x", pady=(0, 8))
            self._slider(frame, "Sticker size", self.sticker_size, 24, 400, resolution=1)
            return

        if mode in {"arrow", "box"}:
            action = "Drag from the start to the arrow tip." if mode == "arrow" else "Drag around the area you want to outline."
            self._hint(frame, action)
            self._slider(frame, "Line width", self.shape_width, 1, 40, resolution=1)
            row = ttk.Frame(frame, style="Panel.TFrame")
            row.pack(fill="x")
            ttk.Button(row, text="Choose color", command=self.choose_shape_color).pack(side="left", fill="x", expand=True)
            ttk.Label(row, textvariable=self.shape_color, style="Muted.TLabel").pack(side="right", padx=(10, 0))
            return

        self._hint(frame, "Choose an annotation tool above.")

    def _slider(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.Variable,
        from_: float,
        to: float,
        resolution: float,
    ) -> None:
        line = ttk.Frame(parent, style="Panel.TFrame")
        line.pack(fill="x", pady=(0, 2))
        ttk.Label(line, text=label, style="Muted.TLabel").pack(side="left")
        value_label = ttk.Label(line, textvariable=variable, style="Muted.TLabel")
        value_label.pack(side="right")
        scale = tk.Scale(
            parent,
            variable=variable,
            from_=from_,
            to=to,
            resolution=resolution,
            orient="horizontal",
            showvalue=False,
            bg="#202329",
            fg="#e8ebef",
            troughcolor="#353a44",
            activebackground="#7e9aff",
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
            length=300,
        )
        scale.pack(fill="x", pady=(0, 7))

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-o>", lambda _e: self.open_image())
        self.bind_all("<Control-s>", lambda _e: self.save_image())
        self.bind_all("<Control-Shift-S>", lambda _e: self.save_image_as())
        self.bind_all("<Control-w>", lambda _e: self.close_current_document())
        self.bind_all("<Control-v>", self._paste_shortcut)
        self.bind_all("<Control-z>", lambda _e: self.undo())
        self.bind_all("<Control-y>", lambda _e: self.redo())
        self.bind_all("<Control-Shift-Z>", lambda _e: self.redo())
        self.bind_all("<Escape>", lambda _e: self.clear_selection())
        self.bind_all("<Key-f>", lambda _e: self.fit_to_window())
        self.bind_all("<Key-1>", lambda _e: self.set_zoom(1.0))
        self.bind_all("<plus>", lambda _e: self.set_zoom(self.zoom * 1.2))
        self.bind_all("<equal>", lambda _e: self.set_zoom(self.zoom * 1.2))
        self.bind_all("<minus>", lambda _e: self.set_zoom(self.zoom / 1.2))
        self.bind_all("<Delete>", lambda _e: self.clear_selection())
        self.bind_all("<BackSpace>", lambda _e: self.clear_focus_zones())
        self.bind_all("<KeyPress-b>", self._before_key_press)
        self.bind_all("<KeyRelease-b>", self._before_key_release)

    def _paste_shortcut(self, event: tk.Event) -> Optional[str]:
        widget_class = event.widget.winfo_class() if event.widget else ""
        if widget_class in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox"}:
            return None
        self.paste_image_from_clipboard()
        return "break"

    def _toggle_before_after(self) -> None:
        self._render_image()
        self._set_status("Showing original image" if self.show_before.get() else "Showing edited image")

    def toggle_before_after(self) -> None:
        self.show_before.set(not self.show_before.get())
        self._toggle_before_after()

    def _before_key_press(self, event: tk.Event) -> None:
        widget_class = event.widget.winfo_class() if event.widget else ""
        if widget_class in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox"}:
            return
        self.before_hold_previous = bool(self.show_before.get())
        if not self.show_before.get():
            self.show_before.set(True)
            self._toggle_before_after()

    def _before_key_release(self, event: tk.Event) -> None:
        widget_class = event.widget.winfo_class() if event.widget else ""
        if widget_class in {"Entry", "TEntry", "Text", "TCombobox", "Spinbox"}:
            return
        if bool(self.show_before.get()) != self.before_hold_previous:
            self.show_before.set(self.before_hold_previous)
            self._toggle_before_after()

    def _setup_drag_and_drop(self) -> None:
        if not DND_AVAILABLE or DND_FILES is None:
            self.after(250, lambda: self._set_status("Open or paste an image to begin • drag-and-drop dependency unavailable"))
            return
        for widget in (self, self.canvas):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
                widget.dnd_bind("<<Drop>>", self._on_file_drop)
            except (tk.TclError, AttributeError):
                continue

    def _on_drop_enter(self, event: tk.Event) -> str:
        self.canvas.configure(bg="#1d2330")
        self._set_status("Release to open the dropped image")
        return getattr(event, "action", "copy")

    def _on_drop_leave(self, event: tk.Event) -> str:
        self.canvas.configure(bg="#13151a")
        if self.image is None:
            self._set_status("Drop an image, paste with Ctrl+V, or open a file")
        return getattr(event, "action", "copy")

    def _on_file_drop(self, event: tk.Event) -> str:
        self.canvas.configure(bg="#13151a")
        raw_items = self.tk.splitlist(getattr(event, "data", ""))
        paths = [self._normalize_dropped_path(item) for item in raw_items]
        candidates = [path for path in paths if path is not None and path.is_file()]
        if not candidates:
            messagebox.showinfo(APP_NAME, "Drop an image file such as PNG, JPEG, WebP, BMP, TIFF, or GIF.")
            return getattr(event, "action", "copy")

        loaded = False
        last_error: Optional[Exception] = None
        for path in candidates:
            try:
                image = self._read_image_file(path)
            except Exception as exc:
                last_error = exc
                continue
            self._load_new_image(image, path, f"Dropped {path.name}")
            loaded = True

        if not loaded:
            details = f"\n\n{last_error}" if last_error else ""
            messagebox.showerror(APP_NAME, f"None of the dropped files could be opened as an image.{details}")
        return getattr(event, "action", "copy")

    @staticmethod
    def _normalize_dropped_path(raw: str) -> Optional[Path]:
        value = raw.strip().strip("{}")
        if not value:
            return None
        if value.lower().startswith("file:"):
            parsed = urlparse(value)
            value = unquote(parsed.path)
            if os.name == "nt" and value.startswith("/") and len(value) > 2 and value[2] == ":":
                value = value[1:]
        return Path(value)

    # --------------------------- Documents and recovery ---------------------------
    def _document_label(self, document: DocumentState) -> str:
        name = document.current_path.name if document.current_path else "Untitled"
        return f"{name}{' *' if document.dirty else ''}"

    def _sync_active_document(self) -> None:
        if self.active_document_id is None or self.image is None or self.original_image is None:
            return
        document = self.documents.get(self.active_document_id)
        if document is None:
            return
        document.image = self.image
        document.original_image = self.original_image
        document.current_path = self.current_path
        document.dirty = self.dirty
        document.undo_stack = self.undo_stack
        document.redo_stack = self.redo_stack
        document.selection = self.selection.copy() if self.selection is not None else None
        document.focus_zones = [zone.copy() for zone in self.focus_zones]
        document.lasso_points = list(self.lasso_points)
        document.zoom = self.zoom
        frame = self.document_tab_frames.get(document.document_id)
        if frame is not None:
            self.document_notebook.tab(frame, text=self._document_label(document))

    def _activate_document(self, document_id: str) -> None:
        document = self.documents.get(document_id)
        if document is None:
            return
        self._switching_documents = True
        try:
            self.active_document_id = document_id
            self.image = document.image
            self.original_image = document.original_image
            self.current_path = document.current_path
            self.dirty = document.dirty
            self.undo_stack = document.undo_stack
            self.redo_stack = document.redo_stack
            self.selection = document.selection.copy() if document.selection is not None else None
            self.focus_zones = [zone.copy() for zone in document.focus_zones]
            self.lasso_points = list(document.lasso_points)
            self.selected_face_index = 0 if self.focus_zones else None
            self.zoom = document.zoom
            self.preview_image = None
            self.focus_preview = None
            self.lasso_preview = []
            self.shape_preview = None
            self.show_before.set(False)
            self.compare_mode.set(False)
            self._render_image()
            self._refresh_tool_options()
            self._update_title()
            self._update_button_states()
        finally:
            self._switching_documents = False

    def _create_document(
        self,
        image: Image.Image,
        path: Optional[Path],
        status: str,
        *,
        original_image: Optional[Image.Image] = None,
        dirty: bool = False,
        selection: Optional[Selection] = None,
        focus_zones: Optional[list[Selection]] = None,
        lasso_points: Optional[list[tuple[int, int]]] = None,
    ) -> None:
        self._sync_active_document()
        document_id = uuid.uuid4().hex
        rgba = image.convert("RGBA")
        document = DocumentState(
            document_id=document_id,
            image=rgba,
            original_image=(original_image or rgba).convert("RGBA").copy(),
            current_path=path,
            dirty=dirty,
            undo_stack=[],
            redo_stack=[],
            selection=selection.copy() if selection is not None else None,
            focus_zones=[zone.copy() for zone in (focus_zones or [])],
            lasso_points=list(lasso_points or []),
            zoom=1.0,
        )
        self.documents[document_id] = document
        frame = ttk.Frame(self.document_notebook)
        self.document_tab_frames[document_id] = frame
        self.tab_to_document[str(frame)] = document_id
        self.document_notebook.add(frame, text=self._document_label(document))
        self.document_notebook.select(frame)
        self._activate_document(document_id)
        self.fit_to_window()
        self._set_status(status)

    def _on_document_tab_changed(self, _event: Optional[tk.Event] = None) -> None:
        if self._switching_documents:
            return
        selected = self.document_notebook.select()
        if not selected:
            return
        document_id = self.tab_to_document.get(selected)
        if document_id is None or document_id == self.active_document_id:
            return
        self._sync_active_document()
        self._activate_document(document_id)

    def close_current_document(self) -> None:
        if self.active_document_id is None:
            return
        self._sync_active_document()
        document = self.documents.get(self.active_document_id)
        if document is None:
            return
        if document.dirty and not messagebox.askyesno(APP_NAME, f"Close '{self._document_label(document)}' without saving?"):
            return
        frame = self.document_tab_frames.pop(document.document_id, None)
        if frame is not None:
            self.tab_to_document.pop(str(frame), None)
            self.document_notebook.forget(frame)
        del self.documents[document.document_id]
        self.active_document_id = None
        if self.documents:
            selected = self.document_notebook.select()
            document_id = self.tab_to_document.get(selected)
            if document_id:
                self._activate_document(document_id)
        else:
            self.image = None
            self.original_image = None
            self.current_path = None
            self.undo_stack = []
            self.redo_stack = []
            self.selection = None
            self.focus_zones = []
            self.lasso_points = []
            self._draw_empty_state()
            self._update_title()
            self._update_button_states()

    def _autosave_tick(self) -> None:
        try:
            self._write_recovery()
        finally:
            self.after(30000, self._autosave_tick)

    def _write_recovery(self) -> None:
        self._sync_active_document()
        dirty_documents = [document for document in self.documents.values() if document.dirty]
        if not dirty_documents:
            self._clear_recovery()
            return
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, object]] = []
        for document in dirty_documents:
            image_name = f"{document.document_id}.png"
            original_name = f"{document.document_id}_original.png"
            document.image.save(self.recovery_dir / image_name, optimize=True)
            document.original_image.save(self.recovery_dir / original_name, optimize=True)
            manifest.append({
                "image": image_name,
                "original": original_name,
                "path": str(document.current_path) if document.current_path else "",
                "selection": document.selection.box if document.selection else None,
                "focus_zones": [zone.box for zone in document.focus_zones],
                "lasso_points": document.lasso_points,
            })
        (self.recovery_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _offer_recovery(self) -> None:
        manifest_path = self.recovery_dir / "manifest.json"
        if not manifest_path.exists() or self.documents:
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            self._clear_recovery()
            return
        if not isinstance(manifest, list) or not manifest:
            self._clear_recovery()
            return
        if not messagebox.askyesno(APP_NAME, f"QuickFX found {len(manifest)} autosaved image(s) from an interrupted session. Restore them?"):
            self._clear_recovery()
            return
        restored = 0
        for item in manifest:
            try:
                image = self._read_image_file(self.recovery_dir / str(item["image"]))
                original = self._read_image_file(self.recovery_dir / str(item["original"]))
                path_value = str(item.get("path", ""))
                path = Path(path_value) if path_value else None
                selection_data = item.get("selection")
                selection = Selection(*selection_data) if isinstance(selection_data, list) and len(selection_data) == 4 else None
                focus_zones = [Selection(*box) for box in item.get("focus_zones", []) if isinstance(box, list) and len(box) == 4]
                lasso_points = [tuple(point) for point in item.get("lasso_points", []) if isinstance(point, list) and len(point) == 2]
                self._create_document(image, path, "Restored autosaved image", original_image=original, dirty=True, selection=selection, focus_zones=focus_zones, lasso_points=lasso_points)
                restored += 1
            except Exception:
                continue
        if restored:
            self._set_status(f"Restored {restored} autosaved image(s)")

    def _clear_recovery(self) -> None:
        if not self.recovery_dir.exists():
            return
        for path in self.recovery_dir.glob("*"):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            self.recovery_dir.rmdir()
        except OSError:
            pass

    # --------------------------- File handling ---------------------------
    def open_image(self) -> None:
        filename = filedialog.askopenfilename(title="Open image", filetypes=SUPPORTED_OPEN)
        if not filename:
            return
        path = Path(filename)
        try:
            image = self._read_image_file(path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open the image.\n\n{exc}")
            return
        self._load_new_image(image, path, f"Opened {path.name}")

    def paste_image_from_clipboard(self) -> None:
        try:
            clipboard_data = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not read the clipboard.\n\n{exc}")
            return

        if isinstance(clipboard_data, Image.Image):
            image = ImageOps.exif_transpose(clipboard_data).convert("RGBA")
            image.load()
            self._load_new_image(image, None, "Pasted image from clipboard")
            return

        candidates: list[Path] = []
        if isinstance(clipboard_data, list):
            candidates.extend(Path(item) for item in clipboard_data if isinstance(item, str))
        else:
            try:
                text_data = self.clipboard_get().strip()
            except tk.TclError:
                text_data = ""
            if text_data:
                for item in text_data.splitlines():
                    path = self._normalize_dropped_path(item.strip().strip('"'))
                    if path is not None:
                        candidates.append(path)

        candidates = [path for path in candidates if path.is_file()]
        if not candidates:
            messagebox.showinfo(
                APP_NAME,
                "The clipboard does not contain an image or a copied image file.\n\n"
                "Copy an image from a browser or image program, or copy an image file in File Explorer, then press Ctrl+V.",
            )
            return

        last_error: Optional[Exception] = None
        for path in candidates:
            try:
                image = self._read_image_file(path)
            except Exception as exc:
                last_error = exc
                continue
            self._load_new_image(image, path, f"Pasted {path.name} from clipboard")
            return
        details = f"\n\n{last_error}" if last_error else ""
        messagebox.showerror(APP_NAME, f"The copied file could not be opened as an image.{details}")

    @staticmethod
    def _read_image_file(path: Path) -> Image.Image:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
            image.load()
        return image

    def _load_new_image(self, image: Image.Image, path: Optional[Path], status: str) -> None:
        self.reset_adjustment_sliders()
        self._create_document(image, path, status)

    def save_image(self) -> None:
        if self.image is None:
            return
        if self.current_path is None:
            self.save_image_as()
            return
        self._save_to_path(self.current_path)

    def save_image_as(self) -> None:
        if self.image is None:
            return
        initial = self.current_path.stem if self.current_path else "edited_image"
        filename = filedialog.asksaveasfilename(
            title="Save image as",
            initialfile=initial,
            defaultextension=".png",
            filetypes=SUPPORTED_SAVE,
        )
        if filename:
            self._save_to_path(Path(filename))

    def _save_image_object(self, image: Image.Image, path: Path) -> None:
        suffix = path.suffix.lower()
        output = image
        save_kwargs: dict[str, object] = {}
        if suffix in {".jpg", ".jpeg"}:
            background = Image.new("RGB", output.size, "white")
            if output.mode == "RGBA":
                background.paste(output, mask=output.getchannel("A"))
            else:
                background.paste(output.convert("RGB"))
            output = background
            save_kwargs = {"quality": 95, "subsampling": 0, "optimize": True}
        elif suffix == ".webp":
            save_kwargs = {"quality": 95, "method": 6}
        elif suffix == ".png":
            save_kwargs = {"optimize": True}
        output.save(path, **save_kwargs)

    def _save_to_path(self, path: Path) -> None:
        assert self.image is not None
        try:
            self._save_image_object(self.image, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save the image.\n\n{exc}")
            return
        self.current_path = path
        self.dirty = False
        self._sync_active_document()
        self._update_title()
        self._set_status(f"Saved {path.name}")

    def _confirm_discard_changes(self) -> bool:
        return True

    def on_close(self) -> None:
        self._sync_active_document()
        dirty_documents = [document for document in self.documents.values() if document.dirty]
        if dirty_documents:
            answer = messagebox.askyesnocancel(
                APP_NAME,
                f"There are {len(dirty_documents)} unsaved tab(s). Exit without saving them?",
            )
            if answer is not True:
                return
        self._clear_recovery()
        self.destroy()

    # --------------------------- History ---------------------------
    def _capture_history_state(self, image: Optional[Image.Image] = None) -> HistoryState:
        assert self.image is not None or image is not None
        source = image if image is not None else self.image
        assert source is not None
        return HistoryState(
            image=source.copy(),
            selection=self.selection.copy() if self.selection is not None else None,
            focus_zones=[zone.copy() for zone in self.focus_zones],
            lasso_points=list(self.lasso_points),
        )

    def _restore_history_state(self, state: HistoryState) -> None:
        self.image = state.image.copy()
        self.selection = state.selection.copy() if state.selection is not None else None
        self.focus_zones = [zone.copy() for zone in state.focus_zones]
        self.lasso_points = list(state.lasso_points)
        self.selected_face_index = 0 if self.focus_zones else None
        self.preview_image = None
        self.focus_preview = None
        self.lasso_preview = []
        self.shape_preview = None
        self.clone_source = None
        self.clone_offset = None
        self.brush_before = None
        self.brush_state_before = None
        self.brush_source = None
        self.brush_last = None
        self.mask_drag_action = None
        self.mask_drag_original = None
        self.mask_drag_start = None

    def _snapshot(self) -> None:
        if self.image is None:
            return
        self.undo_stack.append(self._capture_history_state())
        if len(self.undo_stack) > self.MAX_HISTORY:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def undo(self) -> None:
        if self.image is None or not self.undo_stack:
            return
        self.redo_stack.append(self._capture_history_state())
        state = self.undo_stack.pop()
        self._restore_history_state(state)
        self.dirty = True
        self._render_image()
        self._refresh_tool_options()
        self._update_button_states()
        self._update_title()
        self._sync_active_document()
        self._set_status("Undid last edit — masks preserved")

    def redo(self) -> None:
        if self.image is None or not self.redo_stack:
            return
        self.undo_stack.append(self._capture_history_state())
        state = self.redo_stack.pop()
        self._restore_history_state(state)
        self.dirty = True
        self._render_image()
        self._refresh_tool_options()
        self._update_button_states()
        self._update_title()
        self._sync_active_document()
        self._set_status("Redid edit — masks preserved")

    def _commit_edit(self, new_image: Image.Image, status: str, refit: bool = False, preserve_masks: bool = True) -> None:
        if self.image is None:
            return
        self._snapshot()
        self.image = new_image.convert("RGBA")
        self.preview_image = None
        self.focus_preview = None
        self.lasso_preview = []
        self.shape_preview = None
        self.tool_start_image = None
        self.tool_end_image = None
        self.brush_before = None
        self.brush_state_before = None
        self.brush_source = None
        self.brush_last = None
        if not preserve_masks or refit:
            self.selection = None
            self.focus_zones.clear()
            self.selected_face_index = None
            self.lasso_points = []
            self.clone_source = None
            self.clone_offset = None
        self.dirty = True
        if refit:
            self.fit_to_window()
        else:
            self._render_image()
        self._refresh_tool_options()
        self._update_title()
        self._update_button_states()
        self._sync_active_document()
        self._set_status(status)

    # --------------------------- Selection and direct tools ---------------------------
    def _mask_hit_action(self, point: tuple[int, int], selection: Selection, ellipse: bool = False) -> Optional[str]:
        tolerance = max(4, round(10 / max(self.zoom, 0.05)))
        x, y = point
        corners = {
            "nw": (selection.left, selection.top),
            "ne": (selection.right, selection.top),
            "sw": (selection.left, selection.bottom),
            "se": (selection.right, selection.bottom),
        }
        for action, (hx, hy) in corners.items():
            if abs(x - hx) <= tolerance and abs(y - hy) <= tolerance:
                return action
        if ellipse:
            cx = (selection.left + selection.right) / 2
            cy = (selection.top + selection.bottom) / 2
            rx = max(1, selection.width / 2)
            ry = max(1, selection.height / 2)
            inside = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1
        else:
            inside = selection.left <= x <= selection.right and selection.top <= y <= selection.bottom
        return "move" if inside else None

    def _begin_mask_drag(self, action: str, point: tuple[int, int], selection: Selection, index: Optional[int] = None) -> None:
        self.mask_drag_action = action
        self.mask_drag_index = index
        self.mask_drag_original = selection.copy()
        self.mask_drag_start = point
        self.drag_start_canvas = (0, 0)

    def _update_mask_drag(self, point: tuple[int, int]) -> None:
        if self.image is None or self.mask_drag_action is None or self.mask_drag_original is None or self.mask_drag_start is None:
            return
        dx = point[0] - self.mask_drag_start[0]
        dy = point[1] - self.mask_drag_start[1]
        original = self.mask_drag_original
        action = self.mask_drag_action
        if action == "move":
            moved = self._move_selection_box(original, dx, dy)
        else:
            left, top, right, bottom = original.box
            if "w" in action:
                left += dx
            if "e" in action:
                right += dx
            if "n" in action:
                top += dy
            if "s" in action:
                bottom += dy
            left, right = sorted((left, right))
            top, bottom = sorted((top, bottom))
            moved = Selection(left, top, right, bottom)
        if action != "move":
            moved = self._clamp_selection(moved)
        if self.mask_drag_index is None:
            self.selection = moved
        elif 0 <= self.mask_drag_index < len(self.focus_zones):
            self.focus_zones[self.mask_drag_index] = moved
        self._render_image()

    def _finish_mask_drag(self) -> None:
        if self.mask_drag_action is None:
            return
        self.mask_drag_action = None
        self.mask_drag_index = None
        self.mask_drag_original = None
        self.mask_drag_start = None
        self.drag_start_canvas = None
        self._sync_active_document()
        self._refresh_tool_options()
        self._set_status("Mask position updated")

    def _selection_start(self, event: tk.Event) -> None:
        if self.image is None or not self._canvas_point_inside_image(event.x, event.y):
            return
        self.cancel_preview(render=False)
        ix, iy = self._canvas_to_image(event.x, event.y, clamp=True)
        point = (int(ix), int(iy))
        mode = self.draw_mode.get()

        if mode == "selection" and self.selection is not None:
            action = self._mask_hit_action(point, self.selection)
            if action:
                self._begin_mask_drag(action, point, self.selection)
                return

        if mode == "face" and self.focus_zones:
            for index in range(len(self.focus_zones) - 1, -1, -1):
                zone = self.focus_zones[index]
                action = self._mask_hit_action(point, zone, ellipse=True)
                if action:
                    self.selected_face_index = index
                    self._begin_mask_drag(action, point, zone, index=index)
                    self._render_image()
                    self._refresh_tool_options()
                    return

        if mode in {"selection", "face", "arrow", "box"}:
            self.drag_start_canvas = (event.x, event.y)
            self.tool_start_image = point
            self.tool_end_image = point
            if mode == "selection":
                self.selection = None
                self.lasso_points = []
            elif mode == "face":
                self.focus_preview = None
            else:
                self.shape_preview = Selection(point[0], point[1], point[0], point[1])
            self._render_image()
            return

        if mode == "lasso":
            self.drag_start_canvas = (event.x, event.y)
            self.lasso_preview = [point]
            self.selection = None
            self._render_image()
            return

        if mode in {"blur_brush", "pixel_brush", "mosaic_brush", "black_brush"}:
            self._begin_effect_brush(mode, point)
            return

        if mode in {"clone", "heal"}:
            if self.clone_source is None:
                self.clone_source = point
                self._render_image()
                self._set_status(f"Clone source set at {point[0]}, {point[1]}. Click and drag where you want to paint.")
            else:
                self._begin_clone_brush(mode, point)
            return

        if mode == "sticker":
            self._place_sticker(point)
            return

        if mode == "text":
            self._place_text(point)

    def _selection_drag(self, event: tk.Event) -> None:
        if self.image is None:
            return
        mode = self.draw_mode.get()
        ix, iy = self._canvas_to_image(event.x, event.y, clamp=True)
        point = (int(ix), int(iy))

        if self.mask_drag_action is not None:
            self._update_mask_drag(point)
            return

        if mode == "lasso" and self.drag_start_canvas is not None:
            if not self.lasso_preview or math.hypot(point[0] - self.lasso_preview[-1][0], point[1] - self.lasso_preview[-1][1]) >= 2:
                self.lasso_preview.append(point)
                self._render_image()
            return

        if mode in {"selection", "face", "arrow", "box"} and self.drag_start_canvas is not None and self.tool_start_image is not None:
            self.tool_end_image = point
            x1, y1 = self.tool_start_image
            x2, y2 = point
            left, right = sorted((x1, x2))
            top, bottom = sorted((y1, y2))
            region = Selection(left, top, right, bottom)
            if mode == "selection":
                self.selection = region
            elif mode == "face":
                self.focus_preview = region
            else:
                self.shape_preview = region
            self._render_image()
            return

        if mode in {"blur_brush", "pixel_brush", "mosaic_brush", "black_brush", "clone", "heal"} and self.brush_before is not None:
            self._paint_brush_line(mode, point)

    def _selection_end(self, _event: tk.Event) -> None:
        mode = self.draw_mode.get()
        if self.mask_drag_action is not None:
            self._finish_mask_drag()
            return
        self.drag_start_canvas = None

        if mode == "selection":
            if self.selection and (self.selection.width < 2 or self.selection.height < 2):
                self.selection = None
            self._render_image()
            self._refresh_tool_options()
            self._sync_active_document()
            if self.selection:
                self._set_status(f"Selection: {self.selection.width} × {self.selection.height} px")
            return

        if mode == "lasso":
            if len(self.lasso_preview) >= 3:
                self.lasso_points = list(self.lasso_preview)
                self._set_status(f"Lasso selection: {len(self.lasso_points)} points")
            self.lasso_preview = []
            self._render_image()
            self._refresh_tool_options()
            self._sync_active_document()
            return

        if mode == "face":
            if self.focus_preview and self.focus_preview.width >= 2 and self.focus_preview.height >= 2:
                self.focus_zones.append(self.focus_preview)
                face_count = len(self.focus_zones)
                self.selected_face_index = face_count - 1
            else:
                face_count = len(self.focus_zones)
            self.focus_preview = None
            self._render_image()
            self._refresh_tool_options()
            self._sync_active_document()
            if face_count:
                self._set_status(f"Added face circle #{face_count}")
            return

        if mode in {"arrow", "box"}:
            self._finish_shape(mode)
            return

        if mode in {"blur_brush", "pixel_brush", "mosaic_brush", "black_brush", "clone", "heal"}:
            self._finish_brush(mode)

    def clear_selection(self) -> None:
        if self.selection is not None or self.shape_preview is not None or self.lasso_points or self.lasso_preview:
            self.selection = None
            self.shape_preview = None
            self.lasso_points = []
            self.lasso_preview = []
            self._render_image()
            self._refresh_tool_options()
            self._sync_active_document()
            self._set_status("Selection cleared")

    def clear_focus_zones(self) -> None:
        if self.focus_zones or self.focus_preview:
            self.focus_zones.clear()
            self.selected_face_index = None
            self.focus_preview = None
            self._render_image()
            self._refresh_tool_options()
            self._sync_active_document()
            self._set_status("Face circles cleared")

    def reset_clone_source(self) -> None:
        self.clone_source = None
        self.clone_offset = None
        self._render_image()
        self._set_status("Clone source cleared")

    def _clamp_selection(self, selection: Selection) -> Selection:
        assert self.image is not None
        min_size = 2
        left = max(0, min(selection.left, self.image.width - min_size))
        top = max(0, min(selection.top, self.image.height - min_size))
        right = max(left + min_size, min(selection.right, self.image.width))
        bottom = max(top + min_size, min(selection.bottom, self.image.height))
        return Selection(left, top, right, bottom)

    def _move_selection_box(self, selection: Selection, dx: int, dy: int) -> Selection:
        assert self.image is not None
        width = min(selection.width, self.image.width)
        height = min(selection.height, self.image.height)
        left = max(0, min(selection.left + dx, self.image.width - width))
        top = max(0, min(selection.top + dy, self.image.height - height))
        return Selection(left, top, left + width, top + height)

    def move_selection(self, dx: int, dy: int) -> None:
        if self.image is None or self.selection is None:
            return
        self.selection = self._move_selection_box(self.selection, dx, dy)
        self._render_image()
        self._refresh_tool_options()
        self._set_status("Moved selection")

    def resize_selection(self, delta: int) -> None:
        if self.image is None or self.selection is None:
            return
        sel = self.selection
        self.selection = self._clamp_selection(Selection(sel.left - delta, sel.top - delta, sel.right + delta, sel.bottom + delta))
        self._render_image()
        self._refresh_tool_options()
        self._set_status("Resized selection")

    def _on_face_list_select(self, _event: Optional[tk.Event] = None) -> None:
        if hasattr(self, "face_listbox"):
            selected = self.face_listbox.curselection()
            self.selected_face_index = selected[0] if selected else None
            self._render_image()

    def _selected_face_zone(self) -> tuple[int, Selection] | None:
        if self.selected_face_index is None:
            return None
        if not (0 <= self.selected_face_index < len(self.focus_zones)):
            return None
        return self.selected_face_index, self.focus_zones[self.selected_face_index]

    def move_selected_face(self, dx: int, dy: int) -> None:
        if self.image is None:
            return
        data = self._selected_face_zone()
        if data is None:
            return
        index, zone = data
        self.focus_zones[index] = self._move_selection_box(zone, dx, dy)
        self._render_image()
        self._refresh_tool_options()
        self._set_status(f"Moved face circle #{index + 1}")

    def resize_selected_face(self, delta: int) -> None:
        if self.image is None:
            return
        data = self._selected_face_zone()
        if data is None:
            return
        index, zone = data
        self.focus_zones[index] = self._clamp_selection(Selection(zone.left - delta, zone.top - delta, zone.right + delta, zone.bottom + delta))
        self._render_image()
        self._refresh_tool_options()
        self._set_status(f"Resized face circle #{index + 1}")

    def duplicate_selected_face(self) -> None:
        data = self._selected_face_zone()
        if data is None:
            return
        _, zone = data
        dup = Selection(zone.left + 12, zone.top + 12, zone.right + 12, zone.bottom + 12)
        self.focus_zones.append(self._clamp_selection(dup))
        self.selected_face_index = len(self.focus_zones) - 1
        self._render_image()
        self._refresh_tool_options()
        self._set_status("Duplicated face circle")

    def delete_selected_face(self) -> None:
        data = self._selected_face_zone()
        if data is None:
            return
        index, _ = data
        del self.focus_zones[index]
        if not self.focus_zones:
            self.selected_face_index = None
        else:
            self.selected_face_index = max(0, min(index, len(self.focus_zones) - 1))
        self._render_image()
        self._refresh_tool_options()
        self._set_status("Deleted face circle")

    def crop_to_selection(self) -> None:
        if self.image is None:
            return
        if self.lasso_points:
            xs = [point[0] for point in self.lasso_points]
            ys = [point[1] for point in self.lasso_points]
            box = (max(0, min(xs)), max(0, min(ys)), min(self.image.width, max(xs) + 1), min(self.image.height, max(ys) + 1))
            mask = Image.new("L", self.image.size, 0)
            ImageDraw.Draw(mask).polygon(self.lasso_points, fill=255)
            isolated = Image.new("RGBA", self.image.size, (0, 0, 0, 0))
            isolated.paste(self.image, (0, 0), mask)
            cropped = isolated.crop(box)
            self._commit_edit(cropped, f"Cropped lasso to {cropped.width} × {cropped.height}", refit=True, preserve_masks=False)
            return
        if self.selection is None:
            messagebox.showinfo(APP_NAME, "Draw a rectangle or lasso selection first.")
            return
        cropped = self.image.crop(self.selection.box)
        self._commit_edit(cropped, f"Cropped to {cropped.width} × {cropped.height}", refit=True, preserve_masks=False)

    def _target_box(self) -> tuple[int, int, int, int]:
        assert self.image is not None
        if self.lasso_points:
            xs = [point[0] for point in self.lasso_points]
            ys = [point[1] for point in self.lasso_points]
            return max(0, min(xs)), max(0, min(ys)), min(self.image.width, max(xs) + 1), min(self.image.height, max(ys) + 1)
        if self.selection and self.selection.width > 0 and self.selection.height > 0:
            return self.selection.box
        return 0, 0, self.image.width, self.image.height

    def _target_mask(self) -> Image.Image:
        assert self.image is not None
        mask = Image.new("L", self.image.size, 0)
        draw = ImageDraw.Draw(mask)
        if self.lasso_points:
            draw.polygon(self.lasso_points, fill=255)
        elif self.selection and self.selection.width > 0 and self.selection.height > 0:
            draw.rectangle(self.selection.box, fill=255)
        else:
            mask.paste(255, (0, 0, self.image.width, self.image.height))
        return mask

    def _apply_to_target(self, transform: Callable[[Image.Image], Image.Image], status: str) -> None:
        if self.image is None:
            return
        self.cancel_preview(render=False)
        processed = transform(self.image.copy()).convert("RGBA")
        if processed.size != self.image.size:
            processed = processed.resize(self.image.size, Image.Resampling.LANCZOS)
        result = Image.composite(processed, self.image, self._target_mask())
        self._commit_edit(result, status, preserve_masks=True)

    def _focus_mask(self) -> Image.Image:
        assert self.image is not None
        mask = Image.new("L", self.image.size, 255)
        draw = ImageDraw.Draw(mask)
        for zone in self.focus_zones:
            draw.ellipse(zone.box, fill=0)
        return mask

    def _apply_outside_focus(self, transform: Callable[[Image.Image], Image.Image], status: str) -> None:
        if self.image is None:
            return
        if not self.focus_zones:
            messagebox.showinfo(APP_NAME, "Switch to Face circles mode, draw one or more face circles, then try again.")
            return
        self.cancel_preview(render=False)
        processed = transform(self.image.copy()).convert("RGBA")
        mask = self._focus_mask()
        result = Image.composite(processed, self.image, mask)
        self._commit_edit(result, status)

    def _begin_effect_brush(self, mode: str, point: tuple[int, int]) -> None:
        assert self.image is not None
        self.brush_state_before = self._capture_history_state()
        self.brush_before = self.image.copy()
        if mode == "blur_brush":
            self.brush_source = self.brush_before.filter(ImageFilter.GaussianBlur(radius=max(0.1, float(self.blur_radius.get()))))
        elif mode == "pixel_brush":
            self.brush_source = self._pixelated_copy(self.brush_before, max(2, int(self.pixel_size.get())))
        elif mode == "mosaic_brush":
            self.brush_source = self._mosaic_copy(self.brush_before, max(4, int(self.mosaic_size.get())))
        else:
            self.brush_source = None
        self.brush_last = point
        self._stamp_effect_brush(mode, point)
        self._render_image()

    def _begin_clone_brush(self, mode: str, point: tuple[int, int]) -> None:
        assert self.image is not None and self.clone_source is not None
        self.brush_state_before = self._capture_history_state()
        self.brush_before = self.image.copy()
        self.brush_source = self.brush_before.copy()
        self.clone_offset = (self.clone_source[0] - point[0], self.clone_source[1] - point[1])
        self.brush_last = point
        self._stamp_clone_brush(mode, point)
        self._render_image()

    def _paint_brush_line(self, mode: str, point: tuple[int, int]) -> None:
        if self.brush_last is None:
            self.brush_last = point
        x1, y1 = self.brush_last
        x2, y2 = point
        distance = math.hypot(x2 - x1, y2 - y1)
        spacing = max(1.0, int(self.brush_size.get()) * 0.18)
        steps = max(1, math.ceil(distance / spacing))
        for step in range(1, steps + 1):
            t = step / steps
            p = (round(x1 + (x2 - x1) * t), round(y1 + (y2 - y1) * t))
            if mode in {"clone", "heal"}:
                self._stamp_clone_brush(mode, p)
            else:
                self._stamp_effect_brush(mode, p)
        self.brush_last = point
        self._render_image()

    def _brush_geometry(self, point: tuple[int, int]) -> tuple[tuple[int, int, int, int], Image.Image]:
        assert self.image is not None
        radius = max(2, int(self.brush_size.get()) // 2)
        x, y = point
        left = max(0, x - radius)
        top = max(0, y - radius)
        right = min(self.image.width, x + radius + 1)
        bottom = min(self.image.height, y + radius + 1)
        mask = Image.new("L", (right - left, bottom - top), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, mask.width - 1, mask.height - 1), fill=255)
        return (left, top, right, bottom), mask

    def _stamp_effect_brush(self, mode: str, point: tuple[int, int]) -> None:
        if self.image is None:
            return
        box, mask = self._brush_geometry(point)
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        if mode == "black_brush":
            patch = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 255))
        elif self.brush_source is not None:
            patch = self.brush_source.crop(box)
        else:
            return
        self.image.paste(patch, (box[0], box[1]), mask)

    def _stamp_clone_brush(self, mode: str, point: tuple[int, int]) -> None:
        if self.image is None or self.brush_source is None or self.clone_offset is None:
            return
        box, mask = self._brush_geometry(point)
        width, height = box[2] - box[0], box[3] - box[1]
        offset_x, offset_y = self.clone_offset
        source_box = (box[0] + offset_x, box[1] + offset_y, box[2] + offset_x, box[3] + offset_y)
        destination = self.image.crop(box)
        patch = destination.copy()
        src_left = max(0, source_box[0])
        src_top = max(0, source_box[1])
        src_right = min(self.brush_source.width, source_box[2])
        src_bottom = min(self.brush_source.height, source_box[3])
        if src_right <= src_left or src_bottom <= src_top:
            return
        cropped = self.brush_source.crop((src_left, src_top, src_right, src_bottom))
        paste_x = src_left - source_box[0]
        paste_y = src_top - source_box[1]
        patch.paste(cropped, (paste_x, paste_y))
        if mode == "heal":
            patch = Image.blend(destination, patch, 0.68)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1, int(self.brush_size.get()) / 8)))
        self.image.paste(patch, (box[0], box[1]), mask)

    def _finish_brush(self, mode: str) -> None:
        if self.image is None or self.brush_before is None or self.brush_state_before is None:
            return
        self.undo_stack.append(self.brush_state_before)
        if len(self.undo_stack) > self.MAX_HISTORY:
            del self.undo_stack[0]
        self.redo_stack.clear()
        self.brush_before = None
        self.brush_state_before = None
        self.brush_source = None
        self.brush_last = None
        self.clone_offset = None
        self.dirty = True
        self._update_title()
        self._update_button_states()
        self._render_image()
        self._sync_active_document()
        labels = {
            "blur_brush": "Blur brush stroke",
            "pixel_brush": "Pixel brush stroke",
            "mosaic_brush": "Mosaic brush stroke",
            "black_brush": "Black censor brush stroke",
            "clone": "Clone brush stroke",
            "heal": "Heal brush stroke",
        }
        self._set_status(labels.get(mode, "Brush stroke applied"))

    def _finish_shape(self, mode: str) -> None:
        if self.image is None or self.tool_start_image is None or self.tool_end_image is None:
            self.shape_preview = None
            return
        start = self.tool_start_image
        end = self.tool_end_image
        if math.hypot(end[0] - start[0], end[1] - start[1]) < 2:
            self.shape_preview = None
            self._render_image()
            return
        edited = self.image.copy()
        draw = ImageDraw.Draw(edited)
        color = self.shape_color.get()
        width = max(1, int(self.shape_width.get()))
        if mode == "box":
            left, right = sorted((start[0], end[0]))
            top, bottom = sorted((start[1], end[1]))
            draw.rectangle((left, top, right, bottom), outline=color, width=width)
            status = "Added box"
        else:
            self._draw_arrow(draw, start, end, color, width)
            status = "Added arrow"
        self.shape_preview = None
        self.tool_start_image = None
        self.tool_end_image = None
        self._commit_edit(edited, status)

    @staticmethod
    def _draw_arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str, width: int) -> None:
        draw.line((start, end), fill=color, width=width)
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        head = max(12, width * 3)
        spread = math.pi / 7
        p1 = (end[0] - head * math.cos(angle - spread), end[1] - head * math.sin(angle - spread))
        p2 = (end[0] - head * math.cos(angle + spread), end[1] - head * math.sin(angle + spread))
        draw.polygon((end, p1, p2), fill=color)

    # --------------------------- Effects ---------------------------
    @staticmethod
    def _pixelated_copy(image: Image.Image, block: int) -> Image.Image:
        small_w = max(1, math.ceil(image.width / block))
        small_h = max(1, math.ceil(image.height / block))
        small = image.resize((small_w, small_h), Image.Resampling.BOX)
        return small.resize(image.size, Image.Resampling.NEAREST)

    @staticmethod
    def _mosaic_copy(image: Image.Image, tile: int) -> Image.Image:
        source = image.convert("RGBA")
        out = Image.new("RGBA", source.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(out)
        for y in range(0, source.height, tile):
            for x in range(0, source.width, tile):
                x2 = min(source.width, x + tile)
                y2 = min(source.height, y + tile)
                cell = source.crop((x, y, x2, y2)).resize((1, 1), Image.Resampling.BOX)
                color = cell.getpixel((0, 0))
                gap = 1 if tile >= 8 else 0
                draw.rectangle((x, y, max(x, x2 - gap - 1), max(y, y2 - gap - 1)), fill=color)
        return out

    def _adjust_image_values(self, image: Image.Image, brightness: int, contrast: int, saturation: int, sharpness: int) -> Image.Image:
        result = image.convert("RGBA")
        if brightness:
            result = ImageEnhance.Brightness(result).enhance(max(0, 1 + brightness / 100))
        if contrast:
            result = ImageEnhance.Contrast(result).enhance(max(0, 1 + contrast / 100))
        if saturation:
            result = ImageEnhance.Color(result).enhance(max(0, 1 + saturation / 100))
        if sharpness:
            result = ImageEnhance.Sharpness(result).enhance(max(0, 1 + sharpness / 100))
        return result.convert("RGBA")

    def _vignette_image(self, image: Image.Image, strength: int) -> Image.Image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        w, h = rgba.size
        cx = (w - 1) / 2 if w > 1 else 0
        cy = (h - 1) / 2 if h > 1 else 0
        max_d = max(1.0, math.sqrt(cx * cx + cy * cy))
        mask = Image.new("L", (w, h), 0)
        px = mask.load()
        for y in range(h):
            for x in range(w):
                dx = x - cx
                dy = y - cy
                d = math.sqrt(dx * dx + dy * dy) / max_d
                edge = max(0.0, min(1.0, (d - 0.25) / 0.75))
                px[x, y] = int(255 * min(1.0, edge ** 1.8 * (strength / 100)))
        darkened = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        out = Image.composite(darkened, rgba, mask)
        out.putalpha(alpha)
        return out

    def _glow_image(self, image: Image.Image, strength: int) -> Image.Image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        blur_radius = max(1.0, strength / 8)
        blurred = rgba.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        mixed = Image.blend(rgba, blurred, min(0.75, strength / 115))
        bright = ImageEnhance.Brightness(mixed).enhance(1 + strength / 170)
        contrast = ImageEnhance.Contrast(bright).enhance(1 + strength / 260)
        contrast.putalpha(alpha)
        return contrast

    def _posterize_image(self, image: Image.Image, strength: int) -> Image.Image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        bits = max(2, min(7, 8 - round(strength / 20)))
        rgb = ImageOps.posterize(rgba.convert("RGB"), bits=bits).convert("RGBA")
        rgb.putalpha(alpha)
        return rgb

    def _sketch_image(self, image: Image.Image, strength: int) -> Image.Image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        gray = ImageOps.grayscale(rgba)
        edges = gray.filter(ImageFilter.FIND_EDGES)
        soft = gray.filter(ImageFilter.GaussianBlur(radius=max(1.0, strength / 12)))
        sketch = Image.blend(ImageOps.invert(edges), ImageOps.invert(soft), 0.35)
        enhanced = ImageEnhance.Contrast(sketch).enhance(1 + strength / 80)
        out = enhanced.convert("RGBA")
        out.putalpha(alpha)
        return out

    def _auto_enhance_image(self, image: Image.Image) -> Image.Image:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgb = ImageOps.autocontrast(rgba.convert("RGB"), cutoff=1)
        rgb = ImageEnhance.Color(rgb).enhance(1.08)
        rgb = ImageEnhance.Sharpness(rgb).enhance(1.12)
        out = rgb.convert("RGBA")
        out.putalpha(alpha)
        return out

    def _apply_preset_to_image(self, image: Image.Image, preset: dict[str, object]) -> Image.Image:
        action = str(preset.get("action", "Adjustments"))
        brightness = int(preset.get("brightness", 0))
        contrast = int(preset.get("contrast", 0))
        saturation = int(preset.get("saturation", 0))
        sharpness = int(preset.get("sharpness", 0))
        blur_radius = max(0.1, float(preset.get("blur_radius", 8.0)))
        pixel_size = max(2, int(preset.get("pixel_size", 16)))
        mosaic_size = max(4, int(preset.get("mosaic_size", 22)))
        creative_strength = max(5, int(preset.get("creative_strength", 40)))
        result = image.convert("RGBA")
        if action == "Adjustments":
            result = self._adjust_image_values(result, brightness, contrast, saturation, sharpness)
        elif action == "Auto Enhance":
            result = self._auto_enhance_image(result)
        elif action == "Grayscale":
            alpha = result.getchannel("A")
            result = ImageOps.grayscale(result).convert("RGBA")
            result.putalpha(alpha)
        elif action == "Invert":
            alpha = result.getchannel("A")
            result = ImageOps.invert(result.convert("RGB")).convert("RGBA")
            result.putalpha(alpha)
        elif action == "Blur":
            result = result.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        elif action == "Pixelate":
            result = self._pixelated_copy(result, pixel_size)
        elif action == "Mosaic":
            result = self._mosaic_copy(result, mosaic_size)
        elif action == "Vignette":
            result = self._vignette_image(result, creative_strength)
        elif action == "Glow":
            result = self._glow_image(result, creative_strength)
        elif action == "Posterize":
            result = self._posterize_image(result, creative_strength)
        elif action == "Sketch":
            result = self._sketch_image(result, creative_strength)
        elif action == "Cinematic Look":
            result = self._adjust_image_values(result, brightness, contrast, saturation, sharpness)
            result = self._vignette_image(result, creative_strength)
        return result.convert("RGBA")

    def _effect_processed_image(self, image: Image.Image, effect: str) -> Image.Image:
        if effect == "Blur":
            return image.filter(ImageFilter.GaussianBlur(radius=max(0.1, float(self.blur_radius.get())))).convert("RGBA")
        if effect == "Pixelate":
            return self._pixelated_copy(image, max(2, int(self.pixel_size.get())))
        if effect == "Mosaic":
            return self._mosaic_copy(image, max(4, int(self.mosaic_size.get())))
        alpha = image.getchannel("A")
        black = Image.new("RGBA", image.size, (0, 0, 0, 255))
        black.putalpha(alpha)
        return black

    def preview_selected_effect(self) -> None:
        if self.image is None:
            return
        mode = self.draw_mode.get()
        effect = self.area_effect.get()
        processed = self._effect_processed_image(self.image.copy(), effect)
        if mode == "face":
            if not self.focus_zones:
                messagebox.showinfo(APP_NAME, "Draw one or more face circles first.")
                return
            mask = self._focus_mask()
            context = "outside protected faces"
        else:
            mask = self._target_mask()
            context = "inside selection" if (self.selection or self.lasso_points) else "on whole image"
        self.preview_image = Image.composite(processed, self.image, mask)
        self._render_image()
        self._set_status(f"Previewing {effect.lower()} {context} — adjust the slider, then Apply or Cancel")

    def _refresh_effect_preview(self, *_args: object) -> None:
        if self.preview_image is not None and self.image is not None:
            self.after_idle(self.preview_selected_effect)

    def apply_effect_preview(self) -> None:
        if self.image is None:
            return
        if self.preview_image is None:
            self.preview_selected_effect()
            return
        if self.preview_image is None:
            return
        preview = self.preview_image.copy()
        effect = self.area_effect.get()
        self.preview_image = None
        self._commit_edit(preview, f"Applied {effect.lower()} — masks kept for another test", preserve_masks=True)

    def preview_blur(self) -> None:
        self.preview_selected_effect()

    def apply_blur_preview(self) -> None:
        self.apply_effect_preview()

    def cancel_preview(self, render: bool = True) -> None:
        if self.preview_image is None:
            return
        self.preview_image = None
        if render:
            self._render_image()
            self._set_status("Preview cancelled — masks unchanged")

    def choose_shape_color(self) -> None:
        chosen = colorchooser.askcolor(color=self.shape_color.get(), title="Choose annotation color", parent=self)
        if chosen and chosen[1]:
            self.shape_color.set(chosen[1])

    def _load_font(self, size: int, emoji: bool = False) -> ImageFont.ImageFont:
        candidates: list[str] = []
        if sys.platform.startswith("win"):
            windir = os.environ.get("WINDIR", r"C:\Windows")
            fonts = Path(windir) / "Fonts"
            if emoji:
                candidates.extend([str(fonts / "seguiemj.ttf"), str(fonts / "seguisym.ttf")])
            candidates.extend([str(fonts / "segoeui.ttf"), str(fonts / "arial.ttf")])
        candidates.extend(["DejaVuSans.ttf", "Arial.ttf"])
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _place_sticker(self, point: tuple[int, int]) -> None:
        if self.image is None:
            return
        sticker = self.sticker_choice.get() or "😀"
        size = max(24, int(self.sticker_size.get()))
        font = self._load_font(size, emoji=True)
        layer = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        try:
            bbox = draw.textbbox((0, 0), sticker, font=font, embedded_color=True)
            text_w = max(1, bbox[2] - bbox[0])
            text_h = max(1, bbox[3] - bbox[1])
            draw.text(((layer.width - text_w) / 2 - bbox[0], (layer.height - text_h) / 2 - bbox[1]), sticker, font=font, embedded_color=True)
        except Exception:
            bbox = draw.textbbox((0, 0), sticker, font=font)
            text_w = max(1, bbox[2] - bbox[0])
            text_h = max(1, bbox[3] - bbox[1])
            draw.text(((layer.width - text_w) / 2 - bbox[0], (layer.height - text_h) / 2 - bbox[1]), sticker, font=font, fill=self.shape_color.get())
        crop = layer.getbbox()
        if crop:
            layer = layer.crop(crop)
        edited = self.image.copy()
        x = int(point[0] - layer.width / 2)
        y = int(point[1] - layer.height / 2)
        edited.paste(layer, (x, y), layer)
        self._commit_edit(edited, f"Added sticker {sticker}")

    def _place_text(self, point: tuple[int, int]) -> None:
        if self.image is None:
            return
        dialog = TextToolDialog(self, self.shape_color.get())
        self.wait_window(dialog)
        if dialog.result is None:
            return
        value, size, color, shadow = dialog.result
        self.shape_color.set(color)
        font = self._load_font(size)
        edited = self.image.copy()
        draw = ImageDraw.Draw(edited)
        if shadow:
            offset = max(2, size // 18)
            draw.multiline_text((point[0] + offset, point[1] + offset), value, font=font, fill="#000000", spacing=max(2, size // 8), stroke_width=max(0, size // 30), stroke_fill="#000000")
        draw.multiline_text(point, value, font=font, fill=color, spacing=max(2, size // 8), stroke_width=max(0, size // 35), stroke_fill="#000000")
        self._commit_edit(edited, "Added text")

    def apply_blur(self) -> None:
        radius = max(0.1, float(self.blur_radius.get()))
        self._apply_to_target(
            lambda region: region.filter(ImageFilter.GaussianBlur(radius=radius)),
            f"Applied blur (radius {radius:g})",
        )

    def apply_pixelate(self) -> None:
        block = max(2, int(self.pixel_size.get()))

        def pixelate(region: Image.Image) -> Image.Image:
            small_w = max(1, math.ceil(region.width / block))
            small_h = max(1, math.ceil(region.height / block))
            small = region.resize((small_w, small_h), Image.Resampling.BOX)
            return small.resize(region.size, Image.Resampling.NEAREST)

        self._apply_to_target(pixelate, f"Applied pixelation ({block}px blocks)")

    def apply_mosaic(self) -> None:
        tile = max(4, int(self.mosaic_size.get()))

        def mosaic(region: Image.Image) -> Image.Image:
            source = region.convert("RGBA")
            out = Image.new("RGBA", source.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(out)
            for y in range(0, source.height, tile):
                for x in range(0, source.width, tile):
                    x2 = min(source.width, x + tile)
                    y2 = min(source.height, y + tile)
                    cell = source.crop((x, y, x2, y2)).resize((1, 1), Image.Resampling.BOX)
                    color = cell.getpixel((0, 0))
                    gap = 1 if tile >= 8 else 0
                    draw.rectangle((x, y, max(x, x2 - gap - 1), max(y, y2 - gap - 1)), fill=color)
            return out

        self._apply_to_target(mosaic, f"Applied mosaic ({tile}px tiles)")

    def blur_outside_faces(self) -> None:
        radius = max(0.1, float(self.blur_radius.get()))
        self._apply_outside_focus(
            lambda image: image.filter(ImageFilter.GaussianBlur(radius=radius)),
            f"Blurred outside face circles (radius {radius:g})",
        )

    def pixelate_outside_faces(self) -> None:
        block = max(2, int(self.pixel_size.get()))

        def pixelate(image: Image.Image) -> Image.Image:
            small_w = max(1, math.ceil(image.width / block))
            small_h = max(1, math.ceil(image.height / block))
            small = image.resize((small_w, small_h), Image.Resampling.BOX)
            return small.resize(image.size, Image.Resampling.NEAREST)

        self._apply_outside_focus(pixelate, f"Pixelated outside face circles ({block}px blocks)")

    def mosaic_outside_faces(self) -> None:
        tile = max(4, int(self.mosaic_size.get()))

        def mosaic_full(image: Image.Image) -> Image.Image:
            source = image.convert("RGBA")
            out = Image.new("RGBA", source.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(out)
            for y in range(0, source.height, tile):
                for x in range(0, source.width, tile):
                    x2 = min(source.width, x + tile)
                    y2 = min(source.height, y + tile)
                    cell = source.crop((x, y, x2, y2)).resize((1, 1), Image.Resampling.BOX)
                    color = cell.getpixel((0, 0))
                    gap = 1 if tile >= 8 else 0
                    draw.rectangle((x, y, max(x, x2 - gap - 1), max(y, y2 - gap - 1)), fill=color)
            return out

        self._apply_outside_focus(mosaic_full, f"Mosaiced outside face circles ({tile}px tiles)")

    def blackout_outside_faces(self) -> None:
        def blackout(image: Image.Image) -> Image.Image:
            alpha = image.getchannel("A")
            out = Image.new("RGBA", image.size, (0, 0, 0, 255))
            out.putalpha(alpha)
            return out

        self._apply_outside_focus(blackout, "Blacked out everything outside face circles")

    def add_black_bar_to_selection(self) -> None:
        if self.image is None:
            return
        if self.selection is None or self.selection.width < 2 or self.selection.height < 2:
            messagebox.showinfo(APP_NAME, "Use Rectangle selection mode and drag a bar-sized selection first.")
            return
        edited = self.image.copy()
        draw = ImageDraw.Draw(edited)
        draw.rectangle(self.selection.box, fill=(0, 0, 0, 255))
        self._commit_edit(edited, "Added black bar to selection")

    def add_cinematic_bars(self) -> None:
        if self.image is None:
            return
        max_height = max(1, self.image.height // 2)
        default = max(10, self.image.height // 12)
        bar_height = simpledialog.askinteger(
            APP_NAME,
            f"Enter the height in pixels for the top and bottom cinematic bars (1-{max_height}).",
            initialvalue=default,
            minvalue=1,
            maxvalue=max_height,
            parent=self,
        )
        if bar_height is None:
            return
        edited = self.image.copy()
        draw = ImageDraw.Draw(edited)
        draw.rectangle((0, 0, self.image.width, bar_height), fill=(0, 0, 0, 255))
        draw.rectangle((0, self.image.height - bar_height, self.image.width, self.image.height), fill=(0, 0, 0, 255))
        self._commit_edit(edited, f"Added cinematic bars ({bar_height}px each)")

    def apply_vignette(self) -> None:
        strength = max(5, int(self.creative_strength.get()))

        def vignette(region: Image.Image) -> Image.Image:
            rgba = region.convert("RGBA")
            alpha = rgba.getchannel("A")
            w, h = rgba.size
            cx = (w - 1) / 2 if w > 1 else 0
            cy = (h - 1) / 2 if h > 1 else 0
            max_d = max(1.0, math.sqrt(cx * cx + cy * cy))
            mask = Image.new("L", (w, h), 0)
            px = mask.load()
            for y in range(h):
                for x in range(w):
                    dx = x - cx
                    dy = y - cy
                    d = math.sqrt(dx * dx + dy * dy) / max_d
                    edge = max(0.0, min(1.0, (d - 0.25) / 0.75))
                    px[x, y] = int(255 * min(1.0, edge ** 1.8 * (strength / 100)))
            darkened = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
            out = Image.composite(darkened, rgba, mask)
            out.putalpha(alpha)
            return out

        self._apply_to_target(vignette, f"Applied vignette (strength {strength})")

    def apply_glow(self) -> None:
        strength = max(5, int(self.creative_strength.get()))

        def glow(region: Image.Image) -> Image.Image:
            rgba = region.convert("RGBA")
            alpha = rgba.getchannel("A")
            blur_radius = max(1.0, strength / 8)
            blurred = rgba.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            mixed = Image.blend(rgba, blurred, min(0.75, strength / 115))
            bright = ImageEnhance.Brightness(mixed).enhance(1 + strength / 170)
            contrast = ImageEnhance.Contrast(bright).enhance(1 + strength / 260)
            contrast.putalpha(alpha)
            return contrast

        self._apply_to_target(glow, f"Applied glow (strength {strength})")

    def apply_posterize(self) -> None:
        strength = max(5, int(self.creative_strength.get()))
        bits = max(2, min(7, 8 - round(strength / 20)))

        def poster(region: Image.Image) -> Image.Image:
            rgba = region.convert("RGBA")
            alpha = rgba.getchannel("A")
            rgb = ImageOps.posterize(rgba.convert("RGB"), bits=bits).convert("RGBA")
            rgb.putalpha(alpha)
            return rgb

        self._apply_to_target(poster, f"Applied posterize (bits {bits})")

    def apply_sketch(self) -> None:
        strength = max(5, int(self.creative_strength.get()))
        self._apply_to_target(lambda region: self._sketch_image(region, strength), f"Applied sketch effect (strength {strength})")

    def apply_adjustments(self) -> None:
        b = int(self.brightness.get())
        c = int(self.contrast.get())
        s = int(self.saturation.get())
        sh = int(self.sharpness.get())
        if b == c == s == sh == 0:
            self._set_status("Adjustment sliders are at zero")
            return

        def adjusted(region: Image.Image) -> Image.Image:
            result = region
            if b:
                result = ImageEnhance.Brightness(result).enhance(max(0, 1 + b / 100))
            if c:
                result = ImageEnhance.Contrast(result).enhance(max(0, 1 + c / 100))
            if s:
                result = ImageEnhance.Color(result).enhance(max(0, 1 + s / 100))
            if sh:
                result = ImageEnhance.Sharpness(result).enhance(max(0, 1 + sh / 100))
            return result

        self._apply_to_target(adjusted, "Applied image adjustments")
        self.reset_adjustment_sliders()

    def reset_adjustment_sliders(self) -> None:
        self.brightness.set(0)
        self.contrast.set(0)
        self.saturation.set(0)
        self.sharpness.set(0)

    def auto_enhance(self) -> None:
        def enhance(region: Image.Image) -> Image.Image:
            alpha = region.getchannel("A")
            rgb = ImageOps.autocontrast(region.convert("RGB"), cutoff=1)
            rgb = ImageEnhance.Color(rgb).enhance(1.06)
            rgb = ImageEnhance.Sharpness(rgb).enhance(1.12)
            result = rgb.convert("RGBA")
            result.putalpha(alpha)
            return result

        self._apply_to_target(enhance, "Applied auto enhance")

    def grayscale(self) -> None:
        def gray(region: Image.Image) -> Image.Image:
            alpha = region.getchannel("A")
            out = ImageOps.grayscale(region).convert("RGBA")
            out.putalpha(alpha)
            return out

        self._apply_to_target(gray, "Converted to grayscale")

    def invert_colors(self) -> None:
        def invert(region: Image.Image) -> Image.Image:
            alpha = region.getchannel("A")
            rgb = ImageOps.invert(region.convert("RGB")).convert("RGBA")
            rgb.putalpha(alpha)
            return rgb

        self._apply_to_target(invert, "Inverted colors")

    # --------------------------- Transform ---------------------------
    def rotate(self, degrees: int) -> None:
        if self.image is None:
            return
        rotated = self.image.rotate(degrees, expand=True, resample=Image.Resampling.BICUBIC)
        direction = "left" if degrees > 0 else "right"
        self._commit_edit(rotated, f"Rotated 90° {direction}", refit=True)

    def flip_horizontal(self) -> None:
        if self.image is not None:
            self._commit_edit(ImageOps.mirror(self.image), "Flipped horizontally", preserve_masks=False)

    def flip_vertical(self) -> None:
        if self.image is not None:
            self._commit_edit(ImageOps.flip(self.image), "Flipped vertically", preserve_masks=False)

    def resize_image(self) -> None:
        if self.image is None:
            return
        dialog = ResizeDialog(self, self.image.width, self.image.height)
        self.wait_window(dialog)
        if dialog.result is None:
            return
        width, height = dialog.result
        resized = self.image.resize((width, height), Image.Resampling.LANCZOS)
        self._commit_edit(resized, f"Resized to {width} × {height}", refit=True)

    def reset_to_original(self) -> None:
        if self.image is None or self.original_image is None:
            return
        if not messagebox.askyesno(APP_NAME, "Reset every edit and return to the originally opened image?"):
            return
        self._snapshot()
        self.image = self.original_image.copy()
        self.show_before.set(False)
        self.preview_image = None
        self.selection = None
        self.focus_zones.clear()
        self.selected_face_index = None
        self.focus_preview = None
        self.lasso_points = []
        self.lasso_preview = []
        self.shape_preview = None
        self.tool_start_image = None
        self.tool_end_image = None
        self.clone_source = None
        self.clone_offset = None
        self.brush_before = None
        self.brush_source = None
        self.brush_last = None
        self.dirty = True
        self.fit_to_window()
        self._update_title()
        self._update_button_states()
        self._sync_active_document()
        self._set_status("Reset to original image")

    # --------------------------- Canvas / zoom ---------------------------
    def _draw_empty_state(self) -> None:
        if self.image is not None:
            return
        self.canvas.delete("all")
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        self.canvas.create_text(
            w / 2,
            h / 2 - 22,
            text="Drop into a faster editing flow",
            fill="#e8ebef",
            font=("Segoe UI", 20, "bold"),
        )
        self.canvas.create_text(
            w / 2,
            h / 2 + 18,
            text="Drop an image here, paste with Ctrl+V, or open a file.",
            fill="#838a96",
            font=("Segoe UI", 11),
        )
        self.canvas.create_text(
            w / 2,
            h / 2 + 58,
            text="Ctrl+V to paste  •  Ctrl+O to open",
            fill="#7e9aff",
            font=("Segoe UI", 10, "bold"),
        )

    def _on_canvas_resize(self, _event: tk.Event) -> None:
        if self.image is None:
            self._draw_empty_state()
        else:
            self._render_image()

    def fit_to_window(self) -> None:
        if self.image is None:
            return
        canvas_w = max(100, self.canvas.winfo_width() - 40)
        canvas_h = max(100, self.canvas.winfo_height() - 40)
        self.fit_zoom = min(canvas_w / self.image.width, canvas_h / self.image.height)
        self.zoom = max(0.02, min(self.fit_zoom, 16.0))
        self._render_image()

    def set_zoom(self, zoom: float) -> None:
        if self.image is None:
            return
        self.zoom = max(0.02, min(float(zoom), 16.0))
        self._render_image()

    def _mousewheel_zoom(self, event: tk.Event) -> None:
        if self.image is None:
            return
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_at_cursor(factor, event.x, event.y)

    def _zoom_at_cursor(self, factor: float, _x: float, _y: float) -> None:
        if self.image is None:
            return
        self.set_zoom(self.zoom * factor)

    def _render_image(self) -> None:
        if self.image is None:
            self._draw_empty_state()
            return
        canvas_w = max(1, self.canvas.winfo_width())
        canvas_h = max(1, self.canvas.winfo_height())
        display_w = max(1, int(round(self.image.width * self.zoom)))
        display_h = max(1, int(round(self.image.height * self.zoom)))

        if display_w * display_h > 80_000_000:
            self.zoom = math.sqrt(80_000_000 / (self.image.width * self.image.height))
            display_w = max(1, int(self.image.width * self.zoom))
            display_h = max(1, int(self.image.height * self.zoom))

        edited_image = self.preview_image if self.preview_image is not None else self.image
        if self.show_before.get() and self.original_image is not None:
            source_image = self.original_image.resize(self.image.size, Image.Resampling.LANCZOS)
        elif self.compare_mode.get() and self.original_image is not None:
            original = self.original_image.resize(self.image.size, Image.Resampling.LANCZOS)
            source_image = edited_image.copy()
            split = round(self.image.width * max(5, min(95, int(self.compare_split.get()))) / 100)
            source_image.paste(original.crop((0, 0, split, self.image.height)), (0, 0))
        else:
            source_image = edited_image
        if self.zoom < 1:
            resized = source_image.resize((display_w, display_h), Image.Resampling.LANCZOS)
        else:
            resized = source_image.resize((display_w, display_h), Image.Resampling.NEAREST if self.zoom >= 8 else Image.Resampling.BICUBIC)
        self.preview_photo = ImageTk.PhotoImage(resized)

        x0 = (canvas_w - display_w) / 2
        y0 = (canvas_h - display_h) / 2
        self.image_origin = (x0, y0)

        self.canvas.delete("all")
        self.canvas.create_rectangle(
            x0 - 2,
            y0 - 2,
            x0 + display_w + 2,
            y0 + display_h + 2,
            fill="#0b0c0f",
            outline="#2a2e36",
            width=2,
        )
        self.canvas.create_image(x0, y0, image=self.preview_photo, anchor="nw")
        if self.compare_mode.get() and not self.show_before.get():
            split_x = x0 + self.image.width * self.zoom * max(5, min(95, int(self.compare_split.get()))) / 100
            self.canvas.create_line(split_x, y0, split_x, y0 + display_h, fill="#ffffff", width=3)
            self.canvas.create_text(x0 + 48, y0 + 18, text="BEFORE", fill="white", font=("Segoe UI", 9, "bold"))
            self.canvas.create_text(x0 + display_w - 42, y0 + 18, text="AFTER", fill="white", font=("Segoe UI", 9, "bold"))
        self._draw_focus_zones()
        self._draw_lasso()
        self._draw_shape_preview()
        self._draw_clone_source()
        self._draw_selection()
        self.zoom_text.set(f"{self.zoom * 100:.0f}%")
        self._update_status_dimensions()

    def _draw_focus_zones(self) -> None:
        if not self.focus_zones and not self.focus_preview:
            return
        x0, y0 = self.image_origin
        items = list(self.focus_zones)
        if self.focus_preview is not None:
            items.append(self.focus_preview)
        for index, zone in enumerate(items, start=1):
            left = x0 + zone.left * self.zoom
            top = y0 + zone.top * self.zoom
            right = x0 + zone.right * self.zoom
            bottom = y0 + zone.bottom * self.zoom
            is_preview = zone is self.focus_preview
            is_selected = (not is_preview) and (self.selected_face_index == index - 1)
            outline = "#ff9b54" if is_selected else ("#9ef6b3" if not is_preview else "#ffe38a")
            self.canvas.create_oval(left, top, right, bottom, outline="#ffffff", width=3, dash=(7, 5))
            self.canvas.create_oval(left, top, right, bottom, outline=outline, width=1, dash=(7, 5))
            label = f"Face {index}" if zone is not self.focus_preview else "New"
            self.canvas.create_rectangle(left, max(0, top - 24), left + 58, top, fill=outline, outline="")
            self.canvas.create_text(left + 29, max(12, top - 12), text=label, fill="#111318", font=("Segoe UI", 9, "bold"))
            if is_selected:
                self._draw_mask_handles(left, top, right, bottom, outline)

    def _draw_lasso(self) -> None:
        points = self.lasso_preview if self.lasso_preview else self.lasso_points
        if len(points) < 2:
            return
        x0, y0 = self.image_origin
        canvas_points: list[float] = []
        for x, y in points:
            canvas_points.extend((x0 + x * self.zoom, y0 + y * self.zoom))
        if self.lasso_preview:
            self.canvas.create_line(*canvas_points, fill="#ffe38a", width=2, smooth=True)
        else:
            self.canvas.create_polygon(*canvas_points, outline="#ffffff", fill="", width=3, dash=(7, 5))
            self.canvas.create_polygon(*canvas_points, outline="#c879ff", fill="", width=1, dash=(7, 5))

    def _draw_mask_handles(self, left: float, top: float, right: float, bottom: float, color: str) -> None:
        size = 5
        for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)):
            self.canvas.create_rectangle(x - size, y - size, x + size, y + size, fill=color, outline="#ffffff", width=1)

    def _draw_shape_preview(self) -> None:
        if self.shape_preview is None or self.tool_start_image is None or self.tool_end_image is None:
            return
        x0, y0 = self.image_origin
        start = (x0 + self.tool_start_image[0] * self.zoom, y0 + self.tool_start_image[1] * self.zoom)
        end = (x0 + self.tool_end_image[0] * self.zoom, y0 + self.tool_end_image[1] * self.zoom)
        width = max(1, round(int(self.shape_width.get()) * self.zoom))
        color = self.shape_color.get()
        if self.draw_mode.get() == "box":
            self.canvas.create_rectangle(start[0], start[1], end[0], end[1], outline="#ffffff", width=width + 2, dash=(7, 5))
            self.canvas.create_rectangle(start[0], start[1], end[0], end[1], outline=color, width=width, dash=(7, 5))
        else:
            self.canvas.create_line(start[0], start[1], end[0], end[1], fill="#ffffff", width=width + 2, arrow="last", arrowshape=(14, 18, 7))
            self.canvas.create_line(start[0], start[1], end[0], end[1], fill=color, width=width, arrow="last", arrowshape=(14, 18, 7))

    def _draw_clone_source(self) -> None:
        if self.clone_source is None or self.image is None:
            return
        x0, y0 = self.image_origin
        x = x0 + self.clone_source[0] * self.zoom
        y = y0 + self.clone_source[1] * self.zoom
        radius = max(7, int(self.brush_size.get()) * self.zoom / 2)
        self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline="#ffffff", width=3, dash=(5, 4))
        self.canvas.create_line(x - 9, y, x + 9, y, fill="#ffcc66", width=2)
        self.canvas.create_line(x, y - 9, x, y + 9, fill="#ffcc66", width=2)

    def _draw_selection(self) -> None:
        if not self.selection:
            return
        x0, y0 = self.image_origin
        left = x0 + self.selection.left * self.zoom
        top = y0 + self.selection.top * self.zoom
        right = x0 + self.selection.right * self.zoom
        bottom = y0 + self.selection.bottom * self.zoom
        self.canvas.create_rectangle(left, top, right, bottom, outline="#ffffff", width=3, dash=(7, 5))
        self.canvas.create_rectangle(left, top, right, bottom, outline="#5b7cfa", width=1, dash=(7, 5))
        label = f"{self.selection.width} × {self.selection.height}"
        self.canvas.create_rectangle(left, max(0, top - 25), left + 94, top, fill="#5b7cfa", outline="")
        self.canvas.create_text(left + 47, max(12, top - 13), text=label, fill="white", font=("Segoe UI", 9, "bold"))
        self._draw_mask_handles(left, top, right, bottom, "#5b7cfa")

    def _canvas_to_image(self, canvas_x: float, canvas_y: float, clamp: bool = False) -> tuple[float, float]:
        assert self.image is not None
        x0, y0 = self.image_origin
        x = (canvas_x - x0) / self.zoom
        y = (canvas_y - y0) / self.zoom
        if clamp:
            x = min(max(x, 0), self.image.width)
            y = min(max(y, 0), self.image.height)
        return x, y

    def _canvas_point_inside_image(self, x: float, y: float) -> bool:
        if self.image is None:
            return False
        ix, iy = self._canvas_to_image(x, y)
        return 0 <= ix <= self.image.width and 0 <= iy <= self.image.height

    # --------------------------- Helpers ---------------------------
    def _sidebar_mousewheel(self, _event: tk.Event) -> None:
        return

    @staticmethod
    def _is_descendant(widget: tk.Widget, ancestor: tk.Widget) -> bool:
        current: Optional[tk.Widget] = widget
        while current is not None:
            if current == ancestor:
                return True
            current = current.master
        return False

    def _update_button_states(self) -> None:
        has_image = self.image is not None
        self.undo_button.configure(state="normal" if self.undo_stack else "disabled")
        self.redo_button.configure(state="normal" if self.redo_stack else "disabled")
        if not has_image:
            self.status_text.set("Open an image to begin")

    def _update_title(self) -> None:
        name = self.current_path.name if self.current_path else "Untitled"
        marker = " *" if self.dirty else ""
        self.title(f"{name}{marker} — {APP_NAME}")

    def _set_status(self, text: str) -> None:
        self.status_text.set(text)

    def _update_status_dimensions(self) -> None:
        if self.image is None:
            return
        selection_text = ""
        if self.selection:
            selection_text += f" • Selection {self.selection.width}×{self.selection.height}"
        if self.lasso_points:
            selection_text += f" • Lasso: {len(self.lasso_points)} points"
        if self.focus_zones:
            selection_text += f" • Face circles: {len(self.focus_zones)}"
        self.status_text.set(f"{self.image.width} × {self.image.height} px{selection_text}")


class TextToolDialog(tk.Toplevel):
    def __init__(self, parent: QuickFXEditor, initial_color: str) -> None:
        super().__init__(parent)
        self.title("Add Text")
        self.resizable(False, False)
        self.configure(bg="#202329")
        self.transient(parent)
        self.grab_set()
        self.result: Optional[tuple[str, int, str, bool]] = None
        self.size_var = tk.IntVar(value=48)
        self.color_var = tk.StringVar(value=initial_color)
        self.shadow_var = tk.BooleanVar(value=True)

        frame = ttk.Frame(self, style="Panel.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Text", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.text_box = tk.Text(frame, width=38, height=5, wrap="word", bg="#15181d", fg="#f3f5f7", insertbackground="#ffffff", relief="flat", padx=8, pady=8)
        self.text_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(frame, text="Font size", style="Muted.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(frame, from_=8, to=500, textvariable=self.size_var, width=9).grid(row=2, column=1, sticky="w")
        ttk.Button(frame, text="Choose color", command=self._choose_color).grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(frame, textvariable=self.color_var, style="Muted.TLabel").grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Checkbutton(frame, text="Drop shadow", variable=self.shadow_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 12))
        buttons = ttk.Frame(frame, style="Panel.TFrame")
        buttons.grid(row=5, column=0, columnspan=3, sticky="ew")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Add Text", command=self._accept, style="Accent.TButton").pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._accept())
        self.text_box.focus_set()
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _choose_color(self) -> None:
        chosen = colorchooser.askcolor(color=self.color_var.get(), title="Choose text color", parent=self)
        if chosen and chosen[1]:
            self.color_var.set(chosen[1])

    def _accept(self) -> None:
        value = self.text_box.get("1.0", "end-1c").strip()
        if not value:
            messagebox.showinfo(APP_NAME, "Enter some text first.", parent=self)
            return
        try:
            size = int(self.size_var.get())
            if not 8 <= size <= 500:
                raise ValueError
        except (TypeError, ValueError):
            messagebox.showerror(APP_NAME, "Font size must be between 8 and 500.", parent=self)
            return
        self.result = (value, size, self.color_var.get(), bool(self.shadow_var.get()))
        self.destroy()


class ResizeDialog(tk.Toplevel):
    def __init__(self, parent: QuickFXEditor, width: int, height: int) -> None:
        super().__init__(parent)
        self.title("Resize Image")
        self.resizable(False, False)
        self.configure(bg="#202329")
        self.transient(parent)
        self.grab_set()

        self.original_width = width
        self.original_height = height
        self.aspect = width / height if height else 1
        self.result: Optional[tuple[int, int]] = None
        self.lock_aspect = tk.BooleanVar(value=True)
        self.width_var = tk.StringVar(value=str(width))
        self.height_var = tk.StringVar(value=str(height))
        self._updating = False

        frame = ttk.Frame(self, style="Panel.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Resize image", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(frame, text="Width", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(frame, textvariable=self.width_var, width=14).grid(row=1, column=1, pady=5)
        ttk.Label(frame, text="Height", style="Muted.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        ttk.Entry(frame, textvariable=self.height_var, width=14).grid(row=2, column=1, pady=5)
        ttk.Checkbutton(frame, text="Keep aspect ratio", variable=self.lock_aspect).grid(row=3, column=0, columnspan=2, sticky="w", pady=(7, 14))

        buttons = ttk.Frame(frame, style="Panel.TFrame")
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Resize", command=self._accept, style="Accent.TButton").pack(side="right", padx=(0, 8))

        self.width_var.trace_add("write", self._width_changed)
        self.height_var.trace_add("write", self._height_changed)
        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _width_changed(self, *_args: object) -> None:
        if self._updating or not self.lock_aspect.get():
            return
        try:
            width = int(self.width_var.get())
        except ValueError:
            return
        self._updating = True
        self.height_var.set(str(max(1, round(width / self.aspect))))
        self._updating = False

    def _height_changed(self, *_args: object) -> None:
        if self._updating or not self.lock_aspect.get():
            return
        try:
            height = int(self.height_var.get())
        except ValueError:
            return
        self._updating = True
        self.width_var.set(str(max(1, round(height * self.aspect))))
        self._updating = False

    def _accept(self) -> None:
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            if not (1 <= width <= 50000 and 1 <= height <= 50000):
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Enter valid dimensions between 1 and 50,000 pixels.", parent=self)
            return
        self.result = (width, height)
        self.destroy()


def main() -> None:
    try:
        app = QuickFXEditor()
        app.mainloop()
    except Exception as exc:
        try:
            messagebox.showerror(APP_NAME, f"The app encountered an unexpected error.\n\n{exc}")
        except Exception:
            print(f"{APP_NAME} error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
