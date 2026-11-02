# shellcheck shell=bash
# Shared helpers for setup.sh, usta-run and usta-push. Sourced, not executed.

USTA_ROOT="${USTA_ROOT:-/workspace/usta}"

# Non-secret settings: $USTA_ENV, else $USTA_ROOT/usta.env. Explicit env vars win.
usta_load_env() {
  local file="${USTA_ENV:-$USTA_ROOT/usta.env}" line key
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# || ! "$line" =~ = ]] && continue
    key="${line%%=*}"; key="${key// /}"
    [[ "$key" =~ ^USTA_[A-Z_]+$ ]] || continue          # only usta settings, never secrets
    [[ -n "${!key+x}" ]] && continue                      # already set in the environment
    local value="${line#*=}"
    value="${value%\"}"; value="${value#\"}"
    export "$key=$value"
  done < "$file"
}

# Secrets: env var first, then $USTA_ROOT/secrets/<NAME>. Never echoed.
usta_secret() {
  local name="$1"
  if [[ -z "${!name:-}" && -s "$USTA_ROOT/secrets/$name" ]]; then
    export "$name=$(tr -d '\r\n' < "$USTA_ROOT/secrets/$name")"
  fi
}

# git over HTTPS with the token in $GIT_TOKEN, written to no config file.
# System helpers (keychain, GCM) are bypassed so they cannot hang or leak.
usta_git_auth() {
  local askpass="$USTA_ROOT/.askpass"
  if [[ ! -x "$askpass" ]]; then
    mkdir -p "$USTA_ROOT"
    # shellcheck disable=SC2016  # expanded by the askpass script at run time
    printf '#!/bin/sh\ncase "$1" in Username*) echo x-access-token ;; *) echo "$GIT_TOKEN" ;; esac\n' > "$askpass"
    chmod 700 "$askpass"
  fi
  export GIT_ASKPASS="$askpass" GIT_TERMINAL_PROMPT=0
}

usta_git() { command git -c credential.helper= "$@"; }

usta_country() {
  curl -fsS --max-time 8 "${USTA_COUNTRY_URL:-https://ipinfo.io/country}" 2>/dev/null | tr -d '\r\n[:space:]' || true
}

# Prints a reason and returns 1 if runs must not happen from this egress.
usta_country_ok() {
  local country
  country="$(usta_country)"
  if [[ ! "$country" =~ ^[A-Z]{2}$ ]]; then
    echo "egress country unknown"
    return 1
  fi
  if [[ " ${USTA_BLOCKED_COUNTRIES:-CN HK MO RU BY IR KP SY CU} " == *" $country "* ]]; then
    echo "egress country $country is not supported by Claude"
    return 1
  fi
  echo "$country"
}
