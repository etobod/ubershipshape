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
                       # Plan 070 M1: run-me-admin.ps1 elevates itself and is run by
                       # its absolute path from a normal shell, so the old
                       # "Set-Location <cwd>; ... -File .\run-me-admin.ps1" command is gone.
                       'powershell -ExecutionPolicy Bypass -File "<cwd>\\run-me-admin.ps1"'):
            self.assertIn(phrase, rule)
        self.assertRegex(rule, r"\btry\s*\{", "the block is wrapped in try {")
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

    # loc/inbox/046-plan-2-easy-run-me-handoff-utc.md, M1: the hand-off time is UTC.

    def test_reference_time_is_utc(self):
        path = SKILLS / "ush-common/references/run-me.md"
        self.assertTrue(path.is_file(), "ush-common/references/run-me.md is missing")
        rule = flat(read(path))
        stamp = r"(?:<[^<>]+>|\d{4}-\d{2}-\d{2} \d{2}:\d{2})"
        self.assertRegex(
            rule, rf"# Written: {stamp} \({stamp} UTC\)",
            "the # Written: header carries the local time and the UTC time in brackets")
        text = read(path)
        lowered = text.lower()
        start = lowered.find("after the run")
        self.assertNotEqual(start, -1, "run-me.md has no 'After the run' part")
        end = re.compile(r"(?m)^##+ ").search(text, start + len("after the run"))
        part = flat(lowered[start:end.start() if end else len(text)])
        for token in ("generated_at", "utc", "# written:", "modification time"):
            self.assertIn(token, part, f"'After the run' does not mention {token!r}")
        self.assertRegex(
            part, r"modification time[^.]*\b(?:not|never)\b|\b(?:not|never)\b[^.]*modification time",
            "'After the run' says the file's modification time is not used")

    def test_written_header_utc_has_the_date(self):
        # K1 asks for the full UTC date and time: a hand-off near midnight has a
        # different UTC date, so a time-only "(<HH:MM> UTC)" is not enough.
        path = SKILLS / "ush-common/references/run-me.md"
        rule = flat(read(path))
        header = re.search(r"# Written: [^\n]*?\(([^()]*) UTC\)", rule)
        self.assertIsNotNone(header, "run-me.md has no # Written: header with a UTC time")
        self.assertRegex(
            header.group(1), r"YYYY-MM-DD HH:MM|\d{4}-\d{2}-\d{2} \d{2}:\d{2}",
            "the UTC time in the # Written: header has no date")
        self.assertIn(
            "%Y-%m-%d %H:%M UTC", rule,
            "the machine-time one-liner does not print the UTC date and time")

    def test_read_back_names_utc_header(self):
        for name in ("health", "files", "inventory", "processes", "runall", "settings"):
            doc = SKILLS / f"ush-{name}" / "SKILL.md"
            with self.subTest(skill=f"ush-{name}"):
                self.assertTrue(doc.is_file(), f"ush-{name} has no SKILL.md")
                lowered = flat(read(doc)).lower()
                windows = [lowered[max(0, m.start() - 300):m.end() + 300]
                           for m in re.finditer(re.escape("# written:"), lowered)]
                self.assertTrue(windows, "the SKILL.md does not name the # Written: header")
                self.assertTrue(
                    any("utc" in w and "newer" in w and "run-me-admin.ps1" in w for w in windows),
                    "the read-back does not name the UTC time of run-me-admin.ps1's "
                    "# Written: header as the moment the summary must be newer than")

    def test_failed_elevated_pass_reruns_the_file(self):
        docs = [("run-me.md", SKILLS / "ush-common/references/run-me.md")]
        docs += [(f"ush-{name}", SKILLS / f"ush-{name}" / "SKILL.md")
                 for name in ("health", "files", "inventory", "processes", "runall", "settings")]
        not_run = re.compile(r"did not run|didn't run|not run|not elevated|without elevation")
        rerun = re.compile(r"run-me-admin\.ps1`?(?:(?!\. ).){0,200}?\bagain\b")
        for label, doc in docs:
            with self.subTest(doc=label):
                self.assertTrue(doc.is_file(), f"{label} is missing")
                lowered = flat(read(doc)).lower()
                windows = [lowered[max(0, m.start() - 300):m.end() + 300]
                           for m in re.finditer(r"\bagain\b", lowered)]
                self.assertTrue(
                    any("run-me-admin.ps1" in w and "elevated" in w and not_run.search(w)
                        for w in windows)
                    # The file and "again" in one sentence: an unrelated "again" nearby
                    # (write the report again) is not a rerun of the file.
                    and rerun.search(lowered),
                    "does not tell the user to run the same run-me-admin.ps1 again "
                    "(it elevates itself, plan 070) when the elevated pass did not run")
                if label == "run-me.md":
                    self.assertNotIn("a new run of the skill shows what changed", lowered,
                                     "still offers a new run of the skill as the recovery")


