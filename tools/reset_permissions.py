"""Enable original in-game RESET by configuring the guest executable protection.

Run against an explicit local TOPS-10 Telnet port. This changes only MUD.EXE's
protection, not its contents, player accounts, or the game's authorization rules.
TOPS-10 <051> also permits other-project write/rename/delete/attribute operations;
it is not a reset-only permission. Keep guest Telnet access private.
"""
import argparse
import json
import re
import sys

from tools.inspect_game import NativeInspector

EXECUTABLE = 'DSKB:MUD.EXE[2011,2776]'
READ_ONLY_PROTECTION = '055'
RESET_PROTECTION = '051'


class ProtectionInspector(NativeInspector):
    """Report only structural facts for the one fixed, non-secret query."""
    def command(self,text,marker=b'\n.'):
        if text != 'directory '+EXECUTABLE:
            return super().command(text,marker)
        facts=dict(operation='executable-protection-query',echo_confirmed=False,response_bytes=0)
        was_monitor=self.at_monitor
        def observe(data):
            facts.update(echo_confirmed=was_monitor,response_bytes=len(data),
                directory_entry_seen=bool(re.search(rb'(?m)^MUD[ \t]+EXE[ \t]+\d+[ \t]+<[0-7]{3}>',data)),
                newline_dot_seen=b'\n.' in data,ends_cr_dot=data.endswith(b'\r.'),
                xoff_seen=b'\x13' in data,xon_seen=b'\x11' in data,bell_seen=b'\x07' in data)
        self._response_observer=observe
        try:
            return super().command(text,marker)
        except Exception as error:
            facts['error_type']=type(error).__name__
            facts['eof_seen']=getattr(self.connection,'eof',False) is True
            print(json.dumps(facts,sort_keys=True),file=sys.stderr,flush=True)
            raise
        finally:
            self._response_observer=None


def protection(listing):
    matches = re.findall(r'(?m)^MUD\s+EXE\s+\d+\s+<([0-7]{3})>\s+', listing)
    if len(matches) != 1:
        raise ValueError('Cannot identify exactly one MUD.EXE protection in the directory listing')
    return matches[0]


def configure(native, *, enable=True):
    """Idempotently change the known installation protection; verify disk metadata."""
    current = protection(native.command('directory ' + EXECUTABLE))
    target = RESET_PROTECTION if enable else READ_ONLY_PROTECTION
    if current == target:
        return False
    if current not in (READ_ONLY_PROTECTION, RESET_PROTECTION):
        raise ValueError('Unexpected MUD.EXE protection <' + current + '>; preserved for review')
    native.command('protect ' + EXECUTABLE + '<' + target + '>')
    actual = protection(native.command('directory ' + EXECUTABLE))
    if actual != target:
        raise ValueError('MUD.EXE protection verification failed: <' + actual + '>')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int, help='Loopback guest Telnet port')
    parser.add_argument('--disable', action='store_true', help='Restore the original <055> protection')
    args = parser.parse_args()
    if not 0 < args.port < 65536:
        parser.error('Supply a valid TCP port')
    with ProtectionInspector(args.port) as native:
        changed = configure(native, enable=not args.disable)
    target = READ_ONLY_PROTECTION if args.disable else RESET_PROTECTION
    print(EXECUTABLE + ' <' + target + '> ' + ('configured' if changed else 'already configured'))


if __name__ == '__main__':
    main()
