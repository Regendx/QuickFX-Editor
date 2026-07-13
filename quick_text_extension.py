from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk
from typing import Any, Optional

from PIL import Image, ImageColor, ImageDraw


def install(quickfx_module: Any) -> None:
    """Install the Quick Text workflow onto QuickFXEditor."""
    editor_class = quickfx_module.QuickFXEditor
    if getattr(editor_class, "_quick_text_extension_installed", False):
        return

    original_init = editor_class.__init__
    original_build_annotate_options = editor_class._build_annotate_options
    original_place_text = editor_class._place_text

    def extended_init(self: Any) -> None:
        original_init(self)
        self.quick_text = tk.StringVar(value="Text")
        self.text_size = tk.IntVar(value=48)
        self.text_color = tk.StringVar(value="#ffffff")
        self.text_background = tk.BooleanVar(value=False)
        self.text_background_color = tk.StringVar(value="#000000")
        self.text_background_opacity = tk.IntVar(value=75)
        self.text_outline = tk.BooleanVar(value=True)
        self.text_outline_color = tk.StringVar(value="#000000")
        self.text_outline_width = tk.IntVar(value=2)
        self.text_shadow = tk.BooleanVar(value=True)
        self.text_alignment = tk.StringVar(value="center")
        self.text_style = tk.StringVar(value="Caption")
        self.text_padding = tk.IntVar(value=10)
        self.text_anchor: Optional[tuple[int, int]] = None
        self.recent_texts: list[str] = []
        self.recent_text_choice = tk.StringVar(value="")
        self.quick_text_data_path = Path.home() / ".quickfx_text.json"
        self._load_quick_text_data()

        for variable in (
            self.quick_text,
            self.text_size,
            self.text_color,
            self.text_background,
            self.text_background_color,
            self.text_background_opacity,
            self.text_outline,
            self.text_outline_color,
            self.text_outline_width,
            self.text_shadow,
            self.text_alignment,
            self.text_padding,
        ):
            variable.trace_add("write", self._refresh_text_preview)

        self.bind_all(
            "<Control-Return>",
            lambda _event: self.apply_quick_text() if self.draw_mode.get() == "text" else None,
        )
        self._refresh_tool_options()

    def extended_build_annotate_options(self: Any, mode: str) -> None:
        if mode != "text" or not hasattr(self, "quick_text"):
            original_build_annotate_options(self, mode)
            return

        frame = self.annotate_options_frame
        self._hint(
            frame,
            "Type once, click the image to position it, adjust the style live, then Apply. Advanced supports multiline text.",
        )

        ttk.Label(frame, text="Quick text", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        ttk.Entry(frame, textvariable=self.quick_text).pack(fill="x", pady=(0, 8))

        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Style", style="Muted.TLabel").pack(side="left")
        style_combo = ttk.Combobox(
            row,
            textvariable=self.text_style,
            state="readonly",
            values=("Caption", "Title", "Subtitle", "Meme", "Label"),
            width=14,
        )
        style_combo.pack(side="right", fill="x", expand=True, padx=(8, 0))
        style_combo.bind("<<ComboboxSelected>>", self._apply_quick_text_style)

        self._slider(frame, "Font size", self.text_size, 8, 300, resolution=1)

        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Alignment", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(
            row,
            textvariable=self.text_alignment,
            state="readonly",
            values=("left", "center", "right"),
            width=12,
        ).pack(side="right")

        toggles = ttk.Frame(frame, style="Panel.TFrame")
        toggles.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(toggles, text="Background", variable=self.text_background).pack(side="left")
        ttk.Checkbutton(toggles, text="Outline", variable=self.text_outline).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(toggles, text="Shadow", variable=self.text_shadow).pack(side="left", padx=(8, 0))

        colors = ttk.Frame(frame, style="Panel.TFrame")
        colors.pack(fill="x", pady=(0, 8))
        ttk.Button(colors, text="Text color", command=self.choose_text_color).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(colors, text="Background", command=self.choose_text_background_color).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(colors, text="Outline", command=self.choose_text_outline_color).pack(side="left", fill="x", expand=True, padx=(3, 0))

        self._slider(frame, "Outline width", self.text_outline_width, 0, 12, resolution=1)
        self._slider(frame, "Background opacity", self.text_background_opacity, 0, 100, resolution=1)
        self._slider(frame, "Padding", self.text_padding, 0, 40, resolution=1)

        actions = ttk.Frame(frame, style="Panel.TFrame")
        actions.pack(fill="x", pady=(2, 8))
        ttk.Button(actions, text="Preview / Reposition", command=self.preview_quick_text).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(actions, text="Apply", command=self.apply_quick_text, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(actions, text="Cancel", command=self.cancel_text_preview).pack(side="left", fill="x", expand=True, padx=(3, 0))

        actions2 = ttk.Frame(frame, style="Panel.TFrame")
        actions2.pack(fill="x", pady=(0, 8))
        ttk.Button(actions2, text="Place Center", command=self.place_quick_text_center).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(actions2, text="Advanced…", command=self.open_advanced_text_dialog).pack(side="left", fill="x", expand=True, padx=(4, 0))

        ttk.Label(frame, text="Recent text", style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        recent = ttk.Frame(frame, style="Panel.TFrame")
        recent.pack(fill="x")
        self.recent_text_combo = ttk.Combobox(
            recent,
            textvariable=self.recent_text_choice,
            state="readonly",
            values=tuple(self.recent_texts),
        )
        self.recent_text_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(recent, text="Use", command=self.use_recent_text).pack(side="left")

    def extended_place_text(self: Any, point: tuple[int, int]) -> None:
        if not hasattr(self, "quick_text"):
            original_place_text(self, point)
            return
        if self.image is None:
            return
        self.text_anchor = point
        self.preview_quick_text()

    def load_quick_text_data(self: Any) -> None:
        self.recent_texts = []
        try:
            if self.quick_text_data_path.exists():
                payload = json.loads(self.quick_text_data_path.read_text(encoding="utf-8"))
                values = payload.get("recent_texts", []) if isinstance(payload, dict) else []
                if isinstance(values, list):
                    self.recent_texts = [str(item) for item in values if str(item).strip()][:10]
                    if self.recent_texts:
                        self.recent_text_choice.set(self.recent_texts[0])
        except Exception:
            self.recent_texts = []

    def save_quick_text_data(self: Any) -> None:
        try:
            self.quick_text_data_path.write_text(
                json.dumps({"recent_texts": self.recent_texts}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def choose_text_color(self: Any) -> None:
        chosen = colorchooser.askcolor(color=self.text_color.get(), title="Choose text color", parent=self)
        if chosen and chosen[1]:
            self.text_color.set(chosen[1])

    def choose_text_background_color(self: Any) -> None:
        chosen = colorchooser.askcolor(color=self.text_background_color.get(), title="Choose text background color", parent=self)
        if chosen and chosen[1]:
            self.text_background_color.set(chosen[1])
            self.text_background.set(True)

    def choose_text_outline_color(self: Any) -> None:
        chosen = colorchooser.askcolor(color=self.text_outline_color.get(), title="Choose text outline color", parent=self)
        if chosen and chosen[1]:
            self.text_outline_color.set(chosen[1])
            self.text_outline.set(True)

    def apply_quick_text_style(self: Any, _event: Optional[tk.Event] = None) -> None:
        styles: dict[str, dict[str, object]] = {
            "Caption": {"size": 48, "alignment": "center", "background": False, "outline": True, "outline_width": 2, "shadow": True, "text_color": "#ffffff"},
            "Title": {"size": 76, "alignment": "center", "background": False, "outline": True, "outline_width": 3, "shadow": True, "text_color": "#ffffff"},
            "Subtitle": {"size": 36, "alignment": "center", "background": True, "background_opacity": 70, "outline": False, "outline_width": 0, "shadow": False, "text_color": "#ffffff", "padding": 12},
            "Meme": {"size": 64, "alignment": "center", "background": False, "outline": True, "outline_width": 5, "shadow": False, "text_color": "#ffffff"},
            "Label": {"size": 30, "alignment": "left", "background": True, "background_opacity": 85, "outline": False, "outline_width": 0, "shadow": False, "text_color": "#ffffff", "padding": 10},
        }
        style = styles.get(self.text_style.get(), styles["Caption"])
        self.text_size.set(int(style.get("size", 48)))
        self.text_alignment.set(str(style.get("alignment", "center")))
        self.text_background.set(bool(style.get("background", False)))
        self.text_background_opacity.set(int(style.get("background_opacity", 75)))
        self.text_outline.set(bool(style.get("outline", True)))
        self.text_outline_width.set(int(style.get("outline_width", 2)))
        self.text_shadow.set(bool(style.get("shadow", True)))
        self.text_color.set(str(style.get("text_color", "#ffffff")))
        self.text_padding.set(int(style.get("padding", 10)))
        self._set_status(f"Text style: {self.text_style.get()}")

    def color_with_alpha(_self: Any, color: str, alpha: int) -> tuple[int, int, int, int]:
        try:
            red, green, blue = ImageColor.getrgb(color)
        except ValueError:
            red, green, blue = (0, 0, 0)
        return red, green, blue, max(0, min(255, alpha))

    def text_metrics(self: Any, value: str, size: int, alignment: str, stroke_width: int) -> tuple[Any, tuple[int, int, int, int], int]:
        font = self._load_font(size)
        spacing = max(2, size // 8)
        probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        bbox = draw.multiline_textbbox(
            (0, 0),
            value,
            font=font,
            spacing=spacing,
            align=alignment,
            stroke_width=stroke_width,
        )
        return font, bbox, spacing

    def render_quick_text(self: Any, base: Image.Image, point: tuple[int, int], value: str) -> Image.Image:
        size = max(8, int(self.text_size.get()))
        alignment = self.text_alignment.get() if self.text_alignment.get() in {"left", "center", "right"} else "left"
        outline_width = max(0, int(self.text_outline_width.get())) if self.text_outline.get() else 0
        font, bbox, spacing = self._quick_text_metrics(value, size, alignment, outline_width)
        padding = max(0, int(self.text_padding.get()))
        text_width = max(1, bbox[2] - bbox[0])
        text_height = max(1, bbox[3] - bbox[1])
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x, y = point
        text_x = x + padding - bbox[0]
        text_y = y + padding - bbox[1]

        if self.text_background.get():
            alpha = round(255 * max(0, min(100, int(self.text_background_opacity.get()))) / 100)
            background = self._quick_text_color_with_alpha(self.text_background_color.get(), alpha)
            draw.rounded_rectangle(
                (x, y, x + text_width + padding * 2, y + text_height + padding * 2),
                radius=max(2, min(24, padding)),
                fill=background,
            )

        if self.text_shadow.get():
            offset = max(2, size // 18)
            draw.multiline_text(
                (text_x + offset, text_y + offset),
                value,
                font=font,
                fill=(0, 0, 0, 180),
                spacing=spacing,
                align=alignment,
                stroke_width=outline_width,
                stroke_fill=(0, 0, 0, 200),
            )

        draw.multiline_text(
            (text_x, text_y),
            value,
            font=font,
            fill=self.text_color.get(),
            spacing=spacing,
            align=alignment,
            stroke_width=outline_width,
            stroke_fill=self.text_outline_color.get(),
        )
        return Image.alpha_composite(base.convert("RGBA"), layer)

    def quick_text_dimensions(self: Any, value: str) -> tuple[int, int]:
        size = max(8, int(self.text_size.get()))
        alignment = self.text_alignment.get() if self.text_alignment.get() in {"left", "center", "right"} else "left"
        outline_width = max(0, int(self.text_outline_width.get())) if self.text_outline.get() else 0
        _font, bbox, _spacing = self._quick_text_metrics(value, size, alignment, outline_width)
        padding = max(0, int(self.text_padding.get()))
        return max(1, bbox[2] - bbox[0]) + padding * 2, max(1, bbox[3] - bbox[1]) + padding * 2

    def preview_quick_text(self: Any) -> None:
        if self.image is None:
            return
        value = self.quick_text.get().strip()
        if not value:
            self._set_status("Enter text first")
            return
        if self.text_anchor is None:
            width, height = self._quick_text_dimensions(value)
            self.text_anchor = (
                max(0, (self.image.width - width) // 2),
                max(0, (self.image.height - height) // 2),
            )
        self.preview_image = self._render_quick_text(self.image.copy(), self.text_anchor, value)
        self._render_image()
        self._set_status("Text preview active — click to reposition, edit settings, then Apply")

    def refresh_text_preview(self: Any, *_args: object) -> None:
        if self.text_anchor is not None and self.preview_image is not None and self.image is not None and self.draw_mode.get() == "text":
            self.after_idle(self.preview_quick_text)

    def apply_quick_text(self: Any) -> None:
        if self.image is None:
            return
        if self.text_anchor is None or self.preview_image is None:
            self.preview_quick_text()
        if self.text_anchor is None or self.preview_image is None:
            return
        value = self.quick_text.get().strip()
        edited = self.preview_image.copy()
        self.preview_image = None
        self.text_anchor = None
        self._remember_recent_text(value)
        try:
            self._commit_edit(edited, "Added quick text", preserve_masks=True)
        except TypeError:
            self._commit_edit(edited, "Added quick text")

    def cancel_text_preview(self: Any) -> None:
        if self.text_anchor is None:
            return
        self.preview_image = None
        self.text_anchor = None
        self._render_image()
        self._set_status("Text preview cancelled")

    def place_quick_text_center(self: Any) -> None:
        if self.image is None:
            return
        value = self.quick_text.get().strip()
        if not value:
            self._set_status("Enter text first")
            return
        width, height = self._quick_text_dimensions(value)
        self.text_anchor = (
            max(0, (self.image.width - width) // 2),
            max(0, (self.image.height - height) // 2),
        )
        self.preview_quick_text()

    def open_advanced_text_dialog(self: Any) -> None:
        if self.image is None:
            return
        dialog = quickfx_module.TextToolDialog(self, self.text_color.get())
        self.wait_window(dialog)
        if dialog.result is None:
            return
        value, size, color, shadow = dialog.result
        self.quick_text.set(value)
        self.text_size.set(size)
        self.text_color.set(color)
        self.text_shadow.set(shadow)
        if self.text_anchor is None:
            width, height = self._quick_text_dimensions(value)
            self.text_anchor = (
                max(0, (self.image.width - width) // 2),
                max(0, (self.image.height - height) // 2),
            )
        self.preview_quick_text()

    def remember_recent_text(self: Any, value: str) -> None:
        clean = value.strip()
        if not clean:
            return
        self.recent_texts = [item for item in self.recent_texts if item != clean]
        self.recent_texts.insert(0, clean)
        del self.recent_texts[10:]
        self.recent_text_choice.set(clean)
        if hasattr(self, "recent_text_combo"):
            self.recent_text_combo.configure(values=tuple(self.recent_texts))
        self._save_quick_text_data()

    def use_recent_text(self: Any) -> None:
        value = self.recent_text_choice.get().strip()
        if value:
            self.quick_text.set(value)
            self._set_status("Loaded recent text")

    editor_class.__init__ = extended_init
    editor_class._build_annotate_options = extended_build_annotate_options
    editor_class._place_text = extended_place_text
    editor_class._load_quick_text_data = load_quick_text_data
    editor_class._save_quick_text_data = save_quick_text_data
    editor_class.choose_text_color = choose_text_color
    editor_class.choose_text_background_color = choose_text_background_color
    editor_class.choose_text_outline_color = choose_text_outline_color
    editor_class._apply_quick_text_style = apply_quick_text_style
    editor_class._quick_text_color_with_alpha = color_with_alpha
    editor_class._quick_text_metrics = text_metrics
    editor_class._render_quick_text = render_quick_text
    editor_class._quick_text_dimensions = quick_text_dimensions
    editor_class.preview_quick_text = preview_quick_text
    editor_class._refresh_text_preview = refresh_text_preview
    editor_class.apply_quick_text = apply_quick_text
    editor_class.cancel_text_preview = cancel_text_preview
    editor_class.place_quick_text_center = place_quick_text_center
    editor_class.open_advanced_text_dialog = open_advanced_text_dialog
    editor_class._remember_recent_text = remember_recent_text
    editor_class.use_recent_text = use_recent_text
    editor_class._quick_text_extension_installed = True
