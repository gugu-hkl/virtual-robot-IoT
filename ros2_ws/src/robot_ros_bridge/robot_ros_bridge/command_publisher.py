"""向 /cmd_vel 发布 TwistStamped 的 ROS 2 节点。"""

import argparse
import math
import time

import rclpy
from geometry_msgs.msg import TwistStamped
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)


WHEEL_TRACK_M = 0.16
MAX_WHEEL_LINEAR_M_S = 0.20
PUBLISH_PERIOD_S = 0.1


class CommandPublisherNode(Node):
    def __init__(self):
        super().__init__("robot_command_publisher")

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(
            TwistStamped,
            "/cmd_vel",
            qos,
        )
        self.timer = self.create_timer(
            PUBLISH_PERIOD_S,
            self.on_timer,
        )

        self.linear_m_s = 0.0
        self.angular_rad_s = 0.0
        self.end_time_ns = None
        self.motion_started = False
        self.zero_ticks = 0
        self.finished = False

    def publish_velocity(self, linear_m_s, angular_rad_s):
        message = TwistStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "base_link"
        message.twist.linear.x = float(linear_m_s)
        message.twist.angular.z = float(angular_rad_s)
        self.publisher.publish(message)

    def start_motion(self, linear_m_s, angular_rad_s, duration_s):
        """由 ROS 执行线程调用；持续时间使用仿真时钟。"""
        now_ns = self.get_clock().now().nanoseconds
        if now_ns == 0:
            raise RuntimeError("尚未收到 /clock，不能开始计时运动")

        self.linear_m_s = linear_m_s
        self.angular_rad_s = angular_rad_s
        self.end_time_ns = now_ns + int(duration_s * 1_000_000_000)
        self.motion_started = True
        self.zero_ticks = 0
        self.finished = False

        # 立即发出首条命令；定时器随后持续刷新。
        self.publish_velocity(linear_m_s, angular_rad_s)
        self.get_logger().info(
            f"开始运动：linear.x={linear_m_s:.3f} m/s，"
            f"angular.z={angular_rad_s:.3f} rad/s，"
            f"持续 {duration_s:.1f} 仿真秒"
        )

    def stop_motion(self):
        """由 ROS 执行线程调用。"""
        self.linear_m_s = 0.0
        self.angular_rad_s = 0.0
        self.end_time_ns = None
        self.publish_velocity(0.0, 0.0)

    def on_timer(self):
        now_ns = self.get_clock().now().nanoseconds
        if now_ns == 0:
            return

        if self.end_time_ns is not None and now_ns >= self.end_time_ns:
            self.stop_motion()
        else:
            self.publish_velocity(
                self.linear_m_s,
                self.angular_rad_s,
            )

        # 独立运行时，结束后继续发一段时间的零速度再退出。
        if self.motion_started and self.end_time_ns is None:
            self.zero_ticks += 1
            if self.zero_ticks >= 10:
                self.finished = True


def main():
    parser = argparse.ArgumentParser(
        description="使用自己的 ROS 2 节点控制 Webots TurtleBot"
    )
    parser.add_argument(
        "--linear",
        type=float,
        required=True,
        help="机器人前后线速度，单位 m/s",
    )
    parser.add_argument(
        "--angular",
        type=float,
        default=0.0,
        help="机器人转向角速度，单位 rad/s；左转为正",
    )
    parser.add_argument(
        "--duration",
        type=float,
        required=True,
        help="运动时长，单位 Webots 仿真秒",
    )

    arguments, ros_arguments = parser.parse_known_args()

    values = (
        arguments.linear,
        arguments.angular,
        arguments.duration,
    )
    if not all(math.isfinite(value) for value in values):
        parser.error("速度和时长必须是有限数字")

    if not 0 < arguments.duration <= 60:
        parser.error("时长必须大于 0 且不超过 60 仿真秒")

    # 差速车左右轮的目标轮缘线速度。
    left_m_s = (
        arguments.linear
        - arguments.angular * WHEEL_TRACK_M / 2
    )
    right_m_s = (
        arguments.linear
        + arguments.angular * WHEEL_TRACK_M / 2
    )
    if max(abs(left_m_s), abs(right_m_s)) > MAX_WHEEL_LINEAR_M_S:
        parser.error("该线速度与角速度组合超过当前设定的轮速上限")

    rclpy.init(args=ros_arguments)
    node = CommandPublisherNode()

    try:
        # use_sim_time=true 时，等 /clock 开始更新。
        wait_started = time.monotonic()
        while rclpy.ok() and node.get_clock().now().nanoseconds == 0:
            if time.monotonic() - wait_started > 10:
                raise RuntimeError(
                    "10 秒内没有收到 /clock，请检查 Webots 仿真是否运行"
                )
            rclpy.spin_once(node, timeout_sec=0.1)

        node.start_motion(
            arguments.linear,
            arguments.angular,
            arguments.duration,
        )

        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.2)

    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.stop_motion()
            for _ in range(9):
                node.publish_velocity(0.0, 0.0)
                time.sleep(0.05)

        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()