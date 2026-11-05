"""Ubuntu 摄像头识别 A/B，稳定后调用 FastAPI 切换 OLED 显示目标。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
import numpy as np

from stage3.face_id.face_models import FaceModels, load_templates, open_camera
from stage3.face_id.selection_logic import StableSelector, classify_scores


WINDOW_NAME = "Face ID"
UNCONFIRMED = object()


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
    if not isinstance(result, dict) or result.get("selected_robot") != robot_id:
        raise RuntimeError(f"FastAPI 返回了意外的选择结果：{result}")


def observe_frame(models, templates, frame, threshold, margin):
    faces = models.faces(frame)
    if len(faces) == 0:
        return None, "未见人脸", faces
    if len(faces) > 1:
        return None, "多人同框", faces
    if min(float(faces[0][2]), float(faces[0][3])) < 80:
        return None, "人脸太小", faces
    feature = models.feature(frame, faces[0])
    scores = {label: float(np.dot(feature, template)) for label, template in templates.items()}
    label = classify_scores(scores, threshold=threshold, margin=margin)
    detail = f"A={scores['A']:.3f} B={scores['B']:.3f}"
    return label, detail if label else f"未知或不确定人脸（{detail}）", faces


def draw_preview(frame, faces, label, detail, desired, confirmed, api_error):
    """只画已有识别结果；不再次读取摄像头或运行人脸模型。"""
    view = frame.copy()
    if len(faces) > 1:
        face_text = "MULTIPLE"
    elif len(faces) == 0:
        face_text = "NONE"
    elif label is None:
        face_text = "UNKNOWN"
    else:
        face_text = label

    box_color = (0, 200, 80) if label else (0, 190, 255)
    for face in faces:
        x, y, width, height = (int(value) for value in face[:4])
        cv2.rectangle(view, (x, y), (x + width, y + height), box_color, 2)

    cv2.rectangle(view, (0, 0), (view.shape[1], 94), (25, 30, 40), -1)
    cv2.putText(view, f"FACE: {face_text}", (12, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 255), 2)
    cv2.putText(view, f"TARGET: {desired.lower() if desired else 'wait'}", (12, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220, 230, 230), 2)
    if api_error:
        api_text, api_color = "API: ERROR", (30, 30, 240)
    elif confirmed is UNCONFIRMED:
        api_text, api_color = "API: CONNECTING", (0, 190, 255)
    elif confirmed != desired:
        api_text, api_color = "API: SYNCING", (0, 190, 255)
    else:
        api_text = f"API ACK: {confirmed.lower() if confirmed else 'wait'}"
        api_color = (80, 220, 80)
    cv2.putText(view, api_text, (12, 83),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, api_color, 2)
    return view


def main():
    parser = argparse.ArgumentParser(description="将稳定识别的人脸映射到 OLED 上的机器人 a/b")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--threshold", type=float, default=0.45)
    parser.add_argument("--margin", type=float, default=0.06)
    parser.add_argument("--stable-frames", type=int, default=5)
    parser.add_argument("--clear-after", type=float, default=2.0)
    parser.add_argument("--preview", action="store_true", help="在 Ubuntu 桌面显示实时摄像头画面；窗口中按 q 退出")
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
    window_created = False
    executor = None
    pending_request = None
    pending_label = None
    confirmed = UNCONFIRMED
    api_error = None
    last_success_at = 0.0
    next_request_at = 0.0
    next_recognition_at = 0.0
    next_report_at = 0.0
    failed_reads = 0
    label, detail, faces = None, "未见人脸", []
    desired = None
    try:
        camera = open_camera(args.camera)
        if args.preview:
            cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
            window_created = True
            cv2.resizeWindow(WINDOW_NAME, 640, 480)
        executor = ThreadPoolExecutor(max_workers=1)
        print("识别已启动：A→a、B→b；未知或多人同框不会触发切换。按 Ctrl+C 结束。", flush=True)
        if args.preview:
            print("Ubuntu 预览窗口已打开；选中窗口按 q 结束。", flush=True)

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

            # 识别约每秒 5 次；两次识别之间继续刷新摄像头预览。
            if now >= next_recognition_at:
                label, detail, faces = observe_frame(
                    models, templates, frame, args.threshold, args.margin
                )
                desired = selector.observe(label, now)
                next_recognition_at = now + 0.2
                if now >= next_report_at:
                    print(f"识别={label or '未知'} | {detail} | 屏幕目标={desired or '等待'}", flush=True)
                    next_report_at = now + 2.0

            # HTTP 放在单独线程中，断线和请求超时不会冻结画面。
            if pending_request is not None and pending_request.done():
                try:
                    pending_request.result()
                except RuntimeError as exc:
                    api_error = str(exc)
                    next_request_at = now + 1.0
                    print(api_error, flush=True)
                else:
                    confirmed = pending_label
                    api_error = None
                    last_success_at = now
                    print(f"已同步到 FastAPI：{confirmed.lower() if confirmed else '等待'}", flush=True)
                pending_request = None
                pending_label = None

            if (pending_request is None and now >= next_request_at
                    and (confirmed is UNCONFIRMED or confirmed != desired
                         or now - last_success_at >= 2.0)):
                pending_label = desired
                pending_request = executor.submit(post_selection, args.api, pending_label)

            if args.preview:
                view = draw_preview(frame, faces, label, detail, desired, confirmed, api_error)
                cv2.imshow(WINDOW_NAME, view)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("已从预览窗口退出", flush=True)
                    break
            time.sleep(0.03 if args.preview else 0.16)
    except KeyboardInterrupt:
        print("识别程序已停止", flush=True)
    finally:
        # 等上一条请求结束后再发送清空，避免旧请求覆盖退出时的清空结果。
        if executor is not None:
            executor.shutdown(wait=True)
        if camera is not None:
            camera.release()
        if window_created:
            try:
                cv2.destroyWindow(WINDOW_NAME)
            except cv2.error:
                # 用户可能已点窗口的关闭按钮；仍要继续清空服务端选择。
                pass
        try:
            post_selection(args.api, None)
        except RuntimeError as exc:
            print(f"退出时未能清空屏幕选择：{exc}", flush=True)


if __name__ == "__main__":
    main()
