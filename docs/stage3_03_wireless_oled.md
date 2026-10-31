# 阶段三 · 第三次提交：ESP32 无线 OLED 状态终端

## 本次数据流

Webots a/b → `/a/odom`、`/b/odom` → 双机器人状态网关 `127.0.0.1:8767` → FastAPI `GET /display/state` → Wi-Fi → ESP32 → I²C OLED。

手动选择通过 FastAPI 的 `POST /display/selection` 完成。选择状态保存在**当前单个 FastAPI 进程的内存**；重启 FastAPI 后恢复为“未选择”。此阶段启动 Uvicorn 时只用一个进程，不加 `--workers`。后续人脸识别会调用同一个选择入口。

`GET /display/state` 有三类结果：

- 200，`state: waiting`：尚未选择机器人，ESP32 显示 `WAIT SELECT`。
- 200，`state: live`：返回当前选中机器人的新鲜里程计状态，ESP32 显示标号、x、y、线速度、角速度和数据年龄。
- 503：仿真数据过期、ROS 状态网关断开等，ESP32 清掉旧数值并显示错误。

切换刚好发生在查询期间时，接口短暂返回 `state: switching`，不把上一台机器人的数据贴到新标号下。ESP32 每秒重新查询一次。位置与速度来自 `/odom`，不是 GPS 世界坐标。

## ESP32 接线与环境

沿用已验收的接线：OLED `VCC → 3V3`、`GND → GND`、`SDA → GPIO21`、`SCK/SCL → GPIO22`；I²C 7 位地址 `0x3C`。目标芯片为照片中的经典 ESP32；项目使用 `idf.py set-target esp32`。

本固件使用 ESP-IDF 原生 Wi-Fi、HTTP 客户端和新版 I²C master API。ESP-IDF 6.x 不再内置 JSON 组件，因此项目通过 `main/idf_component.yml` 引入 `espressif/cjson`；首次构建需要组件管理器获取该依赖。[Espressif JSON 迁移说明](https://docs.espressif.com/projects/esp-idf/en/v6.0-beta2/esp32/migration-guides/release-6.x/6.0/protocols.html)、[I²C API](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/i2c.html)。

## 启动顺序

先把本次仓库文件同步到 Ubuntu。沿用上一阶段的双机器人 launch 和状态网关；另起 FastAPI。以下路径按此前你给出的 Ubuntu 目录填写，实际目录不同时自行替换。

**终端 A：Webots 双机器人。**

```bash
source /opt/ros/jazzy/setup.bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
source install/setup.bash
ros2 launch robot_ros_bridge dual_turtlebot.launch.py
```

**终端 B：状态网关。**

```bash
source /opt/ros/jazzy/setup.bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/ros2_ws
source install/setup.bash
ros2 run robot_ros_bridge dual_state_gateway
```

**终端 C：FastAPI。**

```bash
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT
source .venv/bin/activate
ROBOT_BACKEND=ros python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

本次双机器人 OLED 路由独立于旧单机器人 `/status`；页面首页仍属于第二阶段网页，旧 ROS 网关未启动时首页会显示状态连接错误。先通过 `/docs` 或以下新接口验收。

**终端 D：确认 FastAPI 可从局域网访问。**

```bash
hostname -I
curl -i http://127.0.0.1:8000/display/state
```

从 `hostname -I` 选出 Ubuntu 在手机热点中的地址。ESP32 配置中必须填写这个地址，不能填写 `127.0.0.1` 或 Windows 地址。Windows 浏览器先确认 `http://<Ubuntu-IP>:8000/docs` 可打开。

## 编译与刷入 ESP32

ESP-IDF 终端执行：

```bash
. ~/esp/esp-idf/export.sh
cd /home/gugu/virtual_robot_IoT/virtual-robot-IoT/stage3/esp32_oled
idf.py set-target esp32
idf.py menuconfig
```

在 `Robot OLED terminal` 菜单里填写：

| 设置 | 填写内容 |
| --- | --- |
| Wi-Fi hotspot SSID | 已验证可连接的手机热点名称 |
| Wi-Fi hotspot password | 热点密码 |
| FastAPI display URL | `http://<Ubuntu热点IP>:8000/display/state` |
| OLED SDA/SCL/I²C address | 保持 21、22、`0x3C` |
| Status polling interval | 默认 1000 ms |

保存退出后执行：

```bash
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

串口路径使用你之前 I²C 显示测试时成功的设备路径；如果是 `/dev/ttyACM0` 就替换。`sdkconfig` 包含热点密码，已加入 `.gitignore`，不要手动纳入提交。若编译在下载 `espressif/cjson` 时失败，先检查 Ubuntu 的网络与组件管理器错误信息。

## 手动验收

1. 保持三个服务运行，刚刷入的 OLED 应显示 `WAIT SELECT`。ESP32 串口应打印所获得的热点 IP。
2. 在 Windows 浏览器打开 `http://<Ubuntu-IP>:8000/docs`，执行 `POST /display/selection`，请求体为 `{"robot_id":"a"}`。`GET /display/state` 应返回 `state: live`、`selected_robot: a`，OLED 应显示 `ROBOT A` 与 x、y、V、W、AGE。
3. 把请求体改为 `{"robot_id":"b"}`，确认 OLED 改为 `ROBOT B`，对应 `/robots/b/status`。分别用已验收的 ROS 2 命令单独移动 a、b，确认屏幕数据跟随当前选择的机器人变化。
4. 请求体改为 `{"robot_id":null}`，OLED 应回到 `WAIT SELECT`。
5. 再选中 a，暂停 Webots 超过 2 秒。`GET /display/state` 应返回 503，OLED 应显示 `DATA STALE`，旧数值应被清掉；恢复仿真后重新出现实时数值。
6. 停止 FastAPI，OLED 应显示连接错误，不继续显示最后一次的位置。关掉热点，OLED 应显示 `WIFI LOST`。恢复网络和服务后，它应自动重新显示。
7. 最后拔掉电脑数据线，用 USB 移动电源给 ESP32 开发板供电；不依赖电脑串口时 OLED 仍应更新。OLED 的 VCC 仍接开发板 3V3 引脚，不直接接 5V。

## 如果没有显示

- `SET CONFIG`：检查 `menuconfig` 里的 SSID 和 URL，重新构建刷入。
- `WIFI CONNECT` 或 `WIFI LOST`：检查热点仍在 2.4 GHz、密码正确、ESP32 已连上热点。
- `SERVER OFFLINE`：检查 Ubuntu 和 ESP32 是否在同一热点、FastAPI 是否监听 `0.0.0.0:8000`，并先用 Windows 打开 `/docs`。
- `ROS OFFLINE`：检查双机器人状态网关、`/a/odom` 与 `/b/odom`。
- `DATA STALE`：检查 Webots 是否暂停、对应机器人的仿真时间戳是否继续变化。
- `BAD STATUS`：检查 FastAPI 返回的 JSON 字段是否与固件期望一致。
