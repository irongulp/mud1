import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import deploy, external_cutover, external_install
from server import runtime
from server.monitor_scope import MonitorBootstrapError


class ScopeSelectionTests(unittest.TestCase):
    def test_service_environment_selects_scope_and_failure_blocks_systemd_retry(self):
        with patch.dict('os.environ',{'MUD86_MONITOR_SCOPE':'1'}), \
                patch('sys.argv',['runtime','--state','/state','--simh','/simh']), \
                patch('server.runtime.Runtime') as factory:
            factory.return_value.run.side_effect=MonitorBootstrapError('unsupported')
            with self.assertRaises(SystemExit) as error: runtime.main()
        self.assertEqual(error.exception.code,78)
        self.assertTrue(factory.call_args.kwargs['monitor_scope'])
        unit=Path(__file__).resolve().parents[1]/'deploy/mud86-runtime.service'
        self.assertIn('RestartPreventExitStatus=78',unit.read_text())

    def test_default_is_off_and_rerun_preserves_explicit_selection(self):
        self.assertFalse(deploy.selected_monitor_scope(None,{}))
        self.assertTrue(deploy.selected_monitor_scope(True,{}))
        self.assertTrue(deploy.selected_monitor_scope(None,{'monitor_scope':True}))
        for value in ('true',1,{},None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                deploy.selected_monitor_scope(None,{'monitor_scope':value})

    def test_environment_and_cutover_options_agree(self):
        self.assertEqual(deploy.monitor_scope_options(False),[])
        self.assertEqual(deploy.monitor_scope_options(True),['--monitor-scope'])
        self.assertEqual(deploy.runtime_environment('/pdp10',False),'SIMH_BIN=/pdp10\nMUD86_MONITOR_SCOPE=0\n')
        self.assertEqual(deploy.runtime_environment('/pdp10',True),'SIMH_BIN=/pdp10\nMUD86_MONITOR_SCOPE=1\n')

    def test_private_cutover_runtime_gets_explicit_scope_flag(self):
        class Boundary(Exception): pass
        for enabled in (False,True):
            with self.subTest(enabled=enabled),tempfile.TemporaryDirectory() as directory:
                state=Path(directory)
                (state/'game').mkdir()
                (state/'game/guest.dsk').write_bytes(b'fixture')
                with patch('tools.external_install.database_config',return_value=(Mock(),Mock())), \
                        patch('tools.external_install.prepare_sources',return_value=state), \
                        patch('tools.external_install.Runtime',side_effect=Boundary) as runtime:
                    with self.assertRaises(Boundary):
                        external_install.cutover(state,state,'/pdp10',monitor_scope=enabled)
                runtime.assert_called_once_with(state,'/pdp10',port=2020,monitor_scope=enabled)

    def test_cutover_cli_passes_flag_without_changing_verify_only(self):
        for verify_only in (False,True):
            args=argparse.Namespace(state=Path('/state'),config_dir=Path('/config'),simh=Path('/simh'),
                                    verify_only=verify_only,monitor_scope=True)
            with patch('argparse.ArgumentParser.parse_args',return_value=args), \
                    patch('tools.external_cutover.cutover') as cutover, \
                    patch('tools.external_cutover.load_config',return_value={}), \
                    patch('tools.external_cutover.verify_archwizards'):
                external_cutover.main()
            if verify_only: cutover.assert_not_called()
            else: cutover.assert_called_once_with(args.state,args.config_dir,args.simh,monitor_scope=True)
