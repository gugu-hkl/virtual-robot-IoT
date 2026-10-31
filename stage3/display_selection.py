"""本次演示的屏幕选择状态；由单个 FastAPI 进程保存。"""

from threading import Lock


class DisplaySelection:
    def __init__(self):
        self._lock = Lock()
        self._robot_id = None
        self._revision = 0

    def snapshot(self):
        with self._lock:
            return self._robot_id, self._revision

    def select(self, robot_id):
        if robot_id not in (None, "a", "b"):
            raise ValueError("机器人标号只能是 a、b 或 null")
        with self._lock:
            if robot_id != self._robot_id:
                self._robot_id = robot_id
                self._revision += 1
            return self._robot_id, self._revision


display_selection = DisplaySelection()
