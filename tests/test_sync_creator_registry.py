from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selfmedia.creator_profiles.registry_sync import build_update_payload


class SyncCreatorRegistryTests(unittest.TestCase):
    def test_build_update_payload_only_fills_missing_fields(self) -> None:
        payload = build_update_payload(
            {"平台": "抖音", "作者ID": "清华AI小王冲一级", "粉丝数": "", "关键词标签": ""},
            {
                "博主IP": "清华AI小王冲一级",
                "平台": "抖音",
                "平台ID": "93130816637",
                "院校背景": "清华大学",
                "粉丝数(k)": "37",
                "赛道": ["运动", "跑步"],
                "标签": "男、清华ai硕",
            },
        )
        self.assertNotIn("创作者主档ID", payload)
        self.assertNotIn("平台账号ID", payload)
        self.assertEqual(payload["博主IP"], "清华AI小王冲一级")
        self.assertEqual(payload["院校背景"], "清华大学")
        self.assertEqual(payload["粉丝数"], 37000)
        self.assertEqual(payload["赛道"], "运动、跑步")
        self.assertEqual(payload["关键词标签"], "男、清华ai硕")


if __name__ == "__main__":
    unittest.main()