RUN_ME_DOC = SKILLS / "ush-common/references/run-me.md"


def fenced_blocks(text):
    """The bodies of the ``` fenced blocks of a Markdown text, in order."""
    return re.findall(r"(?ms)^```[^\n]*\n(.*?)^```", text)


def admin_frame(text):
    """The fenced block of run-me.md that is the run-me-admin.ps1 frame."""
    for block in fenced_blocks(text):
        if "run-me-admin.out.txt" in block and "Start-Transcript" in block:
            return block
    return None


class TestRunMeElevation(unittest.TestCase):
    """run-me-admin.ps1 elevates itself and run-me files show each block
    (loc/inbox/070-plan-1-hard-run-me-admin-self-elevation.md)."""

    # M1 K1
    def test_admin_frame_elevates_itself_before_transcript(self):
        frame = admin_frame(read(RUN_ME_DOC))
        self.assertIsNotNone(frame, "run-me.md has no run-me-admin.ps1 frame")
        check = re.search(r"if\s*\(\s*-not\s*\(?[^\n]*IsInRole[^\n]*Administrator", frame)
        self.assertIsNotNone(check, "the frame has no IsInRole administrator check")
        else_at = re.search(r"\}\s*else\s*\{", frame[check.end():])
        self.assertIsNotNone(else_at, "the administrator check has no else branch")
        not_admin = frame[check.end():check.end() + else_at.start()]
        admin = frame[check.end() + else_at.end():]
        self.assertIn("Start-Process powershell.exe", not_admin)
        self.assertIn("-Verb RunAs", not_admin)
        self.assertIn("-NoExit", not_admin)
        self.assertIn('-File "<cwd>\\run-me-admin.ps1"', not_admin)
        for token in ("Start-Transcript", "Stop-Transcript", "<the block"):
            self.assertNotIn(token, not_admin, f"{token} runs in the not-elevated branch")
            self.assertIn(token, admin, f"{token} is not in the elevated branch")
        head = frame[:check.start()]
        self.assertNotIn("Start-Transcript", head, "the transcript starts before the check")

    # M1 K2
    def test_admin_command_for_normal_shell(self):
        text = read(RUN_ME_DOC)
        rule = flat(text)
        self.assertIn('powershell -ExecutionPolicy Bypass -File "<cwd>\\run-me-admin.ps1"', rule)
        self.assertIn("uac", rule.lower())
        lowered = rule.lower()
        for phrase in ("run as administrator", "open an elevated", "from an elevated powershell",
                       "in an elevated powershell", "an elevated shell starts elsewhere"):
            self.assertNotIn(phrase, lowered, f"run-me.md still says {phrase!r}")

    # M1 K3
    def test_frame_prints_block_start_and_end(self):
        text = read(RUN_ME_DOC)
        frames = [b for b in fenced_blocks(text) if "Start-Transcript" in b]
        names = {"run-me-admin.out.txt" in b for b in frames}
        self.assertEqual(names, {True, False}, "run-me.md has no frame for each file")
        for frame in frames:
            with self.subTest(frame=frame.splitlines()[0]):
                start = re.search(r'Write-Host "\[<n>/<N>\] [^"\n]*\.\.\."', frame)
                done = re.search(r'Write-Host "\[<n>/<N>\] done"', frame)
                closing = frame.find('Write-Host "Finished. You can close this window."')
                block = frame.find("<the block")
                self.assertIsNotNone(start, "no numbered start line")
                self.assertIsNotNone(done, "no numbered end line")
                self.assertNotEqual(block, -1)
                self.assertLess(start.start(), block)
                self.assertGreater(done.start(), block)
                self.assertGreater(closing, done.start(), "no closing line after the blocks")

    # M1 K4
    def test_not_elevated_rerun_accepts_uac(self):
        lowered = flat(read(RUN_ME_DOC)).lower()
        # The passage about an elevated pass whose summary is not elevated.
        not_elevated = re.compile(r"not elevated|\"elevated\":\s*false"
                                  r"|`elevated`[^.]{0,40}\bfalse\b")
        windows = [lowered[max(0, m.start() - 400):m.end() + 400]
                   for m in not_elevated.finditer(lowered)]
        self.assertTrue(windows, "run-me.md does not name a summary that is not elevated")
        rerun = re.compile(r"run-me-admin\.ps1`?(?:(?!\. ).){0,200}?\bagain\b"
                           r"|\bagain\b(?:(?!\. ).){0,200}?run-me-admin\.ps1")
        same_command = re.compile(r"\bsame command\b")
        accept_uac = re.compile(r"\baccept(?:(?!\. ).){0,80}?\buac\b"
                                r"|\buac\b(?:(?!\. ).){0,80}?\baccept")
        matching = [w for w in windows
                    if "summary" in w and rerun.search(w)
                    and same_command.search(w) and accept_uac.search(w)]
        self.assertTrue(
            matching,
            "after an elevated pass whose summary is not elevated, run-me.md does not tell "
            "the user to run the same run-me-admin.ps1 again with the same command and "
            "accept the UAC prompt")
        for window in matching:
            for phrase in ("open an elevated", "from an elevated powershell",
                           "in an elevated powershell", "run as administrator"):
                self.assertNotIn(phrase, window,
                                 f"the rerun still asks for an elevated shell: {phrase!r}")

    # M2 K1
    def test_no_skill_tells_user_to_open_elevated_shell(self):
        # Prose only: fenced blocks (``` and ````) are skipped, and so is a quote in
        # backticks or quotation marks, such as the header a block printer prints
        # ("Run in an elevated Windows PowerShell").
        quoted = re.compile(r"`[^`]*`|\"[^\"]*\"|“[^”]*”|„[^”]*”")
        asks = (
            ("open an elevated shell",
             re.compile(r"\bopen(?:s|ing)?\s+(?:(?:a|an|the)\s+)?(?:new\s+)?elevated\b")),
            ("start PowerShell as administrator",
             re.compile(r"\b(?:start|open|launch|run)(?:s|ing)?\s+(?:(?:a|an|the)\s+)?"
                        r"(?:new\s+)?(?:windows\s+)?powershell(?:\.exe)?(?:\s+window)?\s+"
                        r"as\s+(?:an?\s+)?admin(?:istrator)?\b")),
            ("in/from an elevated PowerShell",
             re.compile(r"\b(?:in|from)\s+(?:an?|the)\s+elevated\s+(?:windows\s+)?powershell\b")),
        )
        docs = sorted(SKILLS.glob("*/SKILL.md")) + sorted(SKILLS.glob("*/references/*.md"))
        self.assertTrue(docs, "no skill docs found")
        problems = []
        for path in docs:
            name = path.relative_to(SKILLS).as_posix()
            paragraphs = []
            current = []
            for number, line, kind in classify_lines(read(path)):
                if kind != "text" or not line.strip():
                    if current:
                        paragraphs.append(current)
                    current = []
                    continue
                current.append((number, line))
            if current:
                paragraphs.append(current)
            for paragraph in paragraphs:
                text = flat(" ".join(line for _, line in paragraph))
                prose = quoted.sub(" ", text).lower()
                for label, pattern in asks:
                    match = pattern.search(prose)
                    if match:
                        problems.append(
                            f"{name}:{paragraph[0][0]}: {label}: {match.group(0)!r}")
        self.assertEqual(problems, [],
                         "a skill doc still tells the user to open an elevated shell "
                         "(run-me-admin.ps1 elevates itself, plan 070)")

    # M2 K2
    def test_skills_name_self_elevation(self):
        said = re.compile(r"run-me-admin\.ps1`?(?:(?!\. ).){0,80}?\belevates itself\b"
                          r"(?:(?!\. ).){0,40}?\buac\b")
        for name in RUN_ME_SKILLS:
            with self.subTest(skill=f"ush-{name}"):
                lowered = flat(read(SKILLS / f"ush-{name}" / "SKILL.md")).lower()
                self.assertRegex(lowered, said,
                                 "does not say run-me-admin.ps1 elevates itself (a UAC prompt)")

    # M2 K3
    def test_skills_rerun_accepts_uac(self):
        rerun = re.compile(r"run the same `run-me-admin\.ps1`(?:(?!\. ).){0,60}?\bagain\b"
                           r"(?:(?!\. ).){0,60}?\baccept the uac prompt\b")
        for name in ("health", "files", "inventory", "processes", "runall", "settings"):
            with self.subTest(skill=f"ush-{name}"):
                lowered = flat(read(SKILLS / f"ush-{name}" / "SKILL.md")).lower()
                self.assertRegex(lowered, rerun,
                                 "a failed elevated pass is not 'run the same run-me-admin.ps1 "
                                 "again and accept the UAC prompt'")

    # M2 K4
    def test_plugin_version_raised(self):
        plugin = json.loads(read(MANIFEST_DIR / "plugin.json"))
        self.assertEqual(plugin["version"], "1.0.43")


