#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

now_stamp() {
  date "+%Y%m%d-%H%M%S"
}

ensure_repo() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return
  fi

  if git init -b main >/dev/null 2>&1; then
    :
  else
    git init >/dev/null
    git branch -M main >/dev/null 2>&1 || true
  fi
}

ensure_identity() {
  if ! git config user.name >/dev/null 2>&1; then
    git config user.name "hogue-ide-local"
  fi
  if ! git config user.email >/dev/null 2>&1; then
    git config user.email "hogue-ide@local"
  fi
}

has_uncommitted_changes() {
  if ! git diff --quiet || ! git diff --cached --quiet; then
    return 0
  fi
  if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    return 0
  fi
  return 1
}

save_snapshot() {
  local stamp="$1"
  local note="${2:-manual}"
  local stable_tag="stable/${stamp}"

  git add -A
  ensure_identity

  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    if git diff --cached --quiet; then
      echo "No staged changes. Reusing existing HEAD."
    else
      git commit -m "stable: ${stamp} ${note}" >/dev/null
    fi
  else
    if git diff --cached --quiet; then
      git commit --allow-empty -m "stable: ${stamp} initial-empty" >/dev/null
    else
      git commit -m "stable: ${stamp} initial" >/dev/null
    fi
  fi

  local commit
  commit="$(git rev-parse HEAD)"
  git tag -f stable/latest "${commit}" >/dev/null
  git tag -f "${stable_tag}" "${commit}" >/dev/null

  echo "Saved stable snapshot:"
  echo "  ${stable_tag} -> $(git rev-parse --short "${commit}")"
  echo "  stable/latest -> $(git rev-parse --short "${commit}")"
}

cmd="${1:-help}"
shift || true

case "${cmd}" in
  init)
    ensure_repo
    if git rev-parse --verify HEAD >/dev/null 2>&1; then
      echo "Git repo already initialized."
      if ! git rev-parse --verify stable/latest >/dev/null 2>&1; then
        git tag -f stable/latest HEAD >/dev/null
        echo "Created stable/latest -> HEAD"
      fi
      exit 0
    fi

    save_snapshot "$(now_stamp)" "bootstrap"
    ;;

  save)
    ensure_repo
    save_snapshot "$(now_stamp)" "${*:-manual}"
    ;;

  list)
    ensure_repo
    git for-each-ref \
      --sort=-creatordate \
      --format="%(refname:short)  %(objectname:short)  %(creatordate:short)  %(subject)" \
      refs/tags/stable || true
    ;;

  restore)
    ensure_repo
    ref="${1:-stable/latest}"
    if ! git rev-parse --verify "${ref}^{commit}" >/dev/null 2>&1; then
      echo "Unknown snapshot ref: ${ref}"
      exit 1
    fi

    if has_uncommitted_changes; then
      git stash push -u -m "auto-backup-before-restore-$(now_stamp)" >/dev/null || true
      echo "Stashed current in-progress changes before restore."
    fi

    git reset --hard "${ref}" >/dev/null
    git clean -fd >/dev/null
    echo "Restored working tree to ${ref} ($(git rev-parse --short "${ref}"))."
    ;;

  status)
    ensure_repo
    echo "Branch: $(git branch --show-current 2>/dev/null || echo detached)"
    echo "Head:   $(git rev-parse --short HEAD 2>/dev/null || echo none)"
    echo "Stable: $(git rev-parse --short stable/latest 2>/dev/null || echo missing)"
    echo
    git status --short
    ;;

  help|*)
    cat <<'EOF'
Usage: scripts/stable-version.sh <command> [args]

Commands:
  init                 Initialize git and create first stable snapshot.
  save [note]          Save current state as stable/<timestamp> and update stable/latest.
  list                 List saved stable snapshots.
  restore [ref]        Restore to a snapshot (default: stable/latest).
  status               Show current branch/head/stable pointer and working tree status.
EOF
    ;;
esac
