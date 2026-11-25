"""Agent-instruction contract checks (stdlib only, no PyMuPDF/Edge needed).

AGENTS.md and the SKILL.md files tell the agent which commands to run, which parameters exist, what the
defaults are and which stdout lines prove success. Those statements are hand-written prose, so they drift
silently when tools/ changes. These tests read the Markdown and verify every such claim against the code.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

ADAPTERS_DIR = REPO_ROOT / ".agents" / "adapters"
ANTIGRAVITY_ADAPTER = ADAPTERS_DIR / "antigravity.md"

GENERIC_DOCS = [REPO_ROOT / "AGENTS.md", *sorted(SKILLS_DIR.glob("*/SKILL.md"))]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
CLAUDE_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
CLAUDE_SETTINGS = REPO_ROOT / ".claude" / "settings.json"
CLAUDE_POINTERS = sorted(CLAUDE_SKILLS_DIR.glob("*/SKILL.md"))
INSTRUCTION_DOCS = [*GENERIC_DOCS, *sorted(ADAPTERS_DIR.glob("*.md")), CLAUDE_MD, *CLAUDE_POINTERS]
WRAPPER_SCRIPTS = ("extract_pdf_assets.ps1", "pdf_fallback_tools.ps1", "html_packager.ps1")
_CMD_PREFIX_RX = re.compile(r"powershell\.exe -NoProfile -ExecutionPolicy Bypass -File 'tools\\([A-Za-z0-9_]+\.ps1)' ")
SI_DOCS = sorted(SKILLS_DIR.glob("*/si_*.md"))
PS_HOST_PARAMS = {"NoProfile", "ExecutionPolicy", "File", "Command", "NonInteractive"}

# Details that only make sense inside Antigravity (internal paths, tool names, upload naming).
# They must live in .agents/adapters/antigravity.md, never in AGENTS.md, SKILL.md or SI files.
# The environment-detection signal (`<user_information>` / `appDataDir`) is allowed everywhere.
ANTIGRAVITY_ONLY_TOKENS = (
    "view_file",
    "read_file",
    "write_file",
    "StartLine",
    "EndLine",
    "ByteOffset",
    "edit_file",
    "run_command",
    "transcript.jsonl",
    ".system_generated",
    "\\brain\\",
    "<conversation-id>",
    "media_",
)

_PS_COMMAND_RX = re.compile(r"powershell\.exe[^`\n]*")
_SCRIPT_REF_RX = re.compile(r"tools[\\/]([A-Za-z0-9_]+\.ps1)")
_PARAM_TOKEN_RX = re.compile(r"(?<![\w-])-([A-Z][A-Za-z]+)\b")
_PLACEHOLDER_RX = re.compile(r"<[^<>`]*>|\.\.\.")
_STDOUT_SPAN_RX = re.compile(
    r"`((?:\[(?:QA PASS|Note)\]|WARNING:|=== |PreserveLayout mode:|Reader shell already)[^`]*"
    r"|[A-Z][^`]*? -> [^`]*"
    r"|[A-Z][^`]*? for stdout[^`]*)`"
)
_DEFAULT_RX = re.compile(r"`-([A-Z][A-Za-z]+)(?: <\w+>)?`\s*\*?\((?:[^()\n]{0,60}?)mặc định\s*`([^`]+)`")
_SIZE_CLAIM_RX = re.compile(r"\[([^\]]+\.md)\]\(([^)]+)\)[^\n]{0,200}?~(\d+) dòng / ~(\d+) KB")
_MD_LINK_RX = re.compile(r"\]\((?!https?:|mailto:|#|file:)([^)\s]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _ps_params(script: Path) -> dict[str, dict[str, object]]:
    """Parse the top-level param(...) block: name -> {'default': str|None, 'set': list[str]|None}."""
    text = _read(script)
    m = re.search(r"(?ms)^param\s*\((.*?)^\)", text)
    if not m:
        return {}
    block = m.group(1)
    params: dict[str, dict[str, object]] = {}
    pending_set: list[str] | None = None
    for line in block.splitlines():
        vs = re.search(r"\[ValidateSet\(([^)]*)\)\]", line)
        if vs:
            pending_set = re.findall(r"'([^']*)'", vs.group(1))
        pm = re.search(r"\$([A-Za-z]+)\s*(?:=\s*(.+?))?\s*,?\s*$", line)
        if pm and not line.strip().startswith("[ValidateRange") and "$" in line:
            default = pm.group(2)
            if default is not None:
                default = default.strip().rstrip(",").strip().strip("'\"")
            params[pm.group(1)] = {"default": default, "set": pending_set}
            pending_set = None
    return params


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must start with YAML frontmatter")
    return text[: text.index("\n---\n", 4) + len("\n---\n")]


def _read_file_limits() -> tuple[int, int]:
    """Per-call read limits as documented in the Antigravity adapter (single source of truth)."""
    m = re.search(r"khoảng (\d+) dòng / (\d+) KB", _read(ANTIGRAVITY_ADAPTER))
    if not m:
        raise AssertionError("antigravity.md must document the read_file limit as 'khoảng <N> dòng / <K> KB'")
    return int(m.group(1)), int(m.group(2)) * 1024


def _tools_source() -> str:
    parts = [_read(p) for p in sorted((TOOLS_DIR / "src").rglob("*.py"))]  # recursive: includes packages
    parts += [_read(p) for p in sorted(TOOLS_DIR.glob("*.ps1"))]
    return "\n".join(parts)


def _stdout_prefix(span: str) -> str:
    """Literal head of a documented stdout line, up to the first placeholder or the first ' -> '."""
    cut = len(span)
    ph = _PLACEHOLDER_RX.search(span)
    if ph:
        cut = ph.start()
    arrow = span.find(" -> ")
    if arrow != -1:
        cut = min(cut, arrow + len(" ->"))
    return span[:cut].rstrip(" ([")


class TestSkillContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scripts = {p.name: _ps_params(p) for p in TOOLS_DIR.glob("*.ps1")}
        cls.all_params = {name for params in cls.scripts.values() for name in params}
        cls.source = _tools_source()
        cls.docs = {p: _read(p) for p in INSTRUCTION_DOCS}

    def test_docs_present(self) -> None:
        self.assertGreaterEqual(len(INSTRUCTION_DOCS), 3, "AGENTS.md + at least two SKILL.md expected")
        for script in ("extract_pdf_assets.ps1", "html_packager.ps1", "pdf_fallback_tools.ps1"):
            self.assertIn(script, self.scripts)
            self.assertTrue(self.scripts[script], f"could not parse param block of {script}")

    def test_example_commands_use_real_scripts_params_and_actions(self) -> None:
        for doc, text in self.docs.items():
            for cmd in _PS_COMMAND_RX.findall(text):
                with self.subTest(doc=doc.name, cmd=cmd[:90]):
                    sm = _SCRIPT_REF_RX.search(cmd)
                    self.assertIsNotNone(sm, "command must call a tools\\*.ps1 script")
                    script = sm.group(1)
                    self.assertTrue(script in self.scripts, f"script does not exist: tools\\{script}")
                    declared = self.scripts[script]
                    for name in _PARAM_TOKEN_RX.findall(cmd):
                        if name in PS_HOST_PARAMS:
                            continue
                        self.assertTrue(name in declared, f"-{name} is not a parameter of {script}")
                    am = re.search(r"-Action\s+'?([A-Za-z]+)", cmd)
                    if am:
                        allowed = declared["Action"]["set"] or []
                        self.assertTrue(am.group(1) in allowed, f"-Action {am.group(1)} not in ValidateSet {allowed} of {script}")

    def test_backticked_parameters_exist(self) -> None:
        for doc, text in self.docs.items():
            for span in re.findall(r"`([^`\n]+)`", text):
                if not span.startswith("-") or "powershell.exe" in span:
                    continue
                for name in _PARAM_TOKEN_RX.findall(span):
                    with self.subTest(doc=doc.name, param=name):
                        self.assertTrue(name in self.all_params | PS_HOST_PARAMS, f"`-{name}` is documented but no tools\\*.ps1 declares it")

    def test_documented_defaults_match_code(self) -> None:
        for doc, text in self.docs.items():
            for m in _DEFAULT_RX.finditer(text):
                name, documented = m.group(1), m.group(2).strip()
                preceding = list(_SCRIPT_REF_RX.finditer(text, 0, m.start()))
                owners = [preceding[-1].group(1)] if preceding else []
                owners = [s for s in owners if name in self.scripts.get(s, {})] or [
                    s for s, p in self.scripts.items() if name in p
                ]
                with self.subTest(doc=doc.name, param=name):
                    self.assertTrue(owners, f"no script declares -{name}")
                    actual = self.scripts[owners[0]][name]["default"]
                    self.assertIsNotNone(actual, f"-{name} has no default in {owners[0]} but doc says `{documented}`")
                    try:
                        same = float(documented) == float(str(actual))
                    except ValueError:
                        same = documented.lower() == str(actual).lower()
                    self.assertTrue(same, f"-{name}: doc says `{documented}`, {owners[0]} uses `{actual}`")

    def test_documented_stdout_lines_are_printed_by_tools(self) -> None:
        for doc, text in self.docs.items():
            for span in _STDOUT_SPAN_RX.findall(text):
                prefix = _stdout_prefix(span)
                if len(prefix) < 6:
                    continue
                with self.subTest(doc=doc.name, line=span[:70]):
                    self.assertTrue(prefix in self.source, f"no tool prints a line starting with {prefix!r}")

    def test_relative_links_and_tool_paths_exist(self) -> None:
        for doc, text in self.docs.items():
            for target in _MD_LINK_RX.findall(text):
                with self.subTest(doc=doc.name, link=target):
                    self.assertTrue((doc.parent / target.split("#")[0]).exists(), f"broken link: {target}")
            for rel in set(re.findall(r"`(tools[\\/][A-Za-z0-9_\\/.-]+)`", text)):
                if "<" in rel or "*" in rel:
                    continue
                with self.subTest(doc=doc.name, path=rel):
                    self.assertTrue((REPO_ROOT / rel.replace("\\", "/")).exists(), f"missing path: {rel}")

    def test_single_read_files_fit_read_limits_and_size_claims(self) -> None:
        max_lines, max_bytes = _read_file_limits()
        checked = 0
        for doc, text in self.docs.items():
            for m in _SIZE_CLAIM_RX.finditer(text):
                target = (doc.parent / m.group(2)).resolve()
                claimed_lines, claimed_kb = int(m.group(3)), int(m.group(4))
                with self.subTest(doc=doc.name, file=m.group(1)):
                    self.assertTrue(target.is_file(), f"missing {target}")
                    data = target.read_bytes()
                    lines = data.decode("utf-8-sig").count("\n") + 1
                    kb = len(data) / 1024
                    self.assertLessEqual(lines, max_lines, "file must be readable in one call (adapter limit)")
                    self.assertLessEqual(len(data), max_bytes, "file must be readable in one call (adapter limit)")
                    self.assertLess(abs(lines - claimed_lines) / claimed_lines, 0.2, f"doc says ~{claimed_lines} lines, file has {lines}")
                    self.assertLess(abs(kb - claimed_kb) / claimed_kb, 0.2, f"doc says ~{claimed_kb} KB, file is {kb:.1f} KB")
                    checked += 1
        self.assertGreaterEqual(checked, 3, "expected size claims for every SI file read in one call")


    def test_antigravity_details_live_only_in_adapter(self) -> None:
        adapter = _read(ANTIGRAVITY_ADAPTER)
        for token in ANTIGRAVITY_ONLY_TOKENS:
            with self.subTest(token=token):
                self.assertTrue(token in adapter, f"adapter should document {token!r}")
        for doc in [*GENERIC_DOCS, *SI_DOCS]:
            text = _read(doc)
            for token in ANTIGRAVITY_ONLY_TOKENS:
                with self.subTest(doc=doc.relative_to(REPO_ROOT).as_posix(), token=token):
                    self.assertFalse(token in text, f"Antigravity-specific {token!r} belongs in .agents/adapters/antigravity.md")

    def test_generic_docs_point_to_adapter_with_detection_signal(self) -> None:
        for doc in GENERIC_DOCS:
            text = _read(doc)
            with self.subTest(doc=doc.relative_to(REPO_ROOT).as_posix()):
                linked = re.search(r"\]\([./]*(?:\.\./\.\./|\.agents/)adapters/antigravity\.md\)", text)
                self.assertTrue(linked, "must link the Antigravity adapter")
                self.assertTrue("`<user_information>`" in text, "must state the environment-detection signal")
                self.assertTrue("`App Data Directory`" in text, "must state the environment-detection signal")
                self.assertTrue("`appDataDir`" in text, "must state the environment-detection signal")


    def test_claude_pointer_skills_mirror_shared_skills(self) -> None:
        shared = {p.parent.name: p for p in SKILLS_DIR.glob("*/SKILL.md")}
        pointers = {p.parent.name: p for p in CLAUDE_POINTERS}
        self.assertEqual(sorted(pointers), sorted(shared), "every .agents skill needs a .claude/skills pointer (and vice versa)")
        for name, pointer in pointers.items():
            with self.subTest(skill=name):
                text = _read(pointer)
                self.assertEqual(_frontmatter(text), _frontmatter(_read(shared[name])), "name/description must match the shared SKILL.md")
                self.assertTrue(f".agents/skills/{name}/SKILL.md" in text, "pointer must name the shared SKILL.md")
                self.assertTrue(".agents/adapters/claude-code.md" in text, "pointer must name the Claude Code adapter")
                self.assertLess(len(text) - len(_frontmatter(text)), 1500, "pointer must stay a pointer, not a copy of the workflow")

    def test_claude_md_imports_agents_md_and_adapter(self) -> None:
        text = _read(CLAUDE_MD)
        outside_code = re.sub(r"```.*?```|`[^`\n]*`", "", text, flags=re.S)
        imports = re.findall(r"(?m)^@(\S+)\s*$", outside_code)
        self.assertIn("AGENTS.md", imports, "CLAUDE.md must import AGENTS.md (Claude Code skips AGENTS.md once CLAUDE.md exists)")
        self.assertIn(".agents/adapters/claude-code.md", imports)
        for imp in imports:
            with self.subTest(imp=imp):
                self.assertTrue((REPO_ROOT / imp).is_file(), f"import target missing: {imp}")

    def test_claude_settings_preapprove_only_wrapper_commands_used_in_docs(self) -> None:
        rules = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"]
        rule_rx = re.compile(r"^(PowerShell|Bash)\((powershell\.exe -NoProfile -ExecutionPolicy Bypass -File 'tools\\([A-Za-z0-9_]+\.ps1)') \*\)$")
        allowed: dict[str, set[str]] = {}
        for rule in rules:
            with self.subTest(rule=rule):
                m = rule_rx.match(rule)
                self.assertTrue(m, "allow rules may only pre-approve the tools\\*.ps1 wrapper commands")
                self.assertIn(m.group(3), WRAPPER_SCRIPTS)
                allowed.setdefault(m.group(3), set()).add(m.group(1))
        for script in WRAPPER_SCRIPTS:
            with self.subTest(script=script):
                self.assertEqual(allowed.get(script), {"PowerShell", "Bash"}, "each wrapper needs both a PowerShell and a Bash rule")
        for doc, text in self.docs.items():
            for cmd in _PS_COMMAND_RX.findall(text):
                with self.subTest(doc=doc.name, cmd=cmd[:80]):
                    m = _CMD_PREFIX_RX.match(cmd)
                    self.assertTrue(m and m.group(1) in allowed, "documented command would not match the pre-approved rule prefix")


if __name__ == "__main__":
    unittest.main()
