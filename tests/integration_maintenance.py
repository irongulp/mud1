"""Independent Nginx maintenance acceptance; no game disks or public requests.

Run with MUD86_NGINX_IMAGE=<image containing /usr/sbin/nginx>
.venv/bin/python -m tests.integration_maintenance.
"""
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4

from tools.deploy import nginx_config
from server.maintenance import MESSAGE


class NginxMaintenanceTests(unittest.TestCase):
    def test_notice_and_retry_with_gateway_absent(self):
        image = os.environ['MUD86_NGINX_IMAGE']
        with tempfile.TemporaryDirectory(prefix='maintenance-', dir=Path(__file__).resolve().parents[1] / 'runtime') as directory:
            root = Path(directory)
            flag = root / 'maintenance'
            flag.touch()
            config = root / 'nginx.conf'
            config.write_text('events {}\nhttp { access_log off;\n' + nginx_config('mud.etimbo.com') + '\n}\n')
            name = 'mud86-maintenance-' + uuid4().hex
            subprocess.run(['docker', 'run', '-d', '--rm', '--name', name,
                            '-p', '127.0.0.1::80', '-v', str(root) + ':/etc/mud86:ro',
                            '--entrypoint', '/usr/sbin/nginx', image,
                            '-c', '/etc/mud86/nginx.conf', '-g', 'daemon off;'], check=True, capture_output=True)
            try:
                port = int(subprocess.check_output(['docker', 'port', name, '80/tcp'], text=True).strip().rsplit(':', 1)[1])

                def request(path):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                    try:
                        connection.request('GET', path, headers={'Host': 'mud.etimbo.com'})
                        response = connection.getresponse()
                        return response.status, dict(response.getheaders()), response.read().decode('utf-8')
                    finally:
                        connection.close()

                for attempt in range(50):
                    try:
                        status, headers, body = request('/')
                        break
                    except (OSError, http.client.HTTPException):
                        if attempt == 49: raise
                        time.sleep(.1)
                self.assertEqual(status, 503)
                self.assertIn(MESSAGE, body)
                self.assertIn('900000', body)
                self.assertEqual(headers['Retry-After'], '900')
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertIn('charset=utf-8', headers['Content-Type'])
                status, headers, body = request('/maintenance-status')
                self.assertEqual(status, 503)
                self.assertEqual(json.loads(body), {'maintenance': True})
                self.assertEqual(request('/internal/maintenance')[0], 403)
                self.assertEqual(request('/terminal')[0], 503)
                flag.unlink()
                # Docker Desktop's bind mount deletion is briefly asynchronous.
                deadline = time.monotonic() + 3
                while json.loads(request('/maintenance-status')[2])['maintenance']:
                    if time.monotonic() >= deadline: self.fail('Maintenance flag deletion was not observed')
                    time.sleep(.05)
                self.assertEqual(json.loads(request('/maintenance-status')[2]), {'maintenance': False})
                # An absent gateway is now an ordinary upstream failure, not
                # scheduled maintenance. No service start is hidden in the flag.
                self.assertEqual(request('/')[0], 502)
            finally:
                subprocess.run(['docker', 'rm', '-f', name], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
