# OpenAI Facade

## Назначение

`/v1/*` facade даёт внешним OpenAI-compatible клиентам стабильный вход в `arch-docs`, не раскрывая им напрямую внутренний conversation-first contract `conversations/responses`.

Source of truth остаётся backend runtime:

- `POST /api/rest/conversations/`
- `POST /api/rest/responses/`
- `GET /api/rest/responses/{response_id}/`
- `GET /api/rest/conversations/{conversation_id}/stream/`

OpenAI facade только адаптирует запрос/ответ и потоковые события.

Реализация: [openai.py](../../back/app/api/openai.py), [init_arch_workflow.py](../../back/app/services/init_arch_workflow.py)

## Endpoints

### `GET /v1/models`

Публикует facade-models:

- `arch-docs-init_arch`
- `arch-docs-update_arch`
- `arch-docs-query`

Каждая model-id маппится на один внутренний `workflow_type`.

### `POST /v1/responses`

OpenAI-compatible lifecycle entrypoint для long-running workflow.

Поддерживаемые mappings:

- `arch-docs-init_arch` -> `workflow_type=init_arch`
- `arch-docs-update_arch` -> `workflow_type=update_arch`
- `arch-docs-query` -> `workflow_type=query`

Практика использования:

- `input` содержит typed workflow input;
- `metadata.conversation_id` позволяет привязать run к существующему conversation;
- `metadata.engine_name` и `metadata.timeout_seconds` прокидываются во внутренний backend input;
- при `stream=true` facade отдаёт OpenAI-compatible SSE, но backend продолжает жить в conversation timeline.

### `GET /v1/responses/{response_id}`

Возвращает OpenAI-shaped read-model по уже созданному backend response.

Facade маппит внутренние статусы:

- `pending` -> `queued`
- `running` -> `in_progress`
- `interrupted` -> `requires_action`
- `success` -> `completed`
- `failed` -> `failed`
- `cancelled` -> `cancelled`

### `POST /v1/chat/completions`

Query-oriented surface для OpenAI-compatible UI-клиентов вроде LibreChat.

Текущий срез intentionally ограничен:

- поддерживается только `model=arch-docs-query`;
- последний `user` message превращается во внутренний `query.question`;
- `metadata.repo_path` обязателен;
- non-stream mode ждёт terminal result backend response;
- stream mode транслирует backend output в `chat.completion.chunk`.

## Streaming Mapping

Facade не пробрасывает все внутренние workflow events один в один.

### Responses SSE

Во внешний поток маппятся:

- `response.created`
- `response.output_text.delta`
- `response.completed`
- `response.failed`
- `response.cancelled`
- `response.requires_action`

### Chat Completions SSE

Во внешний поток маппятся:

- `chat.completion.chunk` с `delta.content`
- terminal chunk с `finish_reason=stop`
- `data: [DONE]`

## Ограничения

- facade не является source of truth: canonical state живёт во внутреннем conversation-first backend;
- не все conversation items и audit events выводятся во внешний OpenAI stream;
- submit actions (`resume`, `answer_question`, `cancel`) пока остаются на внутреннем transport-слое;
- `chat/completions` пока не покрывает `init_arch` и `update_arch`, чтобы не притворяться обычным chat endpoint для long-running workflow с required actions.
