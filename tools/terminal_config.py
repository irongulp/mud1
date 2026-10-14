"""Terminal initializer setup for an explicitly selected browser/external guest."""
import re

STAGED_TTY = 'sys:xtty.tmp'


def local_tty_config(text):
    lines=text.replace('\r','').splitlines()
    if not any(line.startswith('ALL ') for line in lines) or not any(line.startswith('CTY:') for line in lines):
        raise RuntimeError('Unrecognized guest terminal configuration')
    return '\n'.join(line for line in lines if not line.lstrip().upper().startswith('STOMP '))+'\n'


def protect_bridge_terminals(machine):
    response=machine.command('type sys:tty.ini').replace('\r','')
    original=response.split('\n',1)[1].rsplit('\n.',1)[0]; desired=local_tty_config(original)
    if original.strip()==desired.strip(): return False
    listing = machine.command('directory ' + STAGED_TTY)
    missing = (re.search(r'(?mi)^\?No such file\r?$', listing)
               or re.search(r'(?mi)^%WLDNSF No such files as '+re.escape(STAGED_TTY)+r'\r?$', listing))
    if not missing:
        raise RuntimeError('Guest terminal staging file exists or cannot be checked; preserved for review')
    machine.copy_text(STAGED_TTY, desired)
    staged=machine.command('type '+STAGED_TTY).replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    if staged.strip()!=desired.strip():
        raise RuntimeError('Staged terminal configuration verification failed; active file preserved')
    machine.command('copy xtty.ini=sys:tty.ini')
    machine.command('copy sys:tty.ini='+STAGED_TTY)
    actual=machine.command('type sys:tty.ini').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    if actual.strip()!=desired.strip(): raise RuntimeError('Guest terminal configuration verification failed')
    return True
