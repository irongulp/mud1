"""Build/cache the pinned local timer correction in an independent tree."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import tempfile

from tools.simh_timer import (REVISION as SIMH_REVISION, PATCH_ID, patched_timer,
    ORIGINAL_SHA256 as ORIGINAL_TIMER_SHA256, PATCHED_SHA256 as PATCHED_TIMER_SHA256)

GIT_TIMEOUT_SECONDS = 30
BUILD_TIMEOUT_SECONDS = 180
BUILD_REAP_SECONDS = 5
BINARY = Path('source/BIN/pdp10')
ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_cache(cache):
    try:
        metadata = json.loads((cache/'manifest.json').read_text())
        binary = cache/BINARY
        if (metadata['revision'] != SIMH_REVISION or metadata['patch_id'] != PATCH_ID
                or metadata['timer_sha256'] != PATCHED_TIMER_SHA256
                or digest(cache/'source/PDP10/pdp10_tim.c') != PATCHED_TIMER_SHA256
                or binary.is_symlink() or not os.access(binary, os.X_OK)
                or digest(binary) != metadata['binary_sha256']):
            raise ValueError()
        return binary
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Local simulator cache is incomplete or changed; retained for inspection') from None


def run_build(command, tree, log, *, timeout=BUILD_TIMEOUT_SECONDS):
    process = subprocess.Popen(command, cwd=tree, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        result = process.wait(timeout=timeout)
        if result:
            raise subprocess.CalledProcessError(result, command)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=BUILD_REAP_SECONDS)
        raise


def ensure_simulator(source, cache, *, runner=None):
    source, cache = Path(source).resolve(), Path(cache).resolve()
    if cache == source or source in cache.parents or cache in source.parents:
        raise ValueError('Local simulator cache must be separate from the original source tree')
    run = runner or subprocess.run
    cache.parent.mkdir(parents=True, exist_ok=True)
    with (cache.parent/(cache.name+'.lock')).open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cache.exists():
            return verified_cache(cache)
        revision = run(['git', '--no-replace-objects', '-C', str(source), 'rev-parse', 'HEAD'],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                       timeout=GIT_TIMEOUT_SECONDS).stdout.strip()
        if revision != SIMH_REVISION:
            raise ValueError('Unsupported original SIMH source revision')
        # Failed builds remain private and inspectable. Publish only after all
        # source/binary checks succeed, using one directory rename.
        stage = Path(tempfile.mkdtemp(prefix='.'+cache.name+'-', dir=cache.parent))
        archive = stage/'source.tar'
        with archive.open('wb') as stream:
            run(['git', '--no-replace-objects', '-C', str(source), 'archive', SIMH_REVISION],
                check=True, stdout=stream, stderr=subprocess.PIPE, timeout=GIT_TIMEOUT_SECONDS)
        tree = stage/'source'
        tree.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(tree, filter='data')
        archive.unlink()
        timer = tree/'PDP10/pdp10_tim.c'
        if digest(timer) != ORIGINAL_TIMER_SHA256:
            raise ValueError('Unsupported archived timer checksum')
        corrected = patched_timer(timer.read_text()).encode('utf-8')
        if hashlib.sha256(corrected).hexdigest() != PATCHED_TIMER_SHA256:
            raise ValueError('Unexpected corrected timer checksum')
        timer.write_bytes(corrected)
        (tree/'.git-commit-id').write_text('SIM_GIT_COMMIT_ID '+SIMH_REVISION+'+'+PATCH_ID
                                          +'\nSIM_GIT_UNCOMMITTED_CHANGES 1\n')
        with (stage/'build.log').open('wb') as log:
            command = ['make', 'pdp10', 'USEFUL_PACKAGES=', 'OPTIONAL_PACKAGES=', 'GIT_REPO=']
            if runner is None:
                run_build(command, tree, log)
            else:
                run(command, cwd=tree, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=BUILD_TIMEOUT_SECONDS)
        binary = stage/BINARY
        if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
            raise ValueError('Local simulator build did not produce an executable')
        metadata = dict(revision=SIMH_REVISION, patch_id=PATCH_ID, timer_sha256=digest(timer),
                        binary_sha256=digest(binary))
        with (stage/'manifest.json').open('w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(metadata, stream, indent=2)
            stream.write('\n')
        verified_cache(stage)
        stage.rename(cache)
        return verified_cache(cache)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'upstream/simh')
    parser.add_argument('--cache', type=Path, default=ROOT/'build/local-simh')
    args = parser.parse_args()
    print(ensure_simulator(args.source, args.cache))
