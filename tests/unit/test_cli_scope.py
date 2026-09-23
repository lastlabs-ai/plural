"""`plural auth` scope selection and `plural project init --push` registration."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from hosted_fake import FakeHosted, Key, routed
from project_fixtures import write_project
from typer.testing import CliRunner

from plural.auth import load_config
from plural.cli.main import app
from plural.project import Project

runner = CliRunner()


def _hasher(collection: str, slug: str, payload: dict[str, object]) -> str:
    raise AssertionError("scope tests never push resources")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, home: Path, tmp_path: Path) -> Iterator[FakeHosted]:
    hosted = FakeHosted(_hasher)
    hosted.keys["restricted"] = Key(kind="api_key", account_id="acc_personal", project_id="")
    monkeypatch.chdir(tmp_path)
    with routed(monkeypatch, hosted):
        yield hosted


def cli(*args: str, stdin: str | None = None) -> tuple[int, str]:
    result = runner.invoke(app, list(args), input=stdin)
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    return result.exit_code, result.output


def scope() -> dict[str, object]:
    code, output = cli("auth", "scope", "--json")
    assert code == 0, output
    return dict(json.loads(output))


def login(token: str = "token") -> None:
    code, output = cli("auth", "login", "--api-key-stdin", stdin=f"{token}\n")
    assert code == 0, output


def test_login_stores_the_credential_outside_the_project(
    fake: FakeHosted, home: Path, tmp_path: Path
) -> None:
    project = write_project(tmp_path / "support-desk")
    login()
    stored = [path for path in home.rglob("*") if path.is_file()]
    assert any("token" in path.read_text() for path in stored)
    for path in project.root.rglob("*"):
        if path.is_file():
            assert "token" not in path.read_text()


def test_scope_defaults_to_the_personal_account(fake: FakeHosted) -> None:
    login()
    payload = scope()
    assert payload["scope"] == "account"
    assert payload["account_id"] == "acc_personal"
    assert payload["project"] is None


def test_project_scope_is_validated_before_it_is_saved(fake: FakeHosted, home: Path) -> None:
    fake.add_project("support-desk")
    login()

    code, output = cli("auth", "scope", "--project", "support-desk")
    assert code == 0, output
    assert scope()["project"] == "support-desk"

    before = (home / "config.toml").read_text()
    code, output = cli("auth", "scope", "-p", "missing")
    assert code == 1
    assert "plural project init missing --push" in output
    assert scope()["project"] == "support-desk"
    assert (home / "config.toml").read_text() == before

    code, output = cli("auth", "scope", ".")
    assert code == 0, output
    assert scope()["scope"] == "account"
    assert cli("auth", "scope", "--project", "support-desk")[0] == 0
    assert cli("auth", "scope", "--account")[0] == 0
    assert scope()["scope"] == "account"


def test_scope_keeps_the_organization_context(fake: FakeHosted) -> None:
    fake.add_project("evals", account_id="acc_org")
    login()
    code, output = cli("auth", "scope", "--org", "acme")
    assert code == 0, output
    assert scope()["account_id"] == "acc_org"

    code, output = cli("auth", "scope", "--project", "evals")
    assert code == 0, output
    payload = scope()
    assert payload["account_id"] == "acc_org"
    assert payload["project"] == "evals"
    assert load_config().profiles["default"].account_slug == "acme"

    code, output = cli("auth", "scope", "--org", "missing")
    assert code == 1
    assert "Available: me, acme" in output
    assert scope()["project"] == "evals"


def test_scope_never_widens_a_project_limited_key(fake: FakeHosted) -> None:
    mine = fake.add_project("support-desk")
    fake.add_project("other")
    fake.keys["restricted"].project_id = mine["id"]
    login("restricted")

    assert cli("auth", "scope", "-p", "support-desk")[0] == 0
    for args in (("auth", "scope", "."), ("auth", "scope", "-p", "other")):
        code, output = cli(*args)
        assert code == 1
        assert scope()["project"] == "support-desk"
    code, output = cli("auth", "scope", ".")
    assert "limited to one project" in output
    code, output = cli("auth", "status", "--json")
    assert code == 0, output
    assert json.loads(output)["status"]["project_id"] == mine["id"]


def test_project_init_works_offline(fake: FakeHosted, tmp_path: Path) -> None:
    code, output = cli("project", "init", "support-desk")
    assert code == 0, output
    root = tmp_path / "support-desk"
    for name in ("project.yaml", "pyproject.toml", "README.md"):
        assert (root / name).is_file()
    assert Project.at(root).read_binding() is None
    assert fake.requests == []


def test_project_init_push_creates_a_private_project_and_selects_it(
    fake: FakeHosted, tmp_path: Path
) -> None:
    login()
    code, output = cli("project", "init", "support-desk", "--push")
    assert code == 0, output
    assert "(private)" in output
    [record] = fake.projects.values()
    assert record["visibility"] == "private"
    binding = Project.at(tmp_path / "support-desk").read_binding()
    assert binding is not None and binding.project_id == record["id"]
    assert scope()["project"] == "support-desk"
    binding_text = (tmp_path / "support-desk/.plural").rglob("*")
    assert all("token" not in path.read_text() for path in binding_text if path.is_file())


def test_project_init_push_registers_an_existing_project_without_overwriting(
    fake: FakeHosted, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = write_project(tmp_path / "support-desk")
    existing = fake.add_project("support-desk")
    readme = (project.root / "README.md").read_text()
    login()
    monkeypatch.chdir(project.root / "tasks")

    code, output = cli("project", "init", "support-desk", "--push")
    assert code == 0, output
    assert "leaving its files as they are" in output
    assert list(fake.projects) == [existing["id"]]
    assert (project.root / "README.md").read_text() == readme
    binding = project.read_binding()
    assert binding is not None and binding.project_id == existing["id"]

    creates = len(fake.writes)
    assert cli("project", "init", "support-desk", "--push")[0] == 0
    assert len(fake.writes) == creates

    code, output = cli("project", "init", "other")
    assert code == 1
    assert "cannot be nested" in output


def test_a_project_limited_key_cannot_create_projects(fake: FakeHosted, tmp_path: Path) -> None:
    mine = fake.add_project("support-desk")
    fake.keys["restricted"].project_id = mine["id"]
    login("restricted")
    code, output = cli("project", "init", "new-project", "--push")
    assert code == 1
    assert "cannot create projects" in output
    assert len(fake.projects) == 1


def test_project_show_prefers_local_then_hosted(fake: FakeHosted, tmp_path: Path) -> None:
    write_project(tmp_path / "support-desk")
    fake.add_project("hosted-only")
    login()
    code, output = cli("project", "show", "support-desk", "--json")
    assert code == 0, output
    assert json.loads(output)["location"] == "local"
    code, output = cli("project", "show", "hosted-only", "--json")
    assert code == 0, output
    assert json.loads(output)["location"] == "hosted"
    code, output = cli("project", "show", "hosted-only", "--local")
    assert code == 1


def test_there_is_no_project_push_command(fake: FakeHosted) -> None:
    code, _ = cli("project", "push")
    assert code != 0
