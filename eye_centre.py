"""Reference implementation of Timm & Barth eye-centre localisation ("Accurate
Eye Centre Localisation by Means of Gradients", 2011).

The browser runs this algorithm on a small grayscale crop of each eye and
sends the result in `frame.eye_centres`. This service never sees pixels. This
module is the specification the browser implementation must reproduce
(tests/golden/eye_centre.json); see docs/eye-centre.md for the crop definition.
"""

import numpy as np

CROP_WIDTH = 40
CROP_HEIGHT = 20

# Gradients weaker than mean + factor * std of the gradient magnitudes are
# ignored (the paper's threshold).
GRADIENT_THRESHOLD_FACTOR = 0.3

# Std-dev (px) of the blur applied before the "dark centre" weighting.
WEIGHT_BLUR_SIGMA = 1.0

# Peaks closer than this (px) to the best centre are part of the same peak when
# measuring confidence.
PEAK_EXCLUSION_RADIUS = 5.0


def _gaussian_blur(image, sigma):

    radius = max(1, int(round(3 * sigma)))
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-(offsets ** 2) / (2 * sigma ** 2))
    kernel /= kernel.sum()

    blurred = image
    for axis in (0, 1):
        padded = np.pad(blurred, [(radius, radius) if a == axis else (0, 0) for a in (0, 1)], mode="edge")
        blurred = np.apply_along_axis(lambda line: np.convolve(line, kernel, mode="valid"), axis, padded)

    return blurred


def locate_eye_centre(crop):
    """The eye centre in a CROP_HEIGHT x CROP_WIDTH grayscale crop (0-255,
    dark = low), as `(x, y, confidence)`, x and y normalized 0-1 to the crop.

    The centre is the point whose displacement vectors to the strong gradient
    pixels line up best with those gradients (the paper's objective), weighted
    towards dark points, and counting only gradients that point away from the
    centre. `confidence` (0-1) is how far the best peak stands above the best
    peak that is not next to it: 1 for one clear centre, near 0 when several
    places fit equally well. A crop without gradients returns confidence 0.
    """

    image = np.asarray(crop, dtype=np.float64)

    if image.shape != (CROP_HEIGHT, CROP_WIDTH):
        raise ValueError(f"crop must be {CROP_HEIGHT}x{CROP_WIDTH} (rows x columns)")
    if not np.isfinite(image).all():
        raise ValueError("crop contains non-finite pixels")

    gradient_y, gradient_x = np.gradient(image)
    magnitude = np.hypot(gradient_x, gradient_y)

    strong = magnitude > magnitude.mean() + GRADIENT_THRESHOLD_FACTOR * magnitude.std()

    if not strong.any():
        return 0.5, 0.5, 0.0

    rows, columns = np.nonzero(strong)
    unit_x = gradient_x[strong] / magnitude[strong]
    unit_y = gradient_y[strong] / magnitude[strong]

    centre_rows, centre_columns = np.mgrid[0:CROP_HEIGHT, 0:CROP_WIDTH]
    centre_rows = centre_rows.ravel()[:, None]
    centre_columns = centre_columns.ravel()[:, None]

    displacement_x = columns[None, :] - centre_columns
    displacement_y = rows[None, :] - centre_rows
    distance = np.hypot(displacement_x, displacement_y)
    distance[distance == 0] = np.inf    # a gradient at the candidate itself says nothing

    alignment = np.maximum((displacement_x * unit_x + displacement_y * unit_y) / distance, 0.0)

    weight = (255.0 - _gaussian_blur(image, WEIGHT_BLUR_SIGMA)).ravel() / 255.0
    objective = ((alignment ** 2).sum(axis=1) / len(unit_x) * np.clip(weight, 0.0, 1.0))
    objective = objective.reshape(CROP_HEIGHT, CROP_WIDTH)

    best_row, best_column = np.unravel_index(np.argmax(objective), objective.shape)
    best = objective[best_row, best_column]

    if best <= 0:
        return 0.5, 0.5, 0.0

    far = np.hypot(centre_rows.reshape(objective.shape) - best_row,
                   centre_columns.reshape(objective.shape) - best_column) > PEAK_EXCLUSION_RADIUS
    runner_up = objective[far].max() if far.any() else 0.0

    confidence = float(np.clip(1.0 - runner_up / best, 0.0, 1.0))

    return (best_column + 0.5) / CROP_WIDTH, (best_row + 0.5) / CROP_HEIGHT, confidence
