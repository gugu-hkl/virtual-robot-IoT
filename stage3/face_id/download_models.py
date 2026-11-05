"""下载并校验 OpenCV Zoo 的 YuNet 与 SFace 模型。"""

import hashlib
import os
from pathlib import Path
from urllib.request import Request, urlopen


MODEL_DIR = Path(__file__).resolve().parent / "models"

MODELS = {
    "face_detection_yunet_2023mar.onnx": {
        "url": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
        "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
    "face_recognition_sface_2021dec.onnx": {
        "url": "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
        "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    },
}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_models():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in MODELS.items():
        target = MODEL_DIR / name
        if target.exists() and file_sha256(target) == spec["sha256"]:
            print(f"已校验：{target}")
            continue

        temporary = target.with_suffix(".download")
        request = Request(spec["url"], headers={"User-Agent": "virtual-robot-IoT/1.0"})
        print(f"正在下载：{name}")
        try:
            with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(block)
            actual = file_sha256(temporary)
            if actual != spec["sha256"]:
                raise RuntimeError(
                    f"{name} 校验失败：期望 {spec['sha256']}，实际 {actual}"
                )
            os.replace(temporary, target)
            print(f"已校验：{target}")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    download_models()
