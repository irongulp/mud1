import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from tests.deployment_http import fixture_client
from tests.integration_external_deployment import login


class DeploymentHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_persona_acceptance_matches_hello_again_identity(self):
        app=web.Application()
        async def terminal(request):
            socket=web.WebSocketResponse()
            await socket.prepare(request)
            await socket.send_str('By what name shall I call you?\n*')
            self.assertEqual((await socket.receive()).data,'Deployabc\r')
            await socket.send_str("what's the password?\n*")
            self.assertEqual((await socket.receive()).data,'testpass\r')
            await socket.send_str('Hello again, Deployabc!\n*')
            self.assertEqual((await socket.receive()).data,'score\r')
            await socket.send_str('Score to date: 0\n*')
            self.assertEqual((await socket.receive()).data,'quit\r')
            await socket.send_str('\n.')
            await socket.close()
            return socket
        app.router.add_get('/terminal',terminal)
        async with TestServer(app) as server:
            transcript=await login(str(server.make_url('')).rstrip('/'),'Deployabc','testpass')
        self.assertIn('Hello again, Deployabc!',transcript)

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
