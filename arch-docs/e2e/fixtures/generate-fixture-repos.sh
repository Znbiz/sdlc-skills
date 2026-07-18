#!/usr/bin/env bash
# arch-docs/e2e/fixtures/generate-fixture-repos.sh
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output_dir=${1:-"${script_dir}/generated"}

mkdir -p "${output_dir}"

"${script_dir}/generate-repo.sh" "${output_dir}" svc-core 2025-01-15 1
"${script_dir}/generate-repo.sh" "${output_dir}" svc-billing 2025-03-01 2
"${script_dir}/generate-repo.sh" "${output_dir}" svc-notifications 2025-06-10 1

echo "fixture repos generated in ${output_dir}: svc-core (anchor, oldest created_at), svc-billing, svc-notifications"
