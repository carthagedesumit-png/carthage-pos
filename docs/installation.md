# Windows Installation and Deployment

## System Requirements

- Windows 10 or Windows 11, x64-compatible system.
- 4 GB RAM minimum; 8 GB recommended.
- 500 MB application space plus database, logs, documents, and backups.
- Write access to the selected database and backup locations.
- Optional 58mm/80mm receipt printer and keyboard-wedge barcode scanner.
- Network paths must already be mounted and accessible to the Windows user.

The packaged application includes its Python runtime. Building a release requires
Python, `requirements-build.txt`, and Inno Setup 6. Production releases should
sign both executables and the installer with the organization's code-signing
certificate.

## Release Build

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
.\installer\build.ps1
```

`build.ps1` creates `CarthagePOS.exe` and `CarthagePOSDeployment.exe` with
PyInstaller, then compiles `installer/carthage-pos.iss`. Add
`installer/assets/carthage-pos.ico` before release to apply branded icons.
Version constants, `version_info.txt`, and the Inno Setup version must be updated
together during a release.

## Fresh Installation

1. Run the signed `CarthagePOS-Setup-<version>.exe` as an administrator.
2. Select the installation directory and optional desktop shortcut.
3. Complete the first-run setup window/console.
4. Enter business/store names and a strong administrator account.
5. Select database and backup locations.
6. Choose printer profile, currency, decimal tax rate, and timezone.
7. Setup generates `config/carthage-pos.env` without storing the password.
8. A staging database is migrated, default system/store/category/supplier data
   is created, the administrator is hashed with bcrypt, and integrity is checked.
9. Only a verified database is atomically moved into the selected location.

The generated configuration also establishes API, logging, hardware, backup,
and update defaults. `deployment.json` records non-sensitive installation state.

## Upgrade

Run the newer installer over the existing installation. The deployment manager:

1. Reads installed version and configuration metadata.
2. Checks application, installer, and database compatibility.
3. Creates a SQLite rollback snapshot.
4. Applies migrations and verifies integrity.
5. Restores the previous database automatically if upgrade validation fails.
6. Retains the rollback snapshot under the installation `rollback` directory.

Application binaries are replaced by Inno Setup. Business databases and backups
are never overwritten by the file-copy phase.

## Repair

Use **Repair Carthage POS** from the Start Menu or run:

```powershell
CarthagePOSDeployment.exe repair --install-dir "C:\Program Files\Carthage POS"
```

Repair recreates missing runtime directories, reconstructs the generated
environment file from non-sensitive deployment state, reapplies migrations,
verifies the database, and rebuilds Windows integration metadata. It creates a
rollback snapshot before touching the database.

## Uninstall

Programs and Features invokes the deployment cleanup and then removes packaged
application files. The default uninstall preserves the business database and
backup directory. Full data removal is deliberately separate:

```powershell
CarthagePOSDeployment.exe uninstall --install-dir "C:\Program Files\Carthage POS" `
  --remove-data --confirmation REMOVE-ALL-DATA
```

Only backup files inside a directory carrying the installer ownership marker are
removed. Unrelated files in a shared backup directory are preserved.

## Update Architecture

This milestone does not perform internet updates. Update manifests declare a
semantic version, channel, package name/size, SHA-256 checksum, supported
database range, and minimum installer version. `DownloadAdapter` separates
future HTTPS/BITS delivery from local-file testing.

Staging performs channel/version/compatibility checks, copies through an adapter,
verifies size and SHA-256, and writes `updates/update-state.json`. It never runs
the package. Rollback metadata retains the current version and requires a
database backup before a future update executor swaps binaries.

Channels are `stable`, `beta`, and `development`. A stable installation never
accepts beta/development manifests.

## Configuration Additions

- `POS_INSTALLATION_DIRECTORY`, `POS_DEPLOYMENT_STATE_FILE`
- `POS_CURRENCY`, `POS_TIMEZONE`
- `POS_LOG_LEVEL`, `POS_LOG_DIRECTORY`
- `POS_API_HOST`, `POS_API_PORT`
- `POS_UPDATE_CHANNEL`, `POS_UPDATE_MANIFEST`, `POS_AUTO_UPDATE_CHECK`

Set `CARTHAGE_POS_ENV_FILE` to load a non-default generated environment file.

## Troubleshooting

- **Setup cannot write a folder:** choose a writable data/backup location or run
  the signed installer with administrator rights.
- **Database initialization failed:** review `logs/deployment-audit.jsonl`; the
  staging database is removed automatically.
- **Repair says database missing:** confirm `CARTHAGE_POS_DB` in the environment
  file and restore from the latest verified backup.
- **Printer unavailable:** installation can complete; hardware verification is
  a warning and the POS continues with safe printer fallback.
- **Update rejected:** verify channel, semantic version, package size/checksum,
  database range, and minimum installer version.
- **Timezone unavailable in packaged Windows:** `UTC` always works; other IANA
  names are retained safely even when the optional timezone database is absent.

Run deployment verification from the API, deployment executable, or:

```powershell
python deployment_cli.py verify --install-dir "C:\Program Files\Carthage POS"
```
