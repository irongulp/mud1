from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.deployment_scope import verify_scope


class ScopeEvidenceTests(unittest.TestCase):
    def test_profile_verification_is_not_a_second_final_installation_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=root/'etc/mud86'
            config.mkdir(parents=True)
            (config/'deployment.json').write_text('{"monitor_scope":true}')
            (config/'runtime.env').write_text('MUD86_MONITOR_SCOPE=1\n')
            boot=root/'var/lib/mud86/monitor-boots/fixture'
            boot.mkdir(parents=True)
            (boot/'03-profile-verified.json').write_text('{"installed":false,"stage":"profile-verified"}')
            final=boot/'08-verified.json'
            final.write_text('{"installed":true,"stage":"verified"}')
            def invoke(container,*command):
                output=io.StringIO()
                with patch('pathlib.Path',side_effect=lambda name:root/str(name).lstrip('/')),redirect_stdout(output):
                    exec(command[-1],{})
                return output.getvalue()
            with patch.dict('os.environ',{'MUD86_TEST_MONITOR_SCOPE':'1'}):
                self.assertEqual(verify_scope('fixture',invoke),{'verified_boots':1,'monitor_scope':True})
                final.unlink()
                with self.assertRaises(AssertionError): verify_scope('fixture',invoke)
