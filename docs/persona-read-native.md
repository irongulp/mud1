# Native read-only persona transport verification

## Result

The standalone `PRREAD.BCL` program now performs **challenge-bound epoch
handover and complete R1 record decoding under MUDGUEST** on the original
TOPS-10 runtime. The host supplies synthetic records, not database results.

Follow-up: [persona-mariadb.md](persona-mariadb.md) now verifies the same reader
against real MariaDB through a process-bounded getter. This page records the
preceding in-memory transport milestone.
The later [read-only MUD integration](external-login-readonly.md) goes further:
the actual game consumes database personas with dynamic I/O channels and
TMPCOR-provisioned per-run seeds.

The final run is `runtime/persona-read-verified/` (2026-09-26). It passed 23
completed read attempts plus an interrupted old-owner scenario, including:

- Full eleven-word records, including high bits, name flags and opaque words.
- Two guest jobs on separate pooled terminals.
- Reuse of the same still-connected socket after an owner is killed mid-record.
- Rejection/draining of stale handshakes and rejection of invalid active replies.
- Host-responder restart and a clean restart of the same disposable guest disk.
- Byte-identical persona files before and after the experiments, including reboot.

This is a transport milestone. No MUD executable was relinked, no persona was
loaded into the actual game's profile, and no MariaDB adapter was installed.
See [persona-read-protocol.md](persona-read-protocol.md) for the wire contract
and [storage-channels.md](storage-channels.md) for native ownership findings.

## Implementation

| File | Responsibility |
|---|---|
| `tools/persona_session.py` | H1 ownership state, fresh host epochs, one-frame credit, bounded framing and fixture-backed socket service |
| `tools/fixtures/PRREAD.BCL` | Standalone guest claim, handshake, GET, private staging, validation, publication and release |
| `tests/test_persona_session.py` | Session retirement, confirmation, credit, deadlines and real socket tests |
| `tests/integration_persona_read.py` | Disposable compilation, MUDGUEST sessions, fault injection, persistent handover and same-disk reboot |

The fixture uses native OPEN/RELEASE on the two-member DZ 6/7 pool. Like BRGP,
it reserves I/O channel 17 octal only because it is standalone; an integrated
MUD adapter must obtain a free channel through the existing library.

Each invocation receives a new 72-bit challenge from the private Python test
controller on its controlling TTY, followed by the two canonical name words.
The host session generates a separate fresh 72-bit epoch using `secrets`.
The controlling TTY carries setup and result markers, not returned record words.

**Challenge provisioning is an explicit test precondition.** This proves the
handover protocol when challenges are fresh; it does not implement a source of
fresh challenges inside MUD. Neither challenge nor epoch is an authentication
credential. Do not substitute a reused job number, line number or repeatable
boot clock for the controller's challenge in a future adapter.

## Epoch handover

The private connection may remain open across guest owners:

```text
Guest claims terminal and clears its pending input
Guest -> H1 HELLO <fresh challenge>
Host  -> H1 OFFER <same challenge> <new epoch>
Guest -> H1 ACCEPT <same challenge> <same epoch>
Host  -> H1 READY <same challenge> <same epoch>
Guest -> R1 GET <epoch> <sequence 1> <name words>
```

The host accepts GET only after confirmation. A never-used HELLO retires the
previous owner and any unsent record frames. The fixture host has no detached
lookup worker capable of sending after retirement: it takes an in-memory
snapshot synchronously, then emits only under credit.

During OFFER/READY acquisition, the guest can drain at most sixteen stale
complete lines, bounded by one five-second handshake deadline. It accepts only
the current challenge and the offered epoch. After READY, a wrong epoch,
sequence or frame is a failed read, not silently skipped data.

The important abandonment test pauses host delivery at the second WORD. The
old guest is interrupted and KJOBed; a different MUDGUEST job claims the same
line using the same host socket. The test injects the old OFFER, READY and a
pending old WORD before the new OFFER. The new job drains those stale frames,
binds a new epoch and completes its own record.

## Flow control and private publication

The host sends only one R1 response frame at a time. The guest validates it and
acknowledges its ordinal before the host sends another. There is no fixed baud
sleep in normal service and no 795-byte record burst into native typeahead.

For a FOUND result:

- ACK 00 credits the header.
- ACK 01 through 13 octal credit the eleven WORD frames.
- ACK 14 octal credits the validated END.

The largest R1 data frame in this format has 61 body bytes plus CR. The header,
ordered words, END checksum and packed name must all validate before the guest
copies its scratch vector into the published-record vector. On failure, it
checks that every word of the published vector still equals its initial
sentinel and prints `UNPUBLISHED`. Any partial update instead produces the
explicit failing marker `PARTIAL_COMMIT`.

