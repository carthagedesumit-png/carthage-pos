"""In-process scheduling policy foundation for externally triggered backup runs."""

from calendar import monthrange
from datetime import datetime, timedelta, timezone

from app.backup.backup_service import create_backup
from app.backup.permissions import require_backup_access, require_backup_admin
from app.backup.storage import append_audit, backup_directory, write_json_atomic
from app.core.config import get_config
from app.core.exceptions import BackupError
from app.core.logging_utils import get_logger, log_event


VALID_SCHEDULES = {"MANUAL", "DAILY", "WEEKLY", "MONTHLY"}
logger = get_logger("backup.scheduler")


def get_scheduler_configuration(session) -> dict:
    require_backup_access(session)
    return _load_configuration()


def update_scheduler_configuration(session, schedule: str, enabled: bool = True) -> dict:
    session = require_backup_admin(session)
    schedule = str(schedule or "").strip().upper()
    if schedule not in VALID_SCHEDULES:
        raise BackupError("Schedule must be MANUAL, DAILY, WEEKLY, or MONTHLY.")
    configuration = _load_configuration()
    configuration.update({"schedule": schedule, "enabled": bool(enabled) and schedule != "MANUAL"})
    configuration["next_run_at"] = _next_run(datetime.now(timezone.utc), schedule).isoformat() \
        if configuration["enabled"] else None
    write_json_atomic(_configuration_path(), configuration)
    append_audit("backup_scheduler_updated", session, schedule=schedule,
                 enabled=configuration["enabled"])
    log_event(logger, "backup_scheduler_updated", schedule=schedule,
              enabled=configuration["enabled"], user_id=session.user_id)
    return configuration


def run_scheduled_backup(session, now: datetime | None = None) -> dict:
    """Run a backup only when policy is due; intended for a future app timer hook."""
    session = require_backup_access(session)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    configuration = _load_configuration()
    if not configuration["enabled"] or configuration["schedule"] == "MANUAL":
        return {"ran": False, "reason": "Scheduler is manual or disabled.",
                "configuration": configuration}
    next_run = datetime.fromisoformat(configuration["next_run_at"]) \
        if configuration.get("next_run_at") else now
    if now < next_run:
        return {"ran": False, "reason": "Backup is not due.", "configuration": configuration}
    backup = create_backup(session, name=f"scheduled-{now.strftime('%Y%m%d-%H%M%S')}")
    configuration.update({
        "last_run_at": now.isoformat(),
        "last_backup_id": backup["backup_id"],
        "next_run_at": _next_run(now, configuration["schedule"]).isoformat(),
    })
    write_json_atomic(_configuration_path(), configuration)
    return {"ran": True, "backup": backup, "configuration": configuration}


def _configuration_path():
    return backup_directory() / "scheduler.json"


def _load_configuration() -> dict:
    path = _configuration_path()
    if path.is_file():
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schedule") in VALID_SCHEDULES:
                return data
        except (OSError, ValueError):
            pass
    schedule = get_config().backup.schedule
    enabled = schedule != "MANUAL"
    now = datetime.now(timezone.utc)
    return {
        "schedule": schedule,
        "enabled": enabled,
        "last_run_at": None,
        "last_backup_id": None,
        "next_run_at": _next_run(now, schedule).isoformat() if enabled else None,
    }


def _next_run(now: datetime, schedule: str) -> datetime:
    if schedule == "DAILY":
        return now + timedelta(days=1)
    if schedule == "WEEKLY":
        return now + timedelta(days=7)
    if schedule == "MONTHLY":
        year, month = now.year, now.month + 1
        if month == 13:
            year, month = year + 1, 1
        return now.replace(year=year, month=month,
                           day=min(now.day, monthrange(year, month)[1]))
    return now
