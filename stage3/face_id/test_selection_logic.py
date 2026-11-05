"""与摄像头、模型和 FastAPI 无关的稳定选择验收。"""

import unittest

from stage3.face_id.selection_logic import StableSelector, classify_scores


class SelectionLogicTests(unittest.TestCase):
    def test_only_stable_identity_switches(self):
        selector = StableSelector(stable_frames=3, clear_after_s=2.0)
        self.assertIsNone(selector.observe("A", 0.0))
        self.assertIsNone(selector.observe("A", 0.2))
        self.assertEqual(selector.observe("A", 0.4), "A")
        self.assertEqual(selector.observe("B", 0.6), "A")
        self.assertEqual(selector.observe("B", 0.8), "A")
        self.assertEqual(selector.observe("B", 1.0), "B")

    def test_unknown_breaks_streak_and_clears_after_timeout(self):
        selector = StableSelector(stable_frames=2, clear_after_s=2.0)
        self.assertIsNone(selector.observe("A", 0.0))
        self.assertIsNone(selector.observe(None, 0.1))
        self.assertIsNone(selector.observe("A", 0.2))
        self.assertEqual(selector.observe("A", 0.3), "A")
        self.assertEqual(selector.observe(None, 2.0), "A")
        self.assertIsNone(selector.observe(None, 2.4))

    def test_score_threshold_and_margin(self):
        self.assertEqual(classify_scores({"A": 0.53, "B": 0.32}), "A")
        self.assertEqual(classify_scores({"A": 0.32, "B": 0.53}), "B")
        self.assertIsNone(classify_scores({"A": 0.42, "B": 0.30}))
        self.assertIsNone(classify_scores({"A": 0.55, "B": 0.52}))


if __name__ == "__main__":
    unittest.main()
