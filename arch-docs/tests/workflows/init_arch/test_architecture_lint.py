from __future__ import annotations

from typing import TYPE_CHECKING

from app.workflows.init_arch import architecture_lint

if TYPE_CHECKING:
    from pathlib import Path


def _write(tmp_path: Path, relative_path: str, body: str) -> Path:
    target_path = tmp_path / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(body, encoding="utf-8")
    return target_path


def test_lint_required_sections_reports_missing_file(tmp_path: Path) -> None:
    issues = architecture_lint._lint_required_sections(tmp_path, "architecture/hld.md", ("## X",))

    assert issues == ["ERROR: отсутствует architecture/hld.md"]


def test_lint_required_sections_reports_each_missing_heading(tmp_path: Path) -> None:
    _write(tmp_path, "architecture/hld.md", "# HLD\n\n## Обзор текущей архитектуры\n\nтекст\n")

    issues = architecture_lint._lint_required_sections(
        tmp_path, "architecture/hld.md", architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS["architecture/hld.md"]
    )

    assert "ERROR: architecture/hld.md не содержит обязательную секцию `## Контекстная диаграмма`" in issues
    assert "ERROR: architecture/hld.md не содержит обязательную секцию `## Обзор текущей архитектуры`" not in issues


def test_lint_required_sections_passes_when_all_present(tmp_path: Path) -> None:
    required_sections = architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS["architecture/risks.md"]
    body = "# Риски\n\n" + "\n\n".join(f"{section}\n\nтекст" for section in required_sections)
    _write(tmp_path, "architecture/risks.md", body)

    issues = architecture_lint._lint_required_sections(tmp_path, "architecture/risks.md", required_sections)

    assert issues == []


def test_lint_architecture_artifacts_reports_all_nine_missing_files(tmp_path: Path) -> None:
    issues = architecture_lint.lint_architecture_artifacts(tmp_path)

    for relative_path in architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS:
        assert f"ERROR: отсутствует {relative_path}" in issues


def test_lint_agents_md_skips_when_file_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_agents_md(tmp_path)

    assert issues == []


def test_lint_agents_md_reports_missing_sections_when_present(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "# AGENTS.md\n\n## Что читать первым\n\nтекст\n")

    issues = architecture_lint._lint_agents_md(tmp_path)

    assert "ERROR: AGENTS.md не содержит обязательную секцию `## Source of Truth`" in issues
    assert "ERROR: AGENTS.md не содержит обязательную секцию `## Что читать первым`" not in issues


def test_lint_agents_md_passes_when_all_sections_present(tmp_path: Path) -> None:
    body = "# AGENTS.md\n\n" + "\n\n".join(
        f"{section}\n\nтекст" for section in architecture_lint.AGENTS_REQUIRED_SECTIONS
    )
    _write(tmp_path, "AGENTS.md", body)

    issues = architecture_lint._lint_agents_md(tmp_path)

    assert issues == []


def test_lint_directory_documents_skips_when_directory_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_directory_documents(tmp_path, "features", ("## X",))

    assert issues == []


def test_lint_directory_documents_reports_missing_sections_per_file(tmp_path: Path) -> None:
    _write(tmp_path, "features/0001-auth.md", "# Фича\n\n## Метаданные\n\nтекст\n")

    issues = architecture_lint._lint_directory_documents(tmp_path, "features", architecture_lint.FEATURE_REQUIRED_SECTIONS)

    assert "ERROR: features/0001-auth.md не содержит обязательную секцию `## Бизнес-возможность`" in issues


def test_lint_directory_documents_passes_when_all_sections_present(tmp_path: Path) -> None:
    body = "# Интеграция\n\n" + "\n\n".join(
        f"{section}\n\nтекст" for section in architecture_lint.INTEGRATION_REQUIRED_SECTIONS
    )
    _write(tmp_path, "architecture/integrations/gateway-service.md", body)

    issues = architecture_lint._lint_directory_documents(
        tmp_path, "architecture/integrations", architecture_lint.INTEGRATION_REQUIRED_SECTIONS
    )

    assert issues == []


def _write_contract(tmp_path: Path, name: str, body: str) -> Path:
    return _write(tmp_path, f"architecture/contracts/{name}", body)


def test_lint_contracts_skips_when_directory_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == []


def test_lint_contracts_reports_invalid_yaml(tmp_path: Path) -> None:
    _write_contract(tmp_path, "broken-sync.yml", "openapi: [unclosed\n")

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert issues[0].startswith("ERROR: architecture/contracts/broken-sync.yml невалидный YAML:")


def test_lint_contracts_reports_missing_openapi_or_asyncapi_key(tmp_path: Path) -> None:
    _write_contract(tmp_path, "unknown-sync.yml", "service: gateway-service\n")

    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == [
        "ERROR: architecture/contracts/unknown-sync.yml не является OpenAPI/AsyncAPI контрактом: "
        "отсутствует ключ верхнего уровня `openapi` или `asyncapi`"
    ]


