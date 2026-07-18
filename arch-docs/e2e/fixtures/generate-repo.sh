#!/usr/bin/env bash
# arch-docs/e2e/fixtures/generate-repo.sh
#
# Генерирует git-репозиторий с историей за 12 месяцев, начиная с заданной даты,
# с заданным количеством коммитов в месяц (backdated через GIT_AUTHOR_DATE/
# GIT_COMMITTER_DATE) — используется как фикстура для e2e-проверки того, что
# init_arch (refresh_main_branches/plan_repository_order) корректно читает
# created_at/историю коммитов и это отражается в progress-снепшоте.
set -euo pipefail

target_dir=$1
repo_name=$2
start_date=$3
commits_per_month=$4

# Preflight: date-арифметика несовместима между macOS (BSD `date -v`) и Linux
# (GNU `date -d`). Проверяем, что хотя бы один вариант реально работает на
# этой машине, прежде чем генерировать историю — иначе коммиты получат
# пустую/неверную дату молча.
if date -u -j -v+0m -v+1d -f "%Y-%m-%d" "${start_date}" +"%Y-%m-%d" >/dev/null 2>&1; then
  date_style="bsd"
elif date -u -d "${start_date} +0 month +1 day" +"%Y-%m-%d" >/dev/null 2>&1; then
  date_style="gnu"
else
  echo "error: neither BSD (date -v) nor GNU (date -d) date arithmetic is supported on this host ($(uname -a))." >&2
  echo "generate-repo.sh cannot compute backdated commit dates here." >&2
  exit 1
fi

repo_path="${target_dir}/${repo_name}"
rm -rf "${repo_path}"
mkdir -p "${repo_path}"
cd "${repo_path}"

git init -q -b main
git config user.name "E2E Fixture Bot"
git config user.email "e2e-fixture-bot@example.invalid"

echo "# ${repo_name}" > README.md
git add README.md
GIT_AUTHOR_DATE="${start_date}T09:00:00" GIT_COMMITTER_DATE="${start_date}T09:00:00" \
  git commit -q -m "init: scaffold ${repo_name}"

month_offset=0
while [ "${month_offset}" -lt 12 ]; do
  commit_index=1
  while [ "${commit_index}" -le "${commits_per_month}" ]; do
    if [ "${date_style}" = "bsd" ]; then
      commit_date=$(date -u -j -v+"${month_offset}"m -v+"${commit_index}"d -f "%Y-%m-%d" "${start_date}" +"%Y-%m-%d")
    else
      commit_date=$(date -u -d "${start_date} +${month_offset} month +${commit_index} day" +"%Y-%m-%d")
    fi
    echo "change at ${commit_date}" >> "src-${repo_name}.log"
    git add "src-${repo_name}.log"
    GIT_AUTHOR_DATE="${commit_date}T09:00:00" GIT_COMMITTER_DATE="${commit_date}T09:00:00" \
      git commit -q -m "feat(${repo_name}): change ${month_offset}-${commit_index}"
    commit_index=$((commit_index + 1))
  done
  month_offset=$((month_offset + 1))
done

echo "generated ${repo_name}: $(git -C "${repo_path}" log --oneline | wc -l | tr -d ' ') commits, first $(git -C "${repo_path}" log --reverse --format=%cd --date=short | head -1)"
