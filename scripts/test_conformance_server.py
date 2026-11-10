"""Isolated contracts for the Python helpers embedded in the server-lane script."""

import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.parse

SCRIPT = Path(__file__).with_name("conformance-server.sh")
source = SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
functions = [
    node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
]
helpers = {"os": os, "urllib": urllib}
# Evaluate only local helper definitions, excluding the network-driving script body.
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SCRIPT), "exec"), helpers)  # noqa: S102


class ServerConformanceHelpers(unittest.TestCase):
    def test_numbers_do_not_accept_booleans(self):
        self.assertFalse(helpers["subset_match"](True, 1))
        self.assertFalse(helpers["subset_match"](1, True))
        self.assertTrue(
            helpers["subset_match"]({"value": 2, "extra": True}, {"value": 2})
        )

    def test_signed_credentials_are_headers_not_request_body_fields(self):
        with patch.dict(
            os.environ,
            {
                "EZC_SMOKE_ACCESS_TOKEN": "caller-test-carrier",
                "EZC_SMOKE_CONTEXT_TOKEN": "context-test-carrier",
            },
            clear=True,
        ):
            self.assertEqual(
                helpers["request_headers"](),
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer caller-test-carrier",
                    "x-ezclassify-context-token": "context-test-carrier",
                },
            )
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                helpers["request_headers"](), {"Content-Type": "application/json"}
            )

    def test_context_operation_returns_its_result(self):
        result = {"valid": False}
        self.assertIs(
            helpers["response_value"]({"result": result}, "ctxProcess"), result
        )
        with self.assertRaises(ValueError):
            helpers["response_value"]({"valid": True}, "ctxProcess")

    def test_scan_summary_matches_the_recorded_plan_contract(self):
        self.assertEqual(
            helpers["response_value"](
                {
                    "result": {
                        "results": [
                            {
                                "marking": "High",
                                "start": 0,
                                "result": {"rendered": "HIGH"},
                            }
                        ]
                    }
                },
                "ctxScan",
            ),
            {
                "count": 1,
                "firstMarking": "High",
                "firstStart": 0,
                "firstRendered": "HIGH",
            },
        )
        self.assertEqual(
            helpers["response_value"]({"result": {"results": []}}, "ctxScan")["count"],
            0,
        )
        with self.assertRaises(ValueError):
            helpers["response_value"]({"result": {}}, "ctxScan")


    def test_a_scheme_selector_is_sent_as_the_declared_query(self):
        path = "/v1/ctx/ref-ctx-2/1.0.0/scheme/process"
        self.assertEqual(helpers["case_path"](path, {}), path)
        self.assertEqual(
            helpers["case_path"](path, {"scheme": "ref-scheme-2"}),
            path + "?scheme=ref-scheme-2",
        )
        self.assertEqual(
            helpers["case_path"](path, {"scheme": "a b&c"}),
            path + "?scheme=a+b%26c",
        )

    def test_a_refused_case_passes_only_on_its_status(self):
        self.assertIsNone(helpers["refusal_failure"](404, 404))
        self.assertEqual(
            helpers["refusal_failure"](404, 400), "expected HTTP 404, got HTTP 400"
        )
        self.assertEqual(
            helpers["refusal_failure"](404, None), "expected HTTP 404, got a result"
        )

if __name__ == "__main__":
    unittest.main()
