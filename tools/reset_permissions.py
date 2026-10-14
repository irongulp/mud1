"""Enable original in-game RESET by configuring the guest executable protection.

Run against an explicit local TOPS-10 Telnet port. This changes only MUD.EXE's
protection, not its contents, player accounts, or the game's authorization rules.
TOPS-10 <051> also permits other-project write/rename/delete/attribute operations;
it is not a reset-only permission. Keep guest Telnet access private.
"""
import argparse
import logging
import re

from tools.inspect_game import InspectionError, NativeInspector

EXECUTABLE = 'DSKB:MUD.EXE[2011,2776]'
READ_ONLY_PROTECTION = '055'
RESET_PROTECTION = '051'
RECONCILIATION_ATTEMPTS = 2
LOG = logging.getLogger(__name__)


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
    changed = configure_port(args.port, enable=not args.disable)
    target = READ_ONLY_PROTECTION if args.disable else RESET_PROTECTION
    print(EXECUTABLE + ' <' + target + '> ' + ('configured' if changed else 'already configured'))


def configure_port(port, *, enable=True):
    """Reconcile uncertain metadata through a fresh read after confirmed logout.

    configure always reads before PROTECT. Thus a lost successful reply is
    resolved by observing the target, not by blindly replaying the mutation.
    Unexpected protections and read-back mismatches remain hard failures.
    """
    for attempt in range(RECONCILIATION_ATTEMPTS):
        native = NativeInspector(port)
        admitted = False
        try:
            with native:
                admitted = True
                return configure(native, enable=enable)
        except (InspectionError, OSError, EOFError) as error:
            if not admitted or not native.cleanup_confirmed or attempt + 1 == RECONCILIATION_ATTEMPTS:
                raise
            LOG.warning('Reconnecting for permission read-back after %s; prior logout confirmed',
                        type(error).__name__)


if __name__ == '__main__':
    main()
