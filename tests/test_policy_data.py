import copy
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import Base, make_engine
from app.core.errors import AppError
from app.models import Policy, PolicyAction, PolicySource, PolicyVersion
from app.modules.policies.schemas import PolicyImportFile, PolicyVersionInput
from app.modules.policies.service import (
    PolicyImportError,
    get_policy_context,
    get_version_context,
    import_policies,
)
from scripts import import_policies as cli


@pytest.fixture
def policy_item():
    data = json.loads(Path("examples/policies.example.json").read_text(encoding="utf-8"))
    item = data["policies"][0]
    item["is_example"] = False
    item["sources"][0]["kind"] = "official_page"
    return item


@pytest.fixture
def policy_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'policy.db'}")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def batch_for(*items):
    return PolicyImportFile.model_validate({"schema_version": 1, "policies": list(items)})


def register(engine, *items):
    with Session(engine) as db, db.begin():
        return import_policies(db, batch_for(*items))


def test_registration_roundtrip_and_idempotency(policy_engine, policy_item):
    assert register(policy_engine, policy_item) == {"created": 1, "unchanged": 0}
    assert register(policy_engine, policy_item) == {"created": 0, "unchanged": 1}
    with Session(policy_engine) as db:
        policy = db.scalar(select(Policy))
        result = get_policy_context(db, policy.id, date(2026, 11, 27))
        assert result.title == policy_item["title"] and result.state == "active"
        assert result.policy_id == policy.id and result.version == 1
        assert result.sources[0].url == "https://example.invalid/policy"
        assert result.eligibility.additional_requirements
        assert result.actions[0].due_date is None
        assert get_version_context(db, result.version_id).actions[0].id == result.actions[0].id
        for model in (Policy, PolicyVersion, PolicyAction, PolicySource):
            assert db.scalar(select(func.count()).select_from(model)) == 1


def test_version_history_dates_and_ended_policy_never_fall_back(policy_engine, policy_item):
    register(policy_engine, policy_item)
    changed = copy.deepcopy(policy_item)
    changed.update(version=2, effective_from="2026-06-01", change_summary="Changed")
    changed["actions"][0]["due_date"] = "2026-06-30"
    register(policy_engine, changed)
    ended = copy.deepcopy(changed)
    ended.update(
        version=3, effective_from="2026-10-01", effective_until=None, lifecycle="ended", actions=[]
    )
    register(policy_engine, ended)
    with Session(policy_engine) as db:
        policy_id = db.scalar(select(Policy.id))
        with pytest.raises(AppError) as error:
            get_policy_context(db, policy_id, date(2025, 12, 31))
        assert error.value.code == "POLICY_NOT_EFFECTIVE"
        assert get_policy_context(db, policy_id, date(2026, 5, 31)).version == 1
        assert get_policy_context(db, policy_id, date(2026, 6, 1)).version == 2
        context = get_policy_context(db, policy_id, date(2026, 10, 1))
        assert (context.version, context.state, context.actions) == (3, "ended", [])
        old = db.scalar(select(PolicyVersion).where(PolicyVersion.version == 1))
        assert old.content == policy_item["content"]
    assert register(policy_engine, policy_item) == {"created": 0, "unchanged": 1}


def test_expiry_is_inclusive_and_newer_expired_version_does_not_restore_old(
    policy_engine, policy_item
):
    register(policy_engine, policy_item)
    changed = copy.deepcopy(policy_item)
    changed.update(version=2, effective_from="2026-06-01", effective_until="2026-06-30")
    register(policy_engine, changed)
    with Session(policy_engine) as db:
        policy_id = db.scalar(select(Policy.id))
        assert get_policy_context(db, policy_id, date(2026, 6, 30)).state == "active"
        context = get_policy_context(db, policy_id, date(2026, 7, 1))
        assert (context.version, context.state) == (2, "expired")


@pytest.mark.parametrize(
    "change,code",
    [
        ({"summary": "overwrite"}, "POLICY_VERSION_IMMUTABLE"),
        ({"version": 3}, "POLICY_VERSION_SEQUENCE"),
        ({"version": 2, "effective_from": "2025-12-31"}, "POLICY_EFFECTIVE_ORDER"),
        ({"is_example": True}, "POLICY_EXAMPLE_CONFLICT"),
    ],
)
def test_conflicts_are_atomic(policy_engine, policy_item, change, code):
    register(policy_engine, policy_item)
    conflict = copy.deepcopy(policy_item)
    conflict.update(change)
    if conflict["is_example"]:
        conflict["sources"][0]["kind"] = "example"
    extra = copy.deepcopy(policy_item)
    extra["policy_key"] = "aaa-imported-first"
    with pytest.raises(PolicyImportError, match=code):
        register(policy_engine, extra, conflict)
    with Session(policy_engine) as db:
        assert db.scalar(select(func.count()).select_from(Policy)) == 1
        assert db.scalar(select(func.count()).select_from(PolicyVersion)) == 1


