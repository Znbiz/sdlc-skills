// arch-docs/e2e/helpers/docker-workspace.ts
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);

// Пакет собран как ESM ("type": "module"), поэтому __dirname недоступен —
// вычисляем каталог модуля из import.meta.url.
const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));

// Все команды выполняются относительно корня arch-docs/ (там лежит docker-compose.yml
// и .env.docker), т.к. e2e-пакет живёт в arch-docs/e2e/.
const COMPOSE_CWD = path.resolve(MODULE_DIR, "..", "..");
const COMPOSE_SERVICE = "arch-docs";

async function dockerComposeExec(args: string[]): Promise<string> {
  const { stdout } = await execFileAsync(
    "docker",
    ["compose", "--env-file", ".env.docker", "exec", "-T", COMPOSE_SERVICE, ...args],
    { cwd: COMPOSE_CWD },
  );
  return stdout;
}

export async function seedRepositoriesIntoWorkspace(
  runId: string,
  fixtureDir: string,
  repoNames: string[],
): Promise<{ workspaceDir: string; archRepoDir: string; fixtureRepoUrls: Record<string, string> }> {
  const workspaceDir = `/workspace/e2e-${runId}`;
  const archRepoDir = `${workspaceDir}/arch-doc`;
  // Raw clones live under `<workspaceDir>/.temp/<repoName>` - project-level, shared by every run
  // of the conversation (see arch-docs/docs/spec/2026-07-23-per-workflow-workspace-and-browser.md
  // section 1), and always deleted + re-cloned fresh by `_clone_repositories()` regardless of
  // what's already there. Fixtures are seeded at a separate scratch path and passed as `file://`
  // URLs repo entries, so `_clone_repositories()` does a real (local, no-credentials-needed)
  // `git clone` into `.temp/<repoName>` itself.
  const fixturesDir = `/tmp/e2e-fixtures-${runId}`;

  await dockerComposeExec(["mkdir", "-p", fixturesDir]);

  const fixtureRepoUrls: Record<string, string> = {};
  for (const repoName of repoNames) {
    const hostRepoPath = path.join(fixtureDir, repoName);
    // docker compose cp копирует относительно текущего контейнера сервиса.
    await execFileAsync(
      "docker",
      ["compose", "--env-file", ".env.docker", "cp", hostRepoPath, `${COMPOSE_SERVICE}:${fixturesDir}/${repoName}`],
      { cwd: COMPOSE_CWD },
    );
    fixtureRepoUrls[repoName] = `file://${fixturesDir}/${repoName}`;
  }

  // `docker compose exec`/`docker cp` создают файлы от root, а backend в контейнере работает под
  // непривилегированным пользователем и не сможет ни прочитать фикстуры для `git clone`, ни
  // создать/писать в conversation_workspace_dir (создаётся eagerly самим backend-ом). Делаем оба
  // дерева доступными на запись/чтение backend-у.
  await dockerComposeExec(["chmod", "-R", "0777", fixturesDir]);
  await dockerComposeExec(["mkdir", "-p", workspaceDir]);
  await dockerComposeExec(["chmod", "-R", "0777", workspaceDir]);

  return { workspaceDir, archRepoDir, fixtureRepoUrls };
}

export async function readFileFromContainer(filePath: string): Promise<string> {
  try {
    return await dockerComposeExec(["cat", filePath]);
  } catch (error) {
    throw new Error(`failed to read ${filePath} from container ${COMPOSE_SERVICE}: ${String(error)}`);
  }
}

export async function cleanupWorkspace(runId: string): Promise<void> {
  await dockerComposeExec(["rm", "-rf", `/workspace/e2e-${runId}`, `/tmp/e2e-fixtures-${runId}`]);
}
