"""The ush-advice skill documents (plan 103, M3): the rules and steps of SKILL.md and
the sections and sentences of references/report-format.md.

Checks are case-insensitive substrings within a section or within one item
(a list item or a paragraph, wrapped lines joined), not exact wording.
"""

import re
import unittest

from tests.skill_loader import REPO_ROOT

SKILL_DIR = REPO_ROOT / "skills" / "ush-advice"
SKILL_MD = SKILL_DIR / "SKILL.md"
REPORT_FORMAT = SKILL_DIR / "references" / "report-format.md"
CONTRACT = SKILL_DIR / "references" / "summary-contract.md"


def _read(path):
    if not path.is_file():
        raise AssertionError(f"missing: {path}")
    return path.read_text(encoding="utf-8")


def _section(text, heading):
    """The text under ``## <heading>`` up to the next heading of level 1 or 2."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^##\s+{re.escape(heading)}\s*$", line.strip(), re.IGNORECASE):
            start = index + 1
            break
    if start is None:
        raise AssertionError(f"no '## {heading}' section")
    body = []
    for line in lines[start:]:
        if re.match(r"^#{1,2}\s", line):
            break
        body.append(line)
    return "\n".join(body)


def _items(text):
    """List items and paragraphs, each with its wrapped lines joined."""
    items, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        starts_item = re.match(r"^([-*+]|\d+[.)])\s", stripped)
        if not stripped or starts_item or stripped.startswith("#"):
            if current:
                items.append(" ".join(current))
            current = [stripped] if stripped else []
        else:
            current.append(stripped)
    if current:
        items.append(" ".join(current))
    return items


def _item_with(items, *needles):
    lowered = [needle.lower() for needle in needles]
    return [item for item in items if all(needle in item.lower() for needle in lowered)]


class TestDocs(unittest.TestCase):
    def test_rules_and_sections(self):
        skill = _read(SKILL_MD)
        rules = _section(skill, "Rules")
        rule_items = _items(rules)

        for needle in ("WebFetch", "sources.json", "25H2", "serial number"):
            with self.subTest(f"Rules mention {needle!r}"):
                self.assertIn(needle.lower(), rules.lower())

        for token in ("UBR", "KB"):
            with self.subTest(f"Rules mention {token!r}"):
                self.assertRegex(rules, rf"\b{token}\b")

        with self.subTest("UBR, KB and serial number are forbidden in one rule"):
            forbidden = [item for item in _item_with(rule_items, "serial number")
                         if re.search(r"\bUBR\b", item) and re.search(r"\bKB\b", item)
                         and re.search(r"\b(never|not|no|must not)\b", item, re.IGNORECASE)]
            self.assertTrue(forbidden, f"no rule forbidding UBR, KB and serial number:\n{rules}")

        for search in ("kev", "msrc"):
            with self.subTest(f"partial rule for {search}"):
                self.assertTrue(
                    [item for item in _item_with(rule_items, "partial")
                     if re.search(rf"\b{search}\b", item, re.IGNORECASE)],
                    f"no rule naming both {search!r} and 'partial':\n{rules}")

        with self.subTest("Steps mention --findings"):
            self.assertIn("--findings", _section(skill, "Steps"))

        report_format = _read(REPORT_FORMAT)
        headings = [line for line in report_format.splitlines() if re.match(r"^#+\s", line)]
        for name in ("Unverified", "Firmware"):
            with self.subTest(f"report-format has a section {name!r}"):
                self.assertTrue(any(name.lower() in heading.lower() for heading in headings),
                                f"headings: {headings}")

        format_items = _items(report_format)
        with self.subTest("a sentence about kev_other_count"):
            self.assertTrue(_item_with(format_items, "kev_other_count"))

        with self.subTest("a sentence about a null list when a search is partial"):
            self.assertTrue(_item_with(format_items, "null", "partial"),
                            "no item naming both 'null' and 'partial'")

        with self.subTest("cve_count is named 'CVEs recorded in the findings'"):
            self.assertTrue(_item_with(format_items, "cve_count",
                                       "CVEs recorded in the findings"),
                            "no item naming cve_count as 'CVEs recorded in the findings'")

    def test_review_135_rules(self):
        """Plan 135, M2: the firmware step, the changes row, the update recommendation
        and the contract after the new version and query-warning rules."""
        steps = _items(_section(_read(SKILL_MD), "Steps"))
        with self.subTest("firmware copies manufacturer and model exactly"):
            self.assertTrue(_item_with(steps, "firmware", "machine.firmware", "exactly",
                                       "title"), steps)

        format_items = _items(_read(REPORT_FORMAT))
        with self.subTest("Install the update only for listed true"):
            self.assertTrue(_item_with(format_items, "Install the update",
                                       "`applied` `false` and `listed` `true`"))
        with self.subTest("changes row: time and age of the baseline"):
            self.assertTrue(_item_with(format_items, "rule 12", "baseline.created_at",
                                       "baseline.age_days"))
        with self.subTest("changes row: nothing new only for a compared list"):
            self.assertTrue(_item_with(format_items, "comparison.", "compared",
                                       "nothing new", "not_read", "no comparison"))
        with self.subTest("changes row: no_baseline with baseline.status compared"):
            self.assertTrue(_item_with(format_items, "no_baseline", "no comparison",
                                       "never „nothing new”", "with `compared`"))
        with self.subTest("changes row: items cut from the summary"):
            self.assertTrue(_item_with(format_items, "truncated", "only in the detail file",
                                       "row"))

        contract = _read(CONTRACT)
        rows = [line for line in contract.splitlines() if line.startswith("| `same_version`")]
        with self.subTest("same_version row"):
            self.assertEqual(len(rows), 1, rows)
            self.assertIn("five characters", rows[0])
            self.assertIn("dot", rows[0])
            self.assertNotIn("one of its parts between characters outside", rows[0])

        warnings = _section(contract, "Query warnings")
        bios = _item_with(_items(warnings), "`bios_version`:")
        with self.subTest("bios_version warning: the whole version and four characters"):
            self.assertEqual(len(bios), 1, warnings)
            self.assertIn("whole version", bios[0])
            self.assertIn("four characters", bios[0])
            self.assertNotIn("(or a part of it", warnings)
        with self.subTest("a fact after one v is found"):
            self.assertTrue(_item_with(_items(warnings), "one `v`", "v1.54"), warnings)

        with self.subTest("the baseline after an unreadable file"):
            self.assertTrue(_item_with(_items(_section(contract, "Baseline")),
                                       "unreadable-", "this run"))

    def test_release_info_rules(self):
        """Plan 136, M2: the release-info search and step, msrc only for CVE counts."""
        skill = _read(SKILL_MD)
        rules = _items(_section(skill, "Rules"))
        steps = _items(_section(skill, "Steps"))
        with self.subTest("release-info rule"):
            self.assertTrue(_item_with(rules, "release-info is `read`", "display_version",
                                       "unreadable"), rules)
        with self.subTest("release-info step: B/D rows, cves null, no hotpatch"):
            step = _item_with(steps, "`release-info`:", "`B` -> `release_type` `security`",
                              "`D` -> `preview`", "`cves` `null`", "hotpatch", "OOB")
            self.assertTrue(step, steps)
        with self.subTest("kev without a CVE"):
            self.assertTrue(_item_with(steps, "`kev`:", "no `update` finding has a CVE"), steps)
        with self.subTest("a KB in a query is the kb of an update finding"):
            self.assertTrue(_item_with(rules, "`release-info` table",
                                       "only a KB that is the `kb` of one of your"), rules)
        with self.subTest("msrc step skips hotpatch KBs"):
            self.assertTrue(_item_with(steps, "`msrc`:", "skip hotpatch"), steps)
        with self.subTest("machine.product null: no finding from the MSRC document"):
            self.assertTrue(_item_with(rules, "machine.product", "from the MSRC document"),
                            rules)
        with self.subTest("five searches in step 3"):
            self.assertTrue(_item_with(steps, "five searches", "`release-info`"), steps)

        contract = _read(CONTRACT)
        searches = _section(contract, "Searches")
        with self.subTest("five searches in the contract"):
            self.assertIn("five items", searches)
            self.assertIn("| `release-info` | `updates`", searches)
        with self.subTest("cves null in the contract"):
            rows = [line for line in contract.splitlines() if line.startswith("| `update` |")]
            self.assertEqual(len(rows), 1, rows)
            self.assertIn("or `null`", rows[0].split("`cves`", 1)[1])
        with self.subTest("old wording gone"):
            joined = " ".join(_items(contract))
            self.assertNotIn("cannot be placed", joined)
            report_format = _read(REPORT_FORMAT)
            self.assertNotIn("could not be matched with the update months",
                             " ".join(_items(report_format)))
        with self.subTest("cve_count null is not counted"):
            self.assertTrue(_item_with(_items(_read(REPORT_FORMAT)), "cve_count",
                                       "not counted", "never 0"))

    def test_msrc_step_and_baseline_runs(self):
        """Plan 144, M1: the msrc step records update findings only after the count
        check, and the contract names every run without a baseline save."""
        skill = _read(SKILL_MD)
        steps = _items(_section(skill, "Steps"))
        msrc = _item_with(steps, "`msrc`:", "skip hotpatch")
        with self.subTest("exactly one msrc step"):
            self.assertEqual(len(msrc), 1, steps)
        step = msrc[0].lower() if msrc else ""
        with self.subTest("the condition comes before the KB"):
            self.assertIn("only when `msrc` is `read`", step)
            self.assertIn("the kb", step)
            self.assertLess(step.find("only when `msrc` is `read`"), step.find("the kb"), step)
        with self.subTest("otherwise only the status"):
            self.assertIn("otherwise", step)
            self.assertIn("status", step.split("otherwise", 1)[-1])
        rule = _item_with(_items(_section(skill, "Rules")),
                          "msrc is `read` only when the whole document was read")
        with self.subTest("the rule needs the whole document"):
            self.assertEqual(len(rule), 1)
            self.assertIn("collected", rule[0])
            self.assertIn("neither cut nor summarised", rule[0])
            self.assertNotIn("recorded", rule[0])

        joined = " ".join(_items(_section(_read(CONTRACT), "Baseline")))
        with self.subTest("runs without a baseline save"):
            self.assertIn("only `kev`, only `msrc`, or both", joined)
            self.assertNotIn("only `kev` and `msrc` read", joined)


if __name__ == "__main__":
    unittest.main()
