"""OpenCV YuNet + SFace 摄像头帧处理与本地特征模板。"""

import json
import os
from pathlib import Path

import cv2
import numpy as np

from stage3.face_id.download_models import MODEL_DIR, MODELS, file_sha256


DATA_FILE = Path(__file__).resolve().parent / "data" / "face_templates.json"
DETECTOR_FILE = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
LABELS = ("A", "B")


def unit_vector(value):
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if vector.size != 128 or not np.all(np.isfinite(vector)) or norm <= 1e-8:
        raise ValueError("SFace 特征向量无效")
    return vector / norm


class FaceModels:
    def __init__(self):
        for model_file in (DETECTOR_FILE, RECOGNIZER_FILE):
            if not model_file.exists():
                raise FileNotFoundError(
                    f"缺少模型 {model_file}；先运行 python -m stage3.face_id.download_models"
                )
        self.detector = cv2.FaceDetectorYN.create(
            str(DETECTOR_FILE), "", (320, 320),
            score_threshold=0.85,
            nms_threshold=0.3,
            top_k=5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(RECOGNIZER_FILE), "")

    def faces(self, frame):
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        return [] if faces is None else list(faces)

    def feature(self, frame, face):
        aligned = self.recognizer.alignCrop(frame, face)
        return unit_vector(self.recognizer.feature(aligned))


def open_camera(camera_index):
    camera = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(camera_index)
    if not camera.isOpened():
        raise RuntimeError(f"无法打开摄像头编号 {camera_index}")
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return camera


def load_templates(path=DATA_FILE):
    if not path.exists():
        raise FileNotFoundError("尚未注册人脸；先分别运行 A、B 注册命令")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("model_sha256") != file_sha256(RECOGNIZER_FILE):
        raise ValueError("注册文件与当前 SFace 模型不匹配，请重新注册")
    templates = data.get("templates")
    if not isinstance(templates, dict) or set(templates) != set(LABELS):
        raise ValueError("注册文件必须同时包含 A、B 两个人脸模板")
    return {label: unit_vector(templates[label]) for label in LABELS}


def save_template(label, features, path=DATA_FILE):
    if label not in LABELS:
        raise ValueError("注册标号只能是 A 或 B")
    mean = unit_vector(np.mean(np.stack(features), axis=0))
    model_hash = file_sha256(RECOGNIZER_FILE)
    data = {"model_sha256": model_hash, "templates": {}}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("model_sha256") == model_hash:
            data["templates"] = existing.get("templates", {})
    data["templates"][label] = mean.tolist()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return mean