The synthetic fixture verifies all eleven committed words internally, including
the sign bit, all-ones, sex/asleep bits and unused words. It prints only
`FOUND 11 VERIFIED`, never the password-position word or an aggregate value
from which it could be recovered. This executable is a fixture verifier, not
a general-purpose persona inspector.

The handshake and read each have a five-second native deadline. Acknowledgements
do not extend the read deadline. These are emulator-clock bounds; the acceptance
runner additionally checks a twelve-second host bound for the complete call.
They do not promise wall-clock progress while an emulator is stopped.

## Acceptance results

Final observed host durations include program/control overhead:

| Scenario | Result |
|---|---|
| `fred`, `abcdefghi`, `test1` | Full native verification in 0.850–0.890 seconds |
| Completed-owner handover with stale handshake frames | Verified in 0.982 seconds |
| Abandoned partial read, same socket/new job, stale frames | Verified in 1.048 seconds |
| NOT_FOUND / UNAVAILABLE / INVALID_RECORD | Distinct outcomes; published vector untouched |
| Byte-fragmented responses | Full record verified in 2.158 seconds |
| Wrong epoch or sequence | Rejected, unpublished, channel released |
| Duplicate/out-of-order word index | Rejected, unpublished, channel released |
| Invalid octal digit | Rejected, unpublished, channel released |
| Wrong persona with a recomputed valid checksum | Rejected by native name comparison |
| Wrong final checksum | Rejected before publication |
| Incomplete reply / silence / peer disconnect | Native timeout, unpublished; 5.213–5.220 seconds |
| Responder stops before READY | Native timeout in 5.101 seconds |
| New responder after restart, replaying old handshake | Fresh epoch and successful record |
| Two simultaneous jobs | Different lines and epochs; both records verified |
| Clean KSYS, emulator restart on the same disk, old-handshake replay | Fresh challenge/epoch and successful record |

Ten calls returned validated synthetic records (110 committed payload words).
Three returned legitimate non-FOUND statuses, six rejected invalid replies,
and four timed out. The deliberately interrupted old owner is additional to
those 23 completed calls; it never reported FOUND.

FILCOM `/B` confirmed persona-file byte preservation both before reboot and
after the post-reboot read. Original `source/` SHA-256 values also stayed
unchanged. The guest binary was compiled with the original BCPL compiler/library
on the private disk; no engine authentication/layout test is implied.

## Reproduction and evidence

```sh
.venv/bin/python -m unittest tests.test_persona_session tests.test_persona_protocol tests.test_storage_bridge -v
.venv/bin/python -m tests.integration_persona_read
```

The runner also accepts `--output runtime/<fresh-directory>`. It uses the stopped
first-playable baseline, original tape boot, private loopback ports and the
NOIDLE / 5M / SPEED=*8 profile. It never redirects to a live disk. It performs
KSYS before the same-disk reboot and stops the private emulator at final exit.

There are 42 passing host tests: 14 H1/socket tests, 18 R1 codec tests and 10 B1
tests. The H1 suite includes socket-level credit gating and Python 3.9 timeout
normalization as well as pure state-machine tests.

Final evidence: `runtime/persona-read-verified/report.json`, guest control
transcripts `a.txt`, `b.txt`, `reboot.txt`, `installation.txt`, and the machine's
`console.log`. Reports contain synthetic case outcomes and correlation metadata,
not returned persona/password bodies. Earlier runs remain available:

- `persona-read-first`: the installation helper correctly rejected a companion
  name containing a digit; the program was renamed PRREAD.
- `persona-read-compile`: native records and initial faults passed, then a
  rapid socket replacement received SIMH's explicit busy response.
- `persona-read-handover`: complete native acceptance including reboot; the
  later run adds a persona comparison after that reboot.
- `persona-read-final`: a rapid fault-test reconnect was followed by a brief
  NO_CHANNEL result. Its precise monitor-state cause was not isolated.

The harness now retries only explicit SIMH busy/unavailable connection replies
within a three-second bootstrap bound, and pre-protocol NO_CHANNEL for at most
one second with a new challenge. It does not retry protocol failures, timeouts
or reads already issued. Every final verified call claimed a channel on its
first attempt; those retries did not hide an R1 failure.

## Next boundary

The transport can now carry a complete record under the intended guest account.
The subsequent [MariaDB getter milestone](persona-mariadb.md) adds bounded
backend I/O and real database fixtures. The original in-memory fixture callback
is not itself a database timeout/cancellation mechanism.

Before embedding this in MUD, also provide trusted fresh-challenge provisioning
for the real guest adapter, replace the fixture's fixed I/O channel, and preserve
the source-analysis interception/locking rules. The fixture runner still manages
operator bootstrap and socket recovery; it is not an unattended deployment
service. Writes, migration, authentication compatibility of a relinked MUD and
ambiguous-commit recovery remain later milestones.
