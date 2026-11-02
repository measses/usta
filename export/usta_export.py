#!/usr/bin/env python3
"""usta export: decide what leaves your machine for the cloud computer.

Nothing is included by default. You pick memory folders, skills, agents and
commands; you list what must never go (keywords, files, whole categories);
you preview the result; only then is a bundle written.

    usta_export.py inventory [--json]
    usta_export.py init [--from-json FILE]
    usta_export.py build --dry-run [--json]
    usta_export.py build --approve [--accept-flags]

Standard library only (Python 3.11+, or 3.9+ with `tomli` installed).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        sys.exit("usta: Python 3.11+ is required (or `pip install tomli`).")

HERE = Path(__file__).resolve().parent
PRESETS_FILE = HERE / "presets.toml"
MANIFEST = ".usta-manifest.json"
CATEGORIES = ("memory_projects", "skills", "agents", "commands")

# Files that never leave, whatever the configuration says.
ALWAYS_EXCLUDE = [
    "**/settings*.json", "**/.env", "**/.env.*", "**/*.jsonl", "**/.credentials*",
    "**/credentials*", "**/.mcp.json", "**/*mcp*.json", "**/hooks/**", "**/*.pem",
    "**/*.key", "**/id_rsa*", "**/id_ed25519*", "**/.netrc", "**/.npmrc", "**/.pypirc",
]
# Binary files are copied only if they are plain media/fonts.
BINARY_OK = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".trash", ".DS_Store"}

SECRET_PATTERNS = [
    re.compile(p) for p in (
        r"sk-ant-[A-Za-z0-9_-]{20,}",
        r"sk-(?:proj-)?[A-Za-z0-9_-]{24,}",
        r"gh[pousr]_[A-Za-z0-9]{30,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"xox[abprs]-[A-Za-z0-9-]{10,}",
        r"AKIA[0-9A-Z]{16}",
        r"AIza[0-9A-Za-z_-]{35}",
        r"Bearer\s+[A-Za-z0-9._~+/-]{20,}=*",
    )
]
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
# NAME_KEY=value with a literal value (not $VAR, os.environ, <placeholder>)
KEY_VALUE = re.compile(
    r"(\b[A-Za-z0-9_]*(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD)\b['\"]?\s*[:=]\s*['\"]?)"
    r"(?![$<{]|os\.|process\.|env\.)([A-Za-z0-9_\-./+=]{8,})"
)
# Prose never needs the value; this also keeps strict `API_KEY=` scanners quiet.
PROSE_KEY = re.compile(r"\b([A-Za-z0-9_]*_?API_?KEY)\S*?\s*[:=]\s*\S+")
PROSE_SUFFIXES = {".md", ".txt", ".markdown"}

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<![\w+])(?:\+\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]?\d{3}[ .-]?\d{2,4}(?:[ .-]?\d{2,4})?|0\s?5\d{2}[ .-]?\d{3}[ .-]?\d{2}[ .-]?\d{2})(?!\w)")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
TCKN = re.compile(r"\b[1-9]\d{10}\b")
# 15-16 digit card numbers starting with a real network digit, not glued to paths or words
CARD = re.compile(r"(?<![\w/.-])[3-6]\d{3}(?:[ -]?\d{4}){2}[ -]?\d{3,4}(?![\w/.-])")


# ---------------------------------------------------------------- validators

def iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def tckn_ok(s: str) -> bool:
    d = [int(c) for c in s]
    if len(d) != 11 or d[0] == 0:
        return False
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return d10 == d[9] and sum(d[:10]) % 10 == d[10]


def luhn_ok(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for i, n in enumerate(reversed(digits)):
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


PII_DETECTORS = [
    ("email", EMAIL, None),
    ("phone", PHONE, None),
    ("iban", IBAN, iban_ok),
    ("national-id", TCKN, tckn_ok),
    ("card", CARD, luhn_ok),
]


# ---------------------------------------------------------------- config

@dataclass
class Config:
    claude_dir: Path
    include: dict
    memory_names: dict
    keywords: list
    paths: list
    presets: list
    pii_mode: str
    pii_allow: list
    preset_words: dict = field(default_factory=dict)


def load_presets() -> dict:
    if not PRESETS_FILE.exists():
        return {}
    data = tomllib.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    return {k: v.get("words", []) for k, v in data.items()}


def load_config(path: Path) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    src = data.get("source", {})
    inc = data.get("include", {})
    exc = data.get("exclude", {})
    pii = data.get("pii", {})
    presets_all = load_presets()
    chosen = exc.get("presets", [])
    unknown = [p for p in chosen if p not in presets_all]
    if unknown:
        sys.exit(f"usta: unknown preset(s): {', '.join(unknown)} (known: {', '.join(presets_all)})")
    mode = pii.get("mode", "flag")
    if mode not in ("flag", "redact", "off"):
        sys.exit("usta: [pii] mode must be flag, redact or off")
    return Config(
        claude_dir=Path(os.path.expanduser(src.get("claude_dir", "~/.claude"))).resolve(),
        include={k: list(inc.get(k, [])) for k in CATEGORIES} | {
            "claude_md": bool(inc.get("claude_md", False)),
            "extra_files": list(inc.get("extra_files", [])),
        },
        memory_names=dict(inc.get("memory_names", {})),
        keywords=[k for k in exc.get("keywords", []) if k.strip()],
        paths=list(exc.get("paths", [])),
        presets=chosen,
        pii_mode=mode,
        pii_allow=list(pii.get("allow", [])),
        preset_words={p: presets_all[p] for p in chosen},
    )


# ---------------------------------------------------------------- inventory

def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in walk_files(p))


def walk_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name not in SKIP_DIRS:
                yield Path(dirpath) / name


def inventory(claude_dir: Path) -> dict:
    inv: dict[str, list] = {k: [] for k in CATEGORIES}
    projects = claude_dir / "projects"
    if projects.is_dir():
        for d in sorted(projects.iterdir()):
            mem = d / "memory"
            files = sorted(mem.glob("*.md")) if mem.is_dir() else []
            if files:
                inv["memory_projects"].append({"name": d.name, "files": len(files), "bytes": _size(mem)})
    for cat, sub, pattern in (("skills", "skills", "*"), ("agents", "agents", "*.md"), ("commands", "commands", "*")):
        base = claude_dir / sub
        if not base.is_dir():
            continue
        for p in sorted(base.glob(pattern)):
            if p.name.startswith(".") or p.name in SKIP_DIRS:
                continue
            target = p.resolve()
            if cat == "skills" and not target.is_dir():
                continue
            inv[cat].append({"name": p.name, "bytes": _size(target)})
    return inv


# ---------------------------------------------------------------- matching

def glob_to_regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append({"*": "[^/]*", "?": "[^/]"}.get(c, re.escape(c)))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(rel: str, patterns: list) -> str | None:
    parts = rel.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    for pat in patterns:
        rx = glob_to_regex(pat)
        if any(rx.match(p) for p in prefixes):
            return pat
    return None


def selected(names: list, wanted: list) -> list:
    return [n for n in names if any(fnmatch.fnmatchcase(n, w) for w in wanted)]


def memory_slug(dir_name: str, names: dict) -> str:
    if dir_name in names:
        return names[dir_name]
    tokens = [t for t in dir_name.strip("-").split("-") if t]
    if len(tokens) >= 2 and tokens[0] in ("Users", "home"):
        tokens = tokens[2:]
    if tokens and tokens[0] in ("Documents", "Projects", "projects", "src", "code"):
        tokens = tokens[1:]
    return "-".join(tokens).lower() or "home"


# ---------------------------------------------------------------- filtering

@dataclass
class Report:
    included: list = field(default_factory=list)      # bundle-relative paths
    excluded: list = field(default_factory=list)      # (path, reason)
    removed_lines: int = 0
    masked_values: int = 0
    pii_redacted: int = 0
    flags: list = field(default_factory=list)         # (path, line, kind, preview)
    delta: dict = field(default_factory=dict)


def _preview(line: str, start: int, end: int) -> str:
    """Show the line with the hit marked and every other sensitive value hidden."""
    snippet = line[:start] + "\x00" + line[end:]
    for _, rx, check in PII_DETECTORS:
        snippet = rx.sub(lambda m: m.group(0) if check and not check(m.group(0)) else "‹hidden›", snippet)
    for rx in SECRET_PATTERNS:
        snippet = rx.sub("‹hidden›", snippet)
    return snippet.replace("\x00", "«…»").strip()[:160]


class Filter:
    def __init__(self, cfg: Config, report: Report):
        self.cfg = cfg
        self.report = report
        self.kw = [(k, re.compile(k[3:], re.I) if k.startswith("re:") else re.compile(re.escape(k), re.I))
                   for k in cfg.keywords]
        self.preset = [(p, re.compile(r"\b" + re.escape(w) + r"\b", re.I))
                       for p, words in cfg.preset_words.items() for w in words]

    def _allowed(self, text: str) -> bool:
        return any(a.lower() in text.lower() for a in self.cfg.pii_allow)

    def mask_secrets(self, line: str) -> str:
        for rx in SECRET_PATTERNS:
            line, n = rx.subn("<redacted:secret>", line)
            self.report.masked_values += n

        def kv(m: re.Match) -> str:
            value = m.group(2)
            if re.fullmatch(r"[a-z_]+|x+|\.+|[a-z]{2,4}-\.{2,}.*", value):
                return m.group(0)
            self.report.masked_values += 1
            return m.group(1) + "<redacted>"

        return KEY_VALUE.sub(kv, line)

    def pii(self, rel: str, n: int, line: str) -> str:
        if self.cfg.pii_mode == "off":
            return line
        for kind, rx, check in PII_DETECTORS:
            for m in list(rx.finditer(line)):
                value = m.group(0)
                if check and not check(value):
                    continue
                if self._allowed(value):
                    continue
                if self.cfg.pii_mode == "redact":
                    line = line.replace(value, f"<{kind}>")
                    self.report.pii_redacted += 1
                else:
                    self.report.flags.append((rel, n, kind, _preview(line, m.start(), m.end())))
        return line

    def text(self, rel: str, text: str) -> str:
        prose = Path(rel).suffix.lower() in PROSE_SUFFIXES
        out = []
        skip_level = 0  # inside a markdown section whose heading matched a keyword
        for n, line in enumerate(text.splitlines(keepends=True), 1):
            heading = re.match(r"(#{1,6})\s", line) if prose else None
            if skip_level:
                if heading and len(heading.group(1)) <= skip_level:
                    skip_level = 0
                else:
                    self.report.removed_lines += 1
                    continue
            if any(rx.search(line) for _, rx in self.kw):
                self.report.removed_lines += 1
                if heading:
                    skip_level = len(heading.group(1))
                continue
            if PRIVATE_KEY.search(line):
                self.report.removed_lines += 1
                continue
            line = self.mask_secrets(line)
            if prose:
                line = PROSE_KEY.sub(r"\1 (value hidden)", line)
            line = self.pii(rel, n, line)
            for preset, rx in self.preset:
                m = rx.search(line)
                if m and not self._allowed(line):
                    self.report.flags.append((rel, n, f"preset:{preset}", _preview(line, m.start(), m.end())))
                    break
            out.append(line)
        return "".join(out)


def is_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------- plan

def plan_bundle(cfg: Config) -> tuple[dict, Report]:
    """Return ({bundle_rel: bytes}, report) without touching the disk."""
    report = Report()
    flt = Filter(cfg, report)
    files: dict[str, bytes] = {}
    sources: list[tuple[str, Path]] = []  # (bundle_rel, source file)
    inv = inventory(cfg.claude_dir)

    # memory
    mem_dirs = selected([m["name"] for m in inv["memory_projects"]], cfg.include["memory_projects"])
    index = ["# Memory (read-only copy from your machine)\n",
             "\nFiltered by usta. Read a linked file for detail; do not write here.\n"]
    for d in mem_dirs:
        slug = memory_slug(d, cfg.memory_names)
        src = cfg.claude_dir / "projects" / d / "memory"
        for f in sorted(src.glob("*.md")):
            if f.name != "MEMORY.md":
                sources.append((f"memory/{slug}/{f.name}", f))
        idx = src / "MEMORY.md"
        if idx.exists():
            lines = idx.read_text(encoding="utf-8").splitlines()
            entries = [l for l in lines if re.match(r"\s*[-*] \[", l)]
            if len(entries) < len([l for l in lines if l.strip()]) // 2:
                sources.append((f"memory/{slug}/MEMORY-notes.md", idx))
                entries.append(f"- [{slug} notes](MEMORY-notes.md) — older notes kept in the index file")
            index.append(f"\n## {slug}\n")
            for line in entries:
                index.append(re.sub(r"\]\(([^)/]+\.md)\)", rf"]({slug}/\1)", line) + "\n")

    # skills, agents, commands
    for cat, sub in (("skills", "skills"), ("agents", "agents"), ("commands", "commands")):
        names = selected([e["name"] for e in inv[cat]], cfg.include[cat])
        for name in names:
            root = (cfg.claude_dir / sub / name).resolve()
            if root.is_file():
                sources.append((f"{sub}/{name}", root))
            else:
                for f in walk_files(root):
                    sources.append((f"{sub}/{name}/{f.relative_to(root).as_posix()}", f))

    if cfg.include["claude_md"] and (cfg.claude_dir / "CLAUDE.md").exists():
        sources.append(("personal/CLAUDE.md", cfg.claude_dir / "CLAUDE.md"))
    for extra in cfg.include["extra_files"]:
        p = Path(os.path.expanduser(extra))
        p = p if p.is_absolute() else cfg.claude_dir / extra
        if p.is_file():
            sources.append((f"personal/{Path(extra).name}", p))

    for rel, src in sources:
        if path_matches(rel, ALWAYS_EXCLUDE):
            report.excluded.append((rel, "always-excluded"))
            continue
        hit = path_matches(rel, cfg.paths)
        if hit:
            report.excluded.append((rel, f"path:{hit}"))
            continue
        text = is_text(src)
        if text is None:
            if src.suffix.lower() in BINARY_OK:
                files[rel] = src.read_bytes()
            else:
                report.excluded.append((rel, "binary"))
            continue
        files[rel] = flt.text(rel, text).encode("utf-8")

    if mem_dirs:
        kept_index = []
        for line in index:
            target = re.search(r"\]\(([^)]+\.md)\)", line)
            if target and f"memory/{target.group(1)}" not in files:
                continue  # entry points at an excluded file
            kept_index.append(line)
        files["memory/MEMORY.md"] = flt.text("memory/MEMORY.md", "".join(kept_index)).encode("utf-8")

    report.included = sorted(files)
    return files, report


def guard(files: dict, cfg: Config) -> list[str]:
    """Final check on the output: no keyword, provider secret or literal key may survive."""
    kws = [re.compile(k[3:], re.I) if k.startswith("re:") else re.compile(re.escape(k), re.I) for k in cfg.keywords]
    problems = []
    for rel, data in files.items():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if any(rx.search(line) for rx in kws):
                problems.append(f"keyword {rel}:{n}")
            if any(rx.search(line) for rx in SECRET_PATTERNS) or PRIVATE_KEY.search(line):
                problems.append(f"secret {rel}:{n}")
            for m in KEY_VALUE.finditer(line):
                if any(c.isdigit() for c in m.group(2)) and m.group(2) != "<redacted>":
                    problems.append(f"literal-key {rel}:{n}")
    return problems


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_delta(files: dict, out: Path) -> dict:
    old = {}
    mf = out / MANIFEST
    if mf.exists():
        old = json.loads(mf.read_text(encoding="utf-8")).get("files", {})
    new = {rel: sha(data) for rel, data in files.items()}
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(r for r in set(new) & set(old) if new[r] != old[r]),
        "first_export": not old,
    }


def write_bundle(files: dict, out: Path) -> None:
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".usta-", dir=out.parent))
    try:
        for rel, data in files.items():
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        manifest = {
            "tool": "usta",
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": {rel: sha(data) for rel, data in files.items()},
        }
        (tmp / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        if out.exists():
            shutil.rmtree(out)
        tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ---------------------------------------------------------------- output

def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def print_report(report: Report, files: dict, as_json: bool) -> None:
    size = sum(len(d) for d in files.values())
    if as_json:
        print(json.dumps({
            "included_files": len(report.included),
            "bytes": size,
            "removed_lines": report.removed_lines,
            "masked_values": report.masked_values,
            "pii_redacted": report.pii_redacted,
            "excluded": [{"path": p, "reason": r} for p, r in report.excluded],
            "flags": [{"path": p, "line": n, "kind": k, "preview": v} for p, n, k, v in report.flags],
            "delta": report.delta,
            "included": report.included,
        }, ensure_ascii=False, indent=1))
        return
    tops: dict[str, int] = {}
    for rel in report.included:
        parts = rel.split("/")
        top = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
        tops[top] = tops.get(top, 0) + 1
    print(f"Going to the cloud computer: {len(report.included)} files, {human_bytes(size)}")
    for top, count in sorted(tops.items()):
        print(f"  {top}  ({count})")
    print(f"\nLines removed by your keywords: {report.removed_lines}")
    print(f"Secret values masked: {report.masked_values}")
    if report.pii_redacted:
        print(f"Personal data redacted: {report.pii_redacted}")
    if report.excluded:
        reasons: dict[str, int] = {}
        for _, r in report.excluded:
            reasons[r] = reasons.get(r, 0) + 1
        print("\nLeft out:")
        for r, c in sorted(reasons.items()):
            print(f"  {r}: {c} file(s)")
    if report.flags:
        print(f"\nNeeds your review ({len(report.flags)}):")
        for p, n, k, v in report.flags[:50]:
            print(f"  [{k}] {p}:{n}  {v}")
        if len(report.flags) > 50:
            print(f"  ... {len(report.flags) - 50} more (use --json)")
        print("  Resolve by adding a keyword or path to [exclude], an exception to [pii] allow,")
        print("  or rerun with --accept-flags to keep these lines.")
    d = report.delta
    if d and not d.get("first_export"):
        print(f"\nSince last export: +{len(d['added'])} added, ~{len(d['changed'])} changed, -{len(d['removed'])} removed")


# ---------------------------------------------------------------- init

def toml_list(values: list) -> str:
    return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"


def write_config(path: Path, data: dict) -> None:
    inc = data.get("include", {})
    exc = data.get("exclude", {})
    pii = data.get("pii", {})
    lines = [
        "# usta export configuration. Personal: keep it out of any repo.",
        "",
        "[source]",
        f"claude_dir = {json.dumps(data.get('source', {}).get('claude_dir', '~/.claude'))}",
        "",
        "[include]",
    ]
    for k in CATEGORIES:
        lines.append(f"{k} = {toml_list(inc.get(k, []))}")
    lines += [
        f"claude_md = {'true' if inc.get('claude_md') else 'false'}",
        f"extra_files = {toml_list(inc.get('extra_files', []))}",
        "",
        "[exclude]",
        f"keywords = {toml_list(exc.get('keywords', []))}",
        f"paths = {toml_list(exc.get('paths', []))}",
        f"presets = {toml_list(exc.get('presets', []))}",
        "",
        "[pii]",
        f"mode = {json.dumps(pii.get('mode', 'flag'))}",
        f"allow = {toml_list(pii.get('allow', []))}",
        "",
    ]
    names = inc.get("memory_names", {})
    if names:
        lines.append("[include.memory_names]")
        lines += [f"{json.dumps(k)} = {json.dumps(v)}" for k, v in names.items()]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def pick(label: str, entries: list) -> list:
    if not entries:
        return []
    print(f"\n{label}:")
    for i, e in enumerate(entries, 1):
        extra = f", {e['files']} files" if "files" in e else ""
        print(f"  {i:>2}. {e['name']}  ({human_bytes(e['bytes'])}{extra})")
    answer = input("Include which? [all / none / 1,3,5]: ").strip().lower()
    if answer in ("all", "*"):
        return ["*"]
    if answer in ("", "none", "0"):
        return []
    chosen = []
    for part in answer.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(entries):
            chosen.append(entries[int(part) - 1]["name"])
    return chosen


def cmd_init(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        write_config(cfg_path, data)
        print(f"wrote {cfg_path}")
        return 0
    claude_dir = Path(os.path.expanduser(args.claude_dir)).resolve()
    inv = inventory(claude_dir)
    print("Nothing goes to the cloud computer unless you pick it here.")
    data = {"source": {"claude_dir": str(args.claude_dir)}, "include": {}, "exclude": {}, "pii": {}}
    labels = {"memory_projects": "Memory folders", "skills": "Skills", "agents": "Agents", "commands": "Commands"}
    for cat in CATEGORIES:
        data["include"][cat] = pick(labels[cat], inv[cat])
    presets = load_presets()
    print("\nWhat must never go? Categories:", ", ".join(presets))
    chosen = [p.strip() for p in input("Categories to watch [e.g. work,health]: ").split(",") if p.strip() in presets]
    data["exclude"]["presets"] = chosen
    kws = input("Words that must never go (company, client, people; comma-separated): ")
    data["exclude"]["keywords"] = [k.strip() for k in kws.split(",") if k.strip()]
    write_config(cfg_path, data)
    print(f"\nwrote {cfg_path}. Next: usta_export.py build --dry-run")
    return 0


# ---------------------------------------------------------------- main

def cmd_inventory(args: argparse.Namespace) -> int:
    inv = inventory(Path(os.path.expanduser(args.claude_dir)).resolve())
    if args.json:
        print(json.dumps(inv, indent=1))
        return 0
    for cat in CATEGORIES:
        print(f"{cat} ({len(inv[cat])}):")
        for e in inv[cat]:
            extra = f", {e['files']} files" if "files" in e else ""
            print(f"  {e['name']}  ({human_bytes(e['bytes'])}{extra})")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"usta: {cfg_path} not found. Run `usta_export.py init` first.", file=sys.stderr)
        return 2
    cfg = load_config(cfg_path)
    out = Path(args.out)
    files, report = plan_bundle(cfg)
    report.delta = compute_delta(files, out)
    problems = guard(files, cfg)
    print_report(report, files, args.json)
    if problems:
        print("\nSTOPPED: these survived filtering and would leave your machine:", file=sys.stderr)
        print("\n".join(problems[:50]), file=sys.stderr)
        return 1
    if args.dry_run or not args.approve:
        if not args.json:
            print("\nDry run: nothing written. Rerun with --approve to build.")
        return 0
    if report.flags and not args.accept_flags:
        print("\nNot built: review the flagged lines first (or pass --accept-flags).", file=sys.stderr)
        return 3
    write_bundle(files, out)
    if not args.json:
        print(f"\nBundle written to {out.resolve()}")
    return 0


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="usta_export.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default="exclude.local.toml", help="personal config (default: ./exclude.local.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inventory", help="list what could be exported")
    p.add_argument("--claude-dir", default="~/.claude")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("init", help="create your personal config")
    p.add_argument("--claude-dir", default="~/.claude")
    p.add_argument("--from-json", help="write config from a JSON answer file (for agents)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("build", help="preview or build the bundle")
    p.add_argument("--out", default="bundle")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    mode.add_argument("--approve", action="store_true", help="write the bundle")
    p.add_argument("--accept-flags", action="store_true", help="keep flagged lines as they are")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_build)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
