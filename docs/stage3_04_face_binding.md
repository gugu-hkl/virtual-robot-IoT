# 阶段三 · 第四次提交：人脸识别与机器人显示绑定

## 本次实现

Ubuntu 摄像头 → YuNet 检测人脸 → SFace 提取特征 → 与本地 A/B 模板比较 → 连续稳定识别 → FastAPI `POST /display/selection` → ESP32 轮询 `GET /display/state` → OLED 显示 a/b 实时状态。

这一步只切换**显示目标**，不发运动指令。Webots 中 a、b 的运动仍由前面已验收的控制流程决定。后续再做“识别后触发 square/circle”。

程序只接受画面里恰好一张、足够大的脸。识别到 A 连续 5 帧后选择 a，识别到 B 连续 5 帧后选择 b；未见人脸、未知人脸、多人同框或结果不确定时都不会选择新机器人。已选中的人连续约 2 秒未被识别到，屏幕回到 `WAIT SELECT`。这些数字可通过命令行调整。

模型采用 [OpenCV YuNet 与 SFace 官方示例](https://docs.opencv.org/4.10.0/d0/dd4/tutorial_dnn_face.html)。默认余弦相似度门槛 `0.45`，要求 A/B 分数差至少 `0.06`。OpenCV 示例中的 `0.363` 是其测试数据上的参考值；本项目的默认值更保守，但仍需要用实际摄像头、灯光和两位测试者验收。分数门槛过高会拒绝本人，过低会误认，不能把这套演示逻辑当作安全身份认证。

## 文件与数据

| 文件 | 用途 |
| --- | --- |
| `stage3/face_id/download_models.py` | 下载并校验官方 ONNX 模型 |
| `stage3/face_id/enroll.py` | 分别采集 A、B 的人脸特征 |
| `stage3/face_id/run.py` | 识别并调用 FastAPI 切换 OLED 显示目标 |
| `stage3/face_id/selection_logic.py` | 判定分数和连续帧稳定逻辑 |
| `stage3/face_id/requirements.txt` | 专用 Python 环境的依赖 |

`stage3/face_id/models/`、`stage3/face_id/data/` 和 `.venv-face/` 被 `.gitignore` 忽略。`data/face_templates.json` 仅存两位测试者的特征向量和模型校验值，**没有原始照片**；它仍属于敏感的人脸数据，请只放在自己的 Ubuntu 机器上，不要上传仓库或分享。退出项目时可删除此文件。

## Ubuntu 首次准备

先把本次代码同步到 Ubuntu，并在**仓库根目录**执行。下文沿用已有路径，若实际目录不同请按实际路径替换。

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
python3 -m venv .venv-face
source .venv-face/bin/activate
python -m pip install -r stage3/face_id/requirements.txt
python -m stage3.face_id.download_models
python -m unittest stage3.face_id.test_selection_logic
```

下载约 37 MB 的 SFace 模型与较小的 YuNet 模型。下载脚本会校验 SHA-256，不完整的文件不会用于识别。需要互联网；模型下载一次后可以重复运行校验命令。运行摄像头程序时使用 `.venv-face`，原来的 FastAPI 继续使用 `.venv`，二者是不同进程。

如果你的摄像头编号不是 `0`，在下面的注册和运行命令中都追加 `--camera 1`（或实际编号）。关闭其他占用摄像头的程序，例如 Ubuntu 的相机预览。

## 注册 A 和 B

每次只让一位测试者站在镜头前，脸部保持清晰、光线均匀，轻微改变头部角度。**先完成 A，再完成 B**：

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv-face/bin/activate
python -m stage3.face_id.enroll --person A --camera 0
python -m stage3.face_id.enroll --person B --camera 0
```

每人默认采集 8 个有效帧，帧间至少隔 0.5 秒。画面里有多张脸或脸太小时不会计入。每人最多等待 120 秒；超时退出而不保存本次未完成的注册。重新运行同一个 `--person` 会替换该人的模板。注册完可用下列命令检查**只有 A/B 标签存在**，无需打印特征值：

```bash
python -c 'import json; from pathlib import Path; p=Path("stage3/face_id/data/face_templates.json"); print(sorted(json.loads(p.read_text())["templates"]))'
```

预期输出：`['A', 'B']`。

## 启动与验收

先按 [第三步说明](stage3_03_wireless_oled.md) 启动 Webots 双机器人、`dual_state_gateway`、FastAPI 和 ESP32。FastAPI 使用**单进程**，不加 `--workers`；它的选择状态保存在内存中。运行识别程序时不要再从 `/docs` 手动选择机器人，否则两处会互相覆盖。

另开一个 Ubuntu 终端：

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv-face/bin/activate
python -m stage3.face_id.run --camera 0 --api http://127.0.0.1:8000  #python -m stage3.face_id.run --camera 0 --api http://127.0.0.1:8000 --preview
```

识别程序与 FastAPI 都运行在 Ubuntu，所以这里的 API 地址用 `127.0.0.1`。ESP32 仍继续请求 Ubuntu 的热点 IP。可在另一个终端观察选择接口：

```bash
curl -s http://127.0.0.1:8000/display/state
```

手动验收顺序：

1. 摄像头前无人时，约 2 秒后 OLED 显示 `WAIT SELECT`，`/display/state` 返回 `state: waiting`。
2. 只让 A 面对摄像头并停留约 2 秒；识别终端打印 `已同步到 FastAPI：a`，接口返回 `selected_robot: a`、`state: live`，OLED 显示 `ROBOT A` 和 a 的实时位置与速度。
3. 换成 B；终端打印 `已同步到 FastAPI：b`，接口返回 b，OLED 显示 `ROBOT B` 和 b 的实时状态。可按前面双机器人验收的命令单独控制 a 或 b，检查选中目标的数据确实来自对应的 `/odom`。
4. 只出现未注册者时，不能跳到 a 或 b；出现两张脸时也不能触发新选择。已选中的人消失约 2 秒后，应回到等待状态。
5. 快速晃过 A 或 B、只出现一两帧时，不应切换；稳定停留才切换。遮住摄像头后应回到等待状态。
6. 关闭 FastAPI，识别终端必须打印连接失败，OLED 应显示服务错误或连接错误，而不能宣称选择成功。重启 FastAPI 后，识别程序应重新同步选择。
7. 按 Ctrl+C 停止识别程序，应发送一次清空选择的请求；OLED 回到 `WAIT SELECT`。如果 FastAPI 已关闭，终端会明确打印无法清空的原因。

如果本人一直被判为未知，可先增加灯光、让脸更近、重新采集样本；再查看终端的 A/B 分数。确实需要调整时，可试 `--threshold 0.40`，随后必须用未注册者和多人场景重新验收，不能只验证本人。若 A/B 分数接近，先换两位不同测试者并重新注册。

## 此次提交范围

建议提交信息：`feat(stage3): 加入人脸识别与机器人显示绑定`。只提交源码、依赖清单和说明文档；不要提交 ONNX 模型、`.venv-face` 或 `face_templates.json`。这一提交不包含人脸触发 Webots 运动，后续轨迹联动另做。
