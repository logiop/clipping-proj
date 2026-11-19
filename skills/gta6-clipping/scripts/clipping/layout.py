"""Layout: find the streamer's facecam and plan the 1080x1920 vertical arrangement."""
import statistics
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional, Sequence

import cv2
import numpy as np

from . import config

OUT_W, OUT_H = 1080, 1920
CAM_OUT_H = 640
GAME_OUT_H = OUT_H - CAM_OUT_H
CAM_ASPECT = OUT_W / CAM_OUT_H
GAME_ASPECT = OUT_W / GAME_OUT_H
FACE_ASPECT = OUT_W / OUT_H

YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_SCORE_THRESHOLD = 0.8
MIN_PRESENCE = 0.60          # fraction of sampled frames that must contain the face
STABLE_FRACTION = 0.05       # max center drift from the median, as a fraction of frame width
CORNER_FRACTION = 0.40       # outer share of width and height that counts as a corner
MAX_CAM_AREA = 0.15          # a facecam face is smaller than this share of the frame
BIG_FACE_AREA = 0.15         # a face larger than this share of the frame is "big"
CAM_EXPAND = 1.8
FACE_CROP_HEIGHT_FACTOR = 3.0
KINDS = ("stream", "face", "fit")
FORCED_VALUES = ("auto",) + KINDS


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass(frozen=True)
class LayoutPlan:
    """Everything the ffmpeg filter graph needs, in source pixels.

    stream: `cam` crop scaled to 1080x640 on top, `game` center crop scaled to 1080x1280 below.
    face:   `face` crop (9:16) scaled to 1080x1920.
    fit:    no crops; full frame scaled to 1080 wide over a blurred scaled-to-fill copy.
    """
    kind: str
    src_w: int
    src_h: int
    cam: Optional[Box] = None
    game: Optional[Box] = None
    face: Optional[Box] = None


@lru_cache(maxsize=4)
def _detector(width: int, height: int):
    model = config.paths().models / YUNET_MODEL
    if not model.exists():
        raise FileNotFoundError(f"YuNet model not found: {model}")
    return cv2.FaceDetectorYN.create(
        str(model), "", (width, height), score_threshold=FACE_SCORE_THRESHOLD
    )


def detect_faces(frame: np.ndarray) -> List[Box]:
    """Faces found by YuNet (score >= 0.8) in a BGR frame."""
    height, width = frame.shape[:2]
    detector = _detector(width, height)
    detector.setInputSize((width, height))
    _, found = detector.detect(frame)
    if found is None:
        return []
    return [Box(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in found]


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def _fit_aspect(cx: float, cy: float, w: float, h: float, aspect: float,
                src_w: int, src_h: int) -> Box:
    """Smallest box of `aspect` containing w x h around (cx, cy), shrunk and clamped to the frame."""
    out_w, out_h = (w, w / aspect) if w / h > aspect else (h * aspect, h)
    scale = min(1.0, src_w / out_w, src_h / out_h)
    out_h = _even(out_h * scale)
    out_w = min(_even(out_h * aspect), src_w // 2 * 2)
    x = min(max(int(round(cx - out_w / 2)), 0), src_w - out_w)
    y = min(max(int(round(cy - out_h / 2)), 0), src_h - out_h)
    return Box(x, y, out_w, out_h)


def _in_corner(cx: float, cy: float, frame_w: int, frame_h: int) -> bool:
    near_x = cx < frame_w * CORNER_FRACTION or cx > frame_w * (1 - CORNER_FRACTION)
    near_y = cy < frame_h * CORNER_FRACTION or cy > frame_h * (1 - CORNER_FRACTION)
    return near_x and near_y


def _median_box(boxes: Sequence[Box]) -> Box:
    return Box(*(int(statistics.median(getattr(b, f) for b in boxes)) for f in "xywh"))


def _largest(faces: Sequence[Box]) -> Optional[Box]:
    return max(faces, key=lambda b: b.area) if faces else None


def facecam_box(faces_per_frame: Sequence[Sequence[Box]], frame_w: int, frame_h: int) -> Optional[Box]:
    """Cam crop (aspect 1080:640) around a small, stable, corner face seen in >=60% of frames."""
    if not faces_per_frame:
        return None
    candidates = [f for f in (_largest(faces) for faces in faces_per_frame) if f is not None]
    if len(candidates) < MIN_PRESENCE * len(faces_per_frame):
        return None
    med = _median_box(candidates)
    drift = max(abs(f.cx - med.cx) for f in candidates)
    if drift > STABLE_FRACTION * frame_w:
        return None
    if not _in_corner(med.cx, med.cy, frame_w, frame_h):
        return None
    if med.area >= MAX_CAM_AREA * frame_w * frame_h:
        return None
    return _fit_aspect(med.cx, med.cy, med.w * CAM_EXPAND, med.h * CAM_EXPAND,
                       CAM_ASPECT, frame_w, frame_h)


def big_face(faces_per_frame: Sequence[Sequence[Box]], frame_w: int, frame_h: int) -> Optional[Box]:
    """Median box of a face filling >15% of the frame in >=60% of frames, else None."""
    if not faces_per_frame:
        return None
    largest = [f for f in (_largest(faces) for faces in faces_per_frame) if f is not None]
    big = [f for f in largest if f.area > BIG_FACE_AREA * frame_w * frame_h]
    if len(big) < MIN_PRESENCE * len(faces_per_frame):
        return None
    return _median_box(big)


def _face_crop(face: Box, src_w: int, src_h: int) -> Box:
    height = max(face.h * FACE_CROP_HEIGHT_FACTOR, face.w * 2 / FACE_ASPECT)
    return _fit_aspect(face.cx, face.cy, height * FACE_ASPECT, height, FACE_ASPECT, src_w, src_h)


def plan(src_w: int, src_h: int, cam: Optional[Box], forced: str = "auto",
         big_face: Optional[Box] = None) -> LayoutPlan:
    """Choose the layout. auto: stream if a cam was found, else face if a big face was found, else fit.

    `face` is "followed" by one static crop around the median face position (no per-frame tracking
    in this phase). Forcing a kind that lacks its input degrades to `fit`.
    """
    if forced not in FORCED_VALUES:
        raise ValueError(f"forced must be one of {FORCED_VALUES}, got {forced!r}")
    kind = forced
    if forced == "auto":
        kind = "stream" if cam is not None else "face" if big_face is not None else "fit"
    if kind == "stream" and cam is not None:
        game = _fit_aspect(src_w / 2, src_h / 2, src_w, src_h, GAME_ASPECT, src_w, src_h)
        return LayoutPlan("stream", src_w, src_h, cam=cam, game=game)
    if kind == "face" and (big_face or cam) is not None:
        return LayoutPlan("face", src_w, src_h, face=_face_crop(big_face or cam, src_w, src_h))
    return LayoutPlan("fit", src_w, src_h)
