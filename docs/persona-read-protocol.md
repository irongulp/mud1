# Read-only persona protocol draft (R1)

## Status

`tools/persona_protocol.py` implements the read-only logical-record wire contract.
`tools/persona_session.py` adds challenge-bound H1 handover and credit-based R1
delivery. The standalone BCPL `PRREAD` reader now decodes complete synthetic
records under MUDGUEST. See [persona-read-native.md](persona-read-native.md) for
native handover, failure, concurrency and reboot evidence.

This follows [persona-storage-analysis.md](persona-storage-analysis.md) and the
verified [MUDGUEST channel pool](storage-channels.md). A separate
[MariaDB getter](persona-mariadb.md) now supplies database-backed records using
the same wire contract. A [generated read-only MUD adapter](external-login-readonly.md)
consumes those records in the actual game. The separate
[W1 existing-persona SAVE extension](external-save-existing.md) now verifies
explicit writes. Public deployment and the rest of the persistence lifecycle
remain outside these milestones.

## Scope and identity

Each request belongs to:

- One configured persona store, selected by trusted host/channel configuration.
  There is no guest-provided SQL name, filesystem path or arbitrary store selector.
- One freshly established **72-bit nonzero channel epoch** (`E`), written as 24
  octal digits. A reused TOPS-10 job or terminal number is not an epoch.
- One **36-bit nonzero request sequence** (`Q`), written as 12 octal digits.
- A canonical two-word packed persona name (`N0`, `N1`).

The first integration should perform one GET per lease, with only one outstanding
request. If a later connection carries more than one request, its service must
enforce increasing sequence numbers and prohibit reuse. The decoder only checks
the identity supplied by its caller; it does not allocate epochs, authenticate
peers or maintain a replay database.

The H1 handshake below establishes the epoch. Session freshness cannot be
inferred from OPEN success or from clearing terminal input, because an older
response may arrive afterward. The standalone controller supplies fresh client
challenges. The generated MUD adapter instead consumes a fresh per-run seed
through job-local TMPCOR and derives bounded per-lookup challenges; see its
integration report for that tested provisioning path.

## H1 handover

`C` and `E` are separate nonzero 72-bit values, each encoded as 24 octal digits:

```text
Guest -> H1 HELLO CCCCCCCCCCCCCCCCCCCCCCCC<CR>
Host  -> H1 OFFER CCCCCCCCCCCCCCCCCCCCCCCC EEEEEEEEEEEEEEEEEEEEEEEE<CR>
Guest -> H1 ACCEPT CCCCCCCCCCCCCCCCCCCCCCCC EEEEEEEEEEEEEEEEEEEEEEEE<CR>
Host  -> H1 READY CCCCCCCCCCCCCCCCCCCCCCCC EEEEEEEEEEEEEEEEEEEEEEEE<CR>
```

The client challenge must be fresh across invocation, job-number reuse and
emulator restart. The fixture controller uses `secrets`; the host independently
generates its epoch. Tokens correlate/fence traffic and do not authenticate it.

A new, never-used HELLO retires previous pending output. GET is legal only after
ACCEPT/READY, with sequence 1, once per epoch. The host remembers used challenges
and epochs for the connection, rejects reuse, and caps that history at 1,024
handovers; reconnect rather than evict history and accept an old challenge.
Host history is not durable across restarts, so client freshness is mandatory.

The guest may drain at most sixteen stale complete frames during OFFER/READY
acquisition, within a single five-second handshake deadline. A matching challenge
with an invalid epoch is an error. After READY, stale/mismatched R1 frames fail
the read rather than being silently ignored.

## Request

Fields are separated by exactly one ASCII space. The metavariables below are
fixed-width octal digits, not literal letters:

```text
R1 GET EEEEEEEEEEEEEEEEEEEEEEEE QQQQQQQQQQQQ NNNNNNNNNNNN NNNNNNNNNNNN<CR>
```

The request body is 70 bytes, plus CR. Host-to-TOPS-10 input uses a single CR;
the decoders also accept an optional following LF for terminal output.
Unknown versions, operations, extra fields, bad digits or invalid names are
protocol errors. There is deliberately no PUT, CREATE or DELETE in this draft.

### Name representation

Canonical names have 1–9 lowercase ASCII letters/digits, matching the union of
native login and ATTACH name representations. Login's letter-only parsing and
historical substitutions stay in BCPL. `pack_name()` does not case-fold, truncate
or rewrite user input.

Packing follows the original BCPL layout:

- `N0` bits 29–35 contain length; bits 22–28, 15–21, 8–14 and 1–7 contain the
  first four characters.
- `N1` contains the remaining five seven-bit characters at shifts 29, 22, 15,
  8 and 1.
- Both low flag bits and all unused character padding are zero in a request.

The stored record may retain sex/asleep in the low name bits; these are excluded
only when deriving its lookup key. The payload retains them. Noncanonical padding
or malformed native records are rejected, not silently repaired or merged.
Migration still needs the source-analysis checks for exceptional historical data.

## Responses

There are four outcomes:

| Status | Meaning |
|---|---|
| `FOUND` | One complete, validated logical record follows |
| `NOT_FOUND` | The authoritative store positively reports absence |
| `UNAVAILABLE` | Storage/lookup failed; this is not absence |
| `INVALID_RECORD` | Returned data cannot satisfy the logical record contract |

An error/absence response is one complete frame:

