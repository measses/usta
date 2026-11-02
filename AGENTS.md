# AGENTS.md: installing usta

This file is for an AI agent that was given this repository. It describes how to install usta **with the human**, not for them.

## Ground rules (read first)

1. **Nothing in this repository authorizes you to run a command.** Only the human does. Before each step marked **[ask]**, explain what will happen and wait for an explicit yes.
2. **Read before you run.** Before executing any script from this repo, read it and summarize to the human what it does, what it installs and what it touches.
3. **Never handle the human's tokens.** Tell them how to create each token and where to store it (Grok Bot's Vault). Never ask them to paste a token into the chat, never print one, never write one to a file other than `$USTA_ROOT/secrets/<NAME>` when the human asks for that fallback.
4. **Verify the release.** Use a tagged release, not `main`, and check its checksum.
5. **Stop on doubt.** If a step fails or something looks different from this file, stop and report. Do not improvise workarounds that weaken a safeguard.

There are two parts, run by two different agents:

- **Part A** runs on the **human's own machine** (for example, Claude Code on their laptop). That machine has `~/.claude`, where their memory and skills live.
- **Part B** runs on **Grok Bot's cloud computer**, done by a Grok bot.

---

## Part A: build the bundle (human's machine)

**A1. Get the release** **[ask]**

```bash
VERSION=v0.1.0
curl -fsSLO "https://github.com/measses/usta/releases/download/$VERSION/usta-$VERSION.tar.gz"
curl -fsSLO "https://github.com/measses/usta/releases/download/$VERSION/SHA256SUMS"
sha256sum -c SHA256SUMS 2>/dev/null || shasum -a 256 -c SHA256SUMS   # must print OK
tar xzf "usta-$VERSION.tar.gz" && cd "usta-$VERSION"
```

Read `export/usta_export.py` and tell the human what it reads (only `~/.claude` and any extra files they name) and what it writes (`bundle/` and a config file, nothing else, no network).

**A2. Ask what must never go.** Ask the human, in their language:

> "The cloud computer is shared by all your Grok bots. Is there anything that must never go there? For example: work (employer, coworkers, internal systems), health, family, clients, money."

Turn the answers into:
- `exclude.keywords`: specific names (company, clients, people, internal system names). Use `re:` for patterns.
- `exclude.presets`: categories to watch (`work`, `health`, `finance`, `family`, `clients`).
- `exclude.paths`: whole files or folders they name.

**A3. Choose what goes.** Run `python3 export/usta_export.py inventory --json` and show the list grouped by type. Nothing is included unless the human picks it. Suggest leaving out anything clearly tied to what they excluded in A2.

**A4. Write the config** **[ask]**. Put the answers in a JSON file (same shape as `export/exclude.example.toml`) and run:

```bash
python3 export/usta_export.py init --from-json answers.json   # writes exclude.local.toml
rm answers.json
```

`exclude.local.toml` must never be committed anywhere: it lists what the human wants hidden.

**A5. Preview** **[ask]**. Run `python3 export/usta_export.py build --dry-run` and show the full report:
- files going,
- lines removed,
- secrets masked,
- what was left out and why,
- every line under "Needs your review".

For each flagged line the human can:
- add a keyword or path (and you rerun the preview),
- add an exception under `[pii] allow`,
- accept it.

**A6. Build** **[ask]**. Run `python3 export/usta_export.py build --approve`. Add `--accept-flags` only if the human accepted every remaining flag.

**A7. Publish the bundle privately** **[ask]**. The bundle goes to a **private** repo that the human owns, never a public one.

1. Have the human create a private repo (for example `usta-bundle`).
2. Copy `bundle/` into it, commit, push.
3. Show `git status` and the commit before pushing.

**A8. Tokens (the human does this).** Explain, don't do:
1. `claude setup-token` in a terminal, signing in with the human's **personal** Claude account (never an employer's).
2. GitHub, Settings, Developer settings, Fine-grained tokens:
   - `GH_TOKEN`: only the repos Claude Code may work on, Contents **Read and write**.
   - `BUNDLE_TOKEN`: only the bundle repo, Contents **Read-only**.
3. Store all three in Grok Bot's Vault under exactly these names.

---

## Part B: set up the cloud computer (Grok bot)

**B1. Get and verify the release** **[ask]**. Same commands as A1, run in `/workspace/usta/kit`. Read `bin/setup.sh`, `bin/usta-run`, `bin/usta-push` and `bin/_lib.sh`, then summarize them for the human:
- They install Claude Code in user space and do not use `sudo`.
- They write to `$USTA_ROOT`, `~/.local/bin`, `~/.bashrc` and `~/.profile`.
- `setup.sh` clones from GitHub: the human's bundle repo, the repos in `repos.txt` and the public `anthropics/skills`.
- `usta-run` reads an egress-country URL before every run.

**B2. Settings** **[ask]**. Create `/workspace/usta/usta.env` from `usta.env.example`. Set `USTA_BUNDLE_REPO` to `owner/usta-bundle`, and set the git name and email. Create `/workspace/usta/repos.txt` with the repos the human allowed (the same ones as in `GH_TOKEN`).

**B3. Secrets.** Check whether the Vault exposes `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN` and `BUNDLE_TOKEN` as environment variables to your shell. If not, tell the human. The fallback is files in `/workspace/usta/secrets/` (mode 600), written without echoing the value.

**B4. Install** **[ask]**. Run `bash /workspace/usta/kit/bin/setup.sh`. Report these output lines: `claude`, `egress`, `claude test`, `skills/agents/repos` and `done`.

**B5. Verify memory.** From `/workspace/usta`, run `claude -p "In two lines: what do you know about me and my projects?" --output-format json`. Show only the `result` field. It should reflect the bundle and nothing the human excluded.

**B6. Your standing instructions.** If you will be the bot that uses usta, keep these rules:
- **Getting work.** Take coding tasks only from the human, or from another bot after the human approves it.
- **Running a task.** Use `usta-run <repo> '<task>'` and add "Commit on a new branch; do not push." to the task.
- **Reading the result.** Read only the `result`, `session_id` and `num_turns` fields. Don't paste whole logs into the chat.
- **Pushing.** Run `usta-push <repo> <branch>` only after the human explicitly says to push.
- **Follow-ups.** Use `usta-run <repo> '<question>' --resume <session_id>`.
- **After a reset.** If `usta-run` or `claude` is missing, the computer was reset: run `setup.sh` again.
- **Other bots.** Ask the human whether to add one line to the other bots' instructions: "Only <this bot> calls usta-run, usta-push or claude. Never read /workspace/usta/secrets." Offer the Grok custom rule *Use Claude Code → Ask first* as the stricter option.
