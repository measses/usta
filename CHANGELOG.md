# Changelog

## v0.1.1 (2026-11-02)

Fixes from the first real run on a Grok Bot cloud computer.

- **Export: no more sentence fragments.** In markdown, a keyword now removes the whole paragraph or list item (with its wrapped lines and nested items), not just the matching line. Before, a wrapped sentence could leave its second half behind. Front matter, headings and table rows stay line-level.
- **Setup: no shared-state changes.** The git identity (`USTA_GIT_NAME`/`USTA_GIT_EMAIL`) is set per cloned repo instead of globally, and only a PATH line is added to `~/.bashrc`/`~/.profile`. The `USTA_ROOT`/`CLAUDE_CONFIG_DIR` exports written by v0.1.0 are removed automatically.
- **New `usta-claude` shim:** runs `claude` with usta's config, without touching other tools.

## v0.1.0 (2026-11-02)

First release: opt-in export with keyword/section/path exclusion, secret masking and personal-data review; `setup.sh`, `usta-run`, `usta-push`; AGENTS.md install protocol.
