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
