from __future__ import annotations

import pathlib


class WorkflowAssetLoader:
    def __init__(self, base_dir: pathlib.Path | None = None) -> None:
        self._base_dir = base_dir or pathlib.Path(__file__).resolve().parent

    def read_text(self, workflow_name: str, relative_path: str) -> str:
        asset_path = self.resolve_path(workflow_name, relative_path)
        return asset_path.read_text(encoding="utf-8")

    def resolve_path(self, workflow_name: str, relative_path: str) -> pathlib.Path:
        asset_path = self._base_dir / workflow_name / relative_path
        if not asset_path.exists():
            raise FileNotFoundError(f"workflow asset not found: {workflow_name}/{relative_path}")
        return asset_path


_workflow_asset_loader: WorkflowAssetLoader | None = None


def get_workflow_asset_loader() -> WorkflowAssetLoader:
    global _workflow_asset_loader  # noqa: PLW0603
    if _workflow_asset_loader is None:
        _workflow_asset_loader = WorkflowAssetLoader()
    return _workflow_asset_loader
