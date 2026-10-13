#首先初步写出机器人的设备运行状态打印
#应该包括机器人的初始状态，查询状态，运行控制，停止
#然后定义出任务状态
import time
class Robot:
    #定义出方向坐标映射
    DIRECTIONS = {
        "forward": (0, 1),
        "backward": (0, -1),
        "left": (-1, 0),
        "right": (1, 0),
    }
    #定义预设任务为/task准备
    VALID_TASKS = ['forward', 'square']
    #规定任务基础
    TASK_SPEED = 10  # 任务执行的默认速度
    TASK_SIDE = 20
    def __init__(self):
        #一开始机器人的各种状态:应该包括在线、运动、方向、速度
        #定义任务状态
        self.online = True
        self.moving = False
        self.direction = None
        self.speed = 0
        self.current_task = None

        self.x = 0.0
        self.y = 0.0
        self.trajectory = [
            {"x": 0.0, "y": 0.0, "event": "start"}
        ]
        self._segments = []  # 用于存储任务的每个边的坐标点
        self._segments_index = 0  # 当前任务边的索引
        self._segments_started_at = 0.0  # 当前任务边的开始时间
        self._segments_start_x = 0.0
        self._segments_start_y = 0.0

    #构造轨迹点
    def _record_position(self, event, force=False):
        point = {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "event": event,
        }
        last = self.trajectory[-1]
        position_changed = (
            point["x"] != last["x"] or last["y"] != point["y"]
        )
        #路径变了，就要记录
        if position_changed or force:
            self.trajectory.append(point)


    #运动状态复位
    def _finish_motion(self):
        self._segments = []
        self._segments_index = 0
        self.moving = False
        self.direction = None
        self.speed = 0
        self.current_task = None

    #运动状态更新
    def _update_position(self):
        """根据已经过去的时间，更新机器人位置和运动状态。"""
        if not self._segments:
            return
        now = time.monotonic()
        while self._segments:
            segment = self._segments[self._segments_index]
            duration = segment["duration_s"]
            elapsed = max(0.0, now - self._segment_started_at)
            travel_time = min(elapsed, duration)

            dx, dy = self.DIRECTIONS[segment["direction"]]
            distance = segment["speed"] * travel_time
            self.x = self._segment_start_x + dx * distance
            self.y = self._segment_start_y + dy * distance


            # 当前路段尚未走完
            if elapsed < duration:
                self.direction = segment["direction"]
                self.speed = segment["speed"]
                self._record_position("progress")
                return

            # 当前路段已走完，准备进入下一段
            # 下一路段从这个终点开始，开始时间紧接上一段
            self._record_position("segment_end", force=True)
            self._segment_started_at += duration
            self._segment_start_x = self.x
            self._segment_start_y = self.y
            self._segments_index += 1

            if self._segments_index >= len(self._segments):
                self._finish_motion()
                return


    def _begin_motion(self, segments, event, task_name=None):
        """结算旧运动，再从当前坐标开始新运动。"""
        self._update_position()

        self._segments = segments
        self._segmenst_index = 0
        self._segment_started_at = time.monotonic()
        self._segment_start_x = self.x
        self._segment_start_y = self.y

        self.moving = True
        self.direction = segments[0]["direction"]
        self.speed = segments[0]["speed"]
        self.current_task = task_name

        self._record_position(event, force=True)


    #有了初始状态，如果变化，就要有接受状态的方法
    def get_status(self):
        self._update_position()

        return {
            'online': self.online,
            'moving': self.moving,
            'direction' : self.direction,
            'speed' : self.speed,
            'current_task': self.current_task,
            "position": {
                "x": round(self.x, 3),
                "y": round(self.y, 3),
            },
            "trajectory": list(self.trajectory),
        }
    #有了初始状态，就要有改变状态的方法
    def move_status(self, direction, speed, duration_s):
        #只需要规定方向和速度，这样肯定是正在运动，然后方向和速度要规定，合规才能是运动状态
        if direction not in self.DRICTIONS:
            raise ValueError("运动方向只能前进、后退、向左、向右")
        if not isinstance(speed, (int, float)) or isinstance(speed, bool):
            raise ValueError("速度必须是数字")
        if not 0 < speed <= 100:
            raise ValueError("速度在0-100之间")

        if (not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool) or not 0 < duration_s <= 60):
            raise ValueError("时间必须是数字,且在0到60之间")
        #单段运动
        segments = [
            {
                "direction": direction,
                "speed": speed,
                "duration_s": duration_s,
            }
        ]
        #启动运动
        self._begin_motion(segments, event="move")
      

    #然后需要让机器人停止的方法
    def stop(self):
        # 先计算已经走到哪里，再停在这个坐标
        self._update_position()
        self._finish_motion()
        self._record_position("stop", force=True)


    def start_task(self, name):
        if name not in self.VALID_TASKS:
            raise ValueError("任务名称无效")
        segment_duration = self.TASK_SIDE / self.TASK_SPEED

        if name == "forward":
            directions = ["forward"]
        else:
            # 从当前坐标出发，绕正方形一圈后回到起点
            directions = ["forward", "right", "backward", "left"]

        segments = [
            {
                "direction": direction,
                "speed": self.TASK_SPEED,
                "duration_s": segment_duration,
            }
            for direction in directions
        ]

        self._begin_motion(
            segments,
            event=f"task:{name}",
            task_name=name,
        )

        
        

        