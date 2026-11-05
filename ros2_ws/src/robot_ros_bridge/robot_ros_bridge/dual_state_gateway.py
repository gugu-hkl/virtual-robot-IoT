"""双机器人本机网关：订阅 /a、/b 里程计，并发布各自的运动指令。"""

import json
import math
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor

from robot_ros_bridge.command_publisher import (
    CommandPublisherNode,
    MAX_WHEEL_LINEAR_M_S,
    WHEEL_TRACK_M,
)
from robot_ros_bridge.state_subscriber import StateSubscriberNode


HOST = "127.0.0.1"
PORT = 8767
MAX_AGE_S = 2.0
ROBOT_IDS = ("a", "b")
COMMAND_WAIT_S = 1.5


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class CommandJob:
    def __init__(self, robot_id, payload):
        self.robot_id = robot_id
        self.payload = payload
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.cancelled = False
        self.result = None


class DualStateGateway:
    def __init__(self):
        self.subscribers = {
            robot_id: StateSubscriberNode(
                log_updates=False,
                topic=f"/{robot_id}/odom",
                node_name=f"robot_{robot_id}_state_subscriber",
            )
            for robot_id in ROBOT_IDS
        }
        self.publishers = {
            robot_id: CommandPublisherNode(
                topic=f"/{robot_id}/cmd_vel",
                node_name=f"robot_{robot_id}_command_publisher",
            )
            for robot_id in ROBOT_IDS
        }
        for publisher in self.publishers.values():
            if not publisher.get_parameter("use_sim_time").value:
                raise RuntimeError(
                    "双机器人网关必须使用仿真时钟；启动时添加 "
                    "--ros-args -p use_sim_time:=true"
                )
        self.executor = SingleThreadedExecutor()
        for subscriber in self.subscribers.values():
            self.executor.add_node(subscriber)
        for publisher in self.publishers.values():
            self.executor.add_node(publisher)
        self.commands = queue.Queue()

    def get_status(self, robot_id):
        subscriber = self.subscribers[robot_id]
        odom = subscriber.get_latest_status(max_age_s=MAX_AGE_S)
        if odom is None:
            age_s = subscriber.get_data_age_s()
            if age_s is None:
                return 503, {"error": f"尚未收到 /{robot_id}/odom 数据"}
            return 503, {
                "error": f"/{robot_id}/odom 数据过期，最近一次更新距今 {age_s:.1f} 秒"
            }

        stamp = odom["stamp"]
        return 200, {
            "robot_id": robot_id,
            "online": True,
            "position_source": "odom",
            "position_m": odom["position_m"],
            "yaw_rad": odom["yaw_rad"],
            "yaw_deg": round(math.degrees(odom["yaw_rad"]), 3),
            "linear_m_s": odom["linear_m_s"],
            "angular_rad_s": odom["angular_rad_s"],
            "simulation_time_s": round(stamp["sec"] + stamp["nanosec"] / 1e9, 3),
            "data_age_s": round(subscriber.get_data_age_s(), 3),
            "frame_id": odom["frame_id"],
            "child_frame_id": odom["child_frame_id"],
        }

    def submit_command(self, robot_id, payload):
        job = CommandJob(robot_id, payload)
        self.commands.put(job)
        if not job.done.wait(timeout=COMMAND_WAIT_S):
            with job.lock:
                if not job.done.is_set():
                    job.cancelled = True
                    return 503, {"error": "ROS 控制线程未及时响应，指令已取消"}
        return job.result

    def execute_command(self, robot_id, payload):
        action = payload.get("action")
        publisher = self.publishers[robot_id]
        if action == "stop":
            publisher.stop_motion()
            return 200, {"accepted": True, "robot_id": robot_id, "action": "stop"}

        if action != "move":
            return 400, {"error": "action 只能是 move 或 stop"}
        direction = payload.get("direction")
        speed = payload.get("speed")
        duration_s = payload.get("duration_s")
        if direction not in ("forward", "backward", "left", "right"):
            return 400, {"error": "无效的运动方向"}
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not math.isfinite(speed) or not 0 < speed <= 20:
            return 400, {"error": "speed 必须大于 0 且不超过 20 cm/s"}
        if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or not math.isfinite(duration_s) or not 0 < duration_s <= 10:
            return 400, {"error": "duration_s 必须大于 0 且不超过 10 仿真秒"}

        code, status = self.get_status(robot_id)
        if code != 200:
            return code, status

        speed_m_s = speed / 100.0
        linear_m_s = 0.0
        angular_rad_s = 0.0
        if direction == "forward":
            linear_m_s = speed_m_s
        elif direction == "backward":
            linear_m_s = -speed_m_s
        elif direction == "left":
            angular_rad_s = 2 * speed_m_s / WHEEL_TRACK_M
        else:
            angular_rad_s = -2 * speed_m_s / WHEEL_TRACK_M
        left_wheel = linear_m_s - angular_rad_s * WHEEL_TRACK_M / 2
        right_wheel = linear_m_s + angular_rad_s * WHEEL_TRACK_M / 2
        if max(abs(left_wheel), abs(right_wheel)) > MAX_WHEEL_LINEAR_M_S:
            return 400, {"error": "目标轮速超过控制器上限"}
        try:
            publisher.start_motion(linear_m_s, angular_rad_s, duration_s)
        except RuntimeError as exc:
            return 503, {"error": str(exc)}
        return 200, {
            "accepted": True,
            "robot_id": robot_id,
            "action": "move",
            "direction": direction,
            "duration_s": duration_s,
        }

    def process_commands(self):
        while True:
            try:
                job = self.commands.get_nowait()
            except queue.Empty:
                return
            with job.lock:
                if job.cancelled:
                    continue
                try:
                    job.result = self.execute_command(job.robot_id, job.payload)
                except Exception as exc:
                    self.subscribers[job.robot_id].get_logger().error(
                        f"处理机器人控制指令失败：{exc}"
                    )
                    job.result = 500, {"error": "ROS 网关处理控制指令失败"}
                finally:
                    job.done.set()

    def run(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parts = self.path.split("?")[0].strip("/").split("/")
                if len(parts) != 3 or parts[0] != "robots" or parts[2] != "status":
                    self.send_json(404, {"error": "未知地址"})
                    return
                robot_id = parts[1]
                if robot_id not in gateway.subscribers:
                    self.send_json(404, {"error": "机器人标号只能是 a 或 b"})
                    return
                code, result = gateway.get_status(robot_id)
                self.send_json(code, result)

            def do_POST(self):
                parts = self.path.split("?")[0].strip("/").split("/")
                if len(parts) != 3 or parts[0] != "robots" or parts[2] != "command":
                    self.send_json(404, {"error": "未知地址"})
                    return
                robot_id = parts[1]
                if robot_id not in gateway.publishers:
                    self.send_json(404, {"error": "机器人标号只能是 a 或 b"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2048:
                        raise ValueError("请求体长度无效")
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError("请求体必须是 JSON 对象")
                except (ValueError, UnicodeDecodeError) as exc:
                    self.send_json(400, {"error": str(exc)})
                    return
                code, result = gateway.submit_command(robot_id, payload)
                self.send_json(code, result)

            def send_json(self, code, data):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_string, *args):
                # 后续 ESP32 会频繁轮询，不逐条打印访问日志。
                pass

        server = LocalServer((HOST, PORT), Handler)
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="dual-state-http",
            daemon=True,
        )
        server_thread.start()
        self.subscribers["a"].get_logger().info(f"双机器人状态与控制网关：http://{HOST}:{PORT}")
        try:
            while rclpy.ok():
                self.executor.spin_once(timeout_sec=0.05)
                self.process_commands()
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)

    def close(self):
        if rclpy.ok():
            for publisher in self.publishers.values():
                publisher.stop_motion()
            for _ in range(5):
                for publisher in self.publishers.values():
                    publisher.publish_velocity(0.0, 0.0)
                time.sleep(0.02)
        self.executor.shutdown()
        for subscriber in self.subscribers.values():
            subscriber.destroy_node()
        for publisher in self.publishers.values():
            publisher.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main():
    rclpy.init()
    gateway = None
    try:
        gateway = DualStateGateway()
        gateway.run()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if gateway is not None:
            gateway.close()
        elif rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