# loc/inbox/055-plan-1-hard-report-summary.md, M2: the chat answer is the summary
# section check_report.py printed after its OK line, plus the report path, nothing added.
# Assumptions beyond the plan: the step names "chat", `check_report.py`, "print",
# "OK", "path", and "nothing added" or "nothing else".
REPORT_SKILLS = ("advice", "events", "files", "health", "inventory", "packages",
                 "processes", "runall", "settings")


class TestPlugin(unittest.TestCase):
    def test_chat_answer_is_printed_summary(self):
        for name in REPORT_SKILLS:
            doc = SKILLS / f"ush-{name}" / "SKILL.md"
            with self.subTest(skill=f"ush-{name}"):
                self.assertTrue(doc.is_file(), f"ush-{name} has no SKILL.md")
                steps = re.findall(
                    r"(?ms)^\d+\. Tell the user where the report is.*?(?=^\d+\. |^## |\Z)",
                    read(doc))
                self.assertEqual(len(steps), 1, "one step tells where the report is")
                step = flat(steps[0])
                checks = (
                    ("names the chat answer", r"(?i)\bchat\b"),
                    ("names check_report.py", r"check_report\.py"),
                    ("the text the checker printed", r"(?i)\bprint(?:s|ed)?\b"),
                    ("printed after OK", r"after (?:the |its )?`?OK`?"),
                    ("plus the report path", r"(?i)\bpath\b"),
                    ("nothing added", r"(?i)\bnothing (?:added|else)\b"),
                )
                for label, pattern in checks:
                    self.assertRegex(step, pattern, f"{label}: {step}")

    def test_check_step_sets_utf8_output_in_powershell(self):
        # Final review 055 round 2: Windows PowerShell 5.1 decodes a native program's
        # stdout with [Console]::OutputEncoding, so the check step sets it to UTF-8
        # first (as psrun.py does) and the printed section reaches the chat unchanged.
        for name in REPORT_SKILLS:
            with self.subTest(skill=f"ush-{name}"):
                steps = [flat(step) for step in re.findall(
                    r"(?ms)^\d+\. .*?(?=^\d+\. |^## |\Z)",
                    read(SKILLS / f"ush-{name}" / "SKILL.md"))
                    if "--latest --skill" in step and "check_report.py" in step]
                self.assertEqual(len(steps), 1, "one step runs check_report.py")
                self.assertIn(UTF8_CHECK_SENTENCE, steps[0])


# The same sentence in the check step of every report skill.
UTF8_CHECK_SENTENCE = (
    "In Windows PowerShell, the same command first sets "
    "`[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false);` so the "
    "Polish letters of the printed section reach the chat unchanged; in a POSIX shell "
    "the command runs as it is.")


if __name__ == "__main__":
    unittest.main()
