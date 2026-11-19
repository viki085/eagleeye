"""Remove the gold spotlight burned into the admin console recordings.

The recorder drew the spotlight in the page (media/tools/cursor.js #ee-spotlight): a 2 px gold
border with 10 px corners, a 7% gold tint inside, a 28 px gold glow outside, and a 38% black dim
over everything outside. Every term is known, so for a frame where the spotlight sits still on a
known rectangle, the page underneath can be recovered:

    outside:  out = 0.62 * (page * (1 - g) + gold * g)     g = 0.35 * blurred box mask
    inside:   out = page * 0.93 + gold * 0.07
    border:   0.95 gold over the page: unrecoverable, so painted in from either side

Only frames where the spotlight has settled are cleaned (the edit uses those); the recordings were
made at 1600 x 900 CSS pixels and 2.4x device scale.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from scipy.special import erf

SCALE = 2.4  # device pixels per CSS pixel (1600 x 900 viewport captured at 3840 x 2160)
PAD = 10  # cursor.js __eeSpotlight default padding (CSS px)
RADIUS = 10  # border-radius (CSS px)
BORDER = 2  # border width (CSS px)
GOLD = np.array([197, 163, 104], np.float32)[::-1]  # BGR
DIM = 0.38
TINT = 0.07
GLOW = 0.35
GLOW_SIGMA = 14  # a 28 px box-shadow blur is a Gaussian with sigma = blur / 2


def _rounded(h: int, w: int, x0: float, y0: float, x1: float, y1: float, r: float) -> np.ndarray:
    """Anti-aliased mask (0..1) of a rounded rectangle, rendered at 4x and downsampled."""
    k = 4
    m = np.zeros((h * k, w * k), np.uint8)
    xs0, ys0, xs1, ys1, rs = (round(v * k) for v in (x0, y0, x1, y1, r))
    cv2.rectangle(m, (xs0 + rs, ys0), (xs1 - rs, ys1), 255, -1)
    cv2.rectangle(m, (xs0, ys0 + rs), (xs1, ys1 - rs), 255, -1)
    for cx, cy in ((xs0 + rs, ys0 + rs), (xs1 - rs, ys0 + rs), (xs0 + rs, ys1 - rs), (xs1 - rs, ys1 - rs)):
        cv2.circle(m, (cx, cy), rs, 255, -1)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


class Unspot:
    """Precomputed maps for one spotlight rectangle (CSS px, as the recorder measured it)."""

    def __init__(self, box: dict, shape: tuple[int, int]):
        h, w = shape
        s = SCALE
        x0, y0 = (box["x"] - PAD) * s, (box["y"] - PAD) * s
        x1, y1 = (box["x"] + box["width"] + PAD) * s, (box["y"] + box["height"] + PAD) * s
        outer = _rounded(h, w, x0, y0, x1, y1, RADIUS * s)
        b = BORDER * s
        inner = _rounded(h, w, x0 + b, y0 + b, x1 - b, y1 - b, (RADIUS - BORDER) * s)
        sig = GLOW_SIGMA * s * math.sqrt(2)
        xs, ys = np.arange(w, dtype=np.float32) + 0.5, np.arange(h, dtype=np.float32) + 0.5
        gx = 0.5 * (erf((xs - x0) / sig) - erf((xs - x1) / sig))
        gy = 0.5 * (erf((ys - y0) / sig) - erf((ys - y1) / sig))
        glow = GLOW * np.outer(gy, gx).astype(np.float32) * (1 - outer)
        out_w = 1 - outer  # weight of the outside model
        self.inner = inner[..., None]
        self.ring = np.clip(outer - inner, 0, 1)
        # outside: page = (out / (1 - DIM) - gold * g) / (1 - g)
        self.o_scale = (out_w / ((1 - DIM) * (1 - glow)))[..., None]
        self.o_off = (out_w * glow / (1 - glow))[..., None] * GOLD
        # inside: page = (out - gold * TINT) / (1 - TINT)
        self.i_scale = self.inner / (1 - TINT)
        self.i_off = self.inner * GOLD * TINT / (1 - TINT)
        # the ring, dilated a little so compression smear around it is repainted too
        self.fill = (cv2.dilate((self.ring > 0.02).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
        ys_, xs_ = np.nonzero(self.fill)
        self.crop = (max(ys_.min() - 8, 0), min(ys_.max() + 9, h), max(xs_.min() - 8, 0), min(xs_.max() + 9, w))

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        f = frame.astype(np.float32)
        page = f * self.o_scale - self.o_off + f * self.i_scale - self.i_off
        page = np.clip(page, 0, 255).astype(np.uint8)
        y0, y1, x0, x1 = self.crop
        crop = page[y0:y1, x0:x1]
        mask = self.fill[y0:y1, x0:x1].astype(np.uint8) * 255
        page[y0:y1, x0:x1] = cv2.inpaint(crop, mask, 4, cv2.INPAINT_TELEA)
        return page
