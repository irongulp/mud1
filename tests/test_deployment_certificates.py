from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.deploy import configure_proxy


class CertificateSetupTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.domain = 'mud.example.org'
        self.stack.enter_context(patch('tools.deploy.Path', side_effect=self.local_path))
        self.stack.enter_context(patch('tools.deploy.ACME', self.root / 'acme'))
        self.stack.enter_context(patch('tools.deploy.shutil.which', return_value=None))
        self.stack.enter_context(patch('tools.deploy.subprocess.run', return_value=Mock(returncode=1)))
        self.stack.enter_context(patch('tools.deploy.wait_proxy'))
        self.run = self.stack.enter_context(patch('tools.deploy.run'))
        self.prompt = self.stack.enter_context(patch('builtins.input', return_value='owner@example.org'))
        self.local_path('/etc/nginx/conf.d').mkdir(parents=True)

    def local_path(self, path):
        return self.root / str(path).lstrip('/')

    def existing_certificate(self):
        certificate = self.local_path(f'/etc/letsencrypt/live/{self.domain}/fullchain.pem')
        certificate.parent.mkdir(parents=True)
        certificate.touch()

    def certbot_command(self):
        commands = [call.args for call in self.run.call_args_list if call.args[0] == 'certbot']
        self.assertEqual(len(commands), 1)
        return commands[0]

    def test_existing_certificate_reuses_account_without_prompt_and_still_checks_renewal(self):
        self.existing_certificate()
        configure_proxy(self.domain, http_only=False, email=None)
        self.prompt.assert_not_called()
        command = self.certbot_command()
        self.assertNotIn('--email', command)
        self.assertIn('--non-interactive', command)
        self.assertIn('--keep-until-expiring', command)
        self.assertIn(self.domain, command)
        self.run.assert_any_call('systemctl', 'enable', '--now', 'certbot-renew.timer')
        self.assertIn('listen 443 ssl', self.local_path('/etc/nginx/conf.d/mud86.conf').read_text())

    def test_new_certificate_prompts_for_account_email(self):
        configure_proxy(self.domain, http_only=False, email=None)
        self.prompt.assert_called_once_with('Email address for the HTTPS certificate account: ')
        command = self.certbot_command()
        self.assertEqual(command[command.index('--email') + 1], 'owner@example.org')

    def test_explicit_email_is_passed_without_prompt_on_first_setup_and_rerun(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    self.existing_certificate()
                self.run.reset_mock()
                configure_proxy(self.domain, http_only=False, email='explicit@example.org')
                self.prompt.assert_not_called()
                command = self.certbot_command()
                self.assertEqual(command[command.index('--email') + 1], 'explicit@example.org')

    def test_new_certificate_rejects_empty_account_email(self):
        self.prompt.return_value = '  '
        with self.assertRaisesRegex(ValueError, 'email is required'):
            configure_proxy(self.domain, http_only=False, email=None)
        self.assertFalse(any(call.args[0] == 'certbot' for call in self.run.call_args_list))

    def test_http_only_needs_no_account_or_certbot(self):
        configure_proxy(self.domain, http_only=True, email=None)
        self.prompt.assert_not_called()
        self.assertFalse(any(call.args[0] == 'certbot' for call in self.run.call_args_list))
