import io
import tempfile
import unittest
import subprocess
import os
from pathlib import Path
from unittest.mock import patch

from app.core.exceptions import InstallationError
from app.deployment.installer_arguments import (
    SILENT_INSTALLER_PARAMETERS,
    build_deployment_cli_arguments,
    quote_deployment_cli_arguments,
    redacted_deployment_cli_arguments,
    validate_silent_installer_values,
)


class SilentInstallerArgumentsTestCase(unittest.TestCase):
    def setUp(self):
        self.password = "Test-Only Secret 42!"
        self.values = {
            "CBOSBusiness": "Carthage Test Market",
            "CBOSStore": "Clean Install Store",
            "CBOSAdminUser": "rc.admin",
            "CBOSAdminPasswordFile": r"C:\Secure Input\admin password.txt",
            "CBOSAdminFullName": "RC Test Administrator",
            "CBOSCurrency": "USD",
            "CBOSTaxRate": "0.075",
            "CBOSTimezone": "Asia/Manila",
            "CBOSDeploymentType": "desktop",
            "CBOSPrinter": "none",
        }

    def build_arguments(self):
        return build_deployment_cli_arguments(
            self.values,
            install_dir=r"C:\Program Files\Carthage Business Operating System",
            runtime_root=r"C:\Program Data With Spaces\Carthage POS",
            password_file=r"C:\Temp Files\cbos password.tmp",
        )

    def test_silent_parameters_map_to_deployment_cli_arguments(self):
        arguments = self.build_arguments()
        for parameter, (_, option, _) in SILENT_INSTALLER_PARAMETERS.items():
            if parameter == "CBOSAdminPasswordFile":
                self.assertIn("--admin-password-file", arguments)
                self.assertNotIn("--admin-password", arguments)
            else:
                index = arguments.index(option)
                self.assertEqual(arguments[index + 1], self.values[parameter])
        self.assertEqual(arguments[0], "configure")
        self.assertIn(r"C:\Program Data With Spaces\Carthage POS\data\carthage-pos.db", arguments)

    def test_windows_quoting_preserves_paths_and_values_with_spaces(self):
        command = quote_deployment_cli_arguments(self.build_arguments())
        self.assertIn('"C:\\Program Files\\Carthage Business Operating System"', command)
        self.assertIn('"Carthage Test Market"', command)
        self.assertIn('"RC Test Administrator"', command)
        self.assertIn('"C:\\Temp Files\\cbos password.tmp"', command)

    def test_password_is_not_in_child_arguments_or_log_safe_arguments(self):
        arguments = self.build_arguments()
        command = quote_deployment_cli_arguments(arguments)
        redacted = quote_deployment_cli_arguments(redacted_deployment_cli_arguments(arguments))
        self.assertNotIn(self.password, arguments)
        self.assertNotIn(self.password, command)
        self.assertNotIn("cbos password.tmp", redacted)

    def test_incomplete_silent_input_fails_without_echoing_values(self):
        incomplete = dict(self.values)
        incomplete["CBOSAdminFullName"] = ""
        with self.assertRaises(InstallationError) as raised:
            validate_silent_installer_values(incomplete)
        self.assertIn("Administrator full name", str(raised.exception))
        self.assertNotIn(self.password, str(raised.exception))
        script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        self.assertIn("Log('ERROR: ' + LabelText + ' is required for silent CBOS installation.')", script)

    def test_password_file_is_consumed_and_deleted(self):
        from deployment_cli import _consume_password_file

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
            password_file = Path(root) / "password input.txt"
            password_file.write_text(self.password, encoding="utf-8")
            self.assertEqual(_consume_password_file(password_file), self.password)
            self.assertFalse(password_file.exists())

    def test_inno_code_password_file_contract_is_consumed_exactly(self):
        compiler = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe"
        if not compiler.is_file():
            self.skipTest("Inno Setup compiler is unavailable")
        harness = Path("installer/password-contract-harness.iss").resolve()
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "compiled"
            output.mkdir()
            subprocess.run(
                [str(compiler), f"/O{output}", str(harness)],
                check=True, capture_output=True, text=True,
            )
            executable = output / "CBOS-Password-Contract-Harness.exe"
            password_file = Path(root) / "contract.input"
            subprocess.run(
                [str(executable), "/VERYSILENT", f"/ContractOutput={password_file}"],
                check=False, capture_output=True, text=True,
            )
            raw = password_file.read_bytes()
            self.assertEqual(len(raw), len("Harness-Only 42!".encode("utf-8")))
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\x00", raw)
            self.assertFalse(raw.endswith((b"\r", b"\n")))
            from deployment_cli import _consume_password_file
            self.assertEqual(_consume_password_file(password_file), "Harness-Only 42!")
            self.assertFalse(password_file.exists())

    def test_upgrade_credentials_are_verified_before_files_are_replaced(self):
        script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        preflight = script[script.index("function PrepareToInstall"):script.index("procedure CurStepChanged")]
        self.assertIn("ExtractTemporaryFile('CarthagePOSUpgradeVerifier.exe')", preflight)
        self.assertIn("'verify-upgrade-credentials'", preflight)
        self.assertIn("AdminPage.Values[1]", preflight)
        self.assertIn("SetupValue(AdminPage, 0, 'CBOSAdminUser')", preflight)
        self.assertIn("RuntimeRoot() + '\\config\\deployment.json'", preflight)
        self.assertIn("No application files were replaced", preflight)
        self.assertIn("ResultCode = 17", preflight)
        self.assertIn("verifier could not load its runtime", preflight)

    def test_upgrade_ui_requests_existing_credentials_explicitly(self):
        script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        self.assertIn("Existing administrator username:", script)
        self.assertIn("Current existing administrator password:", script)
        self.assertIn("New administrator username:", script)
        self.assertNotIn("Confirm administrator password", script)

    def test_interactive_install_command_remains_available(self):
        from deployment_cli import main

        request = object()
        with patch("deployment_cli.SetupWizard.collect", return_value=request) as collect:
            with patch("deployment_cli.fresh_install", return_value={"installed": True}):
                with patch("sys.stdout", new=io.StringIO()):
                    self.assertEqual(main(["install"]), 0)
        collect.assert_called_once_with()

    def test_inno_uses_visible_checked_exec_and_no_password_command_argument(self):
        script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        deployment = script[script.index("procedure RunDeploymentConfiguration;"):script.index("function PrepareToInstall")]
        self.assertIn("SW_SHOW, ewWaitUntilTerminated", deployment)
        self.assertIn("--admin-password-file", deployment)
        self.assertNotIn(" --admin-password ", deployment)
        self.assertIn("DeleteFile(PasswordFile)", deployment)
        self.assertIn("LoadSilentAdminPassword", script)
        self.assertNotIn("{param:CBOSAdminPassword|", script)
        self.assertNotIn("SetupWizard", script)
        self.assertNotIn("SW_HIDE", deployment)

    def test_deployment_is_synchronous_and_postinstall_launch_is_non_blocking(self):
        script = Path("installer/carthage-pos.iss").read_text(encoding="utf-8")
        deployment = script[script.index("procedure RunDeploymentConfiguration;"):script.index("procedure CurStepChanged")]
        self.assertIn("ewWaitUntilTerminated", deployment)
        self.assertIn("if ResultCode <> 0", deployment)
        self.assertNotIn("CarthagePOS.exe", deployment)
        run_section = script[script.index("[Run]"):script.index("[Code]")]
        self.assertIn('Description: "Launch CBOS"', run_section)
        self.assertIn("postinstall nowait skipifsilent", run_section)
        post_install = script[script.index("procedure CurStepChanged"):]
        self.assertIn("RunDeploymentConfiguration();", post_install)
        self.assertNotIn("ewNoWait", post_install)
        self.assertNotIn("Exec(ExpandConstant('{app}\\{#MyAppExeName}')", post_install)


if __name__ == "__main__":
    unittest.main()
