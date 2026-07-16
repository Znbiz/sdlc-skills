import type { PropsWithChildren } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { env } from "../shared/config/env";
import styles from "./app-shell.module.css";

const NAV_ITEMS = [
  { to: "/setup", label: "Setup" },
  { to: "/workflows/init", label: "Init Workflow" },
  { to: "/docs", label: "Docs" },
];

export function AppShell() {
  return (
    <AppShellLayout>
      <Outlet />
    </AppShellLayout>
  );
}

export function AppShellLayout({ children }: PropsWithChildren) {
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
      <main className={styles.main}>{children}</main>
    </div>
  );
}
