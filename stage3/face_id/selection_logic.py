"""把单帧识别结果变成稳定的屏幕选择。"""

import math


def classify_scores(scores, threshold=0.45, margin=0.06):
    """仅在分数足够高且与另一人拉开差距时返回 A/B。"""
    if set(scores) != {"A", "B"}:
        raise ValueError("必须同时提供 A、B 的相似度")
    if not all(math.isfinite(score) for score in scores.values()):
        return None
    best = max(scores, key=scores.get)
    other = "B" if best == "A" else "A"
    if scores[best] < threshold or scores[best] - scores[other] < margin:
        return None
    return best


class StableSelector:
    """连续识别相同的人才切换；人消失一段时间后取消选择。"""

    def __init__(self, stable_frames=5, clear_after_s=2.0):
        if stable_frames < 1 or clear_after_s <= 0:
            raise ValueError("稳定帧数和清空等待时间必须为正数")
        self.stable_frames = stable_frames
        self.clear_after_s = clear_after_s
        self.active = None
        self.pending = None
        self.pending_count = 0
        self.last_seen_at = None

    def observe(self, label, now):
        if label not in ("A", "B", None):
            raise ValueError("识别结果必须是 A、B 或 None")

        if label == self.active and label is not None:
            self.last_seen_at = now
            self.pending = None
            self.pending_count = 0
            return self.active

        if label is not None:
            if label == self.pending:
                self.pending_count += 1
            else:
                self.pending = label
                self.pending_count = 1
            if self.pending_count >= self.stable_frames:
                self.active = label
                self.last_seen_at = now
                self.pending = None
                self.pending_count = 0
            return self.active

        self.pending = None
        self.pending_count = 0
        if self.active is not None and now - self.last_seen_at >= self.clear_after_s:
            self.active = None
            self.last_seen_at = None
        return self.active
