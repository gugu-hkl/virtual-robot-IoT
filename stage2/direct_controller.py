"""Webots 外部控制器：读取机器人状态，并通过本机 HTTP 提供给 FastAPI。"""

import json
import math
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from controller import Robot


HOST = "127.0.0.1"
PORT = 8765
STATUS_MAX_AGE_S = 5.0


class LocalStatusServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    robot = Robot()
    time_step_ms = int(robot.getBasicTimeStep())

    devices = {}
    for index in range(robot.getNumberOfDevices()):
        device = robot.getDeviceByIndex(index)
        devices[device.getName()] = device

    print(f"已连接机器人：{robot.getName()}", flush=True)
    print(f"仿真步长：{time_step_ms} ms", flush=True)
    print(f"可用设备：{', '.join(sorted(devices))}", flush=True)

    required_names = (
        "left wheel motor",
        "right wheel motor",
        "gps",
        "inertial_unit",
    )
    missing = [name for name in required_names if name not in devices]
    if missing:
        raise RuntimeError(f"示例世界缺少设备：{missing}")

    left_motor = devices["left wheel motor"]
    right_motor = devices["right wheel motor"]
    gps = devices["gps"]
    inertial_unit = devices["inertial_unit"]

    # 本次只做状态读取，车轮保持停止。
    for motor in (left_motor, right_motor):
        motor.setPosition(float("inf"))
        motor.setVelocity(0.0)

    gps.enable(time_step_ms)
    inertial_unit.enable(time_step_ms)

    # 仿真循环写入状态；HTTP 线程读取状态。用锁保护两者之间的数据。
    status_lock = threading.Lock()
    latest = {"status": None, "updated_at": 0.0}

    class StatusHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/status":
                self.send_json(404, {"error": "未知地址"})
                return

            with status_lock:
                status = latest["status"]
                updated_at = latest["updated_at"]

            if status is None:
                self.send_json(503, {"error": "等待 Webots 首次传感器读数"})
                return

            if time.monotonic() - updated_at > STATUS_MAX_AGE_S:
                self.send_json(503, {"error": "Webots 仿真状态超过 5 秒未更新"})
                return

            self.send_json(200, status)

        def send_json(self, code, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format_string, *args):
            # 网页每约 500 ms 查询一次，避免终端被访问日志刷满。
            pass

    server = LocalStatusServer((HOST, PORT), StatusHandler)
    server_thread = threading.Thread(
        target=server.serve_forever,
        name="local-status-server",
        daemon=True,
    )
    server_thread.start()
    print(f"本机状态接口：http://{HOST}:{PORT}/status", flush=True)

    trajectory = []
    next_print_time = 0.0

    try:
        while robot.step(time_step_ms) != -1:
            x_m, y_m, z_m = gps.getValues()
            yaw_rad = inertial_unit.getRollPitchYaw()[2]
            simulation_time = robot.getTime()

            # Webots GPS 使用米；现有网页位置和刻度使用厘米。
            x_cm = round(x_m * 100, 3)
            y_cm = round(y_m * 100, 3)

            if not trajectory:
                trajectory.append({
                    "x": x_cm,
                    "y": y_cm,
                    "event": "start",
                })

            status = {
                "online": True,
                "moving": False,
                "direction": None,
                "speed": 0,
                "current_task": None,
                "position": {
                    "x": x_cm,
                    "y": y_cm,
                },
                "trajectory": list(trajectory),
                "yaw_deg": round(math.degrees(yaw_rad), 3),
                "world_z_m": round(z_m, 3),
                "simulation_time_s": round(simulation_time, 3),
            }

            with status_lock:
                latest["status"] = status
                latest["updated_at"] = time.monotonic()

            if simulation_time >= next_print_time:
                print(
                    f"仿真 {simulation_time:.1f} s | "
                    f"位置 ({x_cm:.1f}, {y_cm:.1f}) cm | "
                    f"朝向 {status['yaw_deg']:.1f}°",
                    flush=True,
                )
                next_print_time = simulation_time + 1.0
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()