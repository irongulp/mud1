"""Terminal initializer setup for an explicitly selected external guest."""
import time

LINE_DELAY=.1


def local_tty_config(text):
    lines=text.replace('\r','').splitlines()
    if not any(line.startswith('ALL ') for line in lines) or not any(line.startswith('CTY:') for line in lines):
        raise RuntimeError('Unrecognized external guest terminal configuration')
    return '\n'.join(line for line in lines if not line.lstrip().upper().startswith('STOMP '))+'\n'


def protect_bridge_terminals(machine):
    response=machine.command('type sys:tty.ini').replace('\r','')
    original=response.split('\n',1)[1].rsplit('\n.',1)[0]; desired=local_tty_config(original)
    if original.strip()==desired.strip(): return False
    machine.command('copy xtty.ini=sys:tty.ini')
    machine.child.send('copy sys:tty.ini=tty:\r'); machine.child.expect_exact('copy sys:tty.ini=tty:\r\n')
    for line in desired.splitlines():
        machine.child.send(line+'\r'); machine.child.expect_exact('\r\n'); time.sleep(LINE_DELAY)
    machine.child.sendcontrol('z'); machine.child.expect(r'\n\.')
    actual=machine.command('type sys:tty.ini').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    if actual.strip()!=desired.strip(): raise RuntimeError('External terminal configuration verification failed')
    return True
