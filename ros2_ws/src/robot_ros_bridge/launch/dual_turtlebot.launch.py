"""Start two independently controlled TurtleBot3 Burger robots in Webots."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import EmitEvent, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch_ros.actions import Node
from webots_ros2_driver.wait_for_controller_connection import WaitForControllerConnection
from webots_ros2_driver.webots_controller import WebotsController
from webots_ros2_driver.webots_launcher import WebotsLauncher



PACKAGE_NAME = "robot_ros_bridge"


def make_robot_nodes(robot_id, package_dir, control_params):
    """Connect one named Webots robot to its own ROS namespace."""
    namespace = f"/{robot_id}"
    driver = WebotsController(
        robot_name=robot_id,
        namespace=robot_id,
        parameters=[
            {
                "robot_description": os.path.join(
                    package_dir, "resource", f"turtlebot_{robot_id}.urdf"
                ),
                "use_sim_time": True,
                "set_robot_state_publisher": True,
            },
            control_params,
        ],
        remappings=[
            (f"{namespace}/diffdrive_controller/cmd_vel", f"{namespace}/cmd_vel"),
            (f"{namespace}/diffdrive_controller/odom", f"{namespace}/odom"),
        ],
        respawn=True,
    )

    state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        namespace=robot_id,
        output="screen",
        parameters=[
            {
                "robot_description": '<robot name="turtlebot"><link name="base_link"/></robot>',
                "use_sim_time": True,
            }
        ],
    )

    manager = f"{namespace}/controller_manager"
    spawners = [
        Node(
            package="controller_manager",
            executable="spawner",
            namespace=robot_id,
            output="screen",
            arguments=[
                controller_name,
                "-c",
                manager,
                "--controller-manager-timeout",
                "50",
            ],
        )
        for controller_name in ("joint_state_broadcaster", "diffdrive_controller")
    ]

    start_controllers = WaitForControllerConnection(
        target_driver=driver,
        nodes_to_start=spawners,
    )
    return state_publisher, driver, start_controllers


def generate_launch_description():
    package_dir = get_package_share_directory(PACKAGE_NAME)
    world = os.path.join(package_dir, "worlds", "dual_turtlebot.wbt")
    control_params = os.path.join(package_dir, "resource", "ros2control_dual.yaml")

    webots = WebotsLauncher(world=world, mode="realtime", ros2_supervisor=True)
    a_nodes = make_robot_nodes("a", package_dir, control_params)
    b_nodes = make_robot_nodes("b", package_dir, control_params)

    shutdown_on_webots_exit = RegisterEventHandler(
        OnProcessExit(target_action=webots, on_exit=[EmitEvent(event=Shutdown())])
    )
    return LaunchDescription(
        [webots, webots._supervisor, *a_nodes, *b_nodes, shutdown_on_webots_exit]
    )
