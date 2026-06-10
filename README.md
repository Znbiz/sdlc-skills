# sdlc-skills

Reusable skills for coding agents that work on software delivery and architecture tasks.

The repository currently focuses on architecture workflows for three common scenarios:

- restoring and documenting the current `as-is` state of an existing system
- designing a new feature or a significant change in `to-be` form
- refreshing an existing architecture repository after the product has changed

These skills are written as file-based bundles with a root `SKILL.md` plus supporting templates, references, and optional helper scripts. They are intended to be usable from Codex, Claude Code, and other agent environments that support local skill directories.

## Repository layout

| Path | Purpose |
| --- | --- |
| [`init-repo-arch-skill`](./init-repo-arch-skill/) | Reconstruct and document the current architecture of an existing system |
| [`new-feature-arch-skill`](./new-feature-arch-skill/) | Design and document a new feature or system change |
| [`update-repo-arch-skill`](./update-repo-arch-skill/) | Update an existing architecture repository after implementation changes |
| [`frontend-skill`](./frontend-skill/) | Placeholder for frontend-oriented skills |
| [`backend-skill`](./backend-skill/) | Placeholder for backend-oriented skills |

## Skill structure

Each skill is expected to follow the same basic layout:

- `SKILL.md` as the entry point
- `assets/` for templates and reusable artifacts
- `references/` for supporting workflow documents
- `scripts/` for optional helper automation used by the skill

## Supported runtimes

This repository is runtime-agnostic at the content level. The same skill can be consumed by different agent tools as long as they support local skill folders.

### Codex

Codex resolves skills from `~/.codex/skills`. The most practical local setup is to symlink each skill directory into that location.

Example:

```bash
mkdir -p ~/.codex/skills
ln -sfn "$(pwd)/init-repo-arch-skill" ~/.codex/skills/init-repo-arch-skill
ln -sfn "$(pwd)/new-feature-arch-skill" ~/.codex/skills/new-feature-arch-skill
ln -sfn "$(pwd)/update-repo-arch-skill" ~/.codex/skills/update-repo-arch-skill
```

This keeps the installed skills pointing at the working copy of the repository, which is useful while iterating on the skill text and templates.

### Claude Code

Claude Code commonly resolves local skills or commands from a user-scoped directory such as `~/.claude/commands`. The most practical local setup is also to symlink each skill directory into that location.

Example:

```bash
mkdir -p ~/.claude/commands
ln -sfn "$(pwd)/init-repo-arch-skill" ~/.claude/commands/init-repo-arch-skill
ln -sfn "$(pwd)/new-feature-arch-skill" ~/.claude/commands/new-feature-arch-skill
ln -sfn "$(pwd)/update-repo-arch-skill" ~/.claude/commands/update-repo-arch-skill
```

If your Claude setup uses a different directory layout, install the same folders into the directory that your local Claude runtime scans for reusable commands or skills.

### Other agent environments

If your agent runtime uses a different skills directory, install the same folders there either by copy or by symlink. The important part is that each installed skill directory contains a readable `SKILL.md` at its root.

## Installation options

There is no single best installation method for every use case. The right choice depends on whether you optimize for local editing, reproducibility, or distribution.

### Option 1. Symlink local folders

Best for:

- active skill development
- frequent edits
- immediate feedback in a local Codex or Claude setup

Example for Codex:

```bash
mkdir -p ~/.codex/skills
ln -sfn "$(pwd)/init-repo-arch-skill" ~/.codex/skills/init-repo-arch-skill
ln -sfn "$(pwd)/new-feature-arch-skill" ~/.codex/skills/new-feature-arch-skill
ln -sfn "$(pwd)/update-repo-arch-skill" ~/.codex/skills/update-repo-arch-skill
```

Example for Claude Code:

```bash
mkdir -p ~/.claude/commands
ln -sfn "$(pwd)/init-repo-arch-skill" ~/.claude/commands/init-repo-arch-skill
ln -sfn "$(pwd)/new-feature-arch-skill" ~/.claude/commands/new-feature-arch-skill
ln -sfn "$(pwd)/update-repo-arch-skill" ~/.claude/commands/update-repo-arch-skill
```

Tradeoff:

- simplest workflow
- installed state depends on the local checkout path

### Option 2. Copy folders into the target skills directory

Best for:

- isolated environments
- stable snapshots
- situations where symlinks are inconvenient

Example:

```bash
mkdir -p ~/.codex/skills
cp -R init-repo-arch-skill ~/.codex/skills/
cp -R new-feature-arch-skill ~/.codex/skills/
cp -R update-repo-arch-skill ~/.codex/skills/
```

The same approach works for Claude Code if you copy into its local commands directory instead.

Tradeoff:

- stable and simple
- every update requires copying again

### Option 3. Install from Git checkout

Best for:

- teams that want version pinning
- repeatable bootstrap on a new machine

Example:

```bash
git clone <repo-url> ~/src/sdlc-skills
mkdir -p ~/.codex/skills
ln -sfn ~/src/sdlc-skills/init-repo-arch-skill ~/.codex/skills/init-repo-arch-skill
ln -sfn ~/src/sdlc-skills/new-feature-arch-skill ~/.codex/skills/new-feature-arch-skill
ln -sfn ~/src/sdlc-skills/update-repo-arch-skill ~/.codex/skills/update-repo-arch-skill
```

Tradeoff:

- reproducible and easy to update with `git pull`
- still relies on a known checkout location

### Option 4. Bootstrap via npm from Git

Best for:

- developers who already standardize environment setup through Node tooling
- one-command installation
- team-wide bootstrap scripts

Recommended shape:

1. add a small `package.json`
2. expose a CLI like `install-skills`
3. have the CLI create or refresh symlinks in `~/.codex/skills` and optionally `~/.claude/commands`
4. install from Git with `npm install git+ssh://...` or `npm install github:owner/repo`

Typical usage would look like:

```bash
npm install -g github:owner/sdlc-skills
sdlc-skills-install codex
```

Or:

```bash
sdlc-skills-install claude
```

Or without global install:

```bash
npx github:owner/sdlc-skills sdlc-skills-install codex
```

Tradeoff:

- good user experience for installation
- adds packaging and CLI maintenance overhead

### Option 5. Bootstrap script in this repository

Best for:

- keeping the repository toolchain minimal
- predictable installation without adding npm packaging immediately

Recommended shape:

- add `scripts/install-skills.sh`
- accept a target runtime such as `codex` or `claude`
- create or refresh the expected symlinks

Typical usage:

```bash
./scripts/install-skills.sh codex
./scripts/install-skills.sh claude
```

Tradeoff:

- simpler than npm packaging
- not as convenient for external consumers as a published installer

## Recommendation

For now, the most practical default is:

1. keep this repository as the source of truth
2. install skills into Codex and Claude through symlinks
3. add a small installer script in this repository for repeatability

If these skills will be distributed across multiple machines or multiple engineers, the next step is to add a lightweight installer CLI. That can be implemented either as:

- a shell script in `scripts/`
- a small Node package installable from Git

For this repository, a shell installer is the lower-friction first step. An npm-based installer makes sense once you want one-command bootstrap and versioned distribution for a broader team.

## Contributing

When adding or updating skills:

1. keep one skill per folder
2. require a root `SKILL.md`
3. keep reusable templates in `assets/`
4. keep workflow references in `references/`
5. keep helper automation in `scripts/` only when it materially improves execution
6. avoid hardcoding outdated absolute paths in the skill text

## License

[CC BY-NC 4.0](./LICENSE)
