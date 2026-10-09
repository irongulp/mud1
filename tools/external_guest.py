"""Controller-owned external guest sessions; no transcripts of private seeds."""
from tools.inspect_game import NativeInspector
from tools.audit_archwizards import Guest
from tools.persona_bootstrap import SeedIssuer


class ExternalGuest(NativeInspector):
    def __enter__(self):
        try:
            guest=Guest(self.port,'mudguest',[])
            self.connection=guest.connection
            self.connection.write(b'\x03\x03'); self.receive(b'\n.'); self.at_monitor=True
            return self
        except BaseException:
            import sys
            self.__exit__(*sys.exc_info()); raise
    def start(self):
        SeedIssuer().load(self)
        self.command('start',b'By what name shall I call you?'); self.receive(b'*')


def probe_external(port,store):
    from tools.persona_protocol import pack_name
    store.get(pack_name('healthchk'))
    with ExternalGuest(port) as guest:
        guest.start(); guest.send('healthchk')
        index,_,_=guest.connection.expect([rb'What sex do you wish to be\?',rb"what's the password\?",rb'lookup unavailable'],20)
        if index not in (0,1): raise RuntimeError('External in-game lookup did not pass readiness')