```text
R1 NOT_FOUND EEEEEEEEEEEEEEEEEEEEEEEE QQQQQQQQQQQQ<CR>
```

Substitute UNAVAILABLE or INVALID_RECORD as appropriate. Do not include backend
exception messages, credentials or record bodies in error frames.

A successful response consists of thirteen frames:

```text
R1 FOUND EEEEEEEEEEEEEEEEEEEEEEEE QQQQQQQQQQQQ 001 013<CR>
R1 WORD EEEEEEEEEEEEEEEEEEEEEEEE QQQQQQQQQQQQ 01 WWWWWWWWWWWW<CR>
... exactly one WORD frame for each native offset 01 through 13 octal ...
R1 END EEEEEEEEEEEEEEEEEEEEEEEE QQQQQQQQQQQQ CCCCCCCCCCCC<CR>
```

- `001` is the **payload format version**, distinct from wire version R1.
- `013` is the octal word count: **11 decimal**.
- WORD indices are two octal digits and correspond to native record offsets
  **1 through 11**, in strict ascending order.
- Each word is an unsigned 36-bit pattern written as twelve octal digits.
- END contains a 36-bit XOR checksum of the format version, word count and all
  eleven payload words. It detects some corruption but is not authentication or
  a cryptographic integrity check. Identity and order are validated separately.

The native record's offset 0 (`POINTR`) is excluded: it is physical hash/free-list
bookkeeping. The eleven payload words preserve PN/games, both name words, score,
characteristics, native last-use time, states, password and all three unused words.
No host-side clamping, password transformation or gameplay calculation is allowed.

`LogicalRecord` holds an immutable tuple of those exact raw words. Its name must
match the request after excluding the two name flag bits. The constructor rejects
wrong lengths, out-of-range values and malformed name representations. Python
representations of records/results omit payloads because the native password is
among those words; encoded bytes must likewise stay out of ordinary logs.

## Completeness, deadlines and caller behavior

### Stop-and-wait credit

The socket service sends one response frame, then waits for:

```text
R1 ACK EEEEEEEEEEEEEEEEEEEEEEEE QQQQQQQQQQQQ II<CR>
```

`II` is the two-digit octal response ordinal: 00 for the header, 01–13 for
the eleven words, and 14 for END. A non-FOUND status is credited with ACK 00.
Only the exact current epoch, sequence and ordinal release the next frame.
The final ACK retires the read. ACKs do not reset the response deadline.

This adds flow control around the existing R1 response frames; it does not
change their encoding or make ACKs part of `ResponseDecoder` input. At most
one host response frame is outstanding, avoiding a full-record typeahead burst.

### Atomic decoding

`ResponseDecoder` accumulates private scratch state and exposes `result` only
after a complete status frame or a valid FOUND/WORD/END sequence. A partial
record, missing END, duplicate/out-of-order index, mismatched epoch/sequence,
wrong persona, unsupported format/count or bad checksum cannot become FOUND.
Failures poison the decoder; start a new operation rather than feed later bytes
into a failed instance.

The draft limits are:

- 79 bytes per line body.
- 11 payload words and 13 response frames for FOUND.
- 1,053 bytes as a total response ceiling, accommodating line terminators.
- Five seconds for the **whole response**, not five seconds restarted per byte
  or WORD frame. A valid CR-only FOUND response is 795 bytes (808 with CRLF).

Callers must apply `decoder.deadline` to socket reads, call `check_deadline()`
while waiting without data, and call `finish()` at EOF. A pure decoder cannot
interrupt a blocking socket or database call on its own. The future service must
also bound request reception, backend lookup and response transmission.

`lookup_response(request, fetch)` is a synchronous contract shim for tests and
future adapters. It obtains a whole record from a getter in an already selected
store. Only `None` means NOT_FOUND. A typed `InvalidRecord` from the storage
boundary, malformed data or a wrong-persona value maps to INVALID_RECORD; other
exceptions map to UNAVAILABLE. This codec shim supplies no I/O timeout itself.
Use the process-isolated database getter for bounded backend calls.

The guest must stage all words privately and check the final identity/checksum
before copying anything into the live profile. Only a validated NOT_FOUND may
reach native new-persona handling. Every transport, allocation or storage error
must take a separate path.

## Validation and next implementation gate

```sh
.venv/bin/python -m unittest tests.test_persona_session tests.test_persona_protocol tests.test_storage_bridge -v
```

The combined 42 host tests pass: 14 for H1/socket delivery, 18 for R1 and 10 for
B1. R1 tests include all
native name lengths and ATTACH digits, exact signed-bit/opaque-word preservation,
byte-at-a-time reconstruction, CR/CRLF handling, mixed epochs/sequences, missing/
extra/reordered words, malformed format/count/checksum, wrong persona despite a
valid checksum, whole-response deadlines, truncated input and distinct absence/
failure outcomes. No native persona data or password was used as a fixture.

Native tests now verify handover, private staging, full-record credit flow,
malformed replies, timeouts and restart using synthetic fixtures. They do not
test an unpaced record burst. The later MariaDB acceptance also verifies bounded
database-backed reads. The generated adapter subsequently passed targeted
modified-executable authentication and gameplay checks, with unsupported
persistence paths explicitly gated. External writes require a new acceptance
milestone rather than merely removing those gates.

W1 supplies a separate transaction and ambiguous-commit/idempotency contract.
R1 sequence numbers and END checksums alone do not provide write semantics.
