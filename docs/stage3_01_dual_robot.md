# 阶段三 · 第一次提交：双机器人 Webots 与 ROS 2 启动配置

这一提交只建立两台可分别控制的仿真机器人；不启动 FastAPI、摄像头识别或 ESP32。

## 文件与来源

- `ros2_ws/src/robot_ros_bridge/worlds/dual_turtlebot.wbt`：基于 [Webots ROS 2 官方 TurtleBot 世界](https://github.com/cyberbotics/webots_ros2/blob/master/webots_ros2_turtlebot/worlds/turtlebot3_burger_example.wbt)，保留场景并将机器人复制为 `a`、`b`。两台都采用 `controller "<extern>"`。
- `ros2_ws/src/robot_ros_bridge/resource/turtlebot_a.urdf`、`turtlebot_b.urdf`：基于 [官方 TurtleBot Webots URDF](https://github.com/cyberbotics/webots_ros2/blob/master/webots_ros2_turtlebot/resource/turtlebot_webots.urdf)，为雷达和 IMU 设置独立话题及帧名，去掉示例插件。
- `ros2_ws/src/robot_ros_bridge/resource/ros2control_dual.yaml`：以 [官方控制器配置](https://github.com/cyberbotics/webots_ros2/blob/master/webots_ros2_turtlebot/resource/ros2control.yml) 的轮子参数为基础，分别为 `/a`、`/b` 配置控制器。Jazzy 使用 `TwistStamped`，不配置旧版 `use_stamped_vel`。
- `ros2_ws/src/robot_ros_bridge/launch/dual_turtlebot.launch.py`：一份世界、两个 `WebotsController`、两组控制器。参考 [官方 TurtleBot 启动文件](https://github.com/cyberbotics/webots_ros2/blob/master/webots_ros2_turtlebot/launch/robot_launch.py) 和 [官方多机器人启动文件](https://github.com/cyberbotics/webots_ros2/blob/master/webots_ros2_universal_robot/launch/multirobot_launch.py)。
- 复制与改写的官方资源依照 Apache License 2.0；许可证见 `ros2_ws/src/robot_ros_bridge/resource/LICENSE.webots_ros2`。

## Ubuntu 启动

先关闭原来的官方单机器人 launch、旧的 Webots 窗口、阶段二的 ROS 网关和直接控制器，避免多个进程同时控制机器人。把本次修改同步到 Ubuntu 后，在该仓库根目录运行：

```bash
source /opt/ros/jazzy/setup.bash
cd ~/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
colcon build --packages-select robot_ros_bridge --symlink-install
source install/setup.bash
ros2 launch robot_ros_bridge dual_turtlebot.launch.py
```

上面的 `cd` 路径沿用此前你贴出的 Ubuntu 路径；若实际目录不同，进入包含 `src/robot_ros_bridge` 的 `ros2_ws` 即可。首次运行如果 Webots 下载外部 PROTO，请等待完成。Webots 仿真应处于运行状态，不应暂停。

## 验收

另开一个终端，执行：

```bash
source /opt/ros/jazzy/setup.bash
cd ~/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
source install/setup.bash
ros2 topic list -t | grep -E '^/(a|b)/(cmd_vel|odom|scan|imu|joint_states) '
ros2 topic type /a/cmd_vel
ros2 topic type /b/cmd_vel
ros2 control list_controllers -c /a/controller_manager
ros2 control list_controllers -c /b/controller_manager
ros2 topic echo /a/odom --once
ros2 topic echo /b/odom --once
```

应看到两套独立话题；两个 `/cmd_vel` 都是 `geometry_msgs/msg/TwistStamped`；两套 `diffdrive_controller` 和 `joint_state_broadcaster` 都是 `active`；两套 `/odom` 持续更新。雷达、IMU 若未出现，应检查启动日志中的设备插件错误。

先记下两台机器人在 Webots 画面及 `/odom` 中的位置，再仅给 a 发持续 3 秒的前进命令：

```bash
ros2 topic pub --rate 10 --times 30 /a/cmd_vel geometry_msgs/msg/TwistStamped '{header: auto, twist: {linear: {x: 0.10}}}'
```

观察 a 位移，b 静止；命令结束后约半秒应停下。再仅给 b 发命令：

```bash
ros2 topic pub --rate 10 --times 30 /b/cmd_vel geometry_msgs/msg/TwistStamped '{header: auto, twist: {linear: {x: 0.10}}}'
```

观察 b 位移，a 静止。若临近障碍物，先重启世界复位，再做另一台测试。`/odom` 是轮式里程计估计，并非 GPS 真值；本次验收重点是两套机器人独立存在、独立控制和独立回传状态。

## 常见定位点

- 只有一台机器人：检查 Webots 是否加载的是本仓库 `dual_turtlebot.wbt`，而不是官方原世界。
- 只有一套控制器：看启动日志中 `robot_name='a'/'b'` 的连接情况；世界里的机器人 `name` 必须完全对应。
- 控制器没有激活：检查 `/a/controller_manager` 或 `/b/controller_manager` 日志及参数文件是否加载。
- 话题有数据但机器人不动：确认 Webots 仿真正在运行、`/a/cmd_vel` 或 `/b/cmd_vel` 有订阅者、旧进程已退出。
- 运行中可能碰到家具。当前世界沿用官方办公室场景，后续轨迹测试前需要评估起点和轨迹尺寸。
