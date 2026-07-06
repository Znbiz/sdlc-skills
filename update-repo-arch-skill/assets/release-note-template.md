# Release notes — <YYYY-MM-DD>

**Baseline:** диапазон коммитов прогона в целом, если применимо — иначе baseline указан по каждому репозиторию в таблице ниже.

## Что изменилось

- [architecture/integrations/<service>.md](../architecture/integrations/<service>.md) — <короткое описание изменения>
- [architecture/contracts/<service>-sync.yml](../architecture/contracts/<service>-sync.yml) — <короткое описание изменения>

## Затронутые репозитории

| Репозиторий | Классификация | Затронутые категории | Baseline |
|---|---|---|---|
| <repo> | <minor\|significant> | <contracts_and_schemas, data_and_storage, ...> | `<previous_baseline_commit>` → `<new_baseline_commit>` |

## Репозитории без изменений

| Репозиторий | Baseline |
|---|---|
| <repo> | `<commit>` (без изменений) |

## Каскадные эффекты

| Источник | Цель | Причина | Статус |
|---|---|---|---|
| <repo-A> | <repo-B / артефакт> | <почему затронут> | <закрыт без правок / обновлён / вне scope> |

## Новые пробелы

- <описание> — см. `open-questions.md#<id>`

## Репозитории с невалидным baseline (требуют полного пересмотра)

- <repo> — <причина: force-push/rebase/иное>

## Следующий рекомендуемый шаг

<resume_hint из update-progress.json перед его удалением>
