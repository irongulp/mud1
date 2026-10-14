import unittest
from unittest.mock import Mock

from tools.reset_permissions import configure, protection, EXECUTABLE


def listing(code):
    return 'MUD\tEXE   492  <' + code + '>   18-Sep-26\tDSKB: [2011,2776]\r\n.'


class ResetPermissionsTests(unittest.TestCase):
    def test_directory_protection(self):
        self.assertEqual(protection(listing('055')), '055')

    def test_missing_or_ambiguous_file_is_rejected(self):
        for text in ('?No such file', 'OTHER EXE 492 <055> 18-Sep-26',
                     listing('055') + '\n' + listing('051')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                protection(text)

    def test_changes_only_executable_protection_and_verifies_readback(self):
        native = Mock()
        native.command.side_effect = [listing('055'), 'Files protected', listing('051')]
        self.assertTrue(configure(native))
        self.assertEqual([call.args[0] for call in native.command.call_args_list], [
            'directory ' + EXECUTABLE, 'protect ' + EXECUTABLE + '<051>',
            'directory ' + EXECUTABLE])

    def test_rerun_does_not_touch_file(self):
        native = Mock()
        native.command.return_value = listing('051')
        self.assertFalse(configure(native))
        native.command.assert_called_once_with('directory ' + EXECUTABLE)

    def test_failed_readback_is_not_success(self):
        native = Mock()
        native.command.side_effect = [listing('055'), 'OK', listing('055')]
        with self.assertRaisesRegex(ValueError, 'verification'):
            configure(native)

    def test_unexpected_permissions_are_preserved(self):
        native = Mock()
        native.command.return_value = listing('000')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            configure(native)
        self.assertEqual(native.command.call_count, 1)

    def test_restore_does_not_replace_executable_or_personas(self):
        native = Mock()
        native.command.side_effect = [listing('051'), 'OK', listing('055')]
        self.assertTrue(configure(native, enable=False))
        self.assertEqual(native.command.call_args_list[1].args[0],
                         'protect ' + EXECUTABLE + '<055>')


if __name__ == '__main__':
    unittest.main()
