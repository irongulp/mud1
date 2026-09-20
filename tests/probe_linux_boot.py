"""One bounded boot diagnostic on a STOPPED disposable deployment container."""
import argparse
import fcntl
from pathlib import Path
import re

import server.runtime as runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--throttle')
    parser.add_argument('--idle', action='store_true')
    args = parser.parse_args()
    if args.throttle and not re.fullmatch(r'[1-9][0-9]*M', args.throttle):
        parser.error('Use an instruction rate such as 5M')
    original = runtime.simulator_config
    if args.throttle:
        runtime.simulator_config = lambda *values: original(*values).replace(
            'boot tu0', f'set throttle {args.throttle}\nboot tu0')
    with (args.state / 'runtime.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        guest = runtime.Runtime(args.state, args.simh, idle=args.idle)
        try:
            guest.boot()
            print('PASS: original game reached', flush=True)
        finally:
            guest.stop()


if __name__ == '__main__':
    main()
