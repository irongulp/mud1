"""Loopback-only clients for disposable deployment acceptance containers."""
import ipaddress
from urllib.parse import urlsplit

from aiohttp import ClientSession, TCPConnector, TraceConfig


def fixture_client(url):
    parsed=urlsplit(url)
    try:
        loopback=parsed.hostname=='localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback=False
    if parsed.scheme not in ('http','https') or not loopback or parsed.username or parsed.password:
        raise ValueError('Deployment fixture URL must use a loopback HTTP endpoint')
    trace=TraceConfig()
    async def reject_redirect(session,context,parameters):
        raise RuntimeError('Deployment fixture redirect refused')
    trace.on_request_redirect.append(reject_redirect)
    # HTTPS acceptance uses a self-signed certificate in the disposable container.
    return ClientSession(headers={'Host':'mud.etimbo.com'},trace_configs=[trace],
                         connector=TCPConnector(ssl=False))
