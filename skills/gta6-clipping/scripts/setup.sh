#!/usr/bin/env bash
# Creates the private env on the Mac (never on the USB stick) and runs doctor.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE="$HOME/.gta6-clipping"
VENV="$PRIVATE/venv"
MODEL_DIR="$PRIVATE/models"
YUNET="face_detection_yunet_2023mar.onnx"
YUNET_URL="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/$YUNET"

mkdir -p "$PRIVATE" "$MODEL_DIR"
[ -x "$VENV/bin/python" ] || python3.12 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SKILL_DIR/requirements.txt"

if [ ! -s "$MODEL_DIR/$YUNET" ]; then
  curl -fsSL "$YUNET_URL" -o "$MODEL_DIR/$YUNET.part"
  mv "$MODEL_DIR/$YUNET.part" "$MODEL_DIR/$YUNET"
fi

cd "$SKILL_DIR/scripts"
"$VENV/bin/python" -m clipping.doctor
echo "All set"
