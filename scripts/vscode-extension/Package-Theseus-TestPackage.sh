#!/usr/bin/env bash
set -euo pipefail

script_path="${BASH_SOURCE[0]}"
case "$script_path" in
  */*) script_dir="${script_path%/*}" ;;
  *) script_dir="." ;;
esac
# 이 wrapper는 scripts/vscode-extension/에 있으므로 저장소 루트는 두 단계 위입니다.
repo_dir="$(cd -- "$script_dir/../.." && pwd)"
packager="$repo_dir/backend/theseus-core-server/scripts/package-test-distribution.sh"

if [[ ! -f "$packager" ]]; then
  echo "Theseus test package builder was not found." >&2
  echo "" >&2
  echo "Expected:" >&2
  echo "  $packager" >&2
  exit 1
fi

case "${1:-}" in
  -h|--help)
    "$BASH" "$packager" --help
    exit $?
    ;;
esac

echo "Theseus test package build"
echo "Repository: $repo_dir"
echo "Packager  : $packager"
echo ""

"$BASH" "$packager" --build-vsix "$@"

echo ""
echo "Theseus test package build complete."
