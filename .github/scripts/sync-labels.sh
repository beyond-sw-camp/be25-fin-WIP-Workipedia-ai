#!/usr/bin/env bash

set -euo pipefail

root_dir="$(git rev-parse --show-toplevel)"
labels_file="${LABELS_FILE:-${root_dir}/.github/labels.json}"
repository="${GH_REPO:-$(gh repo view --json nameWithOwner --jq '.nameWithOwner')}"

jq -c '.[]' "${labels_file}" | while IFS= read -r label; do
  name="$(jq -r '.name' <<<"${label}")"
  color="$(jq -r '.color' <<<"${label}")"
  description="$(jq -r '.description // ""' <<<"${label}")"

  gh label create "${name}" \
    --repo "${repository}" \
    --color "${color}" \
    --description "${description}" \
    --force
done

if [[ "${1:-}" == "--prune" ]]; then
  while IFS= read -r existing_label; do
    if ! jq -e --arg name "${existing_label}" '.[] | select(.name == $name)' "${labels_file}" >/dev/null; then
      gh label delete "${existing_label}" --repo "${repository}" --yes
    fi
  done < <(gh label list --repo "${repository}" --limit 1000 --json name --jq '.[].name')
fi
