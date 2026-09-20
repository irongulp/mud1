import unittest
from unittest.mock import Mock

from tools.audit_archwizards import Guest, parse_personas, password_result


class ArchwizardAuditTests(unittest.TestCase):
    def test_reads_native_octal_password_values_and_normalizes_names(self):
        data = parse_personas('RUN AUDPWD\r\nPSAUDIT_TOTAL 2\r\n'
                              'PSAUDIT richard 123456701234 1\r\n'
                              'PSAUDIT Roy -1 2\r\n.\r\n')
        self.assertEqual(data['richard']['password_word'], int('123456701234', 8))
        self.assertEqual(data['roy']['password_word'], (1 << 36) - 1)
        self.assertEqual(data['roy']['games'], 2)

    def test_incomplete_or_duplicate_diagnostics_are_rejected(self):
        for text in ('?Cannot open file', 'PSAUDIT_TOTAL 1\n',
                     'PSAUDIT_TOTAL 2\nPSAUDIT roy 1 1\nPSAUDIT roy 2 1\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_personas(text)

    def test_requires_greeting_and_play_prompt_for_acceptance(self):
        self.assertEqual(password_result('No!\r\n.', 'Richard'), 'rejected')
        self.assertEqual(password_result('Yes!\r\nHello again, Richard the arch-wizard!\r\n----*', 'Richard'), 'accepted')
        self.assertEqual(password_result('Yes!\r\n', 'Richard'), 'incomplete')
        self.assertEqual(password_result('Hello, Roy the arch-wizard!\r\n----*', 'Richard'), 'incomplete')

    def attachment_guest(self, prompted, response):
        guest = Guest.__new__(Guest)
        guest.transcript = []
        guest.connection = Mock()
        first = b"attach richard\r\nWhat's the password for this persona?\r\n" if prompted else response
        guest.connection.expect.return_value = (0 if prompted else 1, None, first)
        guest.connection.read_until.return_value = response
        return guest

    def test_attachment_sends_password_only_after_a_prompt(self):
        success = b'Detaching from Roy the arch-wizard.\r\nAttaching to Richard the arch-wizard.\r\n----*'
        for prompted in (True, False):
            with self.subTest(prompted=prompted):
                guest = self.attachment_guest(prompted, success)
                self.assertEqual(guest.attach('Richard', 'fixture'),
                                 {'prompted': prompted, 'accepted': True})
                writes = [call.args[0] for call in guest.connection.write.call_args_list]
                self.assertEqual(writes, [b'attach Richard\r'] + ([b'fixture\r'] if prompted else []))

    def test_attachment_rejects_wrong_password_and_missing_privileges(self):
        for prompted, response in ((True, b'\r\nWrong!\r\n----*'),
                                   (False, b"\r\nNot to Richard you don't!\r\n----*")):
            with self.subTest(prompted=prompted):
                guest = self.attachment_guest(prompted, response)
                self.assertEqual(guest.attach('Richard', 'fixture'),
                                 {'prompted': prompted, 'accepted': False})

    def test_attachment_requires_explicit_result_for_expected_persona(self):
        for response in (b'\r\n----*', b'Attaching to Roy the arch-wizard.\r\n----*'):
            with self.subTest(response=response), self.assertRaises(AssertionError):
                self.attachment_guest(False, response).attach('Richard', 'fixture')


if __name__ == '__main__':
    unittest.main()
