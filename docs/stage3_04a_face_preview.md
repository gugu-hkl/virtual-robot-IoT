# 阶段三 · 人脸识别实时预览窗口

这一步在 Ubuntu 桌面显示正在识别的摄像头画面。预览和人脸识别使用**同一个** `VideoCapture`，不会再打开一次摄像头，也不需要 Windows 客户端程序。Windows 的前置摄像头仍须已连接到 Ubuntu 虚拟机，并能被之前的人脸识别程序读取。

窗口有三行信息：

- `FACE`：本次识别到 A、B、未知、无人或多人同框。
- `TARGET`：连续稳定识别逻辑当前希望选择的机器人；这是本地决策。
- `API ACK`：FastAPI 已确认收到的选择；`API: SYNCING` 表示尚未确认，`API: ERROR` 表示请求失败。ESP32 在下一次轮询 `/display/state` 后才会更新 OLED。

绿色框表示当前检测到的人脸被识别为 A/B；黄色框表示检测到了脸，但它未知、太小或多人同框。窗口只绘制在内存里的画面，不保存照片或视频。

## 更新 Ubuntu 的人脸识别环境

先把本次仓库文件同步到 Ubuntu。**只修改 `.venv-face`；FastAPI 的 `.venv` 和 ESP32 固件不需重装。**在 Ubuntu 桌面终端执行：

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv-face/bin/activate
python -m pip uninstall -y opencv-python-headless opencv-python
python -m pip install -r stage3/face_id/requirements.txt
python -m pip show opencv-python
```

依赖清单现已指定带图形窗口的 `opencv-python==4.10.0.84`。请确认 `pip show` 显示的是 `.venv-face` 中的版本；同一环境不要同时安装 `opencv-python-headless`。如果在 SSH 终端或没有 Ubuntu 图形桌面的环境运行，窗口无法显示；应在虚拟机的 Ubuntu 桌面终端运行。

## 启动

先按 [人脸绑定说明](stage3_04_face_binding.md) 启动 Webots、双机器人状态网关、FastAPI 和 ESP32，并确认 A/B 已注册。关闭 Ubuntu 相机预览和注册程序，避免争用摄像头。然后执行：

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv-face/bin/activate
python -m stage3.face_id.run --camera 0 --preview
```

如果摄像头编号不是 0，使用你注册人脸时成功的 `--camera` 编号。画面会持续刷新，人脸识别约每秒运行 5 次，FastAPI 请求在后台线程运行，网络超时不会卡住画面。选中预览窗口按 `q` 退出，或在终端按 Ctrl+C；程序会释放摄像头并向 FastAPI 发送清空选择。无需窗口时，省略 `--preview` 即可继续运行原有流程。

## 验收

1. Ubuntu 预览窗口持续显示同一摄像头画面；`FACE` 会随镜头中的人变化。无需同时运行另一个相机程序。
2. A 稳定出现在画面中时，先看到 `FACE: A`，再看到 `TARGET: a` 与 `API ACK: a`；OLED 随后显示 `ROBOT A` 和实时状态。B 同理对应 b。
3. 未注册者或多人同框时，窗口应分别显示 `UNKNOWN` 或 `MULTIPLE`，不能因此切换到新机器人。无人约 2 秒后，`TARGET` 与 `API ACK` 应回到 `wait`。
4. 暂时关闭 FastAPI：画面仍能刷新，窗口显示 `API: ERROR`，终端打印连接失败；恢复服务后自动重新同步选择。
5. 在窗口按 `q`：程序结束并释放摄像头。FastAPI 正常时，OLED 应回到 `WAIT SELECT`。

如果 `cv2.namedWindow()` 或 `cv2.imshow()` 报图形后端错误，先检查当前终端是否属于 Ubuntu 图形桌面、`.venv-face` 中是否仍装着 headless 包，再运行 `python -m pip show opencv-python opencv-python-headless`。如果摄像头无法打开，检查它是否仍被 Windows 或其他 Ubuntu 程序占用，以及虚拟机的摄像头连接是否还在。

建议本次提交信息：`feat(stage3): 加入Ubuntu人脸识别实时预览`。提交代码和文档即可；人脸模板、ONNX 模型和虚拟环境继续留在本地。
