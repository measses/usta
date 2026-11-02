#!/usr/bin/env bash
# shellcheck disable=SC2015  # ok() always succeeds, so `a && ok || fail` is safe here
# End-to-end test of setup.sh, usta-run and usta-push with a fake `claude`,
# local bare git repos and a file:// country lookup. No network needed.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
pass=0
ok()   { pass=$((pass + 1)); printf 'ok   %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; exit 1; }

FAKE_TOKEN="fake-oauth-token-$RANDOM$RANDOM"
mkdir -p "$T/home" "$T/fakebin" "$T/git/me"

# fake claude: records its arguments, answers like `claude -p --output-format json`
cat > "$T/fakebin/claude" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "--version" ]]; then echo "9.9.9 (Claude Code)"; exit 0; fi
printf '%s\n' "\$@" > "$T/claude-args"
pwd > "$T/claude-cwd"
echo '{"is_error": false, "result": "OK", "session_id": "s-1", "num_turns": 1}'
EOF
chmod +x "$T/fakebin/claude"

# bare repos: a work repo and a bundle repo
make_repo() {  # name, setup-commands
  local work="$T/src-$1"
  git init -q -b main "$work"
  (cd "$work" && eval "$2" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m init)
  git clone -q --bare "$work" "$T/git/me/$1.git"
}
make_repo proj 'echo hello > README.md'
make_repo bundles 'mkdir -p bundle/memory bundle/skills/s1 bundle/personal && echo "- [a](x/a.md)" > bundle/memory/MEMORY.md && echo skill > bundle/skills/s1/SKILL.md && echo rules > bundle/personal/RULES.md'

echo TR > "$T/country"
cat > "$T/usta.env" <<EOF
USTA_ROOT=$T/root
USTA_GIT_BASE=file://$T/git
USTA_BUNDLE_REPO=me/bundles
USTA_BUNDLE_PATH=bundle
USTA_REPOS_FILE=$T/repos.txt
USTA_COUNTRY_URL=file://$T/country
USTA_ANTHROPIC_SKILLS=
USTA_SKIP_INSTALL=1
EOF
echo "me/proj" > "$T/repos.txt"

run_env() {
  env -i HOME="$T/home" PATH="$T/fakebin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" \
    USTA_ROOT="$T/root" USTA_ENV="$T/usta.env" CLAUDE_CODE_OAUTH_TOKEN="$FAKE_TOKEN" GH_TOKEN="$FAKE_TOKEN" \
    "$@"
}

# --- setup.sh, twice (idempotent)
out1="$(run_env bash "$KIT/bin/setup.sh" 2>&1)" || { echo "$out1"; fail "setup run 1"; }
out2="$(run_env bash "$KIT/bin/setup.sh" 2>&1)" || { echo "$out2"; fail "setup run 2"; }
grep -q '\[usta\] done' <<<"$out2" && ok "setup.sh completes twice" || fail "setup output"
grep -q 'claude test: OK' <<<"$out2" && ok "setup runs the claude test" || fail "claude test line"
grep -q 'egress: TR' <<<"$out2" && ok "setup reports egress country" || fail "egress line"

C="$T/root/claude-config"
[[ -f "$C/skills/s1/SKILL.md" && -f "$C/memory/MEMORY.md" ]] && ok "bundle installed" || fail "bundle files"
grep -q '^@memory/MEMORY.md$' "$C/CLAUDE.md" && grep -q '^@personal/RULES.md$' "$C/CLAUDE.md" \
  && ok "CLAUDE.md imports bundle files" || fail "imports"
grep -q 'usta:imports' "$C/CLAUDE.md" && fail "placeholder left in CLAUDE.md" || ok "placeholder replaced"
[[ -d "$T/root/repos/proj/.git" ]] && ok "repo cloned" || fail "repo clone"
[[ -x "$T/home/.local/bin/usta-run" && -x "$T/home/.local/bin/usta-push" ]] && ok "command shims installed" || fail "shims"
[[ "$(grep -c '# usta PATH' "$T/home/.bashrc")" == 1 ]] && ok ".bashrc edited once" || fail ".bashrc"
if grep -rq "$FAKE_TOKEN" "$T/root" "$T/home" 2>/dev/null; then fail "token written to disk"; else ok "no token on disk"; fi

# --- usta-run
R="$T/home/.local/bin/usta-run"
expect_error() {  # label, expected text, args...
  local label="$1" text="$2"; shift 2
  local res
  res="$(run_env "$@" 2>&1 || true)"
  grep -q '"is_error": true' <<<"$res" && grep -q "$text" <<<"$res" && ok "$label" || { echo "$res"; fail "$label"; }
}
expect_error "run: usage" "usage" "$R"
expect_error "run: invalid repo" "invalid repo" "$R" "../x" "t"
expect_error "run: unknown repo" "no repo nope" "$R" nope "t"
expect_error "run: bad max-turns" "needs a number" "$R" proj "t" --max-turns x
res="$(env -i HOME="$T/home" PATH="$T/fakebin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" USTA_ROOT="$T/root" USTA_ENV="$T/usta.env" "$R" proj "t" 2>&1 || true)"
grep -q "CLAUDE_CODE_OAUTH_TOKEN not set" <<<"$res" && ok "run: needs token" || { echo "$res"; fail "token check"; }
echo CN > "$T/country"
expect_error "run: blocked country" "not supported" "$R" proj "t"
: > "$T/country"
expect_error "run: unknown country" "unknown" "$R" proj "t"
echo TR > "$T/country"

res="$(run_env "$R" proj "fix the readme" --max-turns 5 2>&1)"
grep -q '"result": "OK"' <<<"$res" && grep -q '"session_id": "s-1"' <<<"$res" && ok "run: success JSON" || { echo "$res"; fail "run success"; }
[[ "$(cat "$T/claude-cwd")" == "$T/root/repos/proj" ]] && ok "run: claude runs inside the repo" || fail "cwd"
args="$(cat "$T/claude-args")"
grep -qx -- "--allowedTools" <<<"$args" && grep -qx -- "--disallowedTools" <<<"$args" && ok "run: tool lists passed" || fail "tool args"
grep -q "Bash(git push:\*)" <<<"$args" && ok "run: push denied" || fail "deny list"
grep -qx "5" <<<"$args" && ok "run: max-turns passed" || fail "max-turns"
grep -q "$FAKE_TOKEN" <<<"$args" && fail "token in claude args" || ok "run: token not in args"
ls "$T/root/logs/"*-proj.json >/dev/null 2>&1 && ok "run: log written" || fail "log"

# --- usta-push
P="$T/home/.local/bin/usta-push"
if run_env "$P" proj main >/dev/null 2>&1; then fail "push main allowed"; else ok "push: main refused"; fi
if run_env "$P" proj "--force" >/dev/null 2>&1; then fail "push option-like branch allowed"; else ok "push: option-like branch refused"; fi
(cd "$T/root/repos/proj" && git switch -q -c usta/test && echo x >> README.md \
  && git -c user.name=t -c user.email=t@t commit -qam change)
run_env "$P" proj usta/test >/dev/null 2>&1 && git -C "$T/git/me/proj.git" rev-parse -q --verify usta/test >/dev/null \
  && ok "push: work branch pushed" || fail "push branch"

echo "all $pass checks passed"
