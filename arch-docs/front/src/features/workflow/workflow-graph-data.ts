// Статичное зеркало структуры графа init_arch (см. back/app/workflows/init_arch/graph.py).
// Бэкенд не отдаёт эту структуру через API — граф фиксирован в коде и меняется только вместе с
// релизом бэкенда, поэтому дублирование здесь дешевле нового эндпоинта. При изменении узлов/рёбер
// в graph.py эти данные нужно обновить вручную.

export const HANDLE_ERROR_NODE_ID = "handle_error";
export const DONE_NODE_ID = "done";

export interface ChecklistItemSpec {
  id: string;
  label: string;
}

// Статичное зеркало порядка CHECKLIST_ITEM_TO_REFERENCE (см. back/app/workflows/init_arch/prompts.py).
// Порядок и состав пунктов задаются бэкендом и меняются только вместе с релизом бэкенда.
export const CHECKLIST_ITEMS: ChecklistItemSpec[] = [
  { id: "deleted_functionality_cleanup", label: "Очистка удалённой функциональности" },
  { id: "repository_classification", label: "Классификация репозитория" },
  { id: "repository_structure_mapping", label: "Карта структуры репозитория" },
  { id: "entrypoints_and_interfaces", label: "Точки входа и интерфейсы" },
  { id: "business_flow_orchestration", label: "Оркестрация бизнес-потоков" },
  { id: "configs_and_runtime", label: "Конфигурация и runtime" },
  { id: "tech_stack_collection", label: "Технологический стек" },
  { id: "contracts_and_schemas", label: "Контракты и схемы" },
  { id: "data_and_storage", label: "Данные и хранилища" },
  { id: "domain_entities", label: "Доменные сущности" },
  { id: "integrations_and_dependencies", label: "Интеграции и зависимости" },
  { id: "tests_and_behavior_evidence", label: "Тесты и поведенческие свидетельства" },
  { id: "glossary_updates", label: "Обновление глоссария" },
  { id: "open_questions_review_and_updates", label: "Открытые вопросы" },
  { id: "feature_discovery_and_updates", label: "Обнаружение и обновление фич" },
  { id: "features_index_updates", label: "Обновление реестра фич" },
  { id: "roles_and_permissions_updates", label: "Роли и права доступа" },
  { id: "security_and_auth_updates", label: "Безопасность и аутентификация" },
  { id: "deployment_and_operability", label: "Деплой и эксплуатационная готовность" },
  { id: "risks_and_tech_debt_updates", label: "Риски и технический долг" },
  { id: "architecture_artifact_updates", label: "Обновление архитектурных артефактов" },
  { id: "repository_consistency_review", label: "Финальная проверка консистентности репозитория" },
];

export interface GraphNodeSpec {
  id: string;
  label: string;
  x: number;
  y: number;
}

export interface GraphEdgeSpec {
  id: string;
  source: string;
  target: string;
  label?: string;
  dashed?: boolean;
}

const COLUMN_X = 260;
const ROW_HEIGHT = 90;

