import { useNavigate } from "react-router-dom";
import { Button } from "../../shared/ui/button";
import { Card } from "../../shared/ui/card";
import { ErrorBanner } from "../../shared/ui/error-banner";
import { getLastConversationId, setLastConversationId } from "../../shared/storage/recent-conversation";
import { useCreateConversation } from "./hooks";

export function InitWorkflowStartPage() {
  const navigate = useNavigate();
  const createConversation = useCreateConversation();
  const lastConversationId = getLastConversationId();

  return (
    <div>
      <h1>Init Workflow</h1>
      <Card title="Запуск init_arch">
        <p>Создайте conversation и запустите полный интерактивный сценарий init_arch.</p>
        <Button
          variant="primary"
          disabled={createConversation.isPending}
          onClick={() =>
            createConversation.mutate(undefined, {
              onSuccess: (conversation) => {
                setLastConversationId(conversation.conversation_id);
                navigate(`/workflows/init/${conversation.conversation_id}`);
              },
            })
          }
        >
          Создать conversation
        </Button>
        {createConversation.isError && <ErrorBanner error={createConversation.error} onRetry={() => createConversation.mutate()} />}
        {lastConversationId && (
          <Button variant="secondary" onClick={() => navigate(`/workflows/init/${lastConversationId}`)}>
            Продолжить последний запуск
          </Button>
        )}
      </Card>
    </div>
  );
}
