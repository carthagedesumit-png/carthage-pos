"""Role-enforced backup, restore, scheduler, and portable transfer endpoints."""

from fastapi import APIRouter, Depends, Query

from auth import UserSession
from app.api.dependencies import get_current_session
from app.api.pagination import data_response
from app.api.schemas import (
    BackupCreateRequest, BackupRestoreRequest, BackupSchedulerRequest,
    BackupVerifyRequest, DataImportRequest,
)
from app.backup.backup_service import (
    create_backup, delete_backup, get_backup_metadata, get_backup_status,
    list_backups, verify_backup,
)
from app.backup.restore_service import restore_backup
from app.backup.scheduler_service import (
    get_scheduler_configuration, update_scheduler_configuration,
)
from app.backup.transfer_service import export_resource, import_resource


router = APIRouter(prefix="/backups", tags=["backup and disaster recovery"])


@router.get("")
def backups(session: UserSession = Depends(get_current_session)):
    return data_response(list_backups(session))


@router.post("", status_code=201)
def backup_create(payload: BackupCreateRequest,
                  session: UserSession = Depends(get_current_session)):
    return data_response(create_backup(session, payload.name, payload.backup_type,
                                       payload.compression))


@router.get("/status")
def backup_status(session: UserSession = Depends(get_current_session)):
    return data_response(get_backup_status(session))


@router.post("/restore")
def backup_restore(payload: BackupRestoreRequest,
                   session: UserSession = Depends(get_current_session)):
    return data_response(restore_backup(
        session, payload.backup_id, use_latest=payload.use_latest,
        dry_run=payload.dry_run, confirmation=payload.confirmation,
    ))


@router.post("/verify")
def backup_verify(payload: BackupVerifyRequest,
                  session: UserSession = Depends(get_current_session)):
    return data_response(verify_backup(session, payload.backup_id))


@router.get("/scheduler")
def scheduler_get(session: UserSession = Depends(get_current_session)):
    return data_response(get_scheduler_configuration(session))


@router.post("/scheduler")
def scheduler_update(payload: BackupSchedulerRequest,
                     session: UserSession = Depends(get_current_session)):
    return data_response(update_scheduler_configuration(session, payload.schedule,
                                                         payload.enabled))


@router.get("/exports/{resource}")
def export(resource: str, format: str = Query(default="JSON", pattern="^(?i:JSON|CSV)$"),
           session: UserSession = Depends(get_current_session)):
    return data_response(export_resource(session, resource, format))


@router.post("/imports/{resource}")
def import_data(resource: str, payload: DataImportRequest,
                session: UserSession = Depends(get_current_session)):
    return data_response(import_resource(session, resource, payload.content, payload.format))


@router.get("/{backup_id}")
def backup_metadata(backup_id: str, session: UserSession = Depends(get_current_session)):
    return data_response(get_backup_metadata(session, backup_id))


@router.delete("/{backup_id}")
def backup_delete(backup_id: str, session: UserSession = Depends(get_current_session)):
    return data_response(delete_backup(session, backup_id))
