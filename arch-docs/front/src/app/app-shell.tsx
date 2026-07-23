import type { PropsWithChildren } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { env } from "../shared/config/env";
import styles from "./app-shell.module.css";

const NAV_ITEMS = [
  { to: "/setup", label: "Setup" },
  { to: "/projects", label: "Проекты" },
  { to: "/docs", label: "Документация" },
];

// Страница конкретного проекта (трёхколоночный layout с ресайзом) не должна быть зажата
// общим max-width контейнера - ей нужна вся доступная ширина экрана.
const FULL_WIDTH_ROUTE = /^\/projects\/[^/]+/;

export function AppShell() {
  return (
    <AppShellLayout>
      <Outlet />
    </AppShellLayout>
  );
}

export function AppShellLayout({ children }: PropsWithChildren) {
  const location = useLocation();
  const isFullWidth = FULL_WIDTH_ROUTE.test(location.pathname);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.brand}>{env.appTitle}</span>
        <nav className={styles.nav}>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className={isFullWidth ? `${styles.main} ${styles.mainFullWidth}` : styles.main}>{children}</main>
    </div>
  );
}
