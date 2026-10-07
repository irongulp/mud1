"""Two disposable MUD worlds compiled by the original DBASE, sharing personas."""
import hashlib
from tools.prepare import normalize
from tests.integration_storage_bridge import ROOT
from tests.integration_provisioning import require


def world_sources():
    source = normalize((ROOT / 'source/MUD.TXT').read_bytes())
    mud = source.replace(b'chain\tvalley\troad4', b'chain\tvalley\tstart')
    require(mud != source, 'Missing native chain portal')
    valley = mud.replace(b'*name\tMud', b'*name\tValley').replace(b'chain\tvalley\tstart', b'chain\tmud\tstart')
    return mud, valley


def install_worlds(machine, native, output):
    mud, valley = world_sources()
    native.command('copy natdb.txt=mud.txt')
    native.command('set tty no altmode')
    def rendered(value):
        return '\n'.join(line.expandtabs(8).rstrip() for line in value.splitlines()).strip()
    def type_file(name):
        text = native.command('type ' + name).replace('\r', '')
        return text.split('\n', 1)[1].rsplit('\n.', 1)[0]
    original = normalize((ROOT / 'source/MUD.TXT').read_bytes()).decode('ascii')
    baseline = type_file('natdb.txt')
    # A few original object rows exceed the monitor's maximum width. Check all
    # non-whitespace source, then compare the entire before/after terminal render
    # with only the two intended, short-line substitutions (including whitespace).
    require(''.join(baseline.split()) == ''.join(original.split()), 'Native world source differs from pinned text')
    for world, data in (('mud', mud), ('valley', valley)):
        replacements = []
        if world == 'valley': replacements.append(('*name\tMud', '*name\tValley'))
        replacements.append(('chain\tvalley\troad4', 'chain\t' + ('valley' if world == 'mud' else 'mud') + '\tstart'))
        edit = 'ERnatdb.txt\x1bEWmud.txt\x1bY'
        for old, new in replacements:
            edit += f'N{old}\x1b-{len(old)}DI{new}\x1b'
        edit += 'EX\x1b\x1b'
        native.command('r teco', b'\n*')
        native.connection.write(edit.encode('ascii'))
        edited = native.receive(b'\n.')
        require('?' not in edited, 'Bounded TECO edit failed')
        actual = type_file('mud.txt')
        (output / (world + '-world.txt')).write_text(actual)
        expected = rendered(baseline)
        for before, after in zip(original.splitlines(), data.decode('ascii').splitlines()):
            if before != after:
                require(expected.count(rendered(before)) == 1, 'Ambiguous world edit')
                expected = expected.replace(rendered(before), rendered(after), 1)
        require(rendered(actual) == expected, 'Generated world differs from verified edits')
        native.command('copy ' + ('chainm' if world == 'mud' else 'valley') + '.txt=mud.txt')
        marker = (world.upper() + ' saved').encode('ascii')
        native.send('run dbase' + (' -valley' if world == 'valley' else ''))
        compiled = native.connection.read_until(marker, 120)
        (output / (world + '-dbase.txt')).write_bytes(compiled)
        require(compiled.endswith(marker), 'Original DBASE did not publish ' + world + '; inspect its private build log')
        native.receive(b'\n.'); native.at_monitor = True
        native.command('copy ' + ('chainm' if world == 'mud' else 'chainv') + '.dmp=mud.dmp')
        native.command('protect ' + world + '.exe<055>')
        for kind in 'rtomcg':
            native.command('protect ' + world + '.?' + kind + 'm<055>')
    native.command('copy mud.dmp=chainm.dmp')
    native.command('copy mud.txt=chainm.txt')
    return {'mud_sha256': hashlib.sha256(mud).hexdigest(), 'valley_sha256': hashlib.sha256(valley).hexdigest(),
            'rooms': 420, 'shared_persona_name': 'mud'}
