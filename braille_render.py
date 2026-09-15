import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]

_font_cache = {}


def _find_font_path():

    for path in _FONT_CANDIDATES:
        try:
            ImageFont.truetype(path, 10)
            return path
        except OSError:
            continue

    raise RuntimeError(
        "No TrueType font with Braille glyph support found. "
        "Install DejaVu Sans (e.g. `apt install fonts-dejavu`)."
    )


def _font(size):

    if size not in _font_cache:
        _font_cache[size] = ImageFont.truetype(_find_font_path(), size)

    return _font_cache[size]


def cell_geometry(canvas_width, canvas_height, passage):

    cell_width = canvas_width / passage.num_columns
    line_height = canvas_height / passage.num_rows

    return cell_width, line_height


def _to_bgr(image):

    return np.array(image.convert("RGB"))[:, :, ::-1].copy()


def _new_canvas(canvas_width, canvas_height):

    image = Image.new("RGB", (canvas_width, canvas_height), "black")

    return image, ImageDraw.Draw(image)


def render_calibration_frame(canvas_width, canvas_height, point, radius=15):

    image, draw = _new_canvas(canvas_width, canvas_height)

    x = int(point[0] * canvas_width)
    y = int(point[1] * canvas_height)

    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill="white",
    )

    return _to_bgr(image)


def render_passage_frame(canvas_width, canvas_height, passage, highlight_cell=None):

    image, draw = _new_canvas(canvas_width, canvas_height)

    cell_width, line_height = cell_geometry(canvas_width, canvas_height, passage)
    font = _font(int(min(cell_width, line_height) * 0.6))

    for row, line in enumerate(passage.braille_lines):
        for column, glyph in enumerate(line):

            cx = column * cell_width + cell_width / 2
            cy = row * line_height + line_height / 2

            if highlight_cell == (row, column):
                draw.rectangle(
                    [column * cell_width, row * line_height,
                     (column + 1) * cell_width, (row + 1) * line_height],
                    fill="#333333",
                )

            draw.text((cx, cy), glyph, font=font, fill="white", anchor="mm")

    return _to_bgr(image)


def render_result_frame(canvas_width, canvas_height, result):

    image, draw = _new_canvas(canvas_width, canvas_height)

    font = _font(28)

    lines = [
        f"Reading Speed: {result['cpm']:.1f} CPM / {result['wpm']:.1f} WPM",
        f"Elapsed: {result['elapsed_seconds']:.1f}s",
        f"Saccades: {result['saccades']}",
        f"Regressions: {result['regressions']}",
        f"Skipped characters: {result['skipped_characters']}",
        "",
        "Press any key to exit",
    ]

    for i, line in enumerate(lines):
        draw.text((40, 40 + i * 40), line, font=font, fill="white")

    return _to_bgr(image)
