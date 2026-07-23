import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { Spinner } from "../../shared/ui/spinner";
import { StatusBadge } from "../../shared/ui/status-badge";
import type { ConversationResponse } from "../../shared/api/models";
import { toneFromResponseStatus, responseStatusLabel } from "../../shared/status/status-mapping";
import { setLastConversationId } from "../../shared/storage/recent-conversation";
import { useConversations, useDeleteConversation, useSubmitResponseAction } from "./hooks";
import styles from "./project-list.module.css";

const REPO_CHIPS_LIMIT = 4;

function projectDisplayName(conversation: ConversationResponse): string {
  return conversation.product_name?.trim() || conversation.conversation_id.slice(0, 8);
}

function matchesFilter(conversation: ConversationResponse, filter: string): boolean {
  if (!filter) return true;
  const haystack = [
    conversation.product_name ?? "",
    conversation.conversation_id,
    ...conversation.repositories.map((repository) => repository.repository_name),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(filter.toLowerCase());
}

function ProjectListItem({ conversation }: { conversation: ConversationResponse }) {
  const navigate = useNavigate();
  const submitAction = useSubmitResponseAction(conversation.conversation_id);
  const deleteConversation = useDeleteConversation();
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const activeResponse = conversation.active_response;
  const visibleRepositories = conversation.repositories.slice(0, REPO_CHIPS_LIMIT);
  const hiddenRepositoriesCount = conversation.repositories.length - visibleRepositories.length;

  const open = () => {
    setLastConversationId(conversation.conversation_id);
    navigate(`/projects/${conversation.conversation_id}`);
  };

  const openDocs = () => {
    setLastConversationId(conversation.conversation_id);
    navigate(`/docs?conversationId=${conversation.conversation_id}`);
  };

  // onClick на всей строке - для мыши; explicit кнопка "Открыть" ниже остаётся основной точкой
  // входа для клавиатуры/скринридеров (вложенный role="button" на всю строку с кнопками внутри -
  // антипаттерн ARIA, поэтому не дублируем интерактивность на уровне div).
  return (
    <div className={styles.row} onClick={open}>
      <div className={styles.info}>
        <div className={styles.titleRow}>
          <span className={styles.productName}>{projectDisplayName(conversation)}</span>
          <span className={styles.conversationId}>{conversation.conversation_id}</span>
        </div>
        {conversation.repositories.length > 0 && (
          <div className={styles.repoChips}>
            {visibleRepositories.map((repository) => (
              <span key={repository.repository_name} className={styles.repoChip}>
                {repository.repository_name}
              </span>
            ))}
            {hiddenRepositoriesCount > 0 && <span className={styles.repoChip}>+{hiddenRepositoriesCount}</span>}
          </div>
        )}
        {activeResponse ? (
          <span className={styles.meta}>
            последний запуск: {responseStatusLabel(activeResponse.response_status)}, шаг{" "}
            {activeResponse.current_step_id || "—"}, {new Date(activeResponse.created_at).toLocaleString("ru-RU")}
          </span>
        ) : (
          <span className={styles.meta}>прогонов ещё не было</span>
        )}
      </div>

      <div className={styles.actions} onClick={(event) => event.stopPropagation()}>
        {activeResponse && (
          <StatusBadge
            tone={toneFromResponseStatus(activeResponse.response_status, activeResponse.required_actions.length > 0)}
            label={responseStatusLabel(activeResponse.response_status)}
          />
        )}
        {activeResponse?.response_status === "running" && (
          <Button
            variant="secondary"
            disabled={submitAction.isPending}
            onClick={() => submitAction.mutate({ responseId: activeResponse.response_id, actionType: "pause" })}
          >
            Пауза
          </Button>
        )}
        {activeResponse?.response_status === "paused" && (
          <Button
            variant="primary"
            disabled={submitAction.isPending}
            onClick={() => submitAction.mutate({ responseId: activeResponse.response_id, actionType: "continue" })}
          >
            Продолжить
          </Button>
        )}
        {!showDeleteConfirm && (
          <Button
            variant="danger"
            disabled={submitAction.isPending || deleteConversation.isPending}
            onClick={() => setShowDeleteConfirm(true)}
          >
            Удалить
          </Button>
        )}
        <Button variant="secondary" onClick={openDocs}>
          Документация
        </Button>
        <Button variant="secondary" onClick={open}>
          Открыть
        </Button>
      </div>

      {showDeleteConfirm && (
        <div className={styles.restartConfirm} onClick={(event) => event.stopPropagation()}>
          <p>Это необратимо удалит проект целиком вместе с его прогонами, историей и workspace. Продолжить?</p>
          <div className={styles.actions}>
            <Button
              variant="secondary"
              disabled={deleteConversation.isPending}
              onClick={() => setShowDeleteConfirm(false)}
            >
              Отмена
            </Button>
            <Button
              variant="danger"
              disabled={deleteConversation.isPending}
              onClick={() => {
                deleteConversation.mutate(conversation.conversation_id);
                setShowDeleteConfirm(false);
              }}
            >
              Да, удалить проект целиком
            </Button>
          </div>
        </div>
      )}

      {submitAction.isError && <ErrorBanner error={submitAction.error} />}
      {deleteConversation.isError && <ErrorBanner error={deleteConversation.error} />}
    </div>
  );
}

export function ProjectList() {
  const conversations = useConversations();
  const [filter, setFilter] = useState("");

  const filtered = useMemo(
    () => conversations.data?.filter((conversation) => matchesFilter(conversation, filter)) ?? [],
    [conversations.data, filter],
  );

  if (conversations.isPending) return <Spinner label="Загрузка списка проектов…" />;
  if (conversations.isError) return <ErrorBanner error={conversations.error} onRetry={() => conversations.refetch()} />;
  if (conversations.data.length === 0) return null;

  return (
    <Card title="Проекты">
      <div className={styles.filter}>
        <input
          className={styles.filterInput}
          placeholder="Поиск по названию проекта или репозиторию"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <div className={styles.list}>
        {filtered.map((conversation) => (
          <ProjectListItem key={conversation.conversation_id} conversation={conversation} />
        ))}
      </div>
    </Card>
  );
}
