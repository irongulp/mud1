"""Failure-only physical snapshot for disposable diagnostic runtimes.

Fingerprints derive from the byte-identified images in docs/ksys-image-layout.md.
No historical code bytes, whole memory pages or terminal payloads are published.
The caller owns the existing halt/deadline; this module never resumes or extends it.
"""
import time

from server.monitor_scope import digest_words

if __package__:
    from . import ksys_mapping as mapping
else:  # /checkout/tests/shutdown_capture.py, installed app cwd without tests package.
    import ksys_mapping as mapping

MAX_PHYSICAL_PAGES = 128
REGISTERS = ('EBR', 'PGON', 'T20P', 'SPT', 'UBR', 'PC')
MONITOR_SIGNATURES = {
    (0o506706, 0o506744): '7cb7e03c3414044cbf67ba75bd8ecd05acfaa74469e14e9d234434bfcc8cc239',
    (0o506756, 0o506763): '4692f13d471e8c0dfe410e0b691ca65781713f7ac7d053c1b1d870d88a8cd873',
    (0o510516, 0o510522): '1eb3f0790cadaf6536c587aca9b97427bb07c1eeb35870146536a614f4484108',
    (0o351177, 0o351226): '7d557733d60b47c2baaa0c16b1c2fb2593d75ca3092ead1c149de2ae38f74b3d',
    (0o344245, 0o344247): '7c6c004a22c81502361b993de39aa951371bf323856c9d20b2af3a4dd8ca3615',
    (0o401334, 0o401362): 'a701c9e2743d3db167efd8416b40ae2ed40ae1e9959161808c9953410aa22a68',
    (0o401363, 0o401423): '082603ef3dbefcf98d24d3a3e645bf405b8b20051501538c2120aa23a190b062',
    (0o401554, 0o401621): '35f048cb7fd2da8a269e3fae02f3e88975cea95769b4fc87b5b81d1ed07e6bea',
    (0o350715, 0o350735): '604834eb5bc7c4ad1384ed70228285fa3341315c1bc6e2e941685c415034c5ac',
    (0o454553, 0o454574): '113dd4aa979c6f6176428da41ca0eee7adef85045ea272734e370513bec14087',
    (0o403450, 0o403525): '4dcd9a2033077ab5d6722e677a08a8094dd57fecd9e5185ee64a822e52aab43a',
    (0o406553, 0o406560): 'd6d2eef929c62cfdcd0ddfbf51040c5fe20e037f6666d81ea8faf1f7fe2ed71c',
    (0o402030, 0o402030): '8cc5bbf31a948ba5da6cd43ca3ce03b44c16bbb2ce56f75fd30274cd8b2db1a0',
}
JOB_SIGNATURES = {
    'quasar': (0o500001512, '6e0798051d66a5890b018701ba84c2c8cb39cce78ad099b37dd50535890ca54e'),
    'batcon': (0o10500005027, 'a2c95f73846f699bd04733f952dd4cac81776caaf675b419e16180fc7c012f84'),
}


def capture_halted(console, report, *, scope_verified):
    started = time.monotonic()
    cache = {}
    report.update(outcome='partial', binding=dict(status='unknown'), errors={})

    def check():
        if console.at_prompt is not True or scope_verified is not True:
            raise RuntimeError('Verified scope and existing halt required')
        if console.deadline is None or time.monotonic() >= console.deadline:
            raise TimeoutError('Diagnostic deadline exhausted')

    def physical(address):
        check()
        page = address // mapping.PAGE_WORDS
        if page not in cache:
            if len(cache) >= MAX_PHYSICAL_PAGES:
                raise RuntimeError('Physical page budget exhausted')
            first = page * mapping.PAGE_WORDS
            cache[page] = console.words(first, first + mapping.PAGE_WORDS - 1, physical=True)
        check()
        return mapping.read_word(cache[page].__getitem__, address)

    def attempt(key, operation):
        try:
            value = operation()
            check()
            return value
        except mapping.MappingError as error:
            # These errors contain only controlled messages and named numeric fields.
            report['errors'][key] = dict(reason=str(error), operands=error.evidence)
            return None

    try:
        check()
        registers = {name: console.register(name) for name in REGISTERS}
        check()
        report['registers'] = registers
        if registers['EBR'] != 2 or registers['PGON'] != 1 or registers['T20P'] != 1:
            raise mapping.MappingError('Unsupported paging profile')
        mapper = mapping.Mapper(physical, spt=registers['SPT'])
        executive = lambda address: mapper.word(registers['EBR'], address)
        for (first, last), expected in MONITOR_SIGNATURES.items():
            if digest_words(executive(a) for a in range(first, last + 1)) != expected:
                raise mapping.MappingError('Monitor signature mismatch',
                                           evidence=dict(first=first, last=last))
        report['monitor_verified'] = True
        report['jobs'] = {}
        readers = {}
        for name, fields in (('quasar', mapping.QUASAR_FIELDS), ('batcon', mapping.BATCON_FIELDS)):
            def identify():
                job = mapping.find_job(executive, physical, name.upper())
                reader = lambda address: mapper.word(job['upt'], address)
                version, expected = JOB_SIGNATURES[name]
                first, last = mapping.CODE_RANGES[name]
                if (reader(mapping.JOB_VERSION) != version
                        or digest_words(reader(a) for a in range(first, last + 1)) != expected):
                    raise mapping.MappingError('Job image signature mismatch')
                return job, reader
            identified = attempt(name + '_identity', identify)
            if identified is None:
                continue
            job, reader = identified
            report['jobs'][name] = job
            readers[name] = reader
            if name == 'quasar':
                observed = attempt('registration', lambda: mapping.registration(reader))
                if observed is not None:
                    report['registration'] = observed
            report[name + '_fields'] = {}
            for field, address in fields.items():
                value = attempt(name + '_' + field, lambda: reader(address))
                if value is not None:
                    report[name + '_fields'][field] = value
        if 'registration' in report and 'batcon' in readers:
            context = attempt('binding', lambda: mapping.bind_pid(
                executive, report['registration'], batcon_job=report['jobs']['batcon']['job']))
            if context is not None:
                report['binding'] = dict(status='verified', context=context)
        check()
        if not report['errors']:
            report['outcome'] = 'complete'
    except mapping.MappingError as error:
        report['errors']['capture'] = dict(reason=str(error), operands=error.evidence)
    except Exception as error:
        report['errors']['capture'] = dict(error_type=type(error).__name__)
        # Let private_console keep logging suppressed through teardown: a failed
        # SCP read can leave raw memory output queued after the timeout.
        raise
    finally:
        report.update(physical_pages_read=len(cache), capture_seconds=time.monotonic() - started)
