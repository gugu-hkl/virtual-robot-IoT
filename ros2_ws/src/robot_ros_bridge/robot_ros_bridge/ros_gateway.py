"""本机 HTTP 与 ROS 2 节点之间的网关。"""

import copy
import itertools
import json
import math
import queue
import threading
import time
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

import rclpy
from rclpy.executors import (
    ExternalShutdownException,
    SingleThreadedExecutor,
)

from robot_ros_bridge.command_publisher import (
    CommandPublisherNode,
    MAX_WHEEL_LINEAR_M_S,
    WHEEL_TRACK_M,
)
from robot_ros_bridge.state_subscriber import (
    StateSubscriberNode,
)


HOST = "127.0.0.1"
PORT = 8766

TASK_SIDE_CM = 20.0
TASK_FORWARD_CM_S = 8.0
TASK_TURN_CM_S = 5.0
CIRCLE_RADIUS_CM = 20.0

PHASE_TIMEOUT_S = 12.0
CIRCLE_TIMEOUT_S = 40.0


class GatewayError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class RosGateway:
    def __init__(self):
        self.publisher = CommandPublisherNode()
        self.subscriber = StateSubscriberNode(
            log_updates=False
        )

        if not self.publisher.get_parameter(
            "use_sim_time"
        ).value:
            raise RuntimeError(
                "ROS 网关必须使用仿真时钟；启动时添加 "
                "--ros-args -p use_sim_time:=true"
            )

        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.publisher)
        self.executor.add_node(self.subscriber)

        self.commands = queue.PriorityQueue()
        self.order = itertools.count()

        self.status_lock = threading.Lock()
        self.latest_status = None

        self.last_stamp = None
        self.last_odom = None
        self.position = {"x": 0.0, "y": 0.0}
        self.yaw_deg = 0.0
        self.trajectory = []

        self.direction = None
        self.speed_cm_s = 0.0
        self.manual_end_ns = None

        self.task_name = None
        self.task_phase = None
        self.side_index = 0
        self.phase_started_ns = 0
        self.phase_start_position = None
        self.phase_start_yaw_total = 0.0
        self.previous_yaw = 0.0
        self.total_yaw = 0.0
        self.last_task_result = None

    def record(self, event):
        self.trajectory.append({
            "x": self.position["x"],
            "y": self.position["y"],
            "event": event,
        })

    def make_status(self, odom):
        stamp = odom["stamp"]
        simulation_time_s = (
            stamp["sec"]
            + stamp["nanosec"] / 1_000_000_000
        )

        return {
            "online": True,
            # moving 表示当前有运动指令。
            "moving": self.direction is not None,
            "direction": self.direction,
            "speed": self.speed_cm_s,
            "current_task": self.task_name,
            "task_phase": (
                f"{self.task_phase}_{self.side_index + 1}"
                if self.task_name is not None
                else None
            ),
            "last_task_result": self.last_task_result,
            "position": dict(self.position),
            "trajectory": list(self.trajectory),
            "yaw_deg": self.yaw_deg,
            "simulation_time_s": round(
                simulation_time_s,
                3,
            ),
            "backend": "ros",
            "position_source": "odom",
            "odom_frame": odom["frame_id"],
            "measured_speed_cm_s": round(
                odom["linear_m_s"] * 100,
                3,
            ),
        }

    def publish_status(self, odom):
        status = self.make_status(odom)
        with self.status_lock:
            self.latest_status = status
        return status

    def get_status(self):
        if self.subscriber.get_latest_status() is None:
            raise GatewayError(
                503,
                "尚未收到 /odom，或里程计数据已超过 2 秒",
            )

        with self.status_lock:
            if self.latest_status is None:
                raise GatewayError(
                    503,
                    "正在等待第一条机器人状态",
                )
            return copy.deepcopy(self.latest_status)

    def reset_after_clock_restart(self):
        self.publisher.stop_motion()

        self.direction = None
        self.speed_cm_s = 0.0
        self.manual_end_ns = None

        self.task_name = None
        self.task_phase = None
        self.last_task_result = None

        self.trajectory = []
        self.last_stamp = None

    def finish_task(self, result, event):
        self.publisher.stop_motion()

        self.direction = None
        self.speed_cm_s = 0.0
        self.task_name = None
        self.task_phase = None
        self.last_task_result = result

        self.record(event)

    def start_phase(self, phase):
        self.task_phase = phase
        self.phase_started_ns = (
            self.publisher.get_clock().now().nanoseconds
        )
        self.phase_start_position = dict(self.position)
        self.phase_start_yaw_total = self.total_yaw

        if phase == "straight":
            linear_m_s = TASK_FORWARD_CM_S / 100
            angular_rad_s = 0.0
            self.direction = "forward"
            self.speed_cm_s = TASK_FORWARD_CM_S
        elif phase == "turn":
            linear_m_s = 0.0
            angular_rad_s = (
                2 * (TASK_TURN_CM_S / 100)
                / WHEEL_TRACK_M
            )
            self.direction = "left"
            self.speed_cm_s = TASK_TURN_CM_S
        elif phase == "circle":
            linear_m_s = TASK_FORWARD_CM_S / 100
            angular_rad_s = (
                linear_m_s / (CIRCLE_RADIUS_CM / 100)
            )
            self.direction = "left"
            self.speed_cm_s = TASK_FORWARD_CM_S
        else:
            raise ValueError(f"未知任务阶段：{phase}")

        # 每个阶段有 60 仿真秒的发布器安全上限；
        # 网关自己的阶段超时会更早停止任务。
        self.publisher.start_motion(
            linear_m_s,
            angular_rad_s,
            60.0,
        )

    def advance_task(self, odom, now_ns):
        if self.task_name is None:
            return

        current_yaw = odom["yaw_rad"]
        change = math.atan2(
            math.sin(current_yaw - self.previous_yaw),
            math.cos(current_yaw - self.previous_yaw),
        )
        self.total_yaw += change
        self.previous_yaw = current_yaw

        elapsed_s = (
            now_ns - self.phase_started_ns
        ) / 1_000_000_000

        timeout_s = (
            CIRCLE_TIMEOUT_S
            if self.task_phase == "circle"
            else PHASE_TIMEOUT_S
        )
        if elapsed_s > timeout_s:
            self.finish_task(
                "timeout",
                "task_timeout",
            )
            return

        turned_rad = abs(
            self.total_yaw
            - self.phase_start_yaw_total
        )

        if self.task_phase == "circle":
            if turned_rad >= (
                2 * math.pi - math.radians(5)
            ):
                self.finish_task(
                    "completed",
                    "task_complete",
                )
            return

        if self.task_phase == "straight":
            distance_cm = math.hypot(
                self.position["x"]
                - self.phase_start_position["x"],
                self.position["y"]
                - self.phase_start_position["y"],
            )
            if distance_cm < TASK_SIDE_CM - 0.5:
                return

            self.record("segment_end")
            if self.task_name == "forward":
                self.finish_task(
                    "completed",
                    "task_complete",
                )
            else:
                self.start_phase("turn")
            return

        if self.task_phase == "turn":
            if turned_rad < math.radians(88):
                return

            self.record("segment_end")
            self.side_index += 1

            if self.side_index >= 4:
                self.finish_task(
                    "completed",
                    "task_complete",
                )
            else:
                self.start_phase("straight")

    def refresh_from_odometry(self):
        odom = self.subscriber.get_latest_status()
        if odom is None:
            return

        stamp = (
            odom["stamp"]["sec"],
            odom["stamp"]["nanosec"],
        )

        if stamp == self.last_stamp:
            return

        if (
            self.last_stamp is not None
            and stamp < self.last_stamp
        ):
            self.reset_after_clock_restart()

        self.last_stamp = stamp
        self.last_odom = odom
        self.position = {
            "x": round(
                odom["position_m"]["x"] * 100,
                3,
            ),
            "y": round(
                odom["position_m"]["y"] * 100,
                3,
            ),
        }
        self.yaw_deg = round(
            math.degrees(odom["yaw_rad"]),
            3,
        )

        if not self.trajectory:
            self.record("start")

        now_ns = (
            self.publisher.get_clock().now().nanoseconds
        )

        if (
            self.manual_end_ns is not None
            and now_ns >= self.manual_end_ns
        ):
            self.publisher.stop_motion()
            self.direction = None
            self.speed_cm_s = 0.0
            self.manual_end_ns = None
            self.record("segment_end")

        self.advance_task(odom, now_ns)

        if self.direction is not None:
            previous = self.trajectory[-1]
            distance_cm = math.hypot(
                self.position["x"] - previous["x"],
                self.position["y"] - previous["y"],
            )
            if distance_cm >= 0.5:
                self.record("progress")

        self.publish_status(odom)

    def require_ready(self):
        odom = self.subscriber.get_latest_status()
        if odom is None or self.last_odom is None:
            raise GatewayError(
                503,
                "没有新鲜的 /odom 数据，不能开始运动",
            )

        if (
            self.publisher.get_clock().now().nanoseconds
            == 0
        ):
            raise GatewayError(
                503,
                "尚未收到 /clock，不能开始运动",
            )

        return odom

    def handle_command(self, payload):
        action = payload.get("action")

        if action == "stop":
            if self.task_name is not None:
                self.last_task_result = "stopped"

            self.publisher.stop_motion()
            self.direction = None
            self.speed_cm_s = 0.0
            self.manual_end_ns = None
            self.task_name = None
            self.task_phase = None

            if self.last_odom is not None:
                self.record("stop")

            odom = self.subscriber.get_latest_status()
            if odom is None:
                raise GatewayError(
                    503,
                    "已发布停止指令，但 /odom 已过期，"
                    "无法确认当前位置",
                )

            return {
                "message": (
                    "已向 /cmd_vel 发布零速度；"
                    "当前位置来自最新 /odom"
                ),
                "status": self.publish_status(odom),
            }

        odom = self.require_ready()

        if action == "move":
            direction = payload.get("direction")
            speed = payload.get("speed")
            duration_s = payload.get("duration_s")

            if direction not in (
                "forward",
                "backward",
                "left",
                "right",
            ):
                raise GatewayError(422, "方向无效")

            if (
                isinstance(speed, bool)
                or not isinstance(
                    speed,
                    (int, float),
                )
                or not math.isfinite(speed)
                or not 0 < speed <= 20
            ):
                raise GatewayError(
                    422,
                    "速度必须大于 0 且不超过 20 cm/s",
                )

            if (
                isinstance(duration_s, bool)
                or not isinstance(
                    duration_s,
                    (int, float),
                )
                or not math.isfinite(duration_s)
                or not 0 < duration_s <= 60
            ):
                raise GatewayError(
                    422,
                    "时长必须大于 0 且不超过 60 秒",
                )

            wheel_m_s = speed / 100
            if (
                wheel_m_s
                > MAX_WHEEL_LINEAR_M_S
            ):
                raise GatewayError(
                    422,
                    "速度超过发布器轮速上限",
                )

            if direction == "forward":
                linear_m_s = wheel_m_s
                angular_rad_s = 0.0
            elif direction == "backward":
                linear_m_s = -wheel_m_s
                angular_rad_s = 0.0
            else:
                linear_m_s = 0.0
                angular_rad_s = (
                    2 * wheel_m_s / WHEEL_TRACK_M
                )
                if direction == "right":
                    angular_rad_s = -angular_rad_s

            if self.direction is not None:
                self.record("segment_end")

            if self.task_name is not None:
                self.last_task_result = "interrupted"

            self.task_name = None
            self.task_phase = None

            self.publisher.start_motion(
                linear_m_s,
                angular_rad_s,
                duration_s,
            )

            self.manual_end_ns = (
                self.publisher.end_time_ns
            )
            self.direction = direction
            self.speed_cm_s = float(speed)
            self.record("move")

            message = (
                "已向 /cmd_vel 发布运动指令；"
                "实际位置将随 /odom 更新"
            )

        elif action == "task":
            name = payload.get("name")
            if name not in (
                "forward",
                "square",
                "circle",
            ):
                raise GatewayError(
                    422,
                    "未知预设任务",
                )

            if self.direction is not None:
                self.record("segment_end")

            self.manual_end_ns = None
            self.task_name = name
            self.task_phase = None
            self.side_index = 0
            self.total_yaw = 0.0
            self.previous_yaw = odom["yaw_rad"]
            self.last_task_result = None

            self.record(f"task:{name}")
            self.start_phase(
                "circle"
                if name == "circle"
                else "straight"
            )

            message = (
                f"已启动 ROS 预设任务：{name}；"
                "按 /odom 读数推进轨迹"
            )

        else:
            raise GatewayError(422, "未知指令")

        return {
            "message": message,
            "status": self.publish_status(odom),
        }

    def submit(self, payload):
        ticket = {
            "payload": payload,
            "done": threading.Event(),
            "lock": threading.Lock(),
            "cancelled": False,
            "response": None,
        }

        # 停止指令优先于尚未处理的普通指令。
        priority = (
            0
            if payload.get("action") == "stop"
            else 1
        )
        self.commands.put(
            (priority, next(self.order), ticket)
        )
        return ticket

    def process_one_command(self):
        try:
            _, _, ticket = self.commands.get_nowait()
        except queue.Empty:
            return

        with ticket["lock"]:
            if ticket["cancelled"]:
                return

            try:
                result = self.handle_command(
                    ticket["payload"]
                )
                ticket["response"] = (200, result)
            except GatewayError as exc:
                ticket["response"] = (
                    exc.status_code,
                    {"error": exc.detail},
                )
            except Exception as exc:
                self.publisher.stop_motion()
                self.direction = None
                self.speed_cm_s = 0.0
                self.manual_end_ns = None
                self.task_name = None
                self.task_phase = None

                self.publisher.get_logger().error(
                    f"处理指令失败：{exc}"
                )
                ticket["response"] = (
                    500,
                    {"error": "ROS 网关处理指令失败"},
                )

            ticket["done"].set()

    def run(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, code, data):
                body = json.dumps(
                    data,
                    ensure_ascii=False,
                ).encode("utf-8")

                self.send_response(code)
                self.send_header(
                    "Content-Type",
                    "application/json; charset=utf-8",
                )
                self.send_header(
                    "Cache-Control",
                    "no-store",
                )
                self.send_header(
                    "Content-Length",
                    str(len(body)),
                )
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path != "/status":
                    self.send_json(
                        404,
                        {"error": "未知地址"},
                    )
                    return

                try:
                    status = gateway.get_status()
                except GatewayError as exc:
                    self.send_json(
                        exc.status_code,
                        {"error": exc.detail},
                    )
                    return

                self.send_json(200, status)

            def do_POST(self):
                if self.path != "/command":
                    self.send_json(
                        404,
                        {"error": "未知地址"},
                    )
                    return

                try:
                    length = int(
                        self.headers.get(
                            "Content-Length",
                            "0",
                        )
                    )
                except ValueError:
                    self.send_json(
                        400,
                        {"error": "Content-Length 无效"},
                    )
                    return

                if not 0 < length <= 2048:
                    self.send_json(
                        400,
                        {"error": "请求体长度无效"},
                    )
                    return

                self.connection.settimeout(2.0)

                try:
                    payload = json.loads(
                        self.rfile.read(length)
                    )
                except (
                    ValueError,
                    TimeoutError,
                    OSError,
                ):
                    self.send_json(
                        400,
                        {"error": "请求体不是有效 JSON"},
                    )
                    return

                if not isinstance(payload, dict):
                    self.send_json(
                        400,
                        {"error": "请求体必须是 JSON 对象"},
                    )
                    return

                ticket = gateway.submit(payload)
                ticket["done"].wait(timeout=1.5)

                with ticket["lock"]:
                    response = ticket["response"]
                    if response is None:
                        # 超时后取消，防止仿真恢复时再执行。
                        ticket["cancelled"] = True

                if response is None:
                    self.send_json(
                        503,
                        {
                            "error": (
                                "ROS 网关未及时处理指令；"
                                "排队中的指令已取消"
                            )
                        },
                    )
                    return

                code, result = response
                self.send_json(code, result)

            def log_message(
                self,
                format_string,
                *args,
            ):
                # 网页频繁查询状态，不打印每次访问。
                pass

        server = LocalServer(
            (HOST, PORT),
            Handler,
        )
        server_thread = threading.Thread(
            target=server.serve_forever,
            name="ros-gateway-http",
            daemon=True,
        )
        server_thread.start()

        self.publisher.get_logger().info(
            f"ROS 网关：http://{HOST}:{PORT}"
        )

        try:
            while rclpy.ok():
                self.executor.spin_once(
                    timeout_sec=0.02
                )
                self.refresh_from_odometry()
                self.process_one_command()
        finally:
            if rclpy.ok():
                self.publisher.stop_motion()
                for _ in range(5):
                    self.publisher.publish_velocity(
                        0.0,
                        0.0,
                    )
                    time.sleep(0.02)

            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2.0)

    def close(self):
        self.executor.shutdown()
        self.publisher.destroy_node()
        self.subscriber.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


def main():
    rclpy.init()
    gateway = None

    try:
        gateway = RosGateway()
        gateway.run()
    except (
        KeyboardInterrupt,
        ExternalShutdownException,
    ):
        pass
    finally:
        if gateway is not None:
            gateway.close()
        elif rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()