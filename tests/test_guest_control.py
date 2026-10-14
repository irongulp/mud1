"""Faults cannot turn unverified control input into an executed command."""
import unittest

from tools.guest_control import ControlError, console_notice, operator_redraw, submit_line


class EchoTerminal:
    def __init__(self, fault=None, stale=b'', latency=0):
        self.pending = bytearray(stale)
        self.typed = bytearray()
        self.executed = []
        self.sent = []
        self.now = 0
        self.latency = latency
        self.fault = fault

    def write(self, data):
        self.sent.append(data)
        if data == b'\r':
            self.executed.append(bytes(self.typed))
        else:
            self.typed.extend(data)
            self.pending.extend(self.fault(data) if self.fault else data)

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

    def submit(self, text, **kwargs):
        return submit_line(text, self.write, self.read, timeout=1, clock=lambda: self.now, **kwargs)


class GuestControlTests(unittest.TestCase):
    def test_enter_follows_complete_exact_echo(self):
        terminal = EchoTerminal()
        self.assertEqual(terminal.submit('copy sys:xtty.tmp=tty:'), b'copy sys:xtty.tmp=tty:')
        self.assertEqual(terminal.executed, [b'copy sys:xtty.tmp=tty:'])

    def test_missing_duplicate_reordered_or_wrong_echo_cannot_submit(self):
        for echo in (b'', b'cc', b'oc', b'x'):
            terminal = EchoTerminal(fault=lambda byte: echo)
            with self.subTest(echo=echo), self.assertRaises(ControlError) as error:
                terminal.submit('copy sys:xtty.tmp=tty:')
            self.assertFalse(error.exception.submitted)
            self.assertTrue(error.exception.input_started)
            self.assertEqual(terminal.executed, [])

    def test_stale_output_is_not_searched_for_matching_echo(self):
        terminal = EchoTerminal(stale=b'?Failure\r\n.')
        with self.assertRaises(ControlError):
            terminal.submit('copy sys:xtty.tmp=tty:')
        self.assertEqual(terminal.sent, [])

    def test_witnessed_monitor_padding_is_bounded_and_pre_echo_only(self):
        terminal = EchoTerminal(stale=b'\r\n..')
        terminal.submit('kjob', monitor_padding=True)
        self.assertEqual(terminal.executed, [b'kjob'])
        for terminal in (EchoTerminal(stale=b'.' * 100),
                         EchoTerminal(fault=lambda byte: b'.' + byte if byte == b'j' else byte)):
            with self.assertRaises(ControlError):
                terminal.submit('kjob', monitor_padding=True)
            self.assertEqual(terminal.executed, [])

    def test_one_deadline_covers_all_command_bytes(self):
        terminal = EchoTerminal(latency=.4)
        with self.assertRaises(ControlError):
            terminal.submit('directory sys:xtty.tmp')
        self.assertLessEqual(terminal.now, 1)
        self.assertEqual(terminal.executed, [])

    def test_disconnect_at_enter_is_uncertain_submission(self):
        terminal = EchoTerminal()
        write = terminal.write
        def disconnect(data):
            if data == b'\r':
                raise OSError('closed')
            write(data)
        with self.assertRaises(ControlError) as error:
            submit_line('kjob', disconnect, terminal.read, timeout=1, clock=lambda: terminal.now)
        self.assertTrue(error.exception.submitted)

    def test_control_characters_and_non_ascii_are_rejected(self):
        for text in ('', 'dir\rkjob', 'dir\nkjob', 'dir\x03', 'dir\t', 'caf\xe9'):
            terminal = EchoTerminal()
            with self.subTest(text=text), self.assertRaises(ValueError):
                terminal.submit(text)
            self.assertEqual(terminal.sent, [])

    def test_operator_notice_requires_the_whole_redrawn_prefix(self):
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
                    terminal.submit('set ksys now', redraw=operator_redraw)
                self.assertEqual(terminal.executed, [])
            else:
                terminal.submit('set ksys now', redraw=operator_redraw)
                self.assertEqual(terminal.executed, [b'set ksys now'])

    def test_unknown_operator_redraw_is_rejected(self):
        terminal = EchoTerminal()
        terminal.fault = lambda byte: b'\r\n?Unknown failure\r\nOPR>' + bytes(terminal.typed)
        with self.assertRaises(ControlError):
            terminal.submit('set ksys now', redraw=operator_redraw)
        self.assertEqual(terminal.executed, [])

    def test_hourly_status_is_complete_and_does_not_acknowledge_input(self):
        for uptime in (b':01:13', b'34.66', b'12:01:13'):
            notice = (b'\r\nMonitor KS10\r\nSystem uptime ' + uptime +
                      b'\r\nCurrent date/time Tuesday 13-Oct-126 21:00:00\r\n\r\n')
            terminal = EchoTerminal(stale=notice)
            terminal.submit('r opr', notice=console_notice)
            self.assertEqual(terminal.executed, [b'r opr'])
            terminal = EchoTerminal(stale=notice[:-2])
            with self.assertRaises(ControlError):
                terminal.submit('r opr', notice=console_notice)
            self.assertEqual(terminal.sent, [])

    def test_stomper_notice_is_exact(self):
        notice = b'%%TTY STOMPER: Quieting open line on TTY0 at  NODE. failed, code 0\r\n'
        terminal = EchoTerminal(stale=notice)
        terminal.submit('r opr', notice=console_notice)
        self.assertEqual(terminal.executed, [b'r opr'])
        for bad in (notice.replace(b'code 0', b'code 9'), b'%%unknown failure\r\n', notice[:-2]):
            terminal = EchoTerminal(stale=bad)
            with self.assertRaises(ControlError):
                terminal.submit('r opr', notice=console_notice)
            self.assertEqual(terminal.sent, [])
