import io
import tempfile
import unittest
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

        with tempfile.TemporaryDirectory() as root:
            password_file = Path(root) / "password input.txt"
            password_file.write_text(self.password, encoding="utf-8")
            self.assertEqual(_consume_password_file(password_file), self.password)
            self.assertFalse(password_file.exists())

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
        deployment = script[script.index("procedure RunDeploymentConfiguration;"):]
        self.assertIn("SW_SHOW, ewWaitUntilTerminated", deployment)
        self.assertIn("--admin-password-file", deployment)
        self.assertNotIn(" --admin-password ", deployment)
        self.assertIn("DeleteFile(PasswordFile)", deployment)
        self.assertIn("LoadSilentAdminPassword", script)
        self.assertNotIn("{param:CBOSAdminPassword|", script)
        self.assertNotIn("SetupWizard", script)
        self.assertNotIn("SW_HIDE", deployment)


if __name__ == "__main__":
    unittest.main()
