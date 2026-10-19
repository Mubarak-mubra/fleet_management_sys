from extensions import db as _db


def test_shell_context_exposes_exactly_db_and_eight_models(app):
    ctx = app.make_shell_context()
    assert set(ctx.keys()) == {
        "app", "g", "db", "Vehicle", "TripLog", "FuelLog", "MaintenanceLog",
        "Driver", "Expense", "Project", "User"
    }


def test_shell_context_values(app):
    ctx = app.make_shell_context()
    assert ctx["db"] is _db
    from app.models import Driver, Expense, FuelLog, MaintenanceLog, TripLog, User, Vehicle

    assert ctx["Vehicle"] is Vehicle
    assert ctx["TripLog"] is TripLog
    assert ctx["FuelLog"] is FuelLog
    assert ctx["MaintenanceLog"] is MaintenanceLog
    assert ctx["Driver"] is Driver
    assert ctx["Expense"] is Expense


def test_init_db_cli_returns_zero(app, db):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    assert "created" in result.output.lower()


def test_init_db_cli_creates_eight_tables(app, db):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["init-db"])
    assert result.exit_code == 0, result.output
    names = sorted(db.inspect(db.engine).get_table_names())
    assert names == [
        "driver", "expense", "fuel_log", "maintenance_log", "project", "trip_log", "user", "vehicle"
    ]
