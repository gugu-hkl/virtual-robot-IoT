"""订阅 /odom，读取 TurtleBot 的里程计状态。"""

import copy
import math
import threading
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)


class StateSubscriberNode(Node):
    def __init__(self, log_updates=True):
        super().__init__("robot_state_subscriber")

        # BEST_EFFORT 订阅者既能接收 BEST_EFFORT 发布者，
        # 也能接收 RELIABLE 发布者的数据。
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._lock = threading.Lock()
        self._latest_status = None
        self._last_received_at = None
        self._last_logged_at = 0.0
        self._log_updates = log_updates

        self.subscription = self.create_subscription(
            Odometry,
            "/odom",
            self.on_odometry,
            qos,
        )

        self.get_logger().info("正在订阅 /odom，等待机器人状态……")

    def on_odometry(self, message):
        """每收到一条 /odom 消息，就更新一次内存中的最新状态。"""
        position = message.pose.pose.position
        orientation = message.pose.pose.orientation
        velocity = message.twist.twist

        # 四元数转换为平面朝向角。正值表示逆时针转动。
        sin_yaw = 2.0 * (
            orientation.w * orientation.z
            + orientation.x * orientation.y
        )
        cos_yaw = 1.0 - 2.0 * (
            orientation.y * orientation.y
            + orientation.z * orientation.z
        )
        yaw_rad = math.atan2(sin_yaw, cos_yaw)

        status = {
            "frame_id": message.header.frame_id,
            "child_frame_id": message.child_frame_id,
            "stamp": {
                "sec": message.header.stamp.sec,
                "nanosec": message.header.stamp.nanosec,
            },
            "position_m": {
                "x": position.x,
                "y": position.y,
                "z": position.z,
            },
            "yaw_rad": yaw_rad,
            "linear_m_s": velocity.linear.x,
            "angular_rad_s": velocity.angular.z,
        }

        now = time.monotonic()
        with self._lock:
            self._latest_status = status
            self._last_received_at = now

        # /odom 更新较快；终端约每秒打印一次，内存仍保存每次更新。
        if self._log_updates and now - self._last_logged_at >= 1.0:
            self._last_logged_at = now
            self.get_logger().info(
                f"位置 x={position.x:.3f} m, y={position.y:.3f} m | "
                f"朝向={math.degrees(yaw_rad):.1f}° | "
                f"前进速度={velocity.linear.x:.3f} m/s | "
                f"转向速度={velocity.angular.z:.3f} rad/s"
            )

    def get_latest_status(self, max_age_s=2.0):
        """返回最近的状态；没有数据或数据已过期时返回 None。"""
        with self._lock:
            if self._latest_status is None:
                return None

            if time.monotonic() - self._last_received_at > max_age_s:
                return None

            return copy.deepcopy(self._latest_status)


def main(args=None):
    rclpy.init(args=args)
    node = StateSubscriberNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()