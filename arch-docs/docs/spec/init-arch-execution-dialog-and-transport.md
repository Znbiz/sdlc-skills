# Init Arch Execution Dialog And Transport

## Что закрыто

Этапы 5-7 для `init_arch` теперь опираются не только на in-memory `workflow_registry`, но и на persisted execution dialog в PostgreSQL.

Сервис пишет и читает:

- `workflow_runs` как snapshot текущего run;
- `required_actions` как persisted очередь пользовательских действий;
- `conversation_items` как общую хронологию workflow/audit событий;
- `workflow_step_transitions` как отдельный журнал смены шагов;
- `artifact_events` как отдельный журнал knowledge-artifact решений;
- `cli_tasks` с `workflow_id`, `step_id`, `repository_name`, `domain_id`, `expected_schema_name` для связи LLM worker-аудита с persisted вызовом.

## Read-model

Пользовательский transport теперь читает execution dialog через conversation-first runtime:

- `GET /api/rest/conversations/{conversation_id}/` возвращает conversation и active `response`;
- `GET /api/rest/conversations/{conversation_id}/items/` возвращает persisted timeline items текущего conversation;
- `GET /api/rest/conversations/{conversation_id}/stream/` стримит active response через единый SSE path;
- `GET /api/rest/responses/{response_id}/` возвращает status/read-model response, `required_actions` и `terminal_result`.

Это важно для двух сценариев:

- restart сервиса между вопросом пользователю и ответом;
- диагностика knowledge/interview шагов после завершения или падения workflow.

## Что это даёт этапам 5-7

### Этап 5. Knowledge pipeline

Knowledge-artifact decisions теперь не теряются после завершения шага:

- `llm_task_requested/completed/failed` сохраняют worker-диалог;
- `artifact_written` и `artifact_rejected` доступны как persisted audit trail;
- status/event API позволяет проследить, какие knowledge-артефакты были приняты сервисом.

### Этап 6. Interview loop

Interview loop больше не зависит только от памяти процесса:

- open question становится `required_action`;
- answer flow может быть поднят из БД через lazy restore workflow-record;
- interrupt/event trail воспроизводится через REST status и SSE replay.

### Этап 7-9. Transport contour

REST и MCP используют один backend runtime, а внешний HTTP transport переведён на conversation-first surface:

- conversations;
- responses;
- required actions;
- timeline items;
- SSE stream по conversation.

## Что остаётся дальше

После закрытия этапа 10 поверх conversation-first backend уже поднят отдельный OpenAI-compatible facade:

- `GET /v1/models` публикует facade-models `arch-docs-init_arch`, `arch-docs-update_arch`, `arch-docs-query`;
- `POST /v1/responses` и `GET /v1/responses/{response_id}` транслируют OpenAI-compatible запросы в тот же backend contract `conversations/responses`;
- `POST /v1/chat/completions` даёт query-oriented surface для LibreChat/OpenWebUI-подобных клиентов, не раскрывая им внутренние workflow-specific endpoint-ы;
- facade stream маппит внутренние conversation events в OpenAI-compatible SSE (`response.created`, `response.output_text.delta`, terminal events, `chat.completion.chunk`).

Следующими расширениями остаются:

- полноценная multi-run timeline для нескольких последовательных response в одном conversation;
- causal links и отдельное хранение `llm_messages`;
- facade-level submit actions / richer resume semantics для long-running OpenAI clients.
