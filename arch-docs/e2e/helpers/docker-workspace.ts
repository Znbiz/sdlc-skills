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
): Promise<{ workspaceDir: string; archRepoDir: string }> {
  const workspaceDir = `/workspace/e2e-${runId}`;
  const archRepoDir = `${workspaceDir}/arch-doc`;
  const rawWorkspaceDir = `${workspaceDir}/.temp`;

  await dockerComposeExec(["mkdir", "-p", rawWorkspaceDir]);

  for (const repoName of repoNames) {
    const hostRepoPath = path.join(fixtureDir, repoName);
    // docker compose cp копирует относительно текущего контейнера сервиса.
    await execFileAsync(
      "docker",
      ["compose", "--env-file", ".env.docker", "cp", hostRepoPath, `${COMPOSE_SERVICE}:${rawWorkspaceDir}/${repoName}`],
      { cwd: COMPOSE_CWD },
    );
  }

  // `docker compose exec` и `docker cp` создают каталоги/файлы от root, а backend в контейнере
  // работает под непривилегированным пользователем и не сможет создать arch_repo_dir / писать
  // снепшот внутри root-овного workspace. Делаем засеянное дерево доступным на запись backend-у.
  await dockerComposeExec(["chmod", "-R", "0777", workspaceDir]);

  return { workspaceDir, archRepoDir };
}

export async function readFileFromContainer(filePath: string): Promise<string> {
  try {
    return await dockerComposeExec(["cat", filePath]);
  } catch (error) {
    throw new Error(`failed to read ${filePath} from container ${COMPOSE_SERVICE}: ${String(error)}`);
  }
}

export async function cleanupWorkspace(runId: string): Promise<void> {
  await dockerComposeExec(["rm", "-rf", `/workspace/e2e-${runId}`]);
}