def test_lint_contracts_reports_openapi_missing_title(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "bad-title-sync.yml",
        "openapi: 3.0.3\ninfo:\n  version: '1.0.0'\npaths:\n  /ping:\n    get:\n      responses:\n        \"200\":\n          description: ok\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert issues[0].startswith(
        "ERROR: architecture/contracts/bad-title-sync.yml не проходит валидацию openapi-spec-validator:"
    )
    assert "title" in issues[0]


def test_lint_contracts_reports_openapi_missing_responses(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "bad-responses-sync.yml",
        "openapi: 3.0.3\ninfo:\n  title: API\n  version: '1.0.0'\npaths:\n  /ping:\n    get:\n      summary: ping\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert "responses" in issues[0]


def test_lint_contracts_passes_valid_openapi(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "good-sync.yml",
        (
            "openapi: 3.0.3\n"
            "info:\n"
            "  title: API\n"
            "  version: '1.0.0'\n"
            "paths:\n"
            "  /ping:\n"
            "    get:\n"
            "      responses:\n"
            '        "200":\n'
            "          description: ok\n"
        ),
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == []


def test_lint_contracts_reports_asyncapi_missing_channels(tmp_path: Path) -> None:
    _write_contract(tmp_path, "events-async.yml", "asyncapi: 2.6.0\ninfo:\n  title: Events\n  version: '1.0.0'\n")

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert issues[0].startswith(
        "ERROR: architecture/contracts/events-async.yml не проходит валидацию AsyncAPI 2.6.0 JSON Schema:"
    )
    assert "channels" in issues[0]


def test_lint_contracts_reports_asyncapi_missing_info_version(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "events-async.yml",
        "asyncapi: 2.6.0\ninfo:\n  title: Events\nchannels:\n  user.created:\n    description: x\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert "version" in issues[0]


def test_lint_contracts_passes_valid_asyncapi(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "events-async.yml",
        "asyncapi: 2.6.0\ninfo:\n  title: Events\n  version: '1.0.0'\nchannels:\n  user.created:\n    description: x\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == []


def _write_storage(tmp_path: Path, name: str, body: str) -> Path:
    return _write(tmp_path, f"architecture/storage/{name}", body)


def test_lint_storage_skips_when_directory_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == []


def test_lint_storage_reports_missing_top_level_key(tmp_path: Path) -> None:
    _write_storage(tmp_path, "gateway-service.yml", "service: gateway-service\n")

    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == [
        "ERROR: architecture/storage/gateway-service.yml не содержит mapping верхнего уровня `storage`"
    ]


def test_lint_storage_reports_missing_type(tmp_path: Path) -> None:
    _write_storage(tmp_path, "gateway-service.yml", "storage:\n  id: gateway-tokens\n")

    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == ["ERROR: architecture/storage/gateway-service.yml не содержит `storage.type`"]


def test_lint_storage_passes_valid_document(tmp_path: Path) -> None:
    _write_storage(
        tmp_path,
        "gateway-service.yml",
        "storage:\n  id: gateway-tokens\n  type: postgresql\n",
    )

    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == []


def _write_landscape(tmp_path: Path, body: str) -> Path:
    return _write(tmp_path, "architecture/landscape.yaml", body)


def _write_structure(tmp_path: Path, service_id: str, body: str) -> Path:
    return _write(tmp_path, f"architecture/structure/{service_id}.yml", body)


def test_lint_commit_consistency_skips_when_landscape_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == []


def test_lint_commit_consistency_reports_missing_structure_file(tmp_path: Path) -> None:
    _write_landscape(
        tmp_path,
        "entities:\n  services:\n    - id: gateway-service\n      repository_state:\n        head_commit: abc123\n",
    )

    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == [
        "ERROR: architecture/structure/gateway-service.yml не найден для сервиса `gateway-service` из landscape.yaml"
    ]


def test_lint_commit_consistency_reports_mismatch(tmp_path: Path) -> None:
    _write_landscape(
        tmp_path,
        "entities:\n  services:\n    - id: gateway-service\n      repository_state:\n        head_commit: abc123\n",
    )
    _write_structure(tmp_path, "gateway-service", "repo_structure_map:\n  analyzed_commit: def456\n")

    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == [
        "ERROR: рассинхронизация commit между landscape.yaml (head_commit=`abc123`) и "
        "architecture/structure/gateway-service.yml (analyzed_commit=`def456`) для сервиса `gateway-service`"
    ]


def test_lint_commit_consistency_passes_when_commits_match(tmp_path: Path) -> None:
    _write_landscape(
        tmp_path,
        "entities:\n  services:\n    - id: gateway-service\n      repository_state:\n        head_commit: abc123\n",
    )
    _write_structure(tmp_path, "gateway-service", "repo_structure_map:\n  analyzed_commit: abc123\n")

    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == []
