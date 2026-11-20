"""Read-only KS10 section-zero backing translation for halted private fixtures.

Follows pdp10_pag.c's TOPS-20-style walk (used by this TOPS-10 monitor).
Never invokes the simulator's virtual examiner, which can update CST entries.
This reports resident backing, not permission/CST-age validation for execution.
The caller must bind the monitor fingerprints and keep the guest halted for
the entire observation. No result grants guest-control or shutdown authority.
"""

PAGE_WORDS = 512
HALF_MASK = (1 << 18) - 1
WORD_MASK = (1 << 36) - 1
PHYSICAL_WORDS = 1 << 20
PAGE_MASK = 0o3777
STORAGE_MEDIUM = 0o77000000
POINTER_TYPE_SHIFT = 33
POINTER_IMMEDIATE, POINTER_SHARED, POINTER_INDIRECT = 1, 2, 3
MAP_INDEX_SHIFT, MAP_INDEX_MASK = 18, 0o777
SECTION_ZERO = 0o540
UPT_JOB = 0o322
MAX_INDIRECTIONS = 16
ALLOCATED_JOB = 0o40000 << 18
LAYOUT = dict(max_job=0o43, name=0o12106, status=0o10061,
              core=0o10346, upt=0o14174)
PSB_HEAD = 0o60036
PSB_PID, PSB_NAME, PSB_FLAGS, PSB_DEADLINE = 1, 2, 4, 5
MAX_PSBS = 64
PSB_STATUS_SHIFT = 27
PID_MASK, PID_LIMIT, PID_TABLE = 0o16101, 0o16102, 0o15735
MAX_PID_ENTRIES = 4096
QUASAR_FIELDS = dict(now=0o102624, ksys=0o102647, wake=0o102754)
BATCON_FIELDS = dict(ksys=0o457, count=0o553)
JOB_MASK = 0o777
CONTEXT_SHIFT = 9
PDB_TABLE = 0o12502
PDB_CONTEXT_CHAIN, PDB_CURRENT_CONTEXT = 0o71, 0o72
CONTEXT_NEXT = 2
MAX_CONTEXTS = 64
# QUASAR A$HELL entry / BATCON TOPLVL scheduler; both are fixed page-zero code.
# Identity does not require an otherwise unused KSYS routine to be resident.
CODE_RANGES = dict(quasar=(0o333, 0o400), batcon=(0o652, 0o707))
JOB_VERSION = 0o137


class MappingError(ValueError):
    """Unknown or incompatible mapping; never interpret as process absence."""

    def __init__(self, message, *, evidence=None):
        super().__init__(message)
        self.evidence = evidence


def sixbit(name):
    encoded = 0
    for character in name.ljust(6):
        encoded = (encoded << 6) | (ord(character) - 32)
    return encoded


def read_word(reader, address):
    try:
        word = reader(address)
    except KeyError:
        raise MappingError('Missing captured word') from None
    if type(word) is not int or not 0 <= word <= WORD_MASK:
        raise MappingError('Invalid captured word')
    return word


def verify_image(reader, image, name):
    """Bind version plus every word of a fixed code signature to a pinned image."""
    if name not in CODE_RANGES:
        raise MappingError('Unsupported job image')
    first, last = CODE_RANGES[name]
    for address in (JOB_VERSION, *range(first, last + 1)):
        if read_word(reader, address) != read_word(image.__getitem__, address):
            raise MappingError('Job image signature mismatch', evidence=dict(
                image=name, address=address))


class Mapper:
    def __init__(self, read_physical, *, spt):
        self.read_physical = read_physical
        self.spt = spt

    def physical(self, address):
        if not 0 <= address < PHYSICAL_WORDS:
            raise MappingError('Physical address out of bounds')
        return read_word(self.read_physical, address)

    def page_base(self, pointer):
        if pointer & STORAGE_MEDIUM:
            raise MappingError('Nonresident mapping')
        return (pointer & PAGE_MASK) * PAGE_WORDS

    def resolve(self, pointer, *, section):
        seen = set()
        for _ in range(MAX_INDIRECTIONS):
            if pointer in seen:
                raise MappingError('Cyclic mapping')
            seen.add(pointer)
            kind = pointer >> POINTER_TYPE_SHIFT
            if kind == POINTER_IMMEDIATE:
                self.page_base(pointer)
                return pointer
            if kind not in (POINTER_SHARED, POINTER_INDIRECT):
                raise MappingError('Inaccessible or unsupported pointer')
            indirect = self.physical(self.spt + (pointer & HALF_MASK))
            self.page_base(indirect)
            if kind == POINTER_SHARED:
                return indirect
            index = (pointer >> MAP_INDEX_SHIFT) & MAP_INDEX_MASK
            if section and index:
                raise MappingError('Unsupported nonzero section index')
            pointer = self.physical(self.page_base(indirect) + index)
        raise MappingError('Indirection budget exhausted')

    def address(self, upt, address):
        if not 0 < upt <= PAGE_MASK or not 0 <= address <= HALF_MASK:
            raise MappingError('Invalid UPT or virtual address')
        section = self.resolve(self.physical(upt * PAGE_WORDS + SECTION_ZERO), section=True)
        page = self.physical(self.page_base(section) + address // PAGE_WORDS)
        page = self.resolve(page, section=False)
        return self.page_base(page) + address % PAGE_WORDS

    def word(self, upt, address):
        return self.physical(self.address(upt, address))


def find_job(read_executive, read_physical, name):
    if name not in ('BATCON', 'QUASAR'):
        raise MappingError('Only the two diagnostic system jobs are supported')
    encoded = sixbit(name)
    jobs = [job for job in range(1, LAYOUT['max_job'] + 1)
            if read_word(read_executive, LAYOUT['name'] + job) == encoded]
    if len(jobs) != 1:
        raise MappingError('Missing or ambiguous job name')
    job = jobs[0]
    if not read_word(read_executive, LAYOUT['status'] + job) & ALLOCATED_JOB:
        raise MappingError('Unallocated job')
    if not read_word(read_executive, LAYOUT['core'] + job):
        raise MappingError('Job has no resident core')
    upt = read_word(read_executive, LAYOUT['upt'] + job) & HALF_MASK
    if not 0 < upt <= PAGE_MASK:
        raise MappingError('Missing or invalid UPT')
    if read_word(read_physical, upt * PAGE_WORDS + UPT_JOB) != job:
        raise MappingError('UPT job identity mismatch')
    return dict(job=job, upt=upt)


def current_context(executive, job):
    """Mirror JBCHCT's current-context selection, without changing guest state."""
    pdb = read_word(executive, PDB_TABLE + job) & HALF_MASK
    if not pdb or pdb + PDB_CURRENT_CONTEXT > HALF_MASK:
        raise MappingError('Missing or invalid job PDB')
    pointer = read_word(executive, pdb + PDB_CONTEXT_CHAIN)
    if not pointer:
        # JBCHCT's no-chain path: the only context is number one.
        return 1
    current = read_word(executive, pdb + PDB_CURRENT_CONTEXT)
    seen, numbers, selected = set(), set(), None
    while pointer:
        if (pointer in seen or len(seen) >= MAX_CONTEXTS
                or not 0 < pointer <= HALF_MASK - CONTEXT_NEXT):
            raise MappingError('Invalid or excessive context chain')
        seen.add(pointer)
        number = read_word(executive, pointer) & JOB_MASK
        if not number or number in numbers:
            raise MappingError('Missing or ambiguous context number')
        numbers.add(number)
        if pointer == current:
            selected = number
        pointer = read_word(executive, pointer + CONTEXT_NEXT)
    if selected is None:
        raise MappingError('Current context absent from chain')
    return selected


def registration(quasar):
    """Read QUASAR-owned PSB fields; these do not establish a current BATCON PID."""
    pointer = read_word(quasar, PSB_HEAD) & HALF_MASK
    seen, matches = set(), []
    while pointer:
        if pointer in seen or len(seen) >= MAX_PSBS or pointer + PSB_DEADLINE > HALF_MASK:
            raise MappingError('Invalid or excessive PSB chain')
        seen.add(pointer)
        if read_word(quasar, pointer + PSB_NAME) == sixbit('BATCON'):
            matches.append(pointer)
        pointer = read_word(quasar, pointer) & HALF_MASK
    if len(matches) != 1:
        raise MappingError('Missing or ambiguous BATCON PSB')
    psb = matches[0]
    flags = read_word(quasar, psb + PSB_FLAGS)
    return dict(psb=psb, psb_pid=read_word(quasar, psb + PSB_PID),
                psb_flags=flags, psb_status=flags >> PSB_STATUS_SHIFT,
                psb_deadline=read_word(quasar, psb + PSB_DEADLINE), psbs_seen=len(seen))


def bind_pid(executive, observed, *, batcon_job):
    """Validate ownership independently; never mutate raw registration evidence."""
    pid = observed['psb_pid']
    mask = read_word(executive, PID_MASK)
    limit = read_word(executive, PID_LIMIT)
    if not pid >> 18 or not 0 < mask <= HALF_MASK or not 0 < limit <= MAX_PID_ENTRIES:
        raise MappingError('Unsupported PID identity')
    index = pid & mask
    if index >= limit:
        raise MappingError('PID index out of bounds')
    entry = read_word(executive, PID_TABLE + index)
    if ((entry ^ pid) & (WORD_MASK ^ mask)) or (entry & JOB_MASK) != batcon_job:
        raise MappingError('PSB PID does not bind to BATCON job', evidence=dict(
            psb=observed['psb'], psb_pid=pid, psb_flags=observed['psb_flags'],
            pid_mask=mask, pid_limit=limit, pid_index=index, pid_entry=entry,
            expected_job=batcon_job))
    context = (entry & HALF_MASK) >> CONTEXT_SHIFT
    if context != current_context(executive, batcon_job):
        raise MappingError('PSB PID is not the current BATCON context', evidence=dict(
            psb_pid=pid, pid_entry=entry, expected_job=batcon_job, pid_context=context))
    return context


def shutdown_state(quasar, batcon, executive, *, batcon_job):
    """Strict healthy-state helper; both jobs' signatures must already match."""
    result = registration(quasar)
    result['batcon_context'] = bind_pid(executive, result, batcon_job=batcon_job)
    del result['psb_flags']  # Preserve the original strict helper's report format.
    result.update(('quasar_' + name, read_word(quasar, address))
                  for name, address in QUASAR_FIELDS.items())
    result.update(('batcon_' + name, read_word(batcon, address))
                  for name, address in BATCON_FIELDS.items())
    return result
