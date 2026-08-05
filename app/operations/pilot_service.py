"""Administrator diagnostics, maintenance, recovery, and dashboard preferences."""
import json,os,shutil,tempfile,time
from pathlib import Path
from auth import validate_session
from app.core.config import get_config
from app.core.exceptions import AuthorizationError,ValidationError
from app.core.version import APP_VERSION,DATABASE_SCHEMA_VERSION
from app.database.db_manager import get_connection,get_database_path
from app.database.transactions import transaction
STARTED_AT=time.time();ALLOWED_MAINTENANCE={'OPTIMIZE_DATABASE','CLEAN_TEMP','CLEAN_LOGS','VERIFY_BACKUPS','CLEAR_CACHE'}
STATUS_PASS='PASS';STATUS_UNVERIFIED='UNVERIFIED';STATUS_OPTIONAL='OPTIONAL';STATUS_WARNING='WARNING';STATUS_BLOCKING='BLOCKING'
def _admin(session):
    session=validate_session(session)
    if session.role!='admin':raise AuthorizationError('Administrator access is required.')
    return session
def diagnostics(session):
    session=_admin(session);config=get_config();database=Path(get_database_path());runtime=Path(config.deployment.log_directory).parent
    with get_connection() as conn:integrity=conn.execute('PRAGMA integrity_check').fetchone()[0];schema=conn.execute('PRAGMA user_version').fetchone()[0];modules=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    from app.licensing.license_service import get_license_status
    from app.deployment.update_service import get_update_status
    from app.backup.backup_service import list_backups
    from app.hardware.hardware_service import get_hardware_status
    def safe(default,call):
        try:return call()
        except Exception as exc:return {**default,'error':type(exc).__name__} if isinstance(default,dict) else default
    usage=shutil.disk_usage(database.parent);backups=safe([],lambda:list_backups(session))
    return {'application_version':APP_VERSION,'database_version':schema,'schema_version':DATABASE_SCHEMA_VERSION,'license':safe({'state':'UNKNOWN'},get_license_status),'backup':{'count':len(backups),'latest':backups[0] if backups else None},'update':safe({'status':'UNKNOWN'},get_update_status),'api':{'status':'READY','host':config.api.host,'port':config.api.port},'storage':{'database':str(database),'runtime':str(runtime),'free_bytes':usage.free,'total_bytes':usage.total,'integrity':integrity,'writable':os.access(database.parent,os.W_OK)},'configuration':{'currency':config.deployment.currency,'timezone':config.deployment.timezone,'printer_enabled':config.hardware.printer_enabled,'backup_schedule':config.backup.schedule},'uptime_seconds':round(time.time()-STARTED_AT,1),'installed_modules':modules,'background_jobs':{'backup_schedule':config.backup.schedule,'update_auto_check':config.updates.auto_check},'hardware':safe({'status':'UNKNOWN'},lambda:get_hardware_status(session)),'recovery':recovery_status(session),'pilot_readiness':pilot_readiness(session),'environment_file':'configured' if os.environ.get('CARTHAGE_POS_ENV_FILE') else 'installer/default'}
def recovery_status(session):
    _admin(session)
    with get_connection() as conn:integrity=conn.execute('PRAGMA quick_check').fetchone()[0];carts=[dict(r) for r in conn.execute("SELECT id,status,updated_at FROM checkout_carts WHERE status IN ('ACTIVE','SUSPENDED') ORDER BY updated_at")];pending=conn.execute("SELECT COUNT(*) FROM finance_posting_events WHERE status!='POSTED'").fetchone()[0]
    suggestions=[]
    if integrity!='ok':suggestions.append('Restore the latest verified backup.')
    if carts:suggestions.append('Review and resume or void unfinished checkout carts.')
    if pending:suggestions.append('Review failed or pending finance posting events.')
    return {'database_integrity':integrity,'unfinished_carts':carts,'pending_finance_events':pending,'suggestions':suggestions or ['No recovery action is currently required.']}

