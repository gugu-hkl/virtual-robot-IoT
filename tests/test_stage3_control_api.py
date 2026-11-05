"""不依赖 ROS 2 的双机器人选择与控制边界测试。"""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

import main
from stage2.backend_bridge import BackendError


class Stage3ControlApiTests(unittest.TestCase):
    def setUp(self):
        main.display_selection.select(None)
        main.selection_warning = None
        main.selection_warning_robot = None

    def tearDown(self):
        main.display_selection.select(None)
        main.selection_warning = None
        main.selection_warning_robot = None

    @staticmethod
    def move_request(revision):
        return main.DualMoveRequest(
            direction="forward", speed=8, duration_s=1.5,
            selection_revision=revision,
        )

    def test_move_requires_current_selection_and_revision(self):
        with patch.object(main, "send_robot_command") as send:
            with self.assertRaises(HTTPException) as error:
                main.move_selected_robot("a", self.move_request(0))
            self.assertEqual(error.exception.status_code, 409)
            send.assert_not_called()

    def test_switch_stops_previous_and_rejects_old_page_command(self):
        calls = []

        def send(robot_id, payload):
            calls.append((robot_id, payload))
            return {"accepted": True, "robot_id": robot_id, "action": payload["action"]}

        with patch.object(main, "send_robot_command", side_effect=send), patch.object(
            main, "get_robot_status", return_value={"robot_id": "a"}
        ):
            first = main.set_display_selection(main.DisplaySelectionRequest(robot_id="a"))
            result = main.move_selected_robot("a", self.move_request(first["selection_revision"]))
            self.assertTrue(result["accepted"])
            second = main.set_display_selection(main.DisplaySelectionRequest(robot_id="b"))
            self.assertGreater(second["selection_revision"], first["selection_revision"])
            self.assertIn(("a", {"action": "stop"}), calls)
            with self.assertRaises(HTTPException) as error:
                main.move_selected_robot("a", self.move_request(first["selection_revision"]))
            self.assertEqual(error.exception.status_code, 409)
            main.stop_dual_robot("a")  # 停止操作不要求 a 仍被选中。

    def test_stale_odometry_cannot_start_motion(self):
        with patch.object(main, "send_robot_command") as send, patch.object(
            main, "get_robot_status", side_effect=BackendError(503, "数据过期")
        ):
            first = main.set_display_selection(main.DisplaySelectionRequest(robot_id="a"))
            with self.assertRaises(HTTPException) as error:
                main.move_selected_robot("a", self.move_request(first["selection_revision"]))
            self.assertEqual(error.exception.status_code, 503)
            send.assert_not_called()

    def test_failed_switch_stop_is_visible_until_stop_succeeds(self):
        def send(robot_id, payload):
            if robot_id == "a" and payload["action"] == "stop" and not recovered[0]:
                raise BackendError(503, "网关暂时不可用")
            return {"accepted": True, "robot_id": robot_id, "action": payload["action"]}

        recovered = [False]
        with patch.object(main, "send_robot_command", side_effect=send):
            main.set_display_selection(main.DisplaySelectionRequest(robot_id="a"))
            selected = main.set_display_selection(main.DisplaySelectionRequest(robot_id="b"))
            self.assertEqual(selected["selected_robot"], "b")
            self.assertIn("未能确认停止机器人 a", selected["stop_warning"])
            recovered[0] = True
            main.stop_dual_robot("a")
            self.assertIsNone(main.get_display_selection()["stop_warning"])


if __name__ == "__main__":
    unittest.main()
