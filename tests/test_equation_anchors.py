"""Secondary display labels must be usable HTML fragment targets."""

from collections import Counter
from html.parser import HTMLParser
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])


class SecondaryEquationAnchors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="equation-anchors-")
        cls.addClassCleanup(cls.work.cleanup)
        root = Path(cls.work.name)
        source = Path(__file__).parents[1] / "fixture/secondary_equation_labels.tex"
        shutil.copyfile(source, root / "web.tex")
        (root / "plastex.cfg").write_text(
            "[general]\nrenderer=HTML5\nplugins=texra_blueprint\n"
            "[files]\ndirectory=web\nsplit-level=0\n")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TEXINPUTS=str(root) + "//:")
        proc = subprocess.run(
            [sys.executable, "-c", "from plasTeX.client import plastex; plastex()",
             "--config", "plastex.cfg", "web.tex"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30)
        if proc.returncode:
            raise AssertionError(proc.stdout + proc.stderr)
        cls.log = proc.stdout + proc.stderr
        cls.html = (root / "web/index.html").read_text()
        cls.parsed = Anchors()
        cls.parsed.feed(cls.html)
        destination = os.environ.get("TEXRA_ANCHOR_TEST_OUTPUT")
        if destination:
            shutil.copytree(root / "web", destination)

    def test_all_display_references_have_targets(self):
        expected = {"eq:first_row", "eq:second_row", "eq:third_row",
                    "eq:gather_first", "eq:gather_second", "eq:single"}
        self.assertTrue(expected.issubset(self.parsed.ids), expected - set(self.parsed.ids))
        referenced = {urlsplit(href).fragment for href in self.parsed.links}
        self.assertTrue(expected.issubset(referenced))

    def test_primary_and_secondary_ids_are_unique(self):
        counts = Counter(self.parsed.ids)
        self.assertTrue(all(n == 1 for name, n in counts.items() if name.startswith("eq:")))

    def test_comment_is_not_an_anchor(self):
        self.assertNotIn("eq:comment_only", self.parsed.ids)

    def test_reference_numbers_are_unchanged(self):
        numbers = re.findall(r'<a href="[^"]*#eq:[^"]*"[^>]*>(.*?)</a>', self.html)
        self.assertEqual(numbers, ["1", "2", "3", "4", "5", "6"])

    def test_mathematical_labels_remain_in_mathjax_source(self):
        for label in ["first_row", "second_row", "third_row", "gather_first",
                      "gather_second", "single"]:
            self.assertIn(r"\label{eq:" + label + "}", self.html)
        self.assertNotIn("??", self.html)
        self.assertNotIn("unrecognized command/environment", self.log)


if __name__ == "__main__":
    unittest.main()