def pilot_readiness(session):
    """Return administrator-only, redacted readiness facts without probing hardware."""
    session=_admin(session);config=get_config()
    checks=[]
    def add(code,status,summary):checks.append({'code':code,'status':status,'summary':summary})
    try:
        with get_connection() as conn:
            schema=conn.execute('PRAGMA user_version').fetchone()[0]
            integrity=conn.execute('PRAGMA quick_check').fetchone()[0]
            stores=conn.execute('SELECT COUNT(*) FROM stores WHERE is_active=1').fetchone()[0]
            admins=conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]
        add('database',STATUS_PASS if integrity=='ok' and schema==DATABASE_SCHEMA_VERSION else STATUS_BLOCKING,
            'Database reachable and migration-compatible.' if integrity=='ok' and schema==DATABASE_SCHEMA_VERSION else 'Database integrity or migration compatibility requires attention.')
        add('bootstrap',STATUS_PASS if stores and admins else STATUS_BLOCKING,
            'Active store and administrator are present.' if stores and admins else 'An active store and administrator are required.')
    except Exception:
        add('database',STATUS_BLOCKING,'Database is not reachable.');add('bootstrap',STATUS_BLOCKING,'Bootstrap readiness could not be checked.')
    backup_path=Path(config.backup.directory)
    add('application_data',STATUS_PASS if os.access(Path(get_database_path()).parent,os.W_OK) else STATUS_BLOCKING,
        'Application data location is writable.' if os.access(Path(get_database_path()).parent,os.W_OK) else 'Application data location is not writable.')
    add('backup',STATUS_PASS if backup_path.exists() and os.access(backup_path,os.W_OK) else STATUS_WARNING,
        'Backup location is writable.' if backup_path.exists() and os.access(backup_path,os.W_OK) else 'Backup location is not yet writable.')
    from app.hardware.hardware_service import get_hardware_status
    hw=get_hardware_status(session)
    printer=hw['printer'];drawer=hw['cash_drawer']
    add('receipt_configuration',STATUS_PASS,f"Receipt profile {printer['profile']}; {config.hardware.receipt_copies} configured copy/copies.")
    add('printer',STATUS_UNVERIFIED if printer['enabled'] else STATUS_OPTIONAL,
        'Configured but physical communication is unverified.' if printer['enabled'] else 'Receipt printer is disabled.')
    add('cash_drawer',STATUS_UNVERIFIED if drawer['enabled'] else STATUS_OPTIONAL,
        'Configured but physical operation is unverified.' if drawer['enabled'] else 'Cash drawer is disabled.')
    from app.licensing.license_service import get_license_status
    try:license_state=get_license_status().get('state','UNKNOWN');license_status=STATUS_PASS if license_state not in {'INVALID','EXPIRED','UNKNOWN'} else STATUS_WARNING
    except Exception:license_state='UNKNOWN';license_status=STATUS_WARNING
    add('licensing',license_status,f'Licensing state: {license_state}.')
    add('physical_acceptance',STATUS_UNVERIFIED,'Windows clean-PC and real peripheral acceptance remain pending.')
    return {'application_version':APP_VERSION,'locations':{'application_data':'<application-data>','backup':'<backup-location>'},'checks':checks,
            'overall':STATUS_BLOCKING if any(x['status']==STATUS_BLOCKING for x in checks) else STATUS_WARNING if any(x['status']==STATUS_WARNING for x in checks) else STATUS_UNVERIFIED}
def run_maintenance(session,operation):
    session=_admin(session);operation=str(operation).upper()
    if operation not in ALLOWED_MAINTENANCE:raise ValidationError('Unsupported maintenance operation.')
    try:
        if operation=='OPTIMIZE_DATABASE':
            with get_connection() as conn:conn.execute('PRAGMA optimize');details={'integrity':conn.execute('PRAGMA integrity_check').fetchone()[0]}
        elif operation=='VERIFY_BACKUPS':
            from app.backup.backup_service import list_backups,verify_backup
            details={'verified':[verify_backup(session,x['backup_id']) for x in list_backups(session)]}
        elif operation in {'CLEAN_TEMP','CLEAN_LOGS'}:
            root=Path(tempfile.gettempdir()) if operation=='CLEAN_TEMP' else Path(get_config().deployment.log_directory);removed=0;patterns=['cbos-*.tmp','carthage-*.tmp'] if operation=='CLEAN_TEMP' else ['*.old','*.tmp']
            for pattern in patterns:
                for path in root.glob(pattern):
                    if path.is_file():path.unlink(missing_ok=True);removed+=1
            details={'removed':removed,'root':str(root)}
        else:
            from app.core.config import reset_config_cache
            reset_config_cache();details={'cache':'configuration'}
        status='COMPLETED'
    except Exception as exc:_history(session,operation,'FAILED',{'error':type(exc).__name__});raise
    _history(session,operation,status,details);return {'operation':operation,'status':status,'details':details}
def _history(session,operation,status,details):
    with transaction() as conn:conn.execute('INSERT INTO maintenance_history(operation,status,details,user_id) VALUES(?,?,?,?)',(operation,status,json.dumps(details,default=str,sort_keys=True),session.user_id))
def maintenance_history(session):
    _admin(session)
    with get_connection() as conn:return [dict(r) for r in conn.execute('SELECT * FROM maintenance_history ORDER BY id DESC LIMIT 100')]
def export_configuration(session):
    _admin(session);config=get_config();return {'company':config.company.__dict__,'api':config.api.__dict__,'backup':config.backup.__dict__,'hardware':config.hardware.__dict__,'version':1}
def save_preferences(session,preferences):
    session=validate_session(session);allowed={k:v for k,v in preferences.items() if k in {'favorites','saved_filters','compact_tables','quick_actions'}}
    with transaction() as conn:conn.execute("INSERT INTO user_dashboard_preferences(user_id,preferences) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET preferences=excluded.preferences,updated_at=CURRENT_TIMESTAMP",(session.user_id,json.dumps(allowed,sort_keys=True)))
    return allowed
def get_preferences(session):
    session=validate_session(session)
    with get_connection() as conn:row=conn.execute('SELECT preferences FROM user_dashboard_preferences WHERE user_id=?',(session.user_id,)).fetchone()
    return json.loads(row[0]) if row else {'favorites':[],'saved_filters':{},'quick_actions':[]}
