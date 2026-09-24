from __future__ import annotations

import unittest
from pathlib import Path

from iphone_market.scheduler import build_task_xml, parse_task_xml


class SchedulerTests(unittest.TestCase):
    def test_xml_declares_matching_utf16_encoding(self) -> None:
        xml = build_task_xml(task_name="test-task", project_root=Path("C:/temp/project"))
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-16"?>'))
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("<WakeToRun>false</WakeToRun>", xml)

    def test_parse_keeps_registered_task_name(self) -> None:
        xml = build_task_xml(task_name="test-task", project_root=Path("C:/temp/project"))
        info = parse_task_xml(xml, task_name="fallback")
        self.assertEqual(info.task_name, "test-task")
        self.assertTrue(info.start_when_available)
        self.assertFalse(info.wake_to_run)
        self.assertIn("iphone_market collect", info.arguments or "")
        self.assertIn("--headed", info.arguments or "")


if __name__ == "__main__":
    unittest.main()
