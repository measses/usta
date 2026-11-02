#!/usr/bin/env bash
# usta setup: install or refresh Claude Code on Grok Bot's cloud computer.
# Idempotent: run it again after a reset, a rollback or a new bundle.
#
# Run from a checkout of the usta release:  bash <kit>/bin/setup.sh
#
# Secrets (env vars or $USTA_ROOT/secrets/<NAME>, never printed):
#   CLAUDE_CODE_OAUTH_TOKEN  your own Claude subscription, from `claude setup-token`
#   GH_TOKEN                 fine-grained PAT: repos in repos.txt, Contents read/write
#   BUNDLE_TOKEN             optional, fine-grained PAT: your bundle repo, Contents read-only
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=bin/_lib.sh
source "$KIT/bin/_lib.sh"
usta_load_env

export CLAUDE_CONFIG_DIR="$USTA_ROOT/claude-config"
GIT_BASE="${USTA_GIT_BASE:-https://github.com}"
REPOS_FILE="${USTA_REPOS_FILE:-$USTA_ROOT/repos.txt}"
BIN="$HOME/.local/bin"
log() { printf '[usta] %s\n' "$*"; }

mkdir -p "$USTA_ROOT"/{repos,logs,secrets} "$CLAUDE_CONFIG_DIR" "$BIN"
chmod 700 "$USTA_ROOT/secrets"
usta_secret CLAUDE_CODE_OAUTH_TOKEN
usta_secret GH_TOKEN
usta_secret BUNDLE_TOKEN
usta_git_auth

# 1. PATH and config dir for future shells
for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  # shellcheck disable=SC2016  # $HOME/$PATH must stay literal in the rc file
  grep -q '# usta PATH' "$rc" 2>/dev/null || printf '\n# usta PATH\nexport PATH="$HOME/.local/bin:$PATH"\nexport USTA_ROOT="%s"\nexport CLAUDE_CONFIG_DIR="%s"\n' \
    "$USTA_ROOT" "$CLAUDE_CONFIG_DIR" >> "$rc"
done
export PATH="$BIN:$PATH"

# 2. Claude Code, official installer, user space
if ! command -v claude >/dev/null 2>&1; then
  if [[ -n "${USTA_SKIP_INSTALL:-}" ]]; then log "claude not found and USTA_SKIP_INSTALL set"; exit 1; fi
  log "installing Claude Code"
  curl -fsSL https://claude.ai/install.sh | bash
fi
log "claude $(claude --version 2>/dev/null | head -1)"

# 3. Bundle (optional): your exported memory/skills/agents from a private repo
BUNDLE="${USTA_BUNDLE_DIR:-}"
if [[ -z "$BUNDLE" && -n "${USTA_BUNDLE_REPO:-}" ]]; then
  src="$USTA_ROOT/bundle-src"
  export GIT_TOKEN="${BUNDLE_TOKEN:-${GH_TOKEN:-}}"
  if [[ -d "$src/.git" ]]; then
    usta_git -C "$src" pull -q --ff-only
  else
    rm -rf "$src"
    usta_git clone -q --depth 1 --filter=blob:none --sparse "$GIT_BASE/$USTA_BUNDLE_REPO.git" "$src" 2>/dev/null \
      || usta_git clone -q --depth 1 --sparse "$GIT_BASE/$USTA_BUNDLE_REPO.git" "$src"
    usta_git -C "$src" sparse-checkout set "${USTA_BUNDLE_PATH:-bundle}"
  fi
  BUNDLE="$src/${USTA_BUNDLE_PATH:-bundle}"
fi

# 4. Claude config: the bundle replaces its folders wholesale
for d in memory skills agents commands personal; do
  rm -rf "${CLAUDE_CONFIG_DIR:?}/$d"
  if [[ -n "$BUNDLE" && -d "$BUNDLE/$d" ]]; then cp -R "$BUNDLE/$d" "$CLAUDE_CONFIG_DIR/$d"; fi
done
mkdir -p "$CLAUDE_CONFIG_DIR/skills"

