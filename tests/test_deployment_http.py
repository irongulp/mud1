import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from tests.deployment_http import fixture_client


class DeploymentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_is_rejected_before_following_it(self):
        received=[]
        target_app=web.Application()
        async def target(request):
            received.append(request.path)
            return web.Response(text='unexpected target')
        target_app.router.add_get('/',target)
        async with TestServer(target_app) as target_server:
            redirect_app=web.Application()
            async def redirect(request):
                raise web.HTTPFound(str(target_server.make_url('/')))
            redirect_app.router.add_get('/',redirect)
            async with TestServer(redirect_app) as server:
                async with fixture_client(str(server.make_url('/'))) as client:
                    for request in (client.get,client.ws_connect):
                        with self.subTest(request=request.__name__),self.assertRaisesRegex(RuntimeError,'redirect'):
                            await request(server.make_url('/'))
        self.assertEqual(received,[])

    async def test_public_fixture_url_is_rejected(self):
        for url in ('https://mud.etimbo.com','http://192.0.2.1','file:///tmp/test'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                fixture_client(url)
