"""Faults must not turn an unverified control line into an executed command."""
import unittest

from tools.guest_control import ControlError, submit_line


class EchoTerminal:
    def __init__(self, fault=None, stale=b'', latency=0):
        self.pending = bytearray(stale)
        self.typed = bytearray()
        self.executed = []
        self.sent = []
        self.now = 0
        self.latency = latency
        self.fault = fault

    def clock(self):
        return self.now

    def write(self, data):
        self.sent.append(data)
        if data == b'\r':
            self.executed.append(bytes(self.typed))
            self.typed.clear()
            self.pending.extend(b'\r\n.')
        else:
            self.typed.extend(data)
            echo = self.fault(data) if self.fault else data
            self.pending.extend(echo)

    def read(self, timeout):
        if not self.pending:
            self.now += timeout
            return b''
        if timeout and self.latency > timeout:
            self.now += timeout
            return b''
        if timeout:
            self.now += self.latency
        return bytes([self.pending.pop(0)])

    def submit(self, command, timeout=1):
        return submit_line(command, self.write, self.read, timeout=timeout, clock=self.clock)


class GuestControlTests(unittest.TestCase):
    def test_operator_notice_requires_exact_full_line_redraw(self):
        from tools.guest_control import operator_redraw
        frame = (b'\r\n15:53:15        -- Begin auto take file --\r\n'
                 b'                File: SYS:SYSTEM.CMD[1,4]\r\n\r\nOPR>')
        for corrupt in (False, True):
            terminal = EchoTerminal()
            def echo(byte):
                if bytes(terminal.typed) == b'set ksys no':
                    return frame + (b'set kys no' if corrupt else bytes(terminal.typed))
                return byte
            terminal.fault = echo
            if corrupt:
                with self.assertRaises(ControlError):
                    submit_line('set ksys now', terminal.write, terminal.read, timeout=1,
                                clock=terminal.clock, redraw=operator_redraw)
                self.assertEqual(terminal.executed, [])
            else:
                submit_line('set ksys now', terminal.write, terminal.read, timeout=1,
                            clock=terminal.clock, redraw=operator_redraw)
                self.assertEqual(terminal.executed, [b'set ksys now'])

    def test_unknown_operator_output_is_not_accepted_as_a_redraw(self):
        from tools.guest_control import operator_redraw
        terminal = EchoTerminal()
        terminal.fault = lambda byte: b'\r\n?Unknown failure\r\nOPR>' + bytes(terminal.typed)
        with self.assertRaises(ControlError):
            submit_line('set ksys now', terminal.write, terminal.read, timeout=1,
                        clock=terminal.clock, redraw=operator_redraw)
        self.assertEqual(terminal.executed, [])

    def test_operator_redraw_between_characters_and_before_enter(self):
        from tools.guest_control import operator_redraw
        frame = (b'\r\n15:53:15        -- End auto take file --\r\n'
                 b'                17 lines processed\r\n\r\nOPR>')
        for trigger in (b'n', b'w'):
            terminal = EchoTerminal()
            terminal.fault = lambda byte: byte + frame + bytes(terminal.typed) if byte == trigger else byte
            submit_line('set ksys now', terminal.write, terminal.read, timeout=1,
                        clock=terminal.clock, redraw=operator_redraw)
            self.assertEqual(terminal.executed, [b'set ksys now'])

    def test_witnessed_console_notice_can_interrupt_an_echo(self):
        from tools.guest_control import console_notice
        notice = b'%%TTY STOMPER: Quieting open line on TTY0 at  NODE. failed, code 0\r\n'
        for position in ('before', 'during'):
            with self.subTest(position=position):
                terminal = EchoTerminal(stale=notice if position == 'before' else b'',
                    fault=(lambda byte: notice + byte if byte == b'v' else byte)
                    if position == 'during' else None)
                submit_line('verified control', terminal.write, terminal.read, timeout=1,
                            clock=terminal.clock, notice=console_notice)
                self.assertEqual(terminal.executed, [b'verified control'])

    def test_unknown_and_incomplete_notices_cannot_hide_a_bad_echo(self):
        from tools.guest_control import console_notice
        for notice in (b'%%unknown error\r\n', b'%%TTY STOMPER: Quieting',
                       b'%%TTY STOMPER: Quieting open line on TTY0 at  NODE. failed, code 9\r\n'):
            terminal = EchoTerminal(stale=notice)
            with self.subTest(notice=notice), self.assertRaises(ControlError):
                submit_line('verified control', terminal.write, terminal.read, timeout=1,
                            clock=terminal.clock, notice=console_notice)
            self.assertEqual(terminal.executed, [])
            self.assertLessEqual(terminal.now, 1)

    def test_enter_is_sent_only_after_complete_exact_echo(self):
        terminal = EchoTerminal()
        self.assertEqual(terminal.submit('protect mud.exe<051>'), b'protect mud.exe<051>')
        self.assertEqual(terminal.executed, [b'protect mud.exe<051>'])
        self.assertEqual(bytes(terminal.pending), b'\r\n.')

    def test_dropped_reordered_and_duplicate_echo_never_submit(self):
        for echo in (b'', b'ip', b'pp'):
            with self.subTest(echo=echo):
                terminal = EchoTerminal(fault=lambda byte: echo)
                with self.assertRaises(ControlError) as failure:
                    terminal.submit('protect mud.exe<051>')
                self.assertFalse(failure.exception.submitted)
                self.assertEqual(terminal.executed, [])
                self.assertNotIn(b'\r', terminal.sent)

    def test_stale_prompt_is_not_searched_through_for_matching_characters(self):
        terminal = EchoTerminal(stale=b'\r\n.')
        with self.assertRaises(ControlError):
            terminal.submit('directory mud.exe')
        self.assertEqual(terminal.sent, [])

    def test_known_monitor_boundary_padding_never_substitutes_for_first_echo(self):
        # MVTXT's witnessed return leaves an extra dot after the first monitor
        # marker. It may already be buffered or arrive with the first echo.
        for delayed in (False, True):
            terminal = EchoTerminal(stale=b'\r\n..' if not delayed else b'',
                fault=(lambda byte: b'.' + byte if byte == b'k' else byte) if delayed else None)
            submit_line('kjob', terminal.write, terminal.read, timeout=1,
                        clock=terminal.clock, monitor_padding=True)
            self.assertEqual(terminal.executed, [b'kjob'])
        terminal = EchoTerminal(fault=lambda byte: b'.j')
        with self.assertRaises(ControlError):
            submit_line('kjob', terminal.write, terminal.read, timeout=1,
                        clock=terminal.clock, monitor_padding=True)
        self.assertEqual(terminal.executed, [])

    def test_monitor_padding_is_bounded_and_only_allowed_before_first_echo(self):
        for stale in (b'.' * 100, b'\r\n?error\r\n.'):
            terminal = EchoTerminal(stale=stale)
            with self.subTest(stale=stale), self.assertRaises(ControlError):
                submit_line('kjob', terminal.write, terminal.read, timeout=1,
                            clock=terminal.clock, monitor_padding=True)
            self.assertEqual(terminal.executed, [])
        terminal = EchoTerminal(fault=lambda byte: b'.' + byte if byte == b'j' else byte)
        with self.assertRaises(ControlError):
            submit_line('kjob', terminal.write, terminal.read, timeout=1,
                        clock=terminal.clock, monitor_padding=True)
        self.assertEqual(terminal.executed, [])

    def test_whole_line_has_one_deadline_not_a_timeout_per_character(self):
        terminal = EchoTerminal(latency=.4)
        with self.assertRaises(ControlError):
            terminal.submit('directory mud.exe', timeout=1)
        self.assertLessEqual(terminal.now, 1)
        self.assertEqual(terminal.executed, [])

    def test_disconnect_at_enter_is_an_uncertain_submission(self):
        terminal = EchoTerminal()
        write = terminal.write
        def disconnect(data):
            if data == b'\r':
                raise OSError('connection gone')
            write(data)
        with self.assertRaises(ControlError) as failure:
            submit_line('protect mud.exe<051>', disconnect, terminal.read, timeout=1,
                        clock=terminal.clock)
        self.assertTrue(failure.exception.submitted)

    def test_newlines_controls_and_non_ascii_cannot_bypass_verification(self):
        for command in ('', 'dir\rkjob', 'dir\nkjob', 'dir\x03', 'dir\t', 'caf\xe9'):
            terminal = EchoTerminal()
            with self.subTest(command=command), self.assertRaises(ValueError):
                terminal.submit(command)
            self.assertEqual(terminal.sent, [])
