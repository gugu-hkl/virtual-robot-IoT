# 阶段三 · 第二次提交：双机器人实时状态查询

## 本次链路

Webots 中的 a、b → 各自的 `/a/odom`、`/b/odom` → 本项目 `dual_state_gateway` → Ubuntu 本机 HTTP `127.0.0.1:8767` → FastAPI `GET /robots/a/status`、`GET /robots/b/status` → Windows 浏览器或其他 HTTP 客户端。

本次仅增加状态查询，不改旧的五个接口，也不改控制网页。原 `/status` 仍属于第二阶段的单机器人后端；仅启动双机器人世界和新状态网关时，它不会自动显示 a、b。

`position_m.x/y/z` 的单位是米，`yaw_deg` 是角度，`linear_m_s` 是米/秒，`angular_rad_s` 是弧度/秒。`position_source: "odom"` 表示数据来自轮式里程计，坐标是相对于各自里程计原点的估计值，不是 Webots GPS 世界坐标。`simulation_time_s` 来自消息时间戳；`data_age_s` 是最近一次仿真时间戳变化距今的实际秒数。

## 启动

以下路径沿用此前你贴出的 Ubuntu 路径；如果实际仓库位置不同，替换 `cd`。先关闭旧的单机器人 Webots 启动进程和旧的 ROS 网关。将代码同步到 Ubuntu 后，打开三个终端。

**终端 A：构建并启动双机器人世界。**

```bash
source /opt/ros/jazzy/setup.bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
colcon build --packages-select robot_ros_bridge --symlink-install
source install/setup.bash
ros2 launch robot_ros_bridge dual_turtlebot.launch.py
```

**终端 B：启动新状态网关。**

```bash
source /opt/ros/jazzy/setup.bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
source install/setup.bash
ros2 run robot_ros_bridge dual_state_gateway
```

应看到它正在订阅 `/a/odom`、`/b/odom`，并监听 `127.0.0.1:8767`。ROS 2 系统依赖来自 Jazzy 环境；不要在普通 FastAPI 虚拟环境中直接运行这个 ROS 2 节点。

**终端 C：启动 FastAPI。**

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv/bin/activate
ROBOT_BACKEND=ros python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

此时 `/robots/a/status`、`/robots/b/status` 可以工作；旧 `/status` 若没有运行第二阶段单机器人 ROS 网关，会返回 503。这不是本次双机器人状态接口的故障。

## 验收

在 Ubuntu 或 Windows 浏览器分别打开：

```text
http://<Ubuntu-IP>:8000/robots/a/status
http://<Ubuntu-IP>:8000/robots/b/status
http://<Ubuntu-IP>:8000/docs
```

先在 Ubuntu 直接检查 ROS 状态网关，再检查 FastAPI 转发，便于定位是哪一段出现问题：

```bash
curl -i http://127.0.0.1:8767/robots/a/status
curl -i http://127.0.0.1:8767/robots/b/status
curl -i http://127.0.0.1:8000/robots/a/status
curl -i http://127.0.0.1:8000/robots/b/status
curl -i http://127.0.0.1:8000/robots/c/status
```

前两项应返回 200，并且 `robot_id` 分别是 `a`、`b`；第三项应返回 404。对照 `ros2 topic echo /a/odom --once`、`ros2 topic echo /b/odom --once`，核查位置和速度数值来自对应机器人。

再按上一提交的验收命令单独移动 a，观察 a 的 `position_m`、`linear_m_s` 变化，b 的位置不应跟着改变；随后单独移动 b，检查相反情况。机器人停止后，实测线速度应趋近 0。

在 Webots 中按暂停，等待超过 2 秒，再执行：

```bash
curl -i http://127.0.0.1:8000/robots/a/status
curl -i http://127.0.0.1:8000/robots/b/status
```

两项都应返回 503，错误内容包含“数据过期”。恢复仿真后应重新返回 200。若重复收到相同仿真时间戳，网关也不会把它当作新状态。最后停止终端 B 的状态网关，再查询，FastAPI 应返回连接失败的 503，而不是继续给出旧位置。

## 故障定位

- 8767 可查，8000 不可查：检查 FastAPI 是否启动、Ubuntu 防火墙与局域网地址。
- 8767 返回“尚未收到数据”：检查 `/a/odom`、`/b/odom` 是否存在且持续发布，双机器人控制器是否 `active`。
- 8767 返回“数据过期”：检查 Webots 是否暂停、仿真时间是否推进、对应机器人驱动是否仍在运行。
- 仅一台有数据：分别检查对应 `/a/controller_manager`、`/b/controller_manager` 和双机器人 launch 日志。
