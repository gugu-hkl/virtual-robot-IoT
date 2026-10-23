"""Webots 外部控制器：接收本机指令，驱动车轮，读取真实仿真位置。"""

import json
import math
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from controller import Robot


HOST = "127.0.0.1"
PORT = 8765
STATUS_MAX_AGE_S = 5.0

WHEEL_RADIUS_M = 0.033
INPUT_SPEED_LIMIT_CM_S = 20.0


class LocalControlServer(ThreadingHTTPServer):
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

    for motor in (left_motor, right_motor):
        motor.setPosition(float("inf"))
        motor.setVelocity(0.0)

    gps.enable(time_step_ms)
    inertial_unit.enable(time_step_ms)

    motor_speed_limit = min(
        left_motor.getMaxVelocity(),
        right_motor.getMaxVelocity(),
    )
    max_speed_cm_s = min(
        INPUT_SPEED_LIMIT_CM_S,
        motor_speed_limit * WHEEL_RADIUS_M * 100,
    )
    print(f"本次允许的最高轮缘速度：{max_speed_cm_s:.2f} cm/s", flush=True)

    # HTTP 线程只负责接收请求；Webots 设备只在下面的仿真循环中操作。
    commands = queue.Queue()
    status_lock = threading.Lock()
    latest = {"status": None, "updated_at": 0.0}

    trajectory = []
    motion = {
        "direction": None,
        "speed": 0.0,
        "end_simulation_time": None,
    }
    measurement = {
        "x": 0.0,
        "y": 0.0,
        "z_m": 0.0,
        "yaw_deg": 0.0,
        "simulation_time_s": 0.0,
    }

    def record_position(event):
        trajectory.append({
            "x": measurement["x"],
            "y": measurement["y"],
            "event": event,
        })

    def set_wheels(direction, speed_cm_s):
        wheel_rad_s = (speed_cm_s / 100.0) / WHEEL_RADIUS_M

        if direction == "forward":
            left_speed, right_speed = wheel_rad_s, wheel_rad_s
        elif direction == "backward":
            left_speed, right_speed = -wheel_rad_s, -wheel_rad_s
        elif direction == "left":
            left_speed, right_speed = -wheel_rad_s, wheel_rad_s
        elif direction == "right":
            left_speed, right_speed = wheel_rad_s, -wheel_rad_s
        else:
            raise ValueError(f"未知方向：{direction}")

        left_motor.setVelocity(left_speed)
        right_motor.setVelocity(right_speed)

    def stop_wheels():
        left_motor.setVelocity(0.0)
        right_motor.setVelocity(0.0)
        motion["direction"] = None
        motion["speed"] = 0.0
        motion["end_simulation_time"] = None

    def publish_status():
        status = {
            "online": True,
            # moving 表示当前有运动指令，不是 GPS 计算出的瞬时速度。
            "moving": motion["direction"] is not None,
            "direction": motion["direction"],
            "speed": motion["speed"],
            "current_task": None,
            "position": {
                "x": measurement["x"],
                "y": measurement["y"],
            },
            "trajectory": list(trajectory),
            "yaw_deg": measurement["yaw_deg"],
            "world_z_m": measurement["z_m"],
            "simulation_time_s": measurement["simulation_time_s"],
        }

        with status_lock:
            latest["status"] = status
            latest["updated_at"] = time.monotonic()

        return status

    class ControlHandler(BaseHTTPRequestHandler):
        def send_json(self, code, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def current_status_is_fresh(self):
            with status_lock:
                status = latest["status"]
                updated_at = latest["updated_at"]

            if status is None:
                return False, "等待 Webots 首次传感器读数", None

            if time.monotonic() - updated_at > STATUS_MAX_AGE_S:
                return False, "Webots 仿真状态超过 5 秒未更新", None

            return True, "", status

        def do_GET(self):
            if self.path != "/status":
                self.send_json(404, {"error": "未知地址"})
                return

            fresh, reason, status = self.current_status_is_fresh()
            if not fresh:
                self.send_json(503, {"error": reason})
                return

            self.send_json(200, status)

        def do_POST(self):
            if self.path != "/command":
                self.send_json(404, {"error": "未知地址"})
                return

            fresh, reason, _ = self.current_status_is_fresh()
            if not fresh:
                self.send_json(503, {"error": reason})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_json(400, {"error": "Content-Length 无效"})
                return

            if length <= 0 or length > 2048:
                self.send_json(400, {"error": "请求体长度无效"})
                return

            self.connection.settimeout(2.0)
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, TimeoutError, OSError):
                self.send_json(400, {"error": "请求体不是有效 JSON"})
                return

            if not isinstance(payload, dict):
                self.send_json(400, {"error": "请求体必须是 JSON 对象"})
                return

            action = payload.get("action")
            if action == "move":
                direction = payload.get("direction")
                speed = payload.get("speed")
                duration_s = payload.get("duration_s")

                if direction not in ("forward", "backward", "left", "right"):
                    self.send_json(422, {"error": "方向无效"})
                    return

                if isinstance(speed, bool) or not isinstance(speed, (int, float)):
                    self.send_json(422, {"error": "速度必须是数字"})
                    return

                if (
                    not math.isfinite(speed)
                    or speed <= 0
                    or speed > max_speed_cm_s
                ):
                    self.send_json(
                        422,
                        {"error": f"速度必须大于 0 且不超过 {max_speed_cm_s:.2f} cm/s"},
                    )
                    return

                if (
                    isinstance(duration_s, bool)
                    or not isinstance(duration_s, (int, float))
                    or not math.isfinite(duration_s)
                    or not 0 < duration_s <= 60
                ):
                    self.send_json(422, {"error": "时长必须大于 0 且不超过 60 秒"})
                    return

            elif action != "stop":
                self.send_json(422, {"error": "未知指令"})
                return

            command = {
                "payload": payload,
                "done": threading.Event(),
                "lock": threading.Lock(),
                "cancelled": False,
                "response": None,
            }
            commands.put(command)

            # 等待仿真线程实际设置电机，再向 FastAPI 确认。
            command["done"].wait(timeout=1.5)

            with command["lock"]:
                response = command["response"]
                if response is None:
                    # 超时指令作废；仿真恢复时不能再执行它。
                    command["cancelled"] = True

            if response is None:
                self.send_json(503, {"error": "仿真未及时处理指令，指令已取消"})
                return

            self.send_json(200, response)

        def log_message(self, format_string, *args):
            # 网页每约 500 ms 查询状态，不打印每次访问。
            pass

    server = LocalControlServer((HOST, PORT), ControlHandler)
    server_thread = threading.Thread(
        target=server.serve_forever,
        name="local-control-server",
        daemon=True,
    )
    server_thread.start()

    print(f"本机状态接口：http://{HOST}:{PORT}/status", flush=True)
    print(f"本机指令接口：http://{HOST}:{PORT}/command", flush=True)

    next_progress_time = 0.0
    next_print_time = 0.0

    try:
        while robot.step(time_step_ms) != -1:
            simulation_time = robot.getTime()
            x_m, y_m, z_m = gps.getValues()
            yaw_rad = inertial_unit.getRollPitchYaw()[2]

            measurement["x"] = round(x_m * 100, 3)
            measurement["y"] = round(y_m * 100, 3)
            measurement["z_m"] = round(z_m, 3)
            measurement["yaw_deg"] = round(math.degrees(yaw_rad), 3)
            measurement["simulation_time_s"] = round(simulation_time, 3)

            if not trajectory:
                record_position("start")

            # 轨迹点只取自 GPS；转弯时即使位置近似不变，朝向仍会更新。
            if (
                motion["direction"] is not None
                and simulation_time >= next_progress_time
            ):
                last = trajectory[-1]
                distance_cm = math.hypot(
                    measurement["x"] - last["x"],
                    measurement["y"] - last["y"],
                )
                if distance_cm >= 0.5:
                    record_position("progress")
                next_progress_time = simulation_time + 0.1

            # 按 Webots 仿真时间结束运动。
            end_time = motion["end_simulation_time"]
            if end_time is not None and simulation_time >= end_time:
                stop_wheels()
                record_position("segment_end")
                print("运动时长结束，已停止车轮", flush=True)

            publish_status()

            # 只在此仿真线程调用 Webots 电机 API。
            while True:
                try:
                    command = commands.get_nowait()
                except queue.Empty:
                    break

                with command["lock"]:
                    if command["cancelled"]:
                        continue

                    payload = command["payload"]
                    if payload["action"] == "move":
                        if motion["direction"] is not None:
                            record_position("segment_end")

                        direction = payload["direction"]
                        speed = float(payload["speed"])
                        duration_s = float(payload["duration_s"])

                        set_wheels(direction, speed)
                        motion["direction"] = direction
                        motion["speed"] = speed
                        motion["end_simulation_time"] = (
                            simulation_time + duration_s
                        )
                        next_progress_time = simulation_time + 0.1
                        record_position("move")
                        message = "Webots 控制器已设置车轮速度"

                        print(
                            f"移动：{direction}，{speed:.1f} cm/s，"
                            f"{duration_s:.1f} 仿真秒",
                            flush=True,
                        )
                    else:
                        stop_wheels()
                        record_position("stop")
                        message = "Webots 控制器已设置车轮停止"
                        print("收到停止指令，已设置车轮停止", flush=True)

                    command["response"] = {
                        "message": message,
                        "status": publish_status(),
                    }
                    command["done"].set()

            if simulation_time >= next_print_time:
                print(
                    f"仿真 {simulation_time:.1f} s | "
                    f"GPS ({measurement['x']:.1f}, "
                    f"{measurement['y']:.1f}) cm | "
                    f"朝向 {measurement['yaw_deg']:.1f}°",
                    flush=True,
                )
                next_print_time = simulation_time + 1.0
    finally:
        try:
            left_motor.setVelocity(0.0)
            right_motor.setVelocity(0.0)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()