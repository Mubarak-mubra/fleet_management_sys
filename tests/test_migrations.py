import re
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app import create_app
from app.models import TripLog, Vehicle
from config import TestConfig
from extensions import db

REV_MSG = "initial schema: vehicle, vehicle_type, trip_log, fuel_log, maintenance_log, driver, expense, user, project"
APP_TABLES = ["driver", "expense", "fuel_log", "maintenance_log", "project", "trip_log", "user", "vehicle", "vehicle_type"]
REV_RE = re.compile(r"([0-9a-f]{12})_")


def _invoke(runner, *args):
    result = runner.invoke(args=list(args))
    assert result.exit_code == 0, result.output
    return result.output


def _tables(app):
    with app.app_context():
        names = sa_inspect(db.engine).get_table_names()
    return sorted(n for n in names if n != "alembic_version")


@pytest.fixture(scope="module")
def mig(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mig")
    mig_dir = tmp / "migrations"
    patcher = pytest.MonkeyPatch()
    patcher.setattr(TestConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp / 'mig.db'}")
    recorded = []
    original_print = AlembicConfig.print_stdout

    def _record(self, text, *args):
        recorded.append(str(text) % args if args else str(text))

    AlembicConfig.print_stdout = _record
    try:
        app = create_app("testing")
        runner = app.test_cli_runner()
        _invoke(runner, "db", "init", "-d", str(mig_dir))
        _invoke(runner, "db", "migrate", "-d", str(mig_dir), "-m", REV_MSG)
        yield {"app": app, "runner": runner, "dir": mig_dir, "printed": recorded}
    finally:
        AlembicConfig.print_stdout = original_print
        patcher.undo()


def _revision_file(mig):
    files = sorted(Path(mig["dir"], "versions").glob("*.py"))
    assert files, "no revision files generated"
    return files[0]


def test_db_init_creates_migrations_structure(mig):
    for name in ("alembic.ini", "env.py"):
        assert Path(mig["dir"], name).is_file(), name
    assert Path(mig["dir"], "versions").is_dir()


def test_db_migrate_creates_single_revision_with_all_table_names(mig):
    versions = sorted(Path(mig["dir"], "versions").glob("*.py"))
    assert len(versions) == 1, [v.name for v in versions]
    content = versions[0].read_text()
    match = re.search(r'"""(.*?)"""', content, re.S)
    assert match, "revision has no message docstring"
    message = match.group(1)
    for table in APP_TABLES:
        assert table in message, f"{table!r} missing from revision message"


def _current_output(mig):
    mig["printed"].clear()
    _invoke(mig["runner"], "db", "current", "-d", str(mig["dir"]))
    return "\n".join(mig["printed"])


def test_upgrade_then_stamp_head_then_current(mig):
    _invoke(mig["runner"], "db", "upgrade", "-d", str(mig["dir"]))
    _invoke(mig["runner"], "db", "stamp", "head", "-d", str(mig["dir"]))
    out = _current_output(mig)
    rev_id = REV_RE.search(_revision_file(mig).name).group(1)
    assert rev_id in out, out


def test_upgrade_creates_exactly_nine_app_tables(mig):
    _invoke(mig["runner"], "db", "upgrade", "-d", str(mig["dir"]))
    assert _tables(mig["app"]) == APP_TABLES


def test_downgrade_one_step_then_upgrade_roundtrip(mig):
    _invoke(mig["runner"], "db", "upgrade", "-d", str(mig["dir"]))
    _invoke(mig["runner"], "db", "downgrade", "-d", str(mig["dir"]), "--", "-1")
    assert _tables(mig["app"]) == []
    _invoke(mig["runner"], "db", "upgrade", "-d", str(mig["dir"]))
    assert _tables(mig["app"]) == APP_TABLES
    out = _current_output(mig)
    rev_id = REV_RE.search(_revision_file(mig).name).group(1)
    assert rev_id in out, out


def test_check_constraint_and_cascade_survive_migration(mig):
    _invoke(mig["runner"], "db", "upgrade", "-d", str(mig["dir"]))
    with mig["app"].app_context():
        vehicle = Vehicle(
            name="Migration Vehicle",
            plate_number="GC-MIG001",
            vehicle_type="excavator",
            status="active",
        )
        db.session.add(vehicle)
        db.session.commit()

        bad = TripLog(
            vehicle_id=vehicle.id,
            driver_name="Driver",
            purpose="Constraint check",
            origin="Yard",
            destination="Site",
            start_time=datetime(2026, 1, 2, 8, 0),
            end_time=datetime(2026, 1, 1, 8, 0),
            status="completed",
        )
        db.session.add(bad)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        fk_rows = db.session.execute(text("PRAGMA foreign_key_list(trip_log)")).fetchall()
        assert any(row[6] == "CASCADE" for row in fk_rows), fk_rows

        child = TripLog(
            vehicle_id=vehicle.id,
            driver_name="Driver",
            purpose="Cascade check",
            origin="Yard",
            destination="Site",
            start_time=datetime(2026, 1, 3, 8, 0),
            status="in_progress",
        )
        db.session.add(child)
        db.session.commit()
        child_id = child.id

        db.session.delete(vehicle)
        db.session.commit()
        assert db.session.get(TripLog, child_id) is None


def test_init_db_is_noop_on_migrated_database(mig):
    _invoke(mig["runner"], "db", "upgrade", "-d", str(mig["dir"]))
    before = _tables(mig["app"])
    out = _invoke(mig["runner"], "init-db")
    assert "Database initialized" in out
    assert _tables(mig["app"]) == before == APP_TABLES


def test_committed_migrations_upgrade_cleanly(tmp_path, monkeypatch):
    repo_migrations = Path(__file__).resolve().parent.parent / "migrations"
    versions = sorted((repo_migrations / "versions").glob("*.py"))
    assert len(versions) == 7, (
        "expected the initial, driver, expense, user, project, "
        "vehicle-type-text and vehicle-type-registry revisions"
    )

    # The revisions must form a single linear chain. `parents` collects every
    # revision that something points back at; a linear chain of N revisions has
    # exactly N-1 distinct parents, and the one revision left over is the head.
    parents = set()
    for v in versions:
        rev = REV_RE.search(v.name).group(1)
        links = re.findall(r"^down_revision = (.+)$", v.read_text(), re.M)
        assert len(links) == 1, f"{v.name}: expected one down_revision"
        if links[0].strip() != "None":
            parents.add(links[0].strip().strip("'\""))
    assert len(parents) == len(versions) - 1, (
        f"revisions do not form one chain: {len(versions)} files, "
        f"{len(parents)} distinct parents -> {parents}"
    )

    monkeypatch.setattr(
        TestConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{tmp_path / 'committed.db'}"
    )
    app = create_app("testing")
    runner = app.test_cli_runner()
    _invoke(runner, "db", "upgrade")
    assert _tables(app) == APP_TABLES

    # head is the revision nobody points at as a parent
    all_revs = {REV_RE.search(v.name).group(1) for v in versions}
    assert len(all_revs - parents) == 1, f"expected exactly one head, got {all_revs - parents}"
    head_rev = (all_revs - parents).pop()
    with app.app_context():
        stamped = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert stamped == head_rev

        vehicle = Vehicle(
            name="Committed Migration Vehicle",
            plate_number="GC-COMMIT1",
            vehicle_type="loader",
            status="active",
        )
        db.session.add(vehicle)
        db.session.commit()

        bad = TripLog(
            vehicle_id=vehicle.id,
            driver_name="Driver",
            purpose="Committed migration check",
            origin="Yard",
            destination="Site",
            start_time=datetime(2026, 2, 2, 8, 0),
            end_time=datetime(2026, 2, 1, 8, 0),
            status="completed",
        )
        db.session.add(bad)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        fk_rows = db.session.execute(text("PRAGMA foreign_key_list(trip_log)")).fetchall()
        # The batch recreate must not have lost either FK's ON DELETE action.
        by_table = {row[2]: row[6] for row in fk_rows}
        assert by_table.get("vehicle") == "CASCADE", fk_rows
        assert by_table.get("driver") == "SET NULL", fk_rows

        # ...nor the CHECK constraint, which SQLite reflection cannot see.
        ddl = db.session.execute(
            text("SELECT sql FROM sqlite_master WHERE name='trip_log'")
        ).scalar()
        assert "ck_trip_time" in ddl, ddl

