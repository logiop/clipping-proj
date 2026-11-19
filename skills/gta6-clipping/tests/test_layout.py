import numpy as np
import pytest

from clipping import layout
from clipping.layout import Box

W, H = 1920, 1080


def corner_faces(n=10, jitter=0, present=10):
    """Top-right small face (80x80) in `present` of `n` frames."""
    frames = []
    for i in range(n):
        if i < present:
            frames.append([Box(1700 + (i % 2) * jitter, 100, 80, 80)])
        else:
            frames.append([])
    return frames


def assert_valid_crop(box, src_w, src_h, aspect):
    assert box.w % 2 == 0 and box.h % 2 == 0
    assert 0 <= box.x and 0 <= box.y
    assert box.x + box.w <= src_w and box.y + box.h <= src_h
    assert abs(box.w / box.h - aspect) < 0.01


def test_corner_face_becomes_cam():
    cam = layout.facecam_box(corner_faces(), W, H)

    assert cam is not None
    assert_valid_crop(cam, W, H, 1080 / 640)
    assert cam.x <= 1700 and cam.x + cam.w >= 1780  # contains the face
    assert cam.y <= 100 and cam.y + cam.h >= 180


def test_moving_face_is_not_cam():
    frames = [[Box(1500 + i * 40, 100, 80, 80)] for i in range(10)]

    assert layout.facecam_box(frames, W, H) is None


def test_face_present_in_too_few_frames_is_not_cam():
    assert layout.facecam_box(corner_faces(present=5), W, H) is None


def test_center_face_is_not_cam():
    frames = [[Box(900, 450, 80, 80)] for _ in range(10)]

    assert layout.facecam_box(frames, W, H) is None


def test_big_corner_face_is_not_cam():
    frames = [[Box(1100, 0, 800, 450)] for _ in range(10)]  # >15% of frame area

    assert layout.facecam_box(frames, W, H) is None


def test_empty_input_is_none():
    assert layout.facecam_box([], W, H) is None


def test_no_face_falls_back_to_fit():
    p = layout.plan(W, H, None)

    assert p.kind == "fit"
    assert p.cam is None and p.game is None and p.face is None


def test_auto_with_cam_is_stream():
    cam = layout.facecam_box(corner_faces(), W, H)
    p = layout.plan(W, H, cam)

    assert p.kind == "stream"
    assert (p.src_w, p.src_h) == (W, H)
    assert_valid_crop(p.cam, W, H, 1080 / 640)
    assert_valid_crop(p.game, W, H, 1080 / 1280)


def test_plan_stream_heights_sum_to_1920():
    assert layout.CAM_OUT_H + layout.GAME_OUT_H == 1920
    assert layout.CAM_OUT_H == 640 and layout.GAME_OUT_H == 1280
    assert layout.OUT_W == 1080


def test_game_crop_is_centered():
    p = layout.plan(W, H, Box(1500, 0, 420, 249))

    assert abs((p.game.x + p.game.w / 2) - W / 2) <= 1


def test_forced_layout_wins():
    cam = layout.facecam_box(corner_faces(), W, H)

    assert layout.plan(W, H, cam, forced="fit").kind == "fit"
    assert layout.plan(W, H, None, forced="stream").kind == "fit"  # no cam to crop: degrade
    face = layout.plan(W, H, cam, forced="face", big_face=Box(800, 300, 300, 300))
    assert face.kind == "face"
    assert_valid_crop(face.face, W, H, 9 / 16)


def test_forced_face_without_face_uses_cam_then_fit():
    assert layout.plan(W, H, None, forced="face").kind == "fit"


def test_auto_big_face_without_cam_is_face():
    p = layout.plan(W, H, None, big_face=Box(1700, 700, 200, 200))

    assert p.kind == "face"
    assert_valid_crop(p.face, W, H, 9 / 16)  # clamped inside the frame


def test_auto_cam_beats_big_face():
    cam = layout.facecam_box(corner_faces(), W, H)

    assert layout.plan(W, H, cam, big_face=Box(800, 300, 300, 300)).kind == "stream"


def test_unknown_forced_value_raises():
    with pytest.raises(ValueError):
        layout.plan(W, H, None, forced="bogus")


def test_big_face_from_frames_requires_area_over_15_percent():
    big = Box(500, 100, 900, 900)  # 39% of frame
    small = Box(500, 100, 200, 200)
    assert layout.big_face([[big]] * 5, W, H) is not None
    assert layout.big_face([[small]] * 5, W, H) is None
    assert layout.big_face([], W, H) is None


def test_detect_faces_blank_frame_returns_empty():
    frame = np.zeros((H, W, 3), dtype=np.uint8)

    try:
        result = layout.detect_faces(frame)
    except FileNotFoundError:
        pytest.skip("YuNet model not installed")
    assert result == []


def test_left_edge_mid_height_cam_is_cam():
    """Kai's layout: cam on the left edge at mid-height (face ~ x 60-330, y 380-560 in 1920x1080)."""
    frames = [[Box(60 + (i % 3) * 4, 380 + (i % 2) * 6, 270, 180)] for i in range(10)]
    cam = layout.facecam_box(frames, W, H)

    assert cam is not None
    assert_valid_crop(cam, W, H, 1080 / 640)
    assert cam.x <= 60 and cam.x + cam.w >= 330


def test_bottom_band_cam_is_cam():
    frames = [[Box(900, 900, 80, 80)] for _ in range(10)]  # center x, bottom 30% of height

    assert layout.facecam_box(frames, W, H) is not None


def test_face_moving_through_center_is_not_cam():
    frames = [[Box(700 + i * 50, 450, 80, 80)] for i in range(10)]

    assert layout.facecam_box(frames, W, H) is None


def test_center_band_face_just_inside_is_not_cam():
    frames = [[Box(700, 400, 80, 80)] for _ in range(10)]  # center at x 740 (>35% of 1920), y 440

    assert layout.facecam_box(frames, W, H) is None
