# 第三阶段最终链路：刷脸选择后的双机器人网页控制

## 完整数据流

```text
Ubuntu 摄像头识别 A/B
  → POST /display/selection，选择 a/b
  → Windows 浏览器 /stage3 查询当前选择
  → POST /robots/{id}/move（id 为 a 或 b）
  → Ubuntu 本机双机器人 ROS 网关 127.0.0.1:8767
  → /a/cmd_vel 或 /b/cmd_vel（TwistStamped）
  → Webots 中对应机器人运动
  → /a/odom 或 /b/odom（Odometry）
  → 网页实时状态刷新；ESP32 通过 Wi-Fi 轮询 /display/state 更新 OLED
```

刷脸只决定网页和 OLED 的当前目标。运动由人在网页上点击按钮后发出；**不再做“识别后自动执行正方形/圆形任务”**。切换目标时，FastAPI 会尝试先停止上一台机器人，再更新选择。若停止未能确认，网页会显示警告。停止 a、b 的按钮始终分别可用，便于在没有人脸选择时停机。

旧的单机器人首页 `/` 和五个接口 `/status`、`/sensor`、`/move`、`/stop`、`/task` 继续用于第二阶段。第三阶段新页面是 `/stage3`，使用独立的双机器人路由。请不要同时运行第二阶段单机器人 ROS 网关去控制此双机器人世界。

## 新接口

| 路由 | 作用 |
| --- | --- |
| `GET /display/selection` | 获取当前选中的 a/b、选择版本和切换时的停止警告 |
| `GET /robots/a/status`、`GET /robots/b/status` | 获取各自的最新 `/odom` 位置、朝向、实测线速度和角速度；超过 2 秒无新仿真时间戳则报过期 |
| `POST /robots/{id}/move` | 给当前选中的机器人发送前进、后退、原地左转或右转；请求必须携带当前 `selection_revision`，过期版本返回 409 |
| `POST /robots/{id}/stop` | 停止指定机器人 a 或 b；不要求它当前仍被刷脸选中 |
| `POST /display/selection`、`GET /display/state` | 继续供人脸识别和 ESP32 使用 |

移动输入是 `direction`、`speed`（轮缘速度，cm/s，0～20）、`duration_s`（仿真秒，0～10）和 `selection_revision`。FastAPI 与 ROS 网关都验证参数，里程计数据过期时拒绝启动运动。控制接口的 `accepted: true` 只表示 ROS 网关**接收并发布了指令**；实际运动是否发生，以后续 `/odom` 的位置和速度变化为准。Webots 暂停时仿真时间也暂停，不能把墙钟计时当作机器人已完成运动。

网页坐标图展示**当前选中机器人**的 `/odom` 坐标。a 与 b 的里程计原点各自独立，不能把两套坐标直接当作同一张世界地图；页面分别缓存本次浏览器会话采样到的轨迹，刷新页面后清空。OLED 仍显示已选机器人由 ROS 2 实测的状态，不显示网页采样轨迹。

## Ubuntu 启动顺序

代码同步到 Ubuntu 后，先重新构建 ROS 包。以下目录沿用前面的项目路径；实际位置不同就替换 `cd`。

**终端 A：Webots 双机器人世界。**

```bash
source /opt/ros/jazzy/setup.bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
colcon build --packages-select robot_ros_bridge --symlink-install
source install/setup.bash
ros2 launch robot_ros_bridge dual_turtlebot.launch.py
```

**终端 B：双机器人 ROS 状态与控制网关。**此命令中的仿真时钟参数是本次控制功能必需的：

```bash
source /opt/ros/jazzy/setup.bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
source install/setup.bash
ros2 run robot_ros_bridge dual_state_gateway --ros-args -p use_sim_time:=true
```

**终端 C：FastAPI。**只启动一个进程，不使用 `--workers`；刷脸选择状态保存在该进程内存中。

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv/bin/activate
ROBOT_BACKEND=ros python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**终端 D：人脸识别与 Ubuntu 预览。**A/B 已按前一步完成注册时：

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv-face/bin/activate
python -m stage3.face_id.run --camera 0 --preview
```

ESP32 沿用此前的热点配置和固件，无须修改；它继续轮询 `http://<Ubuntu热点IP>:8000/display/state`。Windows 在同一网络中打开 `http://<Ubuntu热点IP>:8000/stage3`。旧首页 `/` 只展示单机器人第二阶段信息，不用于本次双机器人演示。

## 手动验收

1. 在 Ubuntu 先核对 `ros2 topic list -t` 有 `/a/cmd_vel`、`/b/cmd_vel`、`/a/odom`、`/b/odom`；`ros2 topic type /a/cmd_vel` 应返回 `geometry_msgs/msg/TwistStamped`，`ros2 topic type /a/odom` 应返回 `nav_msgs/msg/Odometry`。确认两个 `diffdrive_controller` 都处于 active。打开 `/stage3` 时，两张机器人卡片出现各自的 `/odom` 数据；无人刷脸时移动按钮禁用。
2. A 出现在摄像头前并稳定识别：预览窗口显示 A，网页选择 a，OLED 显示 `ROBOT A`。在网页选择“前进”、8 cm/s、1.5 秒并发送。Webots 中只有 a 运动，网页 a 的位置和实测速度变化，OLED 的 a 数据随下一次轮询更新。
3. 在网页点“停止 a”，确认网关返回停止确认，随后 a 的 `/odom` 实测速度接近 0。这里以实测数据为准，不能仅凭按钮成功提示判断已经停稳。
4. B 稳定出现：网页和 OLED 切换 b。再发送“原地左转”，Webots 中只有 b 转动，网页 b 的朝向、角速度更新；a 的状态不会被当成 b 显示。
5. 在 A 正运动时切换到 B：网关应先收到停止 a 的请求；若网关不可用，网页明确显示停止警告。旧网页仍携带 a 的选择版本发送移动指令时，应收到 409，不能误控 a。
6. 暂停 Webots 超过 2 秒：状态接口应返回过期错误，网页清掉旧读数并禁用移动；OLED 显示数据过期。恢复后状态重新更新。即使没有人脸选择，网页仍能分别点击“停止 a”和“停止 b”。
7. 按预览窗口的 `q`：人脸程序清除选择，网页回到“等待刷脸”，OLED 回到 `WAIT SELECT`。

要单独验收旧选择版本返回 409，可在 A 被选中时从 `GET /display/selection` 记下 `selection_revision`，切换到 B 后，在 `/docs` 执行 `POST /robots/a/move`，把刚记下的旧版本填入请求体。返回 409 且 Webots 中 a 不重新启动才算通过。`/docs` 中该请求体示例的 `direction` 取 `forward`、`speed` 取 8、`duration_s` 取 1.5 即可。

若网页点“移动”收到“必须使用仿真时钟”的错误，检查终端 B 是否按上面的命令启动并重新构建了 ROS 包。若 `/a/odom` 或 `/b/odom` 数据过期，先检查 Webots 是否暂停和控制器是否 active。机器人 a/b 的世界坐标关系不从 `/odom` 推断。

## 本地检查与提交

Windows 项目虚拟环境可运行 `python -m unittest tests.test_stage3_control_api` 检查选择版本、切换停止和状态过期拦截；`node --check web/stage3.js` 检查网页脚本语法。ROS 2 发布和 Webots 运动仍须在 Ubuntu 实测。

建议提交信息：`feat(stage3): 接入刷脸选择后的双机器人网页控制`。保留此前的人脸模板、模型、Wi-Fi 密码和虚拟环境忽略规则。
