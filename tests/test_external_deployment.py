import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

from server.runtime import simulator_config
from tools.deploy import selected_backend, external_dropins


class ExternalDeploymentTests(unittest.TestCase):
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
