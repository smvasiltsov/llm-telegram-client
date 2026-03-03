from __future__ import annotations

import unittest

from app.services.skill_response import parse_skill_response


class SkillResponseParserTests(unittest.TestCase):
    def test_parse_final_answer(self) -> None:
        parsed = parse_skill_response(
            """
            {
              "type": "final_answer",
              "answer": {
                "text": "Done"
              }
            }
            """
        )
        assert parsed is not None
        self.assertEqual(parsed.decision_type, "final_answer")
        self.assertEqual(parsed.answer_text, "Done")
        self.assertIsNone(parsed.skill_call)

    def test_parse_skill_call(self) -> None:
        parsed = parse_skill_response(
            """
            {
              "type": "skill_call",
              "skill_call": {
                "skill_id": "fs.read_file",
                "arguments": {
                  "path": "README.md"
                }
              }
            }
            """
        )
        assert parsed is not None
        self.assertEqual(parsed.decision_type, "skill_call")
        assert parsed.skill_call is not None
        self.assertEqual(parsed.skill_call.skill_id, "fs.read_file")
        self.assertEqual(parsed.skill_call.arguments, {"path": "README.md"})
        self.assertIsNone(parsed.answer_text)

    def test_parse_skill_call_defaults_missing_arguments_to_empty_object(self) -> None:
        parsed = parse_skill_response(
            """
            {
              "type": "skill_call",
              "skill_call": {
                "skill_id": "fs.list_dir"
              }
            }
            """
        )
        assert parsed is not None
        assert parsed.skill_call is not None
        self.assertEqual(parsed.skill_call.arguments, {})

    def test_parse_embedded_json_object(self) -> None:
        parsed = parse_skill_response(
            'I will use a skill now.\n{"type":"skill_call","skill_call":{"skill_id":"web.search","arguments":{"query":"python"}}}'
        )
        assert parsed is not None
        assert parsed.skill_call is not None
        self.assertEqual(parsed.skill_call.skill_id, "web.search")

    def test_rejects_invalid_decision(self) -> None:
        self.assertIsNone(parse_skill_response('{"type":"unknown"}'))
        self.assertIsNone(parse_skill_response('{"type":"final_answer","answer":{}}'))
        self.assertIsNone(parse_skill_response('{"type":"skill_call","skill_call":{"arguments":{}}}'))
        self.assertIsNone(parse_skill_response('{"type":"skill_call","skill_call":{"skill_id":"fs.read_file","arguments":[]}}'))


if __name__ == "__main__":
    unittest.main()
