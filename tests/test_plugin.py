"""The repository as a Claude Code plugin: manifests, and the paths the skill docs use.

Claude Code substitutes ``${CLAUDE_PLUGIN_ROOT}`` and ``${CLAUDE_PLUGIN_DATA}`` only in
the body of a SKILL.md. A reference is read with the Read tool, which substitutes
nothing, so references use the placeholders ``<plugin root>`` and ``<plugin data>``,
which the model fills from the SKILL.md header.

A fenced block with a ``Set-Location`` line is a block handed to the user: it changes
into the plugin root first, so its script paths stay relative (``skills/...``). Lines
inside a four-backtick example are report text quoted as an example, not commands.
"""

import fnmatch
import json
import re
import unittest

from tests.skill_loader import REPO_ROOT

SKILLS = REPO_ROOT / "skills"
MANIFEST_DIR = REPO_ROOT / ".claude-plugin"

ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}/"
DATA_VAR = "${CLAUDE_PLUGIN_DATA}"
ROOT_PLACEHOLDER = "<plugin root>/"
DATA_PLACEHOLDER = "<plugin data>"

# A path to a skill script or a skill reference, with whatever sits right before it.
SKILL_PATH = re.compile(
    r"(?P<prefix><plugin root>/|[^\s`\"'(]*)skills/ush-[a-z0-9-]+/(?:scripts/[a-z0-9_]+\.py|references/[a-z0-9-]+\.md)")
# A command that runs a skill script.
COMMAND = re.compile(
    r"\bpython(?:\.exe)?\s+-B\s+\"?(?P<prefix>[^\s\"]*)skills/ush-[a-z0-9-]+/scripts/"
    r"(?P<script>[a-z0-9_]+)\.py")
# Scripts that resolve a data directory only in their --latest form.
LATEST_ONLY = {"check_report", "check_repair_plan"}
# Scripts that never resolve a data directory.
NO_DATA_DIR = {"baseline"}
OLD_DEFAULT = re.compile(r"(?i)LOCALAPPDATA[%)]?[\\/]+ubershipshape")
DATA_DIR_FLAG = re.compile(r"(?<!\[)--data-dir\b")


def skill_docs():
    return sorted(SKILLS.glob("ush-*/SKILL.md"))


def reference_docs():
    return sorted(SKILLS.glob("ush-*/references/*.md"))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def classify_lines(text):
    """Yield ``(number, line, kind)``: kind is ``text``, ``block`` (a fenced block
    with a Set-Location line), ``code`` (another fenced block) or ``example`` (inside
    a four-backtick fence)."""
    lines = text.splitlines()
    kinds = ["text"] * len(lines)
    example = False
    fence_start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("````"):
            example = not example
            kinds[index] = "example"
            continue
        if example:
            kinds[index] = "example"
            continue
        if stripped.startswith("```"):
            if fence_start is None:
                fence_start = index
                kinds[index] = "code"
            else:
                body = lines[fence_start + 1:index]
                kind = "block" if any(
                    re.match(r"(?i)\s*Set-Location\b", item) for item in body) else "code"
                for inner in range(fence_start, index + 1):
                    kinds[inner] = kind
                fence_start = None
    for index, line in enumerate(lines):
        yield index + 1, line, kinds[index]


def joined_commands(text):
    """Each command line with its backtick continuation lines joined on."""
    rows = list(classify_lines(text))
    index = 0
    while index < len(rows):
        number, line, kind = rows[index]
        full = line
        while full.rstrip().endswith("`") and not full.rstrip().endswith("``") \
                and kind != "text" and index + 1 < len(rows):
            index += 1
            full = full.rstrip()[:-1] + " " + rows[index][1]
        yield number, full, kind
        index += 1


