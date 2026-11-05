"""在 Ubuntu 摄像头前分别采集 A/B 的 SFace 特征，不保存照片。"""

import argparse
import time

import cv2

from stage3.face_id.face_models import FaceModels, open_camera, save_template


def main():
    parser = argparse.ArgumentParser(description="采集一名测试者的人脸特征")
    parser.add_argument("--person", choices=("A", "B"), required=True)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.samples < 3 or args.timeout <= 0:
        parser.error("--samples 至少为 3，--timeout 必须大于 0")

    cv2.setNumThreads(2)
    models = FaceModels()
    camera = open_camera(args.camera)
    features = []
    started = time.monotonic()
    next_sample = started
    next_notice = started
    print(f"开始注册 {args.person}：请只让这一人面对摄像头，缓慢改变头部角度；按 Ctrl+C 中止。", flush=True)
    try:
        while len(features) < args.samples:
            now = time.monotonic()
            if now - started > args.timeout:
                raise TimeoutError(f"超时：只采集到 {len(features)}/{args.samples} 个有效样本")
            ok, frame = camera.read()
            if not ok:
                time.sleep(0.1)
                continue
            faces = models.faces(frame)
            reason = None
            if len(faces) != 1:
                reason = "请确保画面里恰好一张脸"
            elif min(float(faces[0][2]), float(faces[0][3])) < 80:
                reason = "请靠近摄像头一些"
            elif now >= next_sample:
                features.append(models.feature(frame, faces[0]))
                next_sample = now + 0.5
                print(f"已采集 {len(features)}/{args.samples}", flush=True)
            if reason and now >= next_notice:
                print(reason, flush=True)
                next_notice = now + 2.0
    finally:
        camera.release()

    save_template(args.person, features)
    print(f"{args.person} 注册完成。仅保存特征向量，不保存摄像头照片。", flush=True)


if __name__ == "__main__":
    main()