imports=""
[[ -f "$CLAUDE_CONFIG_DIR/memory/MEMORY.md" ]] && imports+="@memory/MEMORY.md"$'\n'
if [[ -d "$CLAUDE_CONFIG_DIR/personal" ]]; then
  for f in "$CLAUDE_CONFIG_DIR"/personal/*.md; do
    [[ -f "$f" ]] && imports+="@personal/$(basename "$f")"$'\n'
  done
fi
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" == "<!-- usta:imports -->" ]]; then printf '%s' "$imports"; else printf '%s\n' "$line"; fi
done < "$KIT/templates/CLAUDE.md" > "$CLAUDE_CONFIG_DIR/CLAUDE.md"

cat > "$CLAUDE_CONFIG_DIR/settings.json" <<EOF
{
  "permissions": {
    "deny": [
      "Bash(git push:*)",
      "Bash(printenv:*)",
      "Bash(env)",
      "Read(/$USTA_ROOT/secrets/**)"
    ]
  }
}
EOF

# 5. Anthropic's public document skills (no auth)
skills="${USTA_ANTHROPIC_SKILLS-docx pdf pptx xlsx skill-creator}"
if [[ -n "$skills" ]]; then
  tmp="$(mktemp -d)"
  if command git clone -q --depth 1 https://github.com/anthropics/skills.git "$tmp/as" 2>/dev/null; then
    for s in $skills; do
      found="$(find "$tmp/as" -path "*/$s/SKILL.md" | head -1)"
      [[ -n "$found" ]] && rm -rf "${CLAUDE_CONFIG_DIR:?}/skills/$s" && cp -R "$(dirname "$found")" "$CLAUDE_CONFIG_DIR/skills/$s"
    done
  else
    log "anthropics/skills not reachable, document skills skipped"
  fi
  rm -rf "$tmp"
fi

# 6. Command shims (point at this kit)
for cmd in usta-run usta-push; do
  printf '#!/usr/bin/env bash\nexport USTA_ROOT="%s"\nexec "%s/bin/%s" "$@"\n' "$USTA_ROOT" "$KIT" "$cmd" > "$BIN/$cmd"
  chmod 755 "$BIN/$cmd"
done

# 7. Repos from repos.txt (owner/name per line)
if [[ -n "${USTA_GIT_NAME:-}" ]]; then git config --global user.name "$USTA_GIT_NAME"; fi
if [[ -n "${USTA_GIT_EMAIL:-}" ]]; then git config --global user.email "$USTA_GIT_EMAIL"; fi
export GIT_TOKEN="${GH_TOKEN:-}"
if [[ -f "$REPOS_FILE" ]]; then
  while read -r full _; do
    [[ -z "$full" || "$full" == \#* ]] && continue
    name="${full#*/}"
    if [[ -d "$USTA_ROOT/repos/$name/.git" ]]; then
      usta_git -C "$USTA_ROOT/repos/$name" fetch -q origin || log "fetch failed: $full"
    elif usta_git clone -q "$GIT_BASE/$full.git" "$USTA_ROOT/repos/$name"; then
      log "cloned $full"
    else
      log "clone failed: $full"
    fi
  done < "$REPOS_FILE"
else
  log "no repos file at $REPOS_FILE"
fi

# 8. Checks
log "egress: $(usta_country_ok || true)"
if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  out="$(cd "$USTA_ROOT" && claude -p "Reply with exactly: OK" --output-format json 2>/dev/null || true)"
  if grep -q '"result": *"OK"' <<<"$out"; then log "claude test: OK"; else log "claude test failed (output not logged)"; fi
else
  log "CLAUDE_CODE_OAUTH_TOKEN not set, claude test skipped"
fi
count() { find "$1" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' '; }
log "skills: $(count "$CLAUDE_CONFIG_DIR/skills"), agents: $(count "$CLAUDE_CONFIG_DIR/agents"), repos: $(count "$USTA_ROOT/repos")"
log "done"
