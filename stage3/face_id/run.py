"""Ubuntu 摄像头识别 A/B，稳定后调用 FastAPI 切换 OLED 显示目标。"""

import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from stage3.face_id.face_models import FaceModels, load_templates, open_camera
from stage3.face_id.selection_logic import StableSelector, classify_scores


def post_selection(api_base, label):
    robot_id = label.lower() if label else None
    body = json.dumps({"robot_id": robot_id}).encode("utf-8")
    request = Request(
        api_base.rstrip("/") + "/display/selection",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2.0) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"FastAPI 选择请求失败：{exc}") from exc
    if result.get("selected_robot") != robot_id:
        raise RuntimeError(f"FastAPI 返回了意外的选择结果：{result}")


def observe_frame(models, templates, frame, threshold, margin):
    faces = models.faces(frame)
    if len(faces) == 0:
        return None, "未见人脸"
    if len(faces) > 1:
        return None, "多人同框"
    if min(float(faces[0][2]), float(faces[0][3])) < 80:
        return None, "人脸太小"
    feature = models.feature(frame, faces[0])
    scores = {label: float(np.dot(feature, template)) for label, template in templates.items()}
    label = classify_scores(scores, threshold=threshold, margin=margin)
    detail = f"A={scores['A']:.3f} B={scores['B']:.3f}"
    return label, detail if label else f"未知或不确定人脸（{detail}）"


def main():
    parser = argparse.ArgumentParser(description="将稳定识别的人脸映射到 OLED 上的机器人 a/b")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--margin", type=float, default=0.06)
    parser.add_argument("--stable-frames", type=int, default=5)
    parser.add_argument("--clear-after", type=float, default=2.0)
    args = parser.parse_args()
    if not args.api.startswith("http://"):
        parser.error("--api 应为本机 HTTP 地址，例如 http://127.0.0.1:8000")
    if not (0.0 < args.threshold < 1.0 and 0.0 <= args.margin < 1.0):
        parser.error("--threshold 必须在 0 到 1 之间，--margin 必须在 0 到 1 之间")
    if args.stable_frames < 1 or args.clear_after <= 0:
        parser.error("--stable-frames 与 --clear-after 必须大于 0")

    cv2.setNumThreads(2)
    models = FaceModels()
    templates = load_templates()
    selector = StableSelector(args.stable_frames, args.clear_after)
    camera = None
    last_sent = object()
    last_attempt = 0.0
    next_report = 0.0
    failed_reads = 0
    try:
        camera = open_camera(args.camera)
        print("识别已启动：A→a、B→b；未知或多人同框不会触发切换。按 Ctrl+C 结束。", flush=True)
        while True:
            ok, frame = camera.read()
            now = time.monotonic()
            if not ok:
                failed_reads += 1
                if failed_reads >= 5:
                    raise RuntimeError("连续 5 次读取摄像头失败")
                time.sleep(0.1)
                continue
            failed_reads = 0
            label, detail = observe_frame(
                models, templates, frame, args.threshold, args.margin
            )
            desired = selector.observe(label, now)
            if now >= next_report:
                print(f"识别={label or '未知'} | {detail} | 屏幕目标={desired or '等待'}", flush=True)
                next_report = now + 2.0

            # 失败后每秒重试；正常时每 2 秒同步一次，以便 FastAPI 重启后恢复选择。
            if desired != last_sent or now - last_attempt >= 2.0:
                if now - last_attempt >= 1.0:
                    last_attempt = now
                    try:
                        post_selection(args.api, desired)
                    except RuntimeError as exc:
                        print(exc, flush=True)
                    else:
                        last_sent = desired
                        print(f"已同步到 FastAPI：{desired.lower() if desired else '等待'}", flush=True)
            time.sleep(0.16)  # 约 5 帧/秒；减轻虚拟机负载。
    except KeyboardInterrupt:
        print("识别程序已停止", flush=True)
    finally:
        if camera is not None:
            camera.release()
        try:
            post_selection(args.api, None)
        except RuntimeError as exc:
            print(f"退出时未能清空屏幕选择：{exc}", flush=True)


if __name__ == "__main__":
    main()
