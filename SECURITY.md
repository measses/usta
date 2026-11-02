# Security model

usta puts a coding agent with your Claude subscription on a computer you don't fully control. This page lists what that means and what usta does about it.

## Threats and mitigations

**1. The cloud computer is shared by all your bots.**
Grok Bot gives one computer per account, not per bot. Any bot can read installed files and run installed tools.
- Upload as little as possible: export is opt-in, with your never-list, category flags and personal-data checks. Preview before every build.
- Secrets are read from the environment (Vault) or a mode-600 folder. They are never written to config, logs or the bundle.
- Restricting bots is up to you: add an instruction to the other bots, or the Grok custom rule *Use Claude Code → Ask first*. Instructions are not isolation.

**2. Prompt injection through repos, issues and web content.**
Text inside a repo can try to make Claude Code exfiltrate data or change settings.
- `CLAUDE.md` tells Claude Code to treat task text and repo content as data.
- Denied tools: `git push`, `git remote`, `curl`, `wget`, `ssh`, `scp`, `env`, `printenv`, `sudo`, `rm -rf`, and reading the secrets folder.
- **Residual risk:** `npm`, `node`, `python3` and `npx` are allowed, so a malicious script in a repo can still reach the network. Only list repos you own and trust. Tighten `USTA_ALLOWED_TOOLS` if you need to.

**3. Token theft.**
If the computer or a bot is compromised, the tokens on it can be read.
- Use fine-grained GitHub tokens: only the listed repos, Contents only, with an expiry. The bundle token is read-only.
- The Claude token is your subscription; revoke it from your Claude account if you suspect misuse.
- Pushes to protected branches are refused, and every push needs your approval in chat.

**4. Unsupported egress regions.**
The cloud computer's IP changes. `usta-run` checks the egress country before each run and refuses `USTA_BLOCKED_COUNTRIES`, or any country it cannot determine.

**5. Leaks during export.**
- Lines that match your keywords are removed. A matching markdown heading removes its whole section.
- Provider tokens (`sk-ant-`, `ghp_`, `github_pat_`, `xox*`, `AKIA`, `AIza`, `Bearer`) and literal `KEY=value` values are masked.
- Private-key lines are dropped.
- Settings, `.env*`, MCP configs, hooks, `*.jsonl` transcripts, credentials and non-media binaries are always skipped.
- A final guard re-scans the output and refuses to write the bundle if a keyword or secret survived.
- **Pattern matching has limits.** Read the dry-run report, and keep the bundle repo private.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository (Security, then Report a vulnerability). Please don't file public issues for vulnerabilities.
