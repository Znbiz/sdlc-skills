export const env = {
  apiBasePath: (import.meta.env.VITE_API_BASE_PATH ?? "/api").replace(/\/$/, ""),
  appTitle: import.meta.env.VITE_APP_TITLE ?? "arch-docs",
} as const;
