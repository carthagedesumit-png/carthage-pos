# CBOS RC Build

## Authoritative Version

The v1.0 release candidate version is defined once in
`app/core/version.py` as `APP_VERSION`. Installer version metadata, release
manifests, dashboard/API version output, startup logs, and generated
PyInstaller metadata derive from that source.

Current RC:

```text
1.0.0-rc.1
```

Do not edit `installer/version_info.txt` or `installer/carthage-pos.iss` to set
the RC version. The build scripts generate or pass version metadata at build
time.

## Build Command

Install build requirements and run the RC build command from the repository
root:

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
.\scripts\build_rc.ps1
```

The script fails fast if tests, whitespace validation, PyInstaller, artifact
validation, manifest generation, or checksum verification fails. Inno Setup 6
is required unless `-SkipInstaller` is supplied.

Outputs are written to:

```text
release\CBOS-<version>\
```

The release directory contains packaged executables, optional installer output,
`release-manifest.json`, `checksums.txt`, `artifact-inventory.json`,
`build-validation.json`, and `release-evidence.json`.

## Validation

Validate an existing release directory:

```powershell
python .\scripts\validate_release.py validate --release-dir .\release\CBOS-1.0.0-rc.1 --require-executables
```

Generate or refresh release evidence:

```powershell
python .\scripts\validate_release.py evidence --release-dir .\release\CBOS-1.0.0-rc.1 --require-executables
```

The validator checks:

- authoritative version consistency
- release manifest compatibility
- SHA-256 checksum integrity
- packaged dashboard templates/static assets
- executable presence when requested
- installer presence when requested
- prohibited release files such as databases, `.env`, bytecode, tests, caches,
  and logs

Do not report installer success unless the Inno Setup compiler actually builds
the setup artifact.
