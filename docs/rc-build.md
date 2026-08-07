# CBOS RC Build

## Payment and reconciliation RC status

Repository automation covers recorded cash/card/transfer and split tenders,
checkout retry protection, references, partial/refund limits, stock restoration,
tender reporting, receipt output, and cash-session reconciliation. There is no
external gateway verification or banking settlement in this RC. Duplicate
card/transfer references are permitted because offline terminals can legitimately
reuse reference formats; operators should investigate duplicates operationally.

The clean second-PC installation and physical peripheral acceptance test remains
pending because the designated test computer is unavailable. Repository tests do
not replace that acceptance gate, and no second-PC pass is claimed.

## Authoritative Version

The v1.0 release candidate version is defined once in
`app/core/version.py` as `APP_VERSION`. Installer version metadata, release
manifests, dashboard/API version output, startup logs, and generated
PyInstaller metadata derive from that source.

Current RC:

```text
1.0.0-rc.2
```

## Source-only preflight

Before a future build, create canonical-suite evidence in an isolated directory
for the exact 12-character source commit, then run:

```powershell
python .\scripts\build_preflight.py --release-dir .\release\CBOS-1.0.0-rc.2 --test-evidence <isolated-test-evidence.json> [--iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"]
```

The evidence JSON contains `source_commit`, `application_version`, `status` set
to `passed`, and a positive `test_total`. Preflight is read-only: it checks Git,
versions, source compilation, tracked prohibited artifacts, obvious secrets, the
runtime asset manifest, tool discovery, destination safety, and pending physical
gates. It neither installs tools nor invokes PyInstaller or Inno Setup. A missing
PyInstaller or Inno Setup installation is reported as an optional-tool warning;
dirty source, stale test evidence, missing runtime assets, or an existing release
destination are blockers.

Inno Setup discovery accepts `--iscc`, then checks PATH and the standard Inno
Setup 6 directories below `ProgramFiles(x86)` and `ProgramFiles`. The explicit
parameter is useful for a nonstandard installation and safely supports spaces.

The runtime data authority is `app/deployment/runtime_assets.py`. Both PowerShell
build entry points call its JSON argument generator before PyInstaller and append
the returned `--add-data` and `--hidden-import` arguments. The same manifest is
used by preflight and release validation. A missing required file or directory
therefore stops the build before packaging. PyInstaller collects both dashboard
template and static directories plus `app.operations.pilot_data_service`.
Documentation CSV templates under
`docs/pilot-data` are operator aids and are intentionally not runtime payload.

Source evidence, package evidence, installer evidence, clean-PC acceptance,
peripheral acceptance, and pilot go-live approval are distinct gates. Source-only
validation can never mark the latter five as passed. When the designated desktop
is available: verify the clean checkout and tools, run preflight, execute the
documented build command once into a new release directory, validate package and
installer evidence, install on the clean PC, execute `docs/windows-acceptance.md`,
record real peripheral results, and obtain named human go-live approval. Until
those steps occur this RC is not production-ready.

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
python .\scripts\validate_release.py validate --release-dir .\release\CBOS-1.0.0-rc.2 --require-executables --require-installer
```

Generate or refresh release evidence:

```powershell
python .\scripts\validate_release.py evidence --release-dir .\release\CBOS-1.0.0-rc.2 --require-executables --require-installer
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

## Exact post-commit RC2 sequence

After committing this promotion (outside this milestone), bind every command and evidence file to that clean commit:

```powershell
git status --short --branch
$Commit = (git rev-parse --short=12 HEAD).Trim()
git rev-list --left-right --count 'HEAD...@{u}'
python -m unittest discover -s tests -q
# Write isolated test evidence with application_version=1.0.0-rc.2, source_commit=$Commit, status=passed, and the real test_total.
python .\scripts\build_preflight.py --expected-branch feature/reporting-engine --expected-commit $Commit --release-dir .\release\CBOS-1.0.0-rc.2 --test-evidence <isolated-test-evidence.json>
.\scripts\build_rc.ps1
python .\scripts\validate_release.py validate --release-dir .\release\CBOS-1.0.0-rc.2 --require-executables --require-installer
python .\scripts\validate_release.py evidence --release-dir .\release\CBOS-1.0.0-rc.2 --source-commit $Commit --require-executables --require-installer
Get-FileHash .\release\CBOS-1.0.0-rc.2\installer\CBOS-Setup-1.0.0-rc.2.exe -Algorithm SHA256
.\scripts\windows_acceptance.ps1 -ReleaseDir .\release\CBOS-1.0.0-rc.2
```

Record the local Windows result separately. Leave clean-PC, printer, scanner, cash-drawer, broader peripheral, and human pilot approval gates pending until physically executed. If same-commit canonical test evidence already exists, validate its commit, version, passed status, and positive total instead of rerunning tests.
