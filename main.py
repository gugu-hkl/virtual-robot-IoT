print("virtual robot IoT")

from robot import Robot
robot = Robot()
robot.move_status("forward", 5)
print(robot.get_status())
robot.stop()