# QuickFX Editor v1.8

QuickFX is a lightweight Windows image editor for fast censoring, annotations, creative effects, and everyday corrections.

## The v1.8 workflow change

Selections and protected faces are now persistent editing masks. Applying an effect or using Undo no longer removes them.

A typical censor test is now:

1. Draw the face circles once.
2. Choose **Pixelate**.
3. Press **Preview**.
4. Move the pixel-size slider until the result looks right.
5. Press **Apply**.

The preview is non-destructive. Slider changes refresh it automatically. **Undo** restores the previous image while keeping the face circles, rectangle, or lasso ready for another test.

## New in v1.8

- **Persistent masks through Apply, Undo, and Redo**
- **Live preview for Blur, Pixelate, Mosaic, and Black**
- **Direct on-canvas mask editing**
  - Drag a rectangle or face circle to move it
  - Drag corner handles to resize it
  - Select, duplicate, or delete individual face circles
- **Freehand lasso selections** for effects and transparent lasso crops
- **Before/after comparison slider** with a movable split
- **Multiple image tabs**, each with separate masks, zoom, undo, and redo
- **Autosave and crash recovery** for unsaved tabs
- Existing presets and batch processing remain available

## Start the app

1. Extract the entire ZIP to a normal folder.
2. Double-click `run_quickfx.bat`.
3. On first launch, QuickFX creates a private `.venv` and installs its dependencies automatically.

Python 3.10 and newer are supported, including Python 3.13.

## Main areas

- **Censor:** rectangle, lasso, protected faces, censor brushes, clone, and heal
- **Annotate:** text, stickers, arrows, and boxes
- **Adjust:** corrections, filters, creative effects, presets, and batch processing
- **Transform:** crop, resize, rotate, flip, cinematic bars, and reset

## Open images

- Drag one or several image files onto the app; each opens in its own tab
- Press `Ctrl+V` to paste a copied image or copied image file
- Click **Open** or press `Ctrl+O`

## Shortcuts

- `Ctrl+O`: Open in a new tab
- `Ctrl+V`: Paste image into a new tab
- `Ctrl+W`: Close current tab
- `Ctrl+S`: Save
- `Ctrl+Shift+S`: Save As
- `Ctrl+Z`: Undo while preserving masks
- `Ctrl+Y`: Redo while preserving masks
- `Esc`: Clear rectangle or lasso selection
- `Backspace`: Clear protected face circles
- Hold `B`: Temporarily show the original image
- `F`: Fit to window
- `1`: 100% zoom

## Recovery

Dirty tabs are autosaved every 30 seconds. If QuickFX or Windows closes unexpectedly, the next launch offers to restore them.

## Build a standalone executable

Double-click `build_exe.bat`. The executable is created at:

```text
dist\QuickFXEditor.exe
```