class TestManifest(unittest.TestCase):
    def test_manifest_and_skills(self):
        for name in ("plugin.json", "marketplace.json"):
            self.assertTrue((MANIFEST_DIR / name).is_file(), f".claude-plugin/{name} is missing")
        plugin = json.loads(read(MANIFEST_DIR / "plugin.json"))
        market = json.loads(read(MANIFEST_DIR / "marketplace.json"))
        self.assertEqual(plugin.get("name"), "ubershipshape")
        self.assertRegex(str(plugin.get("version")), r"^\d+\.\d+\.\d+$")
        self.assertEqual(market.get("name"), "ubershipshape")
        self.assertEqual((market.get("owner") or {}).get("name"), "etobod")
        entries = [entry for entry in market.get("plugins", [])
                   if entry.get("name") == "ubershipshape"]
        self.assertEqual(len(entries), 1, "the marketplace lists the plugin once")
        self.assertEqual(entries[0].get("source"), "./")
        skill_dirs = sorted(path for path in SKILLS.glob("ush-*") if path.is_dir()
                            and path.name != "ush-common")
        self.assertTrue(skill_dirs)
        for directory in skill_dirs:
            with self.subTest(skill=directory.name):
                doc = directory / "SKILL.md"
                self.assertTrue(doc.is_file(), f"{directory.name} has no SKILL.md")
                front = re.match(r"---\n(.*?)\n---\n", read(doc), re.DOTALL)
                self.assertIsNotNone(front, "SKILL.md has no front matter")
                names = re.findall(r"(?m)^name:\s*(\S+)\s*$", front.group(1))
                self.assertEqual(names, [directory.name])
                # A plain YAML scalar must not hold ": " or " #", or the front matter
                # fails to parse and Claude Code drops the skill.
                for value in re.findall(r"(?m)^[a-z-]+:\s*(.*)$", front.group(1)):
                    if not value.startswith(('"', "'")):
                        self.assertNotIn(": ", value, "unquoted ': ' in the front matter")
                        self.assertNotIn(" #", value, "unquoted ' #' in the front matter")


class TestSkillPaths(unittest.TestCase):
    def test_script_paths_use_plugin_root(self):
        problems = []
        for path, wanted in [(doc, ROOT_VAR) for doc in skill_docs()] + \
                [(doc, ROOT_PLACEHOLDER) for doc in reference_docs()]:
            text = read(path)
            name = path.relative_to(SKILLS).as_posix()
            if path.name != "SKILL.md" and "${CLAUDE_PLUGIN_ROOT}" in text:
                problems.append(f"{name}: a reference holds ${{CLAUDE_PLUGIN_ROOT}}")
            if OLD_DEFAULT.search(text):
                problems.append(f"{name}: still names %LOCALAPPDATA%\\ubershipshape")
            for number, line, kind in classify_lines(text):
                if kind in ("block", "example"):
                    continue
                for match in SKILL_PATH.finditer(line):
                    if not match.group("prefix").endswith(wanted):
                        problems.append(f"{name}:{number}: {match.group(0)}")
        self.assertEqual(problems, [])

    def test_data_dir_on_every_command(self):
        problems = []
        for path in skill_docs() + reference_docs():
            default = (f'--default-data-dir "{DATA_VAR}"' if path.name == "SKILL.md"
                       else f'--default-data-dir "{DATA_PLACEHOLDER}"')
            name = path.relative_to(SKILLS).as_posix()
            for number, line, kind in joined_commands(read(path)):
                if kind == "example":
                    continue
                for match in COMMAND.finditer(line):
                    script = match.group("script")
                    if script in NO_DATA_DIR:
                        continue
                    if script in LATEST_ONLY and "--latest" not in line:
                        continue
                    if not DATA_DIR_FLAG.search(line) and default not in line:
                        problems.append(f"{name}:{number}: {line.strip()}")
        self.assertEqual(problems, [])

    def test_latest_hint_names_a_data_dir(self):
        # A "--latest --skill" hint without a data directory makes check_report
        # exit with a usage error, also when no "python" command is on its line.
        problems = []
        for path in skill_docs() + reference_docs():
            name = path.relative_to(SKILLS).as_posix()
            for number, line in enumerate(read(path).splitlines(), 1):
                if "--latest --skill" not in line:
                    continue
                if not DATA_DIR_FLAG.search(line) and "--default-data-dir" not in line:
                    problems.append(f"{name}:{number}: {line.strip()}")
        self.assertEqual(problems, [])

    def test_header_report_path_and_repair_rule(self):
        for doc in skill_docs():
            text = read(doc)
            with self.subTest(skill=doc.parent.name):
                roots = re.findall(r"(?m)^- Plugin root: `\$\{CLAUDE_PLUGIN_ROOT\}`$", text)
                datas = re.findall(r"(?m)^- Data folder: `\$\{CLAUDE_PLUGIN_DATA\}`$", text)
                self.assertEqual(len(roots), 1, "the plugin root is stated once")
                self.assertEqual(len(datas), 1, "the data folder is stated once")
                steps = re.findall(
                    r"(?ms)^\d+\. Tell the user where the report is.*?(?=^\d+\. |^## |\Z)", text)
                self.assertEqual(len(steps), 1, "one step tells where the report is")
                self.assertIn("absolute path of the report file", " ".join(steps[0].split()))
                # A refused write to the data folder: the user adds the exception, the
                # model changes no settings, and a second refusal stops the skill.
                flat = " ".join(text.split())
                for phrase in ("writing a file to the data folder is refused",
                               "Never change a settings file yourself",
                               "without quotes: `/add-dir <data folder>`",
                               "written with forward slashes",
                               "for this session only, with no settings file edit",
                               "`permissions.additionalDirectories`",
                               "`~/.claude/settings.json`",
                               "never in a project's `.claude` folder",
                               "only after the user says they ran `/add-dir`",
                               "the skill is run again in a new session",
                               "If it is refused again, stop the skill",
                               "Never write the file another way"):
                    self.assertIn(phrase, flat)
        rule = " ".join(read(SKILLS / "ush-common/references/repair-plan.md").split())
        self.assertRegex(
            rule, r"Set-Location[^.]*older plugin version[^.]*\.[^.]*current plugin root")


