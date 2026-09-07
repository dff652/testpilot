"""Mutation fixtures define expected rejection, not successful product runs."""
import copy
import json
from pathlib import Path
import unittest

from scripts.validate_contracts import KINDS, validate

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_corpus(self):
        cases = json.loads((ROOT / "tests" / "contract-cases.json").read_text())
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({c["name"] for c in cases}), len(cases))
        for case in cases:
            with self.subTest(case=case["name"]):
                data = json.loads((ROOT / "examples" / "valid" /
                                   f'{case["kind"]}.json').read_text())
                for change in case["changes"]:
                    node = data
                    parts = change["path"].split("/")
                    for part in parts[:-1]:
                        node = node[part]
                    if change.get("remove"):
                        del node[parts[-1]]
                    else:
                        node[parts[-1]] = copy.deepcopy(change["value"])
                self.assertEqual(not validate(case["kind"], data), case["valid"])

    def test_base_examples(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                data = json.loads((ROOT / "examples" / "valid" / f"{kind}.json").read_text())
                self.assertEqual(validate(kind, data), [])

    def test_top_level_shape_rejected(self):
        for kind in KINDS:
            for value in [None, [], "fixture", 1, {}]:
                with self.subTest(kind=kind, value=value):
                    self.assertTrue(validate(kind, value))

    def test_pilot_declarations(self):
        files = list((ROOT / "examples" / "pilots").glob("*.action.json"))
        projects = set()
        for file in files:
            with self.subTest(file=file.name):
                data = json.loads(file.read_text())
                self.assertEqual(validate("action", data), [])
                self.assertNotIn(data["project_id"], projects)
                projects.add(data["project_id"])
        self.assertEqual(projects, {"agent-mail", "ai-asset-hub", "homelab-doctor"})


if __name__ == "__main__":
    unittest.main()
