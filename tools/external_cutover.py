"""Installed operator entry point for external cutover and validation."""
import argparse
from pathlib import Path
from tools.external_install import cutover,verify_archwizards
from tools.persona_migrate import load_config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path)
    parser.add_argument('--simh',type=Path)
    parser.add_argument('--config-dir',type=Path,required=True)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if args.verify_only:
        verify_archwizards(load_config(args.config_dir/'personas.json')); print('External archwizard records verified; passwords retained')
    else:
        if args.state is None or args.simh is None: parser.error('--state and --simh required')
        cutover(args.state,args.config_dir,args.simh)
        print('Native snapshot imported and external guest prepared; admission remains controlled by setup')


if __name__=='__main__': main()
