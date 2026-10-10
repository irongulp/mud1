import tempfile
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from server.database import configured_port,listener_options
from tools.database_access import (EDITABLE_COLUMNS,EDITOR_COLUMNS,EDITOR_USER,revision_statement,
                                   main,CREDENTIAL_FILE,read_credentials,normalized_view,configure)
from tools.deploy import configure_database_editor


class DatabaseAccessTests(unittest.TestCase):
    def test_unconfigured_editor_has_a_clear_operator_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(SystemExit,'not configured'):
                main(['--config-dir',temporary])
    def test_view_validation_preserves_nonidentity_column_aliases(self):
        definition='select `mud86_personas`.`personas`.`name` AS `score` from `mud86_personas`.`personas`'
        self.assertEqual(normalized_view(definition,'mud86_personas'),'select name as score from personas')

    def test_editor_setup_never_hardens_an_unrelated_database(self):
        with patch('tools.database_access.load_config',return_value=SimpleNamespace(unix_socket='/other/server.sock')), \
                patch('tools.database_access.connect',side_effect=AssertionError('Unrelated database contacted')):
            with self.assertRaises(ValueError): configure(Path('/var/lib/mud86'),Path('/etc/mud86'))
    def test_credentials_are_only_displayed_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/CREDENTIAL_FILE
            value={'format_version':1,'database':'mud86_personas','user':EDITOR_USER,
                   'host':'127.0.0.1','port':3307,'password':'disposable-credential-'*3}
            path.write_text(json.dumps(value)); path.chmod(0o600)
            for show in (False,True):
                output=io.StringIO()
                with redirect_stdout(output):
                    main(['--config-dir',temporary,*(['--show-credentials'] if show else [])])
                self.assertEqual('password' in json.loads(output.getvalue()),show)

    def test_boolean_format_versions_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'listener.json'
            path.write_text(json.dumps({'format_version':True,'port':3307})); path.chmod(0o600)
            with self.assertRaises(ValueError): configured_port(temporary)
            credentials=Path(temporary)/CREDENTIAL_FILE
            credentials.write_text(json.dumps({'format_version':True,'database':'mud86_personas',
                'user':EDITOR_USER,'host':'127.0.0.1','port':3307,'password':'disposable-credential-'*3}))
            credentials.chmod(0o600)
            with self.assertRaises(ValueError): read_credentials(credentials)

    def test_installer_provisions_editor_before_restarting_database(self):
        release=Path('/opt/mud86/current')
        with patch('tools.deploy.run') as run:
            configure_database_editor(release)
        self.assertIn('tools.database_access',run.call_args_list[0].args)
        self.assertIn('--configure',run.call_args_list[0].args)
        self.assertEqual(run.call_args_list[1].args,('systemctl','restart','mud86-database.service'))
    def test_default_remains_socket_only(self):
        self.assertEqual(listener_options(None),['--skip-networking'])

    def test_tcp_listener_is_explicitly_ipv4_loopback(self):
        self.assertEqual(listener_options(3307),[
            '--bind-address=127.0.0.1','--port=3307','--skip-name-resolve'])

    def test_invalid_port_cannot_enable_networking(self):
        for port in (True,0,-1,65536,'3307'):
            with self.subTest(port=port),self.assertRaises(ValueError): listener_options(port)

    def test_editor_view_excludes_password_and_opaque_words(self):
        self.assertNotIn('password_word',EDITOR_COLUMNS)
        self.assertNotIn('opaque_9',EDITOR_COLUMNS)
        for column in ('namespace','name','name_key','generation','revision','created_at','updated_at'):
            self.assertIn(column,EDITOR_COLUMNS)
            self.assertNotIn(column,EDITABLE_COLUMNS)
        self.assertIn('score',EDITABLE_COLUMNS)
        self.assertIn('wizard_eligible_at',EDITABLE_COLUMNS)

    def test_revision_trigger_is_scoped_to_editor_connections(self):
        statement=revision_statement()
        self.assertIn("SUBSTRING_INDEX(USER(),'@',1)='"+EDITOR_USER+"'",statement)
        self.assertIn('SET NEW.revision=OLD.revision+1',statement)
