"""Reproducible timer correction for pinned SIMH 47b7ddab (host code only)."""
import argparse
import hashlib
from pathlib import Path

REVISION = '47b7ddabbe5b548cfc32f2fd45f7bed238ff7921'
PATCH_ID = 'active-tick-v1'
ORIGINAL_SHA256 = '3b39185769f46b6fddb360dc43ff02152ef74d1fb7291c18fbfacfb94a7d9d42'
PATCHED_SHA256 = '0d43430c360826f735ebfe8b59fe665c582b03584382665db42418fde400e5d9'


def patched_timer(text):
    replacements = (
        ('static int32 tim_mult;',
         'static int32 tim_active_tick_in_usecs;                 /* Duration of the scheduled tick */\n'
         'static int32 tim_mult;'),
        ('tick_in_usecs - sim_activate_time_usecs (&tim_unit)',
         'tim_active_tick_in_usecs - sim_activate_time_usecs (&tim_unit)'),
        ('static t_stat tim_svc (UNIT *uptr)\n{',
         'static t_stat tim_svc (UNIT *uptr)\n{\n'
         '/* WRINT may change the next interval before this scheduled tick expires. */\n'
         'tim_active_tick_in_usecs = tick_in_usecs;'),
        ('update_interval(17*4096);',
         'update_interval(17*4096);\n'
         'tim_active_tick_in_usecs = tick_in_usecs;'),
    )
    for original, replacement in replacements:
        if text.count(original) != 1:
            raise ValueError('Unexpected pinned SIMH timer source')
        text = text.replace(original, replacement)
    return text


def apply(source):
    """Verify exact upstream/patch bytes; reject unrelated or additional edits."""
    filename = Path(source) / 'PDP10/pdp10_tim.c'
    raw = filename.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest == PATCHED_SHA256:
        return False
    if digest != ORIGINAL_SHA256:
        raise ValueError('Unexpected pinned SIMH timer source checksum')
    corrected = patched_timer(raw.decode('utf-8').replace('\r\n', '\n')).encode('utf-8')
    corrected_digest = hashlib.sha256(corrected).hexdigest()
    if corrected_digest != PATCHED_SHA256:
        raise ValueError('Unexpected SIMH timer patch checksum: ' + corrected_digest)
    filename.write_bytes(corrected)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Independent pinned SIMH source checkout to patch')
    args = parser.parse_args()
    apply(args.source)
