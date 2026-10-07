import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock,patch,MagicMock

from server.runtime import simulator_config,wait_listener
from tools.deploy import selected_backend, external_dropins
from tools.build_external_guest import read_back


class ExternalDeploymentTests(unittest.TestCase):
    def test_waits_for_fixed_listener_to_leave_time_wait(self):
        fake=MagicMock(); fake.__enter__.return_value=fake
        fake.bind.side_effect=[OSError('TIME_WAIT'),None]
        with patch('server.runtime.socket.socket',return_value=fake),patch('server.runtime.time.sleep') as sleep:
            wait_listener(2020,timeout=10)
        self.assertEqual(fake.bind.call_count,2)
        sleep.assert_called_once()
    def test_repeated_closing_lines_require_unique_source_suffix(self):
        class Native:
            def send(self,text): pass
            def receive(self,marker):
                if marker==b'unique final routine\r\n$]\r\n':
                    return 'type mudlib.bcl\r\nfirst routine\r\n$]\r\nunique final routine\r\n$]\r\n'
                if marker==b'.': return '\r\n.'
                raise AssertionError('Source suffix was not unique')
        self.assertIn('first routine',read_back(Native(),'mudlib.bcl','first routine\n$]\nunique final routine\n$]\n'))
    def test_macro_labels_do_not_terminate_type_verification(self):
        class Native:
            def send(self,text): self.sent=text
            def receive(self,marker):
                if marker==b'        END ..BCPL\r\n':
                    return 'type mboots.mac\r\n        TITLE BCPL\r\n..BCPL:: TDZA 1,1\r\n        END ..BCPL\r\n'
                if marker==b'.': return '\r\n.'
                raise AssertionError('Unsafe monitor marker during source TYPE')
        native=Native(); expected='\tTITLE BCPL\n..BCPL:: TDZA 1,1\n\tEND ..BCPL\n'
        self.assertIn('..BCPL:: TDZA',read_back(native,'mboots.mac',expected))
    def test_native_configuration_keeps_no_raw_lines(self):
        self.assertNotIn('Line=',simulator_config(Path('/private/state'),2020,False))
    def test_external_raw_lines_reserved_before_boot(self):
        text=simulator_config(Path('/private/state'),2020,False,bridge_ports={6:22006,7:22007})
        self.assertIn('Line=6,127.0.0.1:22006;notelnet',text)
        self.assertLess(text.index('Line=7'),text.index('boot tu0'))
    def test_backend_default_preserves_existing_selection(self):
        self.assertEqual(selected_backend(None,{}),'native')
        self.assertEqual(selected_backend(None,{'persona_storage':'mariadb'}),'mariadb')
        with self.assertRaises(ValueError): selected_backend('native',{'persona_storage':'mariadb'})
        self.assertEqual(selected_backend('mariadb',{'persona_storage':'native'}),'mariadb')
    def test_only_external_units_require_database(self):
        runtime,gateway=external_dropins(Path('/etc/mud86/personas.json'))
        self.assertIn('Requires=mud86-database.service',runtime)
        self.assertIn('MUD86_PERSONA_CONFIG=/etc/mud86/personas.json',gateway)
