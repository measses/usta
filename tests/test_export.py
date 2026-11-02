"""Tests for export/usta_export.py against a fake ~/.claude tree."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "export"))
import usta_export as u  # noqa: E402

ANT_KEY = "sk-ant-api03-" + "A1b2C3d4" * 4
EVDS_LIKE = "aB3dE5fG7h"  # 10 chars, mixed case + digits: the case that slipped once


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def claude(tmp_path: Path) -> Path:
    c = tmp_path / "claude"
    mem = c / "projects" / "-Users-alice-code-shop" / "memory"
    write(mem / "MEMORY.md",
          "- [Shop stack](project_stack.md) — next.js\n"
          "- [Acme work](project_acme.md) — day job\n")
    write(mem / "project_stack.md",
          "Uses Next.js and Supabase.\n"
          "Deploy notes for Acme Corp staging.\n"
          f"TCMB_API_KEY={EVDS_LIKE} in .env\n"
          f"key {ANT_KEY}\n"
          "Write to ops@shop.example for alerts.\n"
          "IBAN GB82WEST12345698765432 for refunds.\n"
          "Order id 12345678901 is not an ID number.\n"
          "My wife likes the dark theme.\n")
    write(mem / "project_acme.md", "Acme Corp incident notes.\n")
    write(c / "projects" / "-Users-alice-work-secret" / "memory" / "notes.md", "work only\n")
    write(c / "projects" / "-Users-alice-code-shop" / "chat.jsonl", '{"msg": "transcript"}\n')
    write(c / "skills" / "good-skill" / "SKILL.md", "---\nname: good-skill\n---\nDo good things.\n")
    write(c / "skills" / "good-skill" / ".env", "OPENAI_API_KEY=sk-live-123456789012345678901234\n")  # gitleaks:allow (fake)
    write(c / "skills" / "good-skill" / "references" / "clients" / "acme.md", "client list\n")
    (c / "skills" / "good-skill" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (c / "skills" / "good-skill" / "data.sqlite").write_bytes(b"SQLite format 3\x00\x01")
    write(c / "skills" / "other-skill" / "SKILL.md", "other\n")
    write(c / "agents" / "reviewer.md", "Review code.\n")
    write(c / "agents" / "company-docs.md", "Writes Acme Corp decks.\n")
    write(c / "commands" / "plan.md", "Plan things.\n")
    write(c / "settings.json", '{"hooks": {}}\n')
    write(c / "CLAUDE.md", "Global rules.\n")
    return c


def config(tmp_path: Path, claude: Path, **over) -> Path:
    data = {
        "source": {"claude_dir": str(claude)},
        "include": {"memory_projects": [], "skills": [], "agents": [], "commands": []},
        "exclude": {"keywords": [], "paths": [], "presets": []},
        "pii": {"mode": "flag", "allow": []},
    }
    for section, values in over.items():
        data[section].update(values)
    path = tmp_path / "exclude.local.toml"
    u.write_config(path, data)
    return path


def plan(cfg_path: Path):
    return u.plan_bundle(u.load_config(cfg_path))


def test_nothing_included_by_default(tmp_path, claude):
    files, report = plan(config(tmp_path, claude))
    assert files == {}
    assert report.included == []


def test_inventory_lists_categories(claude):
    inv = u.inventory(claude)
    assert [m["name"] for m in inv["memory_projects"]] == ["-Users-alice-code-shop", "-Users-alice-work-secret"]
    assert [s["name"] for s in inv["skills"]] == ["good-skill", "other-skill"]
    assert {a["name"] for a in inv["agents"]} == {"reviewer.md", "company-docs.md"}


def test_globs_select_and_paths_exclude(tmp_path, claude):
    cfg = config(tmp_path, claude,
                 include={"memory_projects": ["*code*"], "skills": ["good-*"], "agents": ["reviewer.md"]},
                 exclude={"paths": ["skills/good-skill/references/**", "memory/*/project_acme.md"]})
    files, report = plan(cfg)
    assert "memory/shop/project_stack.md" in files
    assert not any("work-secret" in f for f in files)
    assert "skills/good-skill/SKILL.md" in files
    assert "skills/other-skill/SKILL.md" not in files
    assert "agents/reviewer.md" in files and "agents/company-docs.md" not in files
    assert not any("references/clients" in f for f in files)
    assert "memory/shop/project_acme.md" not in files
    # index entry for the excluded file is dropped too
    assert "project_acme" not in files["memory/MEMORY.md"].decode()
    reasons = dict(report.excluded)
    assert reasons["memory/shop/project_acme.md"].startswith("path:")


def test_keywords_remove_lines(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]}, exclude={"keywords": ["acme corp"]})
    files, report = plan(cfg)
    text = files["memory/shop/project_stack.md"].decode()
    assert "Acme" not in text
    assert "Next.js" in text
    assert report.removed_lines >= 2  # stack line + acme file line


def test_regex_keyword(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]}, exclude={"keywords": ["re:staging\\b"]})
    files, _ = plan(cfg)
    assert "staging" not in files["memory/shop/project_stack.md"].decode()


def test_secrets_masked_including_short_mixed_key(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]})
    files, report = plan(cfg)
    text = files["memory/shop/project_stack.md"].decode()
    assert EVDS_LIKE not in text
    assert ANT_KEY not in text
    assert "TCMB_API_KEY" in text  # name kept, value gone
    assert report.masked_values >= 2
    assert u.guard(files, u.load_config(cfg)) == []


def test_prose_api_key_lines_are_scanner_safe(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]})
    files, _ = plan(cfg)
    text = files["memory/shop/project_stack.md"].decode()
    assert "TCMB_API_KEY (value hidden)" in text


def test_pii_flag_mode_lists_valid_hits_only(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]})
    _, report = plan(cfg)
    kinds = {(p.split("/")[-1], k) for p, _, k, _ in report.flags}
    assert ("project_stack.md", "email") in kinds
    assert ("project_stack.md", "iban") in kinds
    assert not any(k == "national-id" for _, k in kinds)  # 12345678901 fails the checksum
    for _, _, _, preview in report.flags:
        assert "GB82WEST" not in preview and "ops@shop" not in preview


def test_pii_redact_mode(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]}, pii={"mode": "redact"})
    files, report = plan(cfg)
    text = files["memory/shop/project_stack.md"].decode()
    assert "<email>" in text and "<iban>" in text
    assert report.pii_redacted >= 2


def test_pii_allow_list(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]},
                 pii={"mode": "flag", "allow": ["ops@shop.example"]})
    _, report = plan(cfg)
    assert not any(k == "email" for _, _, k, _ in report.flags)


def test_validators():
    assert u.iban_ok("GB82WEST12345698765432") and not u.iban_ok("GB82WEST12345698765433")
    assert u.tckn_ok("10000000146") and not u.tckn_ok("12345678901")
    assert u.luhn_ok("4111 1111 1111 1111") and not u.luhn_ok("4111111111111112")
    assert not u.luhn_ok("0000000000000000")


def test_presets_flag_but_keep(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]}, exclude={"presets": ["family"]})
    files, report = plan(cfg)
    assert "My wife" in files["memory/shop/project_stack.md"].decode()
    assert any(k == "preset:family" for _, _, k, _ in report.flags)


def test_unknown_preset_rejected(tmp_path, claude):
    cfg = config(tmp_path, claude, exclude={"presets": ["nope"]})
    with pytest.raises(SystemExit):
        u.load_config(cfg)


def test_always_excluded_and_binaries(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"skills": ["good-skill"], "memory_projects": ["*code*"]})
    files, report = plan(cfg)
    reasons = dict(report.excluded)
    assert reasons["skills/good-skill/.env"] == "always-excluded"
    assert "skills/good-skill/logo.png" in files
    assert reasons["skills/good-skill/data.sqlite"] == "binary"
    assert not any(f.endswith(".jsonl") or "settings" in f for f in files)


def test_claude_md_opt_in(tmp_path, claude):
    files, _ = plan(config(tmp_path, claude))
    assert "personal/CLAUDE.md" not in files
    files, _ = plan(config(tmp_path, claude, include={"claude_md": True}))
    assert files["personal/CLAUDE.md"] == b"Global rules.\n"


def test_guard_catches_survivors(tmp_path, claude):
    cfg = u.load_config(config(tmp_path, claude, exclude={"keywords": ["Acme"]}))
    problems = u.guard({"a.md": b"Acme slipped through\n", "b.md": f"x {ANT_KEY}\n".encode()}, cfg)
    assert any(p.startswith("keyword a.md") for p in problems)
    assert any(p.startswith("secret b.md") for p in problems)


def test_dry_run_writes_nothing_and_approve_writes(tmp_path, claude, capsys):
    cfg = config(tmp_path, claude, include={"agents": ["reviewer.md"], "commands": ["*"]})
    out = tmp_path / "bundle"
    assert u.main(["--config", str(cfg), "build", "--dry-run", "--out", str(out)]) == 0
    assert not out.exists()
    assert u.main(["--config", str(cfg), "build", "--approve", "--out", str(out)]) == 0
    assert (out / "agents" / "reviewer.md").exists()
    manifest = json.loads((out / u.MANIFEST).read_text())
    assert "agents/reviewer.md" in manifest["files"]
    capsys.readouterr()


def test_flags_block_build_until_accepted(tmp_path, claude):
    cfg = config(tmp_path, claude, include={"memory_projects": ["*code*"]})
    out = tmp_path / "bundle"
    assert u.main(["--config", str(cfg), "build", "--approve", "--out", str(out)]) == 3
    assert not out.exists()
    assert u.main(["--config", str(cfg), "build", "--approve", "--accept-flags", "--out", str(out)]) == 0
    assert out.exists()


def test_delta_since_last_export(tmp_path, claude, capsys):
    cfg = config(tmp_path, claude, include={"agents": ["*"]})
    out = tmp_path / "bundle"
    u.main(["--config", str(cfg), "build", "--approve", "--out", str(out)])
    write(claude / "agents" / "reviewer.md", "Review code carefully.\n")
    write(claude / "agents" / "new.md", "New agent.\n")
    files, report = plan(cfg)
    delta = u.compute_delta(files, out)
    assert delta["added"] == ["agents/new.md"]
    assert delta["changed"] == ["agents/reviewer.md"]
    assert not delta["first_export"]
    capsys.readouterr()


def test_init_from_json_roundtrip(tmp_path, claude):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({
        "source": {"claude_dir": str(claude)},
        "include": {"skills": ["good-skill"], "memory_names": {"-Users-alice-code-shop": "shop"}},
        "exclude": {"keywords": ["Acme Corp"], "presets": ["work"]},
        "pii": {"mode": "redact"},
    }))
    cfg_path = tmp_path / "exclude.local.toml"
    assert u.main(["--config", str(cfg_path), "init", "--from-json", str(answers)]) == 0
    cfg = u.load_config(cfg_path)
    assert cfg.include["skills"] == ["good-skill"]
    assert cfg.keywords == ["Acme Corp"]
    assert cfg.pii_mode == "redact"
    assert cfg.memory_names == {"-Users-alice-code-shop": "shop"}


def test_heading_keyword_drops_whole_section(tmp_path, claude):
    write(claude / "BRAIN.md",
          "# Brain\n## Threads\n### Thread: Acme migration\nStatus: open\nStep 2 done.\n"
          "### Thread: Side project\nShip it.\n## Rules\nBe brief.\n")
    cfg = config(tmp_path, claude, include={"extra_files": [str(claude / "BRAIN.md")]},
                 exclude={"keywords": ["acme"]})
    files, report = plan(cfg)
    text = files["personal/BRAIN.md"].decode()
    assert "Acme" not in text and "Step 2 done" not in text and "Status: open" not in text
    assert "### Thread: Side project" in text and "Ship it." in text and "Be brief." in text
    assert report.removed_lines == 3


def test_preview_hides_other_values_on_the_line(tmp_path, claude):
    write(claude / "agents" / "two.md", "Contacts: a@one.example and b@two.example\n")
    cfg = config(tmp_path, claude, include={"agents": ["two.md"]})
    _, report = plan(cfg)
    previews = [v for _, _, k, v in report.flags if k == "email"]
    assert len(previews) == 2
    for v in previews:
        assert "a@one" not in v and "b@two" not in v


def test_card_ignores_timestamps_in_paths(tmp_path, claude):
    write(claude / "agents" / "ts.md", "backup at /root/deploy-before-4111111111111111.tar and card 4111 1111 1111 1111\n")
    cfg = config(tmp_path, claude, include={"agents": ["ts.md"]})
    _, report = plan(cfg)
    cards = [v for _, _, k, v in report.flags if k == "card"]
    assert len(cards) == 1 and "«…»" in cards[0]
