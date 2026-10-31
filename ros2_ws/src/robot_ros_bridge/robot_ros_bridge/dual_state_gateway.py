"""将 /a/odom、/b/odom 转为供 FastAPI 查询的本机 HTTP 状态服务。"""

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor

from robot_ros_bridge.state_subscriber import StateSubscriberNode


HOST = "127.0.0.1"
PORT = 8767
MAX_AGE_S = 2.0
ROBOT_IDS = ("a", "b")


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


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
        self.executor = SingleThreadedExecutor()
        for subscriber in self.subscribers.values():
            self.executor.add_node(subscriber)

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
        self.subscribers["a"].get_logger().info(
            f"双机器人状态网关：http://{HOST}:{PORT}"
        )
        try:
            while rclpy.ok():
                self.executor.spin_once(timeout_sec=0.1)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)

    def close(self):
        self.executor.shutdown()
        for subscriber in self.subscribers.values():
            subscriber.destroy_node()
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
