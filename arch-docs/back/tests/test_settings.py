from app.settings import GatewaySettings


def test_gateway_settings_expose_workflow_group_defaults() -> None:
    settings = GatewaySettings(auth_secret="secret")

    assert settings.workflows.init.historical_window_months == 3


def test_gateway_settings_support_nested_workflow_overrides() -> None:
    settings = GatewaySettings(
        auth_secret="secret",
        workflows={"init": {"historical_window_months": 6}},
    )

    assert settings.workflows.init.historical_window_months == 6


def test_gateway_settings_expose_hardening_defaults() -> None:
    settings = GatewaySettings(auth_secret="secret")

    assert settings.workflows.init.max_step_timeout_seconds == 900
    assert settings.workflows.init.raw_workspace_subdir == ".temp"
    assert settings.workflows.init.arch_repo_dirname == "arch-doc"
    assert settings.audit.max_prompt_chars == 12000
    assert settings.audit.max_output_chars == 16000
    assert settings.audit.max_error_chars == 8000


def test_gateway_settings_support_nested_hardening_overrides() -> None:
    settings = GatewaySettings(
        auth_secret="secret",
        workflows={
            "init": {
                "historical_window_months": 6,
                "max_step_timeout_seconds": 1200,
                "raw_workspace_subdir": ".raw",
                "arch_repo_dirname": "docs-arch",
            }
        },
        audit={
            "max_prompt_chars": 2048,
            "max_output_chars": 4096,
            "max_error_chars": 1024,
        },
    )

    assert settings.workflows.init.max_step_timeout_seconds == 1200
    assert settings.workflows.init.raw_workspace_subdir == ".raw"
    assert settings.workflows.init.arch_repo_dirname == "docs-arch"
    assert settings.audit.max_prompt_chars == 2048
    assert settings.audit.max_output_chars == 4096
    assert settings.audit.max_error_chars == 1024
