from glob import glob
from setuptools import setup


package_name = "robot_ros_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        (
            "share/" + package_name,
            ["package.xml"],
        ),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/worlds", glob("worlds/*.wbt")),
        (
            "share/" + package_name + "/resource",
            glob("resource/turtlebot_*.urdf")
            + glob("resource/ros2control_dual.yaml")
            + glob("resource/LICENSE.webots_ros2"),
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="student",
    maintainer_email="2861833407@qq.com",
    description="ROS 2 nodes for the Webots TurtleBot assessment project",
    license="MIT",
    entry_points={
        "console_scripts": [
            "command_publisher = robot_ros_bridge.command_publisher:main",
            "state_subscriber = robot_ros_bridge.state_subscriber:main",
            "ros_gateway = robot_ros_bridge.ros_gateway:main",
            "dual_state_gateway = robot_ros_bridge.dual_state_gateway:main",
        ],
    },
)
