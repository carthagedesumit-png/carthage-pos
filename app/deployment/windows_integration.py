"""Windows shell integration manifest consumed by the installer build."""

from pathlib import Path

from app.core.version import APP_VERSION, INSTALLER_VERSION
from app.deployment.models import SetupRequest


def build_windows_integration_manifest(request: SetupRequest) -> dict:
    request = request.validated()
    return build_windows_integration_manifest_from_setup(request.safe_dict())


def build_windows_integration_manifest_from_setup(setup: dict) -> dict:
    install_dir = Path(setup["installation_directory"])
    return {
        "application_name": "Carthage POS",
        "publisher": "Carthage Systems",
        "application_version": APP_VERSION,
        "installer_version": INSTALLER_VERSION,
        "executable": str(install_dir / "CarthagePOS.exe"),
        "setup_executable": str(install_dir / "CarthagePOSDeployment.exe"),
        "icon": str(install_dir / "assets" / "carthage-pos.ico"),
        "desktop_shortcut": bool(setup.get("create_desktop_shortcut", True)),
        "start_menu_shortcut": bool(setup.get("create_start_menu_shortcut", True)),
        "start_menu_group": "Carthage POS",
        "uninstall_registry_key": r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CarthagePOS",
        "deployment_type": setup.get("deployment_type", "desktop"),
        "network_deployment_ready": setup.get("deployment_type") == "network",
    }
