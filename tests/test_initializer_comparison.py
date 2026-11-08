import unittest
from unittest.mock import Mock, patch

from tests.prepare_initializer_comparison import configure_pair_arm

ORIGINAL='ALL KSYS LC WIDTH:255\nCTY: GALOPR\nSTOMP ACCOUNT "SYSTEM"\n'
DISABLED='ALL KSYS LC WIDTH:255\nCTY: GALOPR\n'


class InitializerComparisonTests(unittest.TestCase):
    def machine(self,disabled):
        machine=Mock()
        configs=iter([ORIGINAL,DISABLED if disabled else ORIGINAL])
        states=iter(['STOMPR', '' if disabled else 'STOMPR'])
        def command(text):
            if text=='type sys:tty.ini': return text+'\r\n'+next(configs)+'\n.'
            if text=='systat': return next(states)
            raise AssertionError(text)
        machine.command.side_effect=command
        machine.stop.return_value=True
        return machine

    def test_candidate_uses_verified_configuration_and_both_arms_reboot_once(self):
        for disabled in (False,True):
            with self.subTest(disabled=disabled):
                machine=self.machine(disabled)
                report={}
                with patch('tests.prepare_initializer_comparison.protect_bridge_terminals',return_value=True) as protect:
                    configure_pair_arm(machine,disabled,report)
                self.assertEqual(machine.boot.call_count,2)
                machine.stop.assert_called_once()
                self.assertEqual(protect.call_count,int(disabled))
                self.assertEqual(report['initializer_running'],not disabled)

    def test_failed_stop_never_reboots(self):
        machine=self.machine(True)
        machine.stop.return_value=False
        with patch('tests.prepare_initializer_comparison.protect_bridge_terminals',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'Unconfirmed'): configure_pair_arm(machine,True,{})
        machine.boot.assert_called_once()
        machine.stop.assert_called_once()

    def test_missing_initial_initializer_does_not_become_a_control(self):
        machine=self.machine(False)
        machine.command.side_effect=lambda text: text+'\n'+DISABLED+'\n.'
        with self.assertRaisesRegex(RuntimeError,'enabled initializer'): configure_pair_arm(machine,False,{})
        machine.boot.assert_called_once()