def test_correction_with_same_effective_date_uses_new_version(policy_engine, policy_item):
    register(policy_engine, policy_item)
    policy_item.update(version=2, summary="Reviewed correction")
    register(policy_engine, policy_item)
    with Session(policy_engine) as db:
        policy_id = db.scalar(select(Policy.id))
        assert get_policy_context(db, policy_id, date(2026, 1, 1)).version == 2


def test_reordered_sets_do_not_change_digest(policy_engine, policy_item):
    policy_item["eligibility"]["region_codes"] = ["seoul", "busan"]
    register(policy_engine, policy_item)
    policy_item["eligibility"]["region_codes"].reverse()
    assert register(policy_engine, policy_item)["unchanged"] == 1


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("policy", "version", True),
        ("policy", "version", "1"),
        ("policy", "is_example", "false"),
        ("policy", "effective_from", 1767225600),
        ("policy", "effective_from", "2026-02-30"),
        ("policy", "effective_from", "2026-01-01T00:00:00Z"),
        ("policy", "effective_until", "2025-01-01"),
        ("policy", "title", "   "),
        ("policy", "category", "arbitrary"),
        ("policy", "policy_key", "../invalid"),
        ("policy", "unexpected", "secret"),
        ("eligibility", "age_min", 151),
        ("eligibility", "age_max", 18),
        ("eligibility", "region_codes", ["seoul", "seoul"]),
        ("eligibility", "transport_cards", ["other_or_none"]),
        ("eligibility", "requires_confirmation", False),
        ("source", "reuse_confirmed", False),
        ("source", "reuse_confirmed", "true"),
        ("source", "checked_on", "2026-11-28"),
        ("source", "kind", "example"),
        ("source", "url", "http://example.invalid/policy"),
        ("source", "url", "https://secret@example.invalid/policy"),
        ("source", "url", "https://example.invalid/?serviceKey=secret"),
        ("source", "url", "https://example.invalid/#secret"),
        ("source", "url", "https://example.invalid:bad/"),
        ("action", "due_date", "2026-09-31"),
        ("action", "url", "javascript:alert(1)"),
    ],
)
def test_invalid_file_values_rejected(policy_item, target, field, value):
    node = {
        "policy": policy_item,
        "eligibility": policy_item["eligibility"],
        "source": policy_item["sources"][0],
        "action": policy_item["actions"][0],
    }[target]
    node[field] = value
    with pytest.raises(ValidationError):
        PolicyVersionInput.model_validate(policy_item)


@pytest.mark.parametrize("field", ["sources", "actions"])
def test_duplicate_child_keys_rejected(policy_item, field):
    policy_item[field].append(copy.deepcopy(policy_item[field][0]))
    with pytest.raises(ValidationError):
        batch_for(policy_item)


def test_duplicate_policy_rejected(policy_item):
    with pytest.raises(ValidationError):
        batch_for(policy_item, policy_item)


