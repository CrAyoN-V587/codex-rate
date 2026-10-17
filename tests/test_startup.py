import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from codex_rate import startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "Personal Tools 测试" / "Codex Rate"
        self.executable = self.project / "dist" / "CodexRate.exe"
        self.executable.parent.mkdir(parents=True)
        self.executable.touch()
        self.enterContext(patch.object(startup, "__file__",
                                       str(self.project / "codex_rate" / "startup.py")))
        self.enterContext(patch.object(startup.sys, "frozen", False, create=True))

        # Every registry API is replaced, including when running tests on Windows.
        self.registry = Mock(HKEY_CURRENT_USER=object(), KEY_QUERY_VALUE=1,
                             KEY_SET_VALUE=2, REG_SZ=1, REG_EXPAND_SZ=2)
        self.key_exists = True
        self.values = {"OtherApp": ('"C:\\Other Tools\\Other.exe" --quiet', 1)}
        self.original_values = self.values.copy()
        self.registry.OpenKey.side_effect = self.open_key
        self.registry.CreateKeyEx.side_effect = self.create_key
        self.registry.QueryValueEx.side_effect = self.query_value
        self.registry.SetValueEx.side_effect = self.set_value
        self.registry.DeleteValue.side_effect = self.delete_value
        self.enterContext(patch.dict(sys.modules, {"winreg": self.registry}))

    def open_key(self, hive, path, reserved, access):
        self.assertIs(hive, self.registry.HKEY_CURRENT_USER)
        self.assertEqual(path, r"Software\Microsoft\Windows\CurrentVersion\Run")
        self.assertEqual(reserved, 0)
        if not self.key_exists:
            raise FileNotFoundError(path)
        return nullcontext("run-key")

    def create_key(self, hive, path, reserved, access):
        self.key_exists = True
        return self.open_key(hive, path, reserved, access)

    def query_value(self, key, name):
        self.assertEqual(key, "run-key")
        try:
            return self.values[name]
        except KeyError:
            raise FileNotFoundError(name) from None

    def set_value(self, key, name, reserved, kind, value):
        self.assertEqual(key, "run-key")
        self.assertEqual(reserved, 0)
        self.values[name] = (value, kind)

    def delete_value(self, key, name):
        self.assertEqual(key, "run-key")
        try:
            del self.values[name]
        except KeyError:
            raise FileNotFoundError(name) from None

    def test_source_command_quotes_the_absolute_dist_executable(self):
        self.assertEqual(startup.command(), f'"{self.executable}" --background')

    def test_frozen_registration_uses_executable_outside_extraction_directory(self):
        permanent = self.project / "Installed App" / "CodexRate.exe"
        permanent.parent.mkdir()
        permanent.touch()
        extracted = self.project / "_MEI12345"
        with patch.object(startup.sys, "frozen", True, create=True), patch.object(
                startup.sys, "executable", str(permanent)), patch.object(
                startup.sys, "_MEIPASS", str(extracted), create=True), patch.object(
                startup, "__file__", str(extracted / "codex_rate" / "startup.py")):
            expected = f'"{permanent}" --background'
            self.assertEqual(startup.command(), expected)
            self.assertEqual(startup.enable(), expected)
            self.assertEqual(self.values["CodexRate"], (expected, self.registry.REG_SZ))
            self.assertTrue(startup.is_enabled())

    def test_enable_twice_preserves_other_apps_and_writes_only_once(self):
        expected = f'"{self.executable}" --background'
        self.assertEqual(startup.enable(), expected)
        self.assertEqual(startup.enable(), expected)
        self.assertTrue(startup.is_enabled())
        self.assertEqual(self.values, {**self.original_values,
                                      "CodexRate": (expected, self.registry.REG_SZ)})
        self.registry.SetValueEx.assert_called_once_with(
            "run-key", "CodexRate", 0, self.registry.REG_SZ, expected)
        self.registry.CreateKeyEx.assert_called_with(
            self.registry.HKEY_CURRENT_USER, startup.RUN_KEY, 0,
            self.registry.KEY_QUERY_VALUE | self.registry.KEY_SET_VALUE)

    def test_disable_twice_preserves_other_apps_and_the_run_key(self):
        startup.enable()
        self.assertTrue(startup.disable())
        self.assertFalse(startup.disable())
        self.assertFalse(startup.is_enabled())
        self.assertEqual(self.values, self.original_values)
        self.assertTrue(self.key_exists)
        self.registry.DeleteValue.assert_called_with("run-key", "CodexRate")
        self.registry.DeleteKey.assert_not_called()

    def test_missing_run_key_is_disabled_and_disable_does_not_create_it(self):
        self.key_exists = False
        self.assertFalse(startup.is_enabled())
        self.assertFalse(startup.disable())
        self.assertFalse(self.key_exists)
        self.registry.CreateKeyEx.assert_not_called()
        self.registry.DeleteValue.assert_not_called()

    def test_enable_creates_missing_run_key(self):
        self.key_exists = False
        startup.enable()
        self.assertTrue(self.key_exists)
        self.assertTrue(startup.is_enabled())

    def test_missing_value_is_disabled_without_changing_other_apps(self):
        self.assertFalse(startup.is_enabled())
        self.assertFalse(startup.disable())
        self.assertEqual(self.values, self.original_values)

    def test_enable_replaces_old_app_command_without_touching_other_values(self):
        self.values["CodexRate"] = ('"C:\\Old Install\\CodexRate.exe" --background', 1)
        self.assertFalse(startup.is_enabled())
        startup.enable()
        self.assertTrue(startup.is_enabled())
        self.assertEqual(self.values["OtherApp"], self.original_values["OtherApp"])

    def test_enable_repairs_wrong_registry_value_type(self):
        self.values["CodexRate"] = (startup.command(), self.registry.REG_EXPAND_SZ)
        self.assertFalse(startup.is_enabled())
        startup.enable()
        self.assertTrue(startup.is_enabled())
        self.assertEqual(self.values["CodexRate"][1], self.registry.REG_SZ)

    def test_command_can_be_inspected_but_missing_executable_cannot_be_enabled(self):
        self.executable.unlink()
        self.assertEqual(startup.command(), f'"{self.executable}" --background')
        with self.assertRaisesRegex(FileNotFoundError, "Codex Rate executable not found"):
            startup.enable()
        self.assertEqual(self.values, self.original_values)
        self.registry.CreateKeyEx.assert_not_called()
        self.registry.SetValueEx.assert_not_called()

    def test_directory_named_exe_cannot_be_enabled(self):
        self.executable.unlink()
        self.executable.mkdir()
        with self.assertRaises(FileNotFoundError):
            startup.enable()
        self.registry.CreateKeyEx.assert_not_called()

    def test_disable_can_remove_an_old_command_after_executable_is_deleted(self):
        startup.enable()
        self.executable.unlink()
        self.assertTrue(startup.disable())
        self.assertEqual(self.values, self.original_values)

    def test_registry_read_permission_errors_are_not_reported_as_disabled(self):
        for failing_api in (self.registry.OpenKey, self.registry.QueryValueEx):
            with self.subTest(api=failing_api):
                previous = failing_api.side_effect
                failing_api.side_effect = PermissionError("denied")
                try:
                    with self.assertRaises(PermissionError):
                        startup.is_enabled()
                finally:
                    failing_api.side_effect = previous

    def test_registry_write_permission_errors_reach_the_caller(self):
        operations = ((startup.enable, self.registry.CreateKeyEx),
                      (startup.enable, self.registry.QueryValueEx),
                      (startup.enable, self.registry.SetValueEx),
                      (startup.disable, self.registry.OpenKey),
                      (startup.disable, self.registry.DeleteValue))
        for operation, failing_api in operations:
            with self.subTest(operation=operation.__name__, api=failing_api):
                previous = failing_api.side_effect
                failing_api.side_effect = PermissionError("denied")
                try:
                    with self.assertRaises(PermissionError):
                        operation()
                finally:
                    failing_api.side_effect = previous
                self.assertEqual(self.values, self.original_values)


if __name__ == "__main__":
    unittest.main()
