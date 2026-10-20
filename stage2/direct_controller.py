"""连接 Webots 示例世界中的 TurtleBot，读取仿真传感器。"""

from controller import Robot

def main():
    robot = Robot()
    time_step_ms = int(robot.getBasicTimeStep())

    # 先列出实际设备名称，缺设备时排查。
    devices = {}
    for index in range(robot.getNumberOfDevices()):
        device = robot.getDeviceByIndex(index)
        devices[device.getName()] = device

    print(f"已连接机器人：{robot.getName()}", flush=True)
    print(f"仿真步长：{time_step_ms} ms", flush=True)
    print(f"可用设备：{', '.join(sorted(devices))}", flush=True)

    required_names = (
        "left wheel motor",
        "right wheel motor",
        "gps",
        "inertial_unit",
    )
    missing = [name for name in required_names if name not in devices]
    if missing:
        raise RuntimeError(f"示例世界缺少设备：{missing}")

    left_motor = devices["left wheel motor"]
    right_motor = devices["right wheel motor"]
    gps = devices["gps"]
    inertial_unit = devices["inertial_unit"]

    # 只读状态，两侧车轮保持停止。
    for motor in (left_motor, right_motor):
        motor.setPosition(float("inf"))
        motor.setVelocity(0.0)

    gps.enable(time_step_ms)
    inertial_unit.enable(time_step_ms)

    next_print_time = 0.0

    while robot.step(time_step_ms) != -1:
        simulation_time = robot.getTime()
        if simulation_time < next_print_time:
            continue

        x, y, z = gps.getValues()
        yaw_rad = inertial_unit.getRollPitchYaw()[2]

        print(
            f"仿真时间 {simulation_time:.1f} s | "
            f"GPS ({x:.3f}, {y:.3f}, {z:.3f}) m | "
            f"朝向 {yaw_rad:.3f} rad",
            flush=True,
        )
        next_print_time = simulation_time + 1.0


if __name__ == "__main__":
    main()