# E2E fixture repos

Генерируются `generate-fixture-repos.sh` — три синтетических git-репозитория
с backdated-историей за 12 месяцев, использующиеся в `tests/init-arch-snapshot.spec.ts`
для проверки, что `init_arch` (`refresh_main_branches`/`plan_repository_order`)
корректно читает реальную git-историю и что это видно в `repo-initialization-progress.yaml`.

Пересоздать: `./generate-fixture-repos.sh [output-dir]` (по умолчанию `./generated`,
директория в `.gitignore` — фикстуры не коммитятся, генерируются перед прогоном e2e).

- `svc-core` — первый коммит `2025-01-15`, 1 коммит/месяц. Самый старый `created_at` →
  ожидаемый anchor repository в `plan_repository_order`.
- `svc-billing` — первый коммит `2025-03-01`, 2 коммита/месяц.
- `svc-notifications` — первый коммит `2025-06-10`, 1 коммит/месяц.
