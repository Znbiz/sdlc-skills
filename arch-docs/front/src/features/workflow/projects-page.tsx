import { useNavigate } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { getLastConversationId, setLastConversationId } from "../../shared/storage/recent-conversation";
import { useCreateConversation } from "./hooks";
import { ProjectList } from "./project-list";
import styles from "./project-page.module.css";

export function ProjectsPage() {
  const navigate = useNavigate();
  const createConversation = useCreateConversation();
  const lastConversationId = getLastConversationId();

  return (
    <div className={styles.page}>
      <h1>Проекты</h1>
      <Card title="Новый проект">
        <p>Создайте проект и настройте название/репозитории на его странице перед запуском init_arch.</p>
        <Button
          variant="primary"
          disabled={createConversation.isPending}
          onClick={() =>
            createConversation.mutate(undefined, {
              onSuccess: (conversation) => {
                setLastConversationId(conversation.conversation_id);
                navigate(`/projects/${conversation.conversation_id}`);
              },
            })
          }
        >
          Создать проект
        </Button>
        {createConversation.isError && <ErrorBanner error={createConversation.error} onRetry={() => createConversation.mutate()} />}
        {lastConversationId && (
          <Button variant="secondary" onClick={() => navigate(`/projects/${lastConversationId}`)}>
            Продолжить последний проект
          </Button>
        )}
      </Card>
      <ProjectList />
    </div>
  );
}
