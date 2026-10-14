"""Installed operator entry point for external cutover and validation."""
import argparse
import json
from pathlib import Path
from tools.external_install import cutover,verify_archwizards
from tools.persona_migrate import load_config
from server.runtime import runtime_lease


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--simh',type=Path)
    parser.add_argument('--config-dir',type=Path,required=True)
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--runtime-lock-fd',type=int,help='Internal inherited installer lease descriptor')
    args=parser.parse_args()
    if args.verify_only:
        verify_archwizards(load_config(args.config_dir/'personas.json')); print('External archwizard records verified; passwords retained')
    else:
        if args.state is None or args.simh is None: parser.error('--state and --simh required')
        with runtime_lease(args.state, lock_fd=args.runtime_lock_fd) as descriptor:
            if json.loads((args.state/'shutdown.json').read_text()).get('clean') is not True:
                raise RuntimeError('A confirmed stopped native snapshot is required for cutover')
            cutover(args.state,args.config_dir,args.simh,runtime_lock_fd=descriptor)
        print('Native snapshot imported and external guest prepared; admission remains controlled by setup')


if __name__=='__main__': main()
