# Gap Analysis: temporal diff contract for `init_arch`

## Что есть сейчас

Текущий backend в `arch-docs` умеет:

- выбрать `anchor_repository_name` и `current_snapshot_at`;
- отсортировать `ordered_repository_names` по `created_at`;
- для каждого репозитория найти `snapshot commit` не позже `snapshot_date`;
- при необходимости checkout-нуть `.temp/<repo>` на найденный commit;
- пропустить workflow дальше, если snapshot-state выглядит завершённым.

Это даёт корректный снимок состояния, но не даёт нормализованной дельты текущего окна.

## Что считается разрывом

Сервис пока не хранит и не валидирует как first-class state:

- `previous_snapshot_commit`
- `window_start_commit`
- `window_end_commit`
- `commit_range`
- `diff_stat_summary`
- `changed_paths`
- `commit_log_summary`

Следствие: `historical_prep_is_complete()` сейчас подтверждает только snapshot gate, а downstream analysis ещё может стартовать без range/diff context.

## Зафиксированный target contract

Temporal analysis для `init_arch` должен считаться завершённым только когда для окна подготовлены обе части:

1. `snapshot-state`
2. `temporal-delta`

Нормативные правила:

- для любого окна после первого анализ идёт по паре `snapshot_commit` + `changes since previous snapshot`;
- `window_end_commit` должен совпадать с `snapshot_commit`;
- для первого окна baseline берётся от первого доступного commit или `created_at`-baseline и помечается явно;
- если baseline/history отсутствуют или range не строится, это фиксируется отдельным статусом, а не считается молчаливым успехом;
- checkout без delta-context не закрывает historical prep contract.

## Что закреплено этим этапом

- glossary для diff-aware temporal model;
- правило first-window / intermediate-window / missing-history;
- запрет считать checkout-only prep достаточным для downstream analysis;
- явное расхождение между текущей реализацией и target contract.
