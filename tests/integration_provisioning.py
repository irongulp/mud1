"""Exercise first-install provisioning on an isolated first-playable disk copy."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from tools.audit_archwizards import ARCHWIZARDS, Guest, MAX_BOOT_ATTEMPTS, logoff
from tools.benchmark_idle import Emulator
from tools.provision_archwizards import CREDENTIAL_FILE, NativePersonas, provision, render_credentials

ROOT = Path(__file__).resolve().parents[1]
CLI_TIMEOUT = 180


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def source_hashes():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (ROOT / 'source').rglob('*') if path.is_file()}


def run(output):
    output.mkdir(mode=0o700)
    state = output / 'private'
    report = {'complete': False}
    original_sources = source_hashes()
    machine = wire = None
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print(f'Provisioning integration: private boot {attempt + 1}', flush=True)
            machine = Emulator(output / f'machine-{attempt + 1}', 'noidle', speed_factor=8)
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        command = [sys.executable, '-m', 'tools.provision_archwizards', '--port', str(machine.port),
                   '--state-dir', str(state)]
        first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=CLI_TIMEOUT)
        require(first.returncode == 0, 'First CLI run failed: ' + first.stderr)
        initial_journal = (state / CREDENTIAL_FILE).read_bytes()
        require(state.stat().st_mode & 0o777 == 0o700, 'Credential directory is not owner-only')
        require((state / CREDENTIAL_FILE).stat().st_mode & 0o777 == 0o600,
                'Credential journal is not owner-only')
        entries = json.loads(initial_journal)['credentials']
        require(set(entries) == set(ARCHWIZARDS), 'Missing archwizard credentials')
        require(all(entry['initial_password_word'] for entry in entries.values()), 'A saved password is zero')
        require(len({entry['initial_password_word'] for entry in entries.values()}) == len(ARCHWIZARDS),
                'Generated credentials collided in native password values')
        require(all(entry['initial_password'] not in first.stdout + first.stderr for entry in entries.values()),
                'Default CLI output disclosed credentials')
        report['first_run'] = 'seven saved personas; seven distinct nonzero native password values'

        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=CLI_TIMEOUT)
        require(second.returncode == 0, 'Second CLI run failed: ' + second.stderr)
        require((state / CREDENTIAL_FILE).read_bytes() == initial_journal, 'Rerun changed credential journal')
        require(second.stdout.count('preserved (') == len(ARCHWIZARDS), 'Rerun did not preserve all personas')
        require(all(entry['initial_password'] not in second.stdout + second.stderr for entry in entries.values()),
                'Rerun output disclosed credentials')
        report['rerun'] = 'all seven preserved; credential journal byte-identical'

        with NativePersonas(machine.port) as native:
            before = native.records()
            report['direct_logins'] = {}
            for name in ARCHWIZARDS:
                guest = Guest(machine.port, 'mudguest', [], wire)
                wire = guest.connection
                accepted = guest.authenticate(name, entries[name]['initial_password'])
                require(accepted == (name != 'Richard'), 'Unexpected direct-login result for ' + name)
                report['direct_logins'][name] = accepted
                guest.close()
            after_logins = native.records()
            require(all(after_logins[name.lower()]['password_word'] == entry['initial_password_word']
                        for name, entry in entries.items()), 'Login checks changed a stored password')

            guest = Guest(machine.port, 'mudguest', [], wire)
            wire = guest.connection
            require(guest.authenticate('Roy', entries['Roy']['initial_password']), 'Roy login failed')
            attached = guest.attach('Richard', entries['Richard']['initial_password'])
            require(attached == {'prompted': True, 'accepted': True}, 'Richard attachment failed')
            report['richard_attachment'] = attached
            # Reproduce the real persistence case so the provisioner must
            # preserve an altered credential, not silently reset it on rerun.
            guest.save('Richard')
            guest.close()
            drifted = native.records()
            require(drifted['richard']['password_word'] == before['roy']['password_word'],
                    'Attached SAVE did not establish the changed-password fixture')
            result = provision(native, state)
            richard = next(row for row in result if row['name'] == 'Richard')
            require(richard == {'name': 'Richard', 'status': 'changed'}, 'Changed Richard credential was mislabelled')
            require(entries['Richard']['initial_password'] not in render_credentials(result, reveal=True),
                    'Stale Richard credential was shown as current')
            require(native.records() == drifted, 'Rerun modified native persona records')
            require((state / CREDENTIAL_FILE).read_bytes() == initial_journal, 'Rerun replaced initial credentials')
            report['password_change'] = 'native change preserved; stale Richard credential suppressed'
            logoff(wire)
            wire = None
        report['source_modified'] = source_hashes() != original_sources
        require(not report['source_modified'], 'Original source files changed')
        console = (machine.directory / 'console.log').read_text()
        require(all(entry['initial_password'] not in console for entry in entries.values()),
                'Emulator console log contains a generated password')
        report['private_storage_and_output'] = '0700 directory, 0600 journal; no credentials in default output or console log'
        report['complete'] = True
        print(json.dumps(report, indent=2), flush=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if wire is not None:
            wire.close()
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'runtime' / f'provisioning-check-{time.time_ns()}')
    args = parser.parse_args()
    run(args.output.resolve())
