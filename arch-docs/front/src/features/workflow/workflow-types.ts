export const INIT_ARCH_WORKFLOW_TYPE = "init_arch";

export interface WorkflowTypeOption {
  value: string;
  label: string;
}

// Реестр типов workflow, доступных для запуска на странице проекта. Сейчас поддерживается только
// init_arch - когда появятся новые типы, добавить их сюда и подключить соответствующую форму
// запуска в WorkflowRunPanel (сейчас там жёстко зашит рендер InitArchForm).
export const WORKFLOW_TYPE_OPTIONS: WorkflowTypeOption[] = [
  { value: INIT_ARCH_WORKFLOW_TYPE, label: "init_arch — инициализация архитектурной документации" },
];
