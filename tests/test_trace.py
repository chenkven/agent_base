"""DSH event projection shown beside the chat."""

import unittest

from app.trace import summarize_run_events


class TraceTest(unittest.TestCase):
    def test_available_tools_and_actual_calls_are_distinct(self) -> None:
        events = [
            {"type": "request/header", "data": {"header": {"tools": [
                {"name": "skill"}, {"name": "mcp__demo_tools__current_time"},
                {"name": "bash"},
            ]}}},
            {"type": "tool/call", "time": 1000, "data": {
                "callId": "s1", "name": "skill", "arguments": '{"name":"demo_skill"}',
            }},
            {"type": "tool/result", "time": 1012, "data": {
                "message": {"toolCallId": "s1", "isError": False},
            }},
            {"type": "tool/call", "time": 1020, "data": {
                "callId": "m1", "name": "mcp__demo_tools__current_time", "arguments": "{}",
            }},
            {"type": "tool/result", "time": 1050, "data": {
                "message": {"content": [{"toolCallId": "m1", "isError": True}]},
            }},
        ]
        self.assertEqual(summarize_run_events(events), {
            "available_tools": ["skill", "mcp__demo_tools__current_time"],
            "tool_calls": [
                {"name": "skill: demo_skill", "kind": "skill", "status": "completed", "duration_ms": 12},
                {"name": "mcp__demo_tools__current_time", "kind": "mcp", "status": "error", "duration_ms": 30},
            ],
        })


if __name__ == "__main__":
    unittest.main()