# Skills whose SKILL.md hands the user a block (not ush-advice, which hands off none).
RUN_ME_SKILLS = ("settings", "health", "inventory", "processes", "files", "runall", "events")
RUN_ME_FILES = ("run-me.ps1", "run-me-admin.ps1", "run-me.out.txt", "run-me-admin.out.txt")
OLD_HAND_OFF = ("paste this block", "paste it into", "offer the user this block")


def flat(text):
    return " ".join(text.split())


class TestRunMe(unittest.TestCase):
    """A block for the user is delivered in run-me.ps1 / run-me-admin.ps1 in the cwd
    (loc/inbox/031-plan-3-medium-run-me-delivery.md, M1)."""

    def test_skills_hand_off_through_run_me(self):
        for name in RUN_ME_SKILLS:
            doc = SKILLS / f"ush-{name}" / "SKILL.md"
            with self.subTest(skill=f"ush-{name}"):
                self.assertTrue(doc.is_file(), f"ush-{name} has no SKILL.md")
                text = flat(read(doc))
                for wanted in ("run-me.md", "run-me.ps1", "run-me-admin.ps1"):
                    self.assertIn(wanted, text)
                lowered = text.lower()
                for phrase in OLD_HAND_OFF:
                    self.assertNotIn(phrase, lowered, f"still says {phrase!r}")

    def test_rule_holds_its_parts(self):
        path = SKILLS / "ush-common/references/run-me.md"
        self.assertTrue(path.is_file(), "ush-common/references/run-me.md is missing")
        rule = flat(read(path))
        lowered = rule.lower()
        # The transcript path is the absolute cwd, written into the file: a pasted
        # file has no $PSScriptRoot and would write its transcript to the drive root.
        self.assertNotIn("$PSScriptRoot", rule)
        for phrase in ('Start-Transcript -Path "<cwd>\\run-me.out.txt"',
                       'Start-Transcript -Path "<cwd>\\run-me-admin.out.txt"',
                       "finally { Stop-Transcript }",
                       "run-me.out.txt",
                       "run-me-admin.out.txt",
                       "git check-ignore",
                       "powershell -ExecutionPolicy Bypass -File .\\run-me.ps1",
                       "powershell -ExecutionPolicy Bypass -File .\\run-me-admin.ps1"):
            self.assertIn(phrase, rule)
        self.assertRegex(rule, r"\btry\s*\{", "the block is wrapped in try {")
        self.assertRegex(
            rule, r"Set-Location\b[^`\n]*;\s*powershell -ExecutionPolicy Bypass -File "
                  r"\.\\run-me-admin\.ps1",
            "the elevated command changes into the cwd first")
        # The written file is read back and compared with its source line by line.
        self.assertIn("read back", lowered)
        self.assertIn("line by line", lowered)
        self.assertIn("word for word", lowered)

    def test_gitignore_lists_run_me_files(self):
        path = REPO_ROOT / ".gitignore"
        self.assertTrue(path.is_file(), ".gitignore is missing")
        patterns = [line.strip() for line in read(path).splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        for name in RUN_ME_FILES:
            with self.subTest(name=name):
                ignored = False
                # The last matching line wins; a "!" line un-ignores.
                for pattern in patterns:
                    negated = pattern.startswith("!")
                    body = pattern[1:] if negated else pattern
                    body = body.lstrip("/").rstrip("/")
                    if fnmatch.fnmatchcase(name, body):
                        ignored = not negated
                self.assertTrue(ignored, f".gitignore does not ignore {name}")


if __name__ == "__main__":
    unittest.main()
