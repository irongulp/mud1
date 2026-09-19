import unittest

from server.password_input import PasswordInput


class PasswordInputTests(unittest.TestCase):
    def test_fragmented_existing_password_prompt_and_corrected_submission(self):
        editor = PasswordInput()
        for text in ["This persona already exists - what's the pass", "word?\r", "\n*"]:
            editor.observe(text)
        self.assertEqual(editor.feed('testpaxs'), '')
        self.assertEqual(editor.feed('\x7f\x08ss'), '')
        self.assertEqual(editor.feed('\r'), 'testpass\r')
        self.assertEqual(editor.feed('look\r'), 'look\r')

    def test_creation_prompts_and_line_editing(self):
        for prompt in [
            'Give me a password for this persona of up to 10 letters, please.',
            'No password on this persona - give me one of up to 10 letters, please.',
        ]:
            with self.subTest(prompt=prompt):
                editor = PasswordInput()
                editor.observe(prompt + '\r\n*')
                self.assertEqual(editor.feed('\x7fwrong\x15test bad\x17pass'), '')
                self.assertEqual(editor.feed('\x15correct\r\n'), 'correct\r\n')

    def test_normal_input_and_cancellation_are_forwarded(self):
        editor = PasswordInput()
        self.assertEqual(editor.feed('wx\x7fho\r'), 'wx\x7fho\r')
        editor.observe("This persona already exists - what's the password?\r\n*")
        self.assertEqual(editor.feed('secret\x03'), '\x03')
        self.assertEqual(editor.feed('look\r'), 'look\r')

    def test_password_buffer_is_bounded(self):
        editor = PasswordInput()
        editor.observe("This persona already exists - what's the password?\r\n*")
        with self.assertRaises(ValueError):
            editor.feed('x' * (editor.MAX_LINE_LENGTH + 1))