export const GRAPH_NODES: GraphNodeSpec[] = [
  { id: "define_scope", label: "Определение области анализа", x: COLUMN_X, y: 0 * ROW_HEIGHT },
  { id: "request_repository_list", label: "Запрос списка репозиториев", x: COLUMN_X, y: 1 * ROW_HEIGHT },
  { id: "prepare_temp_workspace", label: "Подготовка рабочей директории", x: COLUMN_X, y: 2 * ROW_HEIGHT },
  { id: "clone_repositories", label: "Клонирование репозиториев", x: COLUMN_X, y: 3 * ROW_HEIGHT },
  { id: "refresh_main_branches", label: "Обновление main-веток", x: COLUMN_X, y: 4 * ROW_HEIGHT },
  { id: "plan_repository_order", label: "Планирование порядка анализа", x: COLUMN_X, y: 5 * ROW_HEIGHT },
  { id: "assess_scope_and_domains", label: "Оценка объёма и доменов репозитория", x: COLUMN_X, y: 6 * ROW_HEIGHT },
  { id: "analyze_repositories", label: "Анализ репозиториев", x: COLUMN_X, y: 7 * ROW_HEIGHT },
  { id: "analyze_repositories_item", label: "Анализ репозитория (пункт чеклиста)", x: COLUMN_X + 320, y: 7 * ROW_HEIGHT },
  { id: "interview_user", label: "Интервью с пользователем", x: COLUMN_X, y: 8 * ROW_HEIGHT },
  { id: "refine_features", label: "Описание фич продукта", x: COLUMN_X, y: 9 * ROW_HEIGHT },
  { id: "build_navigation_index", label: "Сборка навигационного индекса", x: COLUMN_X, y: 10 * ROW_HEIGHT },
  { id: "run_knowledge_lint", label: "Проверка целостности документации", x: COLUMN_X, y: 11 * ROW_HEIGHT },
  { id: "validate_final", label: "Финальная проверка консистентности", x: COLUMN_X, y: 12 * ROW_HEIGHT },
  { id: "generate_release_notes", label: "Генерация release notes", x: COLUMN_X, y: 13 * ROW_HEIGHT },
  { id: "confirm_next_temporal_window", label: "Подтверждение следующего временного окна", x: COLUMN_X, y: 14 * ROW_HEIGHT },
  { id: "finalize_progress", label: "Завершение прогона", x: COLUMN_X, y: 15 * ROW_HEIGHT },
  { id: DONE_NODE_ID, label: "Готово", x: COLUMN_X, y: 16 * ROW_HEIGHT },
  {
    id: HANDLE_ERROR_NODE_ID,
    label: "Обработка ошибки шага\n(после 3 неудачных попыток любого шага)",
    x: COLUMN_X - 340,
    y: 7 * ROW_HEIGHT,
  },
];

export const GRAPH_EDGES: GraphEdgeSpec[] = [
  { id: "e-define_scope-request_repository_list", source: "define_scope", target: "request_repository_list" },
  {
    id: "e-request_repository_list-prepare_temp_workspace",
    source: "request_repository_list",
    target: "prepare_temp_workspace",
  },
  { id: "e-prepare_temp_workspace-clone_repositories", source: "prepare_temp_workspace", target: "clone_repositories" },
  { id: "e-clone_repositories-refresh_main_branches", source: "clone_repositories", target: "refresh_main_branches" },
  { id: "e-refresh_main_branches-plan_repository_order", source: "refresh_main_branches", target: "plan_repository_order" },
  {
    id: "e-plan_repository_order-assess_scope_and_domains",
    source: "plan_repository_order",
    target: "assess_scope_and_domains",
  },
  {
    id: "e-assess_scope_and_domains-analyze_repositories",
    source: "assess_scope_and_domains",
    target: "analyze_repositories",
  },
  {
    id: "e-analyze_repositories-analyze_repositories_item",
    source: "analyze_repositories",
    target: "analyze_repositories_item",
    label: "по одному репозиторию",
  },
  {
    id: "e-analyze_repositories_item-analyze_repositories",
    source: "analyze_repositories_item",
    target: "analyze_repositories",
    label: "следующий репозиторий",
    dashed: true,
  },
  {
    id: "e-analyze_repositories-interview_user",
    source: "analyze_repositories",
    target: "interview_user",
    label: "все репозитории обработаны",
  },
  { id: "e-interview_user-refine_features", source: "interview_user", target: "refine_features" },
  { id: "e-refine_features-build_navigation_index", source: "refine_features", target: "build_navigation_index" },
  { id: "e-build_navigation_index-run_knowledge_lint", source: "build_navigation_index", target: "run_knowledge_lint" },
  { id: "e-run_knowledge_lint-validate_final", source: "run_knowledge_lint", target: "validate_final" },
  { id: "e-validate_final-generate_release_notes", source: "validate_final", target: "generate_release_notes" },
  {
    id: "e-generate_release_notes-confirm_next_temporal_window",
    source: "generate_release_notes",
    target: "confirm_next_temporal_window",
  },
  {
    id: "e-confirm_next_temporal_window-refresh_main_branches",
    source: "confirm_next_temporal_window",
    target: "refresh_main_branches",
    label: "следующее временное окно",
    dashed: true,
  },
  {
    id: "e-confirm_next_temporal_window-finalize_progress",
    source: "confirm_next_temporal_window",
    target: "finalize_progress",
    label: "все окна пройдены",
  },
  { id: "e-finalize_progress-done", source: "finalize_progress", target: DONE_NODE_ID },
  {
    id: "e-handle_error-done",
    source: HANDLE_ERROR_NODE_ID,
    target: DONE_NODE_ID,
    label: "abort",
    dashed: true,
  },
];