def test_future_review_rejected_without_db(policy_item, monkeypatch, tmp_path, capsys):
    policy_item["reviewed_on"] = "2099-01-01"
    file = tmp_path / "future.json"
    file.write_text(json.dumps({"schema_version": 1, "policies": [policy_item]}), encoding="utf-8")
    monkeypatch.setattr(
        cli, "get_settings", lambda: pytest.fail("Validation must not read DB settings")
    )
    assert cli.main([str(file)]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "POLICY_FUTURE_REVIEW"


def test_cli_default_does_not_load_settings_or_connect(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: pytest.fail("No settings access allowed"))
    monkeypatch.setattr(
        cli, "make_engine", lambda *args, **kwargs: pytest.fail("No DB connection allowed")
    )
    assert cli.main(["examples/policies.example.json"]) == 0
    assert json.loads(capsys.readouterr().out)["database"] == "not_connected"


def test_cli_apply_and_repeat_use_one_transaction(policy_engine, monkeypatch, capsys):
    from app.core.config import Settings

    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, database_url=str(policy_engine.url))
    )
    assert cli.main(["examples/policies.example.json", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["created"] == 1
    assert cli.main(["examples/policies.example.json", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["unchanged"] == 1


def test_example_remote_apply_rejected_before_connect(monkeypatch, capsys):
    from app.core.config import Settings

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(
            _env_file=None, database_url="postgresql://fake:fake@fake.supabase.co/postgres"
        ),
    )
    monkeypatch.setattr(cli, "make_engine", lambda *args, **kwargs: pytest.fail("Must not connect"))
    assert cli.main(["examples/policies.example.json", "--apply"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "POLICY_EXAMPLE_TARGET_FORBIDDEN"


@pytest.mark.parametrize("override", ["production", "hostaddr", "service", "query"])
def test_example_target_overrides_blocked_before_connect(monkeypatch, capsys, override):
    from types import SimpleNamespace

    from app.core.database_url import resolve_database_url

    url = "postgresql://fake:fake@localhost/boso_test"
    if override == "query":
        url += "?service=remote"
    if override in {"hostaddr", "service"}:
        monkeypatch.setenv(
            "PGHOSTADDR" if override == "hostaddr" else "PGSERVICE", "test-only-override"
        )
    settings = SimpleNamespace(
        app_env="production" if override == "production" else "development",
        get_database_url=lambda: resolve_database_url(url),
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "make_engine", lambda *args, **kwargs: pytest.fail("Must not connect"))
    assert cli.main(["examples/policies.example.json", "--apply"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "POLICY_EXAMPLE_TARGET_FORBIDDEN"


def test_specific_climate_card_requires_confirmation(policy_item):
    policy_item["eligibility"].update(
        transport_cards=["climate_card"], additional_requirements=[], requires_confirmation=False
    )
    with pytest.raises(ValidationError):
        batch_for(policy_item)


@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_schema_version_requires_an_integer(policy_item, value):
    with pytest.raises(ValidationError):
        PolicyImportFile.model_validate({"schema_version": value, "policies": [policy_item]})


def test_future_version_does_not_replace_current_version_early(policy_engine, policy_item):
    register(policy_engine, policy_item)
    policy_item.update(version=2, effective_from="2027-01-01", effective_until=None)
    register(policy_engine, policy_item)
    with Session(policy_engine) as db:
        policy_id = db.scalar(select(Policy.id))
        assert get_policy_context(db, policy_id, date(2026, 12, 31)).version == 1
        assert get_policy_context(db, policy_id, date(2027, 1, 1)).version == 2


@pytest.mark.parametrize(
    "payload,code",
    [
        (b'{"schema_version":1,"schema_version":1}', "POLICY_DUPLICATE_JSON_KEY"),
        (b"x" * (cli.MAX_FILE_BYTES + 1), "POLICY_FILE_TOO_LARGE"),
        (b"not-json secret", "POLICY_FILE_INVALID"),
        (b"\xffsecret", "POLICY_FILE_INVALID"),
    ],
    ids=["duplicate-key", "oversized", "malformed", "invalid-utf8"],
)
def test_cli_invalid_files_never_echo_contents(tmp_path, capsys, payload, code):
    file = tmp_path / "secret.json"
    file.write_bytes(payload)
    assert cli.main([str(file)]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == code
    assert "secret" not in output


def test_cli_commit_failure_never_reports_success(policy_engine, monkeypatch, capsys):
    from app.core.config import Settings

    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, database_url=str(policy_engine.url))
    )

    class FailingSession(Session):
        def commit(self):
            raise RuntimeError("secret driver URL")

    # Session.begin() commits via SessionTransaction, not Session.commit().
    from sqlalchemy import event

    def fail_commit(session):
        raise RuntimeError("secret driver URL")

    event.listen(FailingSession, "before_commit", fail_commit)
    monkeypatch.setattr(cli, "Session", FailingSession)
    assert cli.main(["examples/policies.example.json", "--apply"]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "POLICY_IMPORT_FAILED"
    assert "secret" not in output and '"status": "ok"' not in output
    with Session(policy_engine) as db:
        assert db.scalar(select(func.count()).select_from(Policy)) == 0


def test_example_and_unknown_policies_are_not_exposed(policy_engine):
    batch = cli.load_file(Path("examples/policies.example.json"))
    with Session(policy_engine) as db, db.begin():
        import_policies(db, batch)
    with Session(policy_engine) as db:
        policy_id = db.scalar(select(Policy.id))
        version_id = db.scalar(select(PolicyVersion.id))
        for call in (
            lambda: get_policy_context(db, policy_id),
            lambda: get_policy_context(db, uuid4()),
            lambda: get_version_context(db, version_id),
            lambda: get_version_context(db, uuid4()),
        ):
            with pytest.raises(AppError) as error:
                call()
            assert error.value.status == 404
