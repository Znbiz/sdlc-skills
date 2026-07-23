import pathlib

import pytest

from app.services.docs_browser import (
    DocsFileNotFoundError,
    DocsPathForbiddenError,
    MediaKind,
    build_docs_tree,
    delete_docs_path,
    detect_media_kind,
    read_docs_file,
    resolve_within_root,
)


@pytest.fixture
def arch_repo(tmp_path):
    root = tmp_path / "arch-doc"
    root.mkdir()
    (root / "README.md").write_text("# Title\n")
    (root / "architecture").mkdir()
    (root / "architecture" / "hld.md").write_text("# HLD\n")
    (root / "architecture" / "tech-stack.yaml").write_text("stack: python\n")
    (root / "config.json").write_text("{}\n")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    return root


class TestDetectMediaKind:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("README.md", MediaKind.MARKDOWN),
            ("tech-stack.yaml", MediaKind.YAML),
            ("tech-stack.yml", MediaKind.YAML),
            ("config.json", MediaKind.JSON),
            ("notes.txt", MediaKind.TEXT),
            ("logo.png", MediaKind.UNSUPPORTED),
        ],
    )
    def test_maps_extension_to_media_kind(self, filename, expected):
        assert detect_media_kind(pathlib.Path(filename)) == expected


class TestResolveWithinRoot:
    def test_resolves_valid_relative_path(self, arch_repo):
        resolved = resolve_within_root(str(arch_repo), "architecture/hld.md")
        assert resolved == arch_repo / "architecture" / "hld.md"

    def test_rejects_parent_traversal(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            resolve_within_root(str(arch_repo), "../outside.md")

    def test_rejects_absolute_escape_via_symlink_style_path(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            resolve_within_root(str(arch_repo), "architecture/../../outside.md")

    def test_raises_not_found_for_missing_file(self, arch_repo):
        with pytest.raises(DocsFileNotFoundError):
            resolve_within_root(str(arch_repo), "does-not-exist.md")


class TestBuildDocsTree:
    def test_builds_nested_tree_with_media_kinds(self, arch_repo):
        tree = build_docs_tree(str(arch_repo))

        assert tree["node_type"] == "directory"
        assert tree["path"] == ""
        names = {child["name"] for child in tree["children"]}
        assert names == {"README.md", "architecture", "config.json", "logo.png"}

        readme = next(child for child in tree["children"] if child["name"] == "README.md")
        assert readme["node_type"] == "file"
        assert readme["media_kind"] == "markdown"
        assert readme["size"] > 0
        assert readme["modified_at"]

        architecture = next(child for child in tree["children"] if child["name"] == "architecture")
        assert architecture["node_type"] == "directory"
        assert {c["name"] for c in architecture["children"]} == {"hld.md", "tech-stack.yaml"}

    def test_excludes_symlink_pointing_outside_root(self, arch_repo, tmp_path):
        outside_dir = tmp_path / "escape_target"
        outside_dir.mkdir()
        (arch_repo / "escape_link").symlink_to(outside_dir)

        tree = build_docs_tree(str(arch_repo))

        names = {child["name"] for child in tree["children"]}
        assert "escape_link" not in names

    def test_excludes_symlink_pointing_to_file_inside_root(self, arch_repo):
        (arch_repo / "linked.md").symlink_to(arch_repo / "README.md")

        tree = build_docs_tree(str(arch_repo))

        names = {child["name"] for child in tree["children"]}
        assert "linked.md" not in names


class TestReadDocsFile:
    def test_reads_markdown_file_content(self, arch_repo):
        result = read_docs_file(str(arch_repo), "README.md")

        assert result["media_kind"] == "markdown"
        assert result["content"] == "# Title\n"
        assert result["encoding"] == "utf-8"
        assert result["size"] > 0

    def test_returns_metadata_only_for_unsupported_binary(self, arch_repo):
        result = read_docs_file(str(arch_repo), "logo.png")

        assert result["media_kind"] == "unsupported"
        assert result["content"] is None
        assert result["encoding"] is None

    def test_degrades_to_unsupported_on_unicode_decode_error(self, arch_repo):
        (arch_repo / "binary.md").write_bytes(b"\xff\xfe\x00\x01")

        result = read_docs_file(str(arch_repo), "binary.md")

        assert result["media_kind"] == "unsupported"
        assert result["content"] is None
        assert result["encoding"] is None

    def test_rejects_path_traversal(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            read_docs_file(str(arch_repo), "../outside.md")

    def test_raises_not_found_for_missing_file(self, arch_repo):
        with pytest.raises(DocsFileNotFoundError):
            read_docs_file(str(arch_repo), "missing.md")


class TestDeleteDocsPath:
    def test_deletes_file(self, arch_repo):
        delete_docs_path(str(arch_repo), "README.md")

        assert not (arch_repo / "README.md").exists()

    def test_deletes_directory_recursively(self, arch_repo):
        delete_docs_path(str(arch_repo), "architecture")

        assert not (arch_repo / "architecture").exists()

    def test_rejects_path_traversal(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            delete_docs_path(str(arch_repo), "../outside.md")

    def test_rejects_deleting_root(self, arch_repo):
        with pytest.raises(DocsPathForbiddenError):
            delete_docs_path(str(arch_repo), "")

    def test_raises_not_found_for_missing_path(self, arch_repo):
        with pytest.raises(DocsFileNotFoundError):
            delete_docs_path(str(arch_repo), "missing.md")
