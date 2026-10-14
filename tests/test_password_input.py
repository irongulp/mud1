import unittest

from server.password_input import PasswordInput


class PasswordInputTests(unittest.TestCase):
    PASSWORD_PROMPTS = (
        "This persona already exists - what's the password?",
        'Give me a password for this persona of up to 9 letters, please.',
        'No password on this persona - give me one of up to 9 letters, please.',
    )
    REDRAW_START = '\x12^R\x12\x7f\r'
    REDRAW = REDRAW_START + '\x1b[C\x1b[K'

    def test_coalesced_redraw_password_prompts_use_silent_editing(self):
        for prompt in self.PASSWORD_PROMPTS:
            with self.subTest(prompt=prompt):
                editor = PasswordInput()
                editor.observe(prompt + '\r\n*' + self.REDRAW)
                self.assertTrue(editor.active)
                self.assertEqual(editor.feed('ab\x7fc\r'), 'ac\r')

    def test_redraw_password_recognition_is_independent_of_split_position(self):
        for prompt in self.PASSWORD_PROMPTS:
            frame = prompt + '\r\n*' + self.REDRAW
            for split in range(len(frame) + 1):
                with self.subTest(prompt=prompt, split=split):
                    editor = PasswordInput()
                    editor.observe(frame[:split])
                    editor.observe(frame[split:])
                    self.assertTrue(editor.active)
                    self.assertEqual(editor.feed('ab\x7fc\r'), 'ac\r')

    def test_long_coalesced_redraw_does_not_drop_password_context(self):
        for prompt in self.PASSWORD_PROMPTS:
            with self.subTest(prompt=prompt):
                editor = PasswordInput()
                frame = prompt + '\r\n*' + self.REDRAW_START + '\x1b[C' * 80
                self.assertGreater(len(frame), editor.PROMPT_WINDOW)
                editor.observe(frame)
                self.assertTrue(editor.active)
                self.assertEqual(editor.feed('ab\x7fc\r'), 'ac\r')

    def test_partial_redraw_latches_password_before_context_is_trimmed(self):
        editor = PasswordInput()
        frame = self.PASSWORD_PROMPTS[1] + '\r\n*' + self.REDRAW_START + '\x1b[C' * 80 + '\x1b['
        self.assertGreater(len(frame), editor.PROMPT_WINDOW)
        editor.observe(frame)
        self.assertTrue(editor.active)
        self.assertEqual(editor.feed('ab'), '')
        editor.observe('C\x1b[K')
        self.assertEqual(editor.feed('\x7fc\r'), 'ac\r')

    def test_later_redraw_preserves_buffered_edits_and_does_not_rearm(self):
        editor = PasswordInput()
        editor.observe(self.PASSWORD_PROMPTS[0] + '\r\n*')
        self.assertEqual(editor.feed('ab'), '')
        editor.observe(self.REDRAW)
        self.assertEqual(editor.feed('\x7fc\r'), 'ac\r')
        editor.observe('\x1b[C\x1b[K')
        self.assertFalse(editor.active)
        self.assertEqual(editor.feed('look\r'), 'look\r')

    def test_arbitrary_terminal_tails_do_not_activate_password_mode(self):
        for tail in ('\x1b[H', '\x1b[31m', self.REDRAW_START + '\x1b[H', 'other output'):
            with self.subTest(tail=tail):
                editor = PasswordInput()
                editor.observe(self.PASSWORD_PROMPTS[0] + '\r\n*' + tail)
                self.assertFalse(editor.active)

    def test_unrelated_starred_redraw_is_not_a_password_prompt(self):
        editor = PasswordInput()
        editor.observe('What sex do you wish to be?\r\n*' + self.REDRAW)
        self.assertFalse(editor.active)
        self.assertEqual(editor.feed('m\r'), 'm\r')

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
