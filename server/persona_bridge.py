"""Production secondary-terminal owner for external persona persistence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import logging
import socket
import time

from tools.persona_write_session import serve_personas

BRIDGE_LINES=(6,7)
CONNECT_TIMEOUT=15
LOG=logging.getLogger(__name__)


def reserve_ports():
    with ExitStack() as stack:
        ports={}
        for line in BRIDGE_LINES:
            connection=stack.enter_context(socket.socket())
            connection.bind(('127.0.0.1',0)); ports[line]=connection.getsockname()[1]
        return ports


def connect_slave(machine,line,port):
    for setting in ('slave','echo'):
        if '?' in machine.command(f'set tty tty{line:o}: {setting}'):
            raise RuntimeError('Cannot configure storage terminal')
    deadline=time.monotonic()+CONNECT_TIMEOUT
    while time.monotonic()<deadline:
        channel=socket.create_connection(('127.0.0.1',port),max(.1,deadline-time.monotonic()))
        try:
            channel.settimeout(max(.1,deadline-time.monotonic())); channel.sendall(b'\r')
            data=b''
            while not data.endswith(b'\r\n'):
                block=channel.recv(1)
                if not block or len(data)>79: raise RuntimeError('Invalid storage terminal bootstrap')
                data+=block
            if data in (b'Line connection busy\r\n',b'Line connection not available\r\n'):
                channel.close(); time.sleep(.05); continue
            if data!=b'\r\n': raise RuntimeError('Unexpected storage terminal bootstrap')
            if '?' in machine.command(f'set tty tty{line:o}: no echo'):
                raise RuntimeError('Cannot suppress storage terminal echo')
            return channel
        except BaseException:
            channel.close(); raise
    raise TimeoutError('Storage terminal reconnect deadline')


class PersonaBridge:
    def __init__(self,machine,ports,store):
        self.machine,self.ports,self.store=machine,ports,store
        self.stopping=False
    def __enter__(self):
        self.stack=ExitStack()
        try:
            self.channels=[self.stack.enter_context(connect_slave(self.machine,line,self.ports[line])) for line in BRIDGE_LINES]
            self.executor=ThreadPoolExecutor(max_workers=len(self.channels))
            self.futures=[self.executor.submit(self.worker,channel) for channel in self.channels]
            return self
        except BaseException:
            self.stack.close(); raise
    def worker(self,channel):
        while not self.stopping:
            try:
                serve_personas(channel,self.store,allow_delete=True,allow_create=True,allow_admin=True)
                return
            except TimeoutError: continue
            except (OSError,ValueError) as error:
                if not self.stopping: LOG.error('Persona bridge ended: %s',type(error).__name__)
                return
    def __exit__(self,*exc):
        self.stopping=True
        for channel in self.channels:
            try: channel.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        self.executor.shutdown(wait=True); self.stack.close()
