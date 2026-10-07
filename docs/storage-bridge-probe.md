# PDP-10 / host bridge feasibility probe

## Verified result

On 2026-09-26, a standalone BCPL program running under the original TOPS-10
7.04 exchanged PING/PONG requests with a host Python responder through an
**assigned secondary terminal**, separate from its controlling terminal.
The guest reconstructed all returned 36-bit test words, including bit 35 and
all-ones. Two guest jobs also completed the exchange concurrently using separate
reserved lines.

This completes the initial transport feasibility experiment described in
[external-storage.md](external-storage.md). It does not implement persona
lookup, a storage transaction, a production service or a MariaDB adapter.
The [persona analysis](persona-storage-analysis.md) remains the guide to the
future game interception boundary.

Follow-up: [storage-channels.md](storage-channels.md) now verifies MUDGUEST
permissions and a bounded native OPEN/RELEASE pool. The host-tested
[R1 draft](persona-read-protocol.md) defines a read-only logical record exchange.
The later [native R1 proof](persona-read-native.md) verifies that exchange and
challenge-bound handover with synthetic records under MUDGUEST.
The results and limits below describe the original B1 transport milestone.

## Components and boundary

```text
Standalone BRGP.BCL job
  controlling TTY: setup and diagnostic results only
  assigned secondary TTY: framed PING/PONG traffic
       |
       | TOPS-10 TRMOP. terminal I/O
       v
SIMH DZ line 6 or 7, dedicated raw loopback socket
       |
       v
Host storage_bridge.respond(): validate and return PONG
```

- `tools/fixtures/BRGP.BCL`: independent guest probe, compiled with the original
  BCPL compiler/library. No MUD objects are linked, and it opens no game files.
- `tools/storage_bridge.py`: bounded incremental framing and a storage-free
  responder for an already connected socket. It is not a public listener/CLI.
- `tests/test_storage_bridge.py`: host codec, framing, isolation and deadline
  tests.
- `tests/integration_storage_bridge.py`: disposable boot, compilation, reserved
  line setup, fault injection, concurrent jobs and evidence collection.

The experiment uses pinned SIMH revision
`47b7ddabbe5b548cfc32f2fd45f7bed238ff7921`. Its `pdp10` target uses
`PDP11/pdp11_dz.c`, with four eight-line DZ multiplexers configured by
`PDP10/pdp10_defs.h`. Do not confuse this with the separate `ks10_dz.c`
implementation used by other build targets.

The shared multiplexer supports a per-line raw socket via:

```text
attach dz Line=7,127.0.0.1:<private-port>;notelnet
```

This is added only to the disposable machine's configuration **before SIMH is
spawned**. Its ordinary Telnet listener uses another private port. The existing
live configuration and emulator are not used by the runner.

## Native setup findings

The operator console first marks each bridge terminal as a slave:

```text
set tty tty7: slave
```

The probe's maintenance job assigns that terminal:

```text
assign tty7: brg:
```

The runner establishes the raw connection, sends one CR and consumes the
bootstrap CRLF while echo is enabled. It then sets:

```text
set tty tty7: no echo
```

These details matter:

1. **Startup:** the first attempt without incoming data saw no complete request
   at the host. The CR bootstrap produced a working exchange in subsequent
   experiments. The exact carrier/terminal-state cause has not been isolated;
   the current runner retains the verified sequence.
2. **Echo:** program-level `TRMOP.` echo suppression alone allowed part of a
   host reply to leak back into the request stream. Explicit monitor-level
   `NO ECHO` eliminated the corruption. The host parser rejects malformed
   traffic rather than filtering out suspected echoes.
3. **Line terminators:** host replies must end with a **single CR**. Sending
   CRLF supplied an additional input terminator. The guest allows only an
   optional LF between response frames, never LF within a frame.
4. **Ownership:** secondary I/O uses `TRMOP.` against a universal terminal index.
   The probe derives its index prefix using `TRMNO.` and refuses to use its own
   controlling TTY as the bridge. Line numbers are restricted to 0–7 by this
   small fixture; the runner reserves 6 and 7.

The local extracted monitor reference is
`build/monitor/dskb:10_7.mon..scnser.mac`: `TOPTB0` at lines 7474–7489 describes
skip-input, clear-input, output-character and input-character functions;
`TOPTB1` at line 7608 and `TOPECH` at 7100 describe program echo control.
This ignored reference is useful research material, not a new build dependency.
The repeatable proof compiles/runs against the installed historical monitor.

## Experimental framing and word representation

Every request and response has fixed fields:

```text
B1 PING ssssss rrrrrr wwwwwwwwwwww<CR>
B1 PONG ssssss rrrrrr wwwwwwwwwwww<CR>
```

- `B1` is the experimental protocol version.
- Session and request IDs are six octal digits each, nonzero 18-bit values.
- The payload is twelve octal digits representing all 36 bits of one word.
- The body is 34 ASCII bytes; guest output adds CRLF, while host input to
  TOPS-10 uses CR only. The host decoder accepts CR with an optional following LF.
- The decoder rejects controls, malformed fields and input exceeding 64 bytes
  without a frame terminator. It never interprets input as monitor commands.
- Host sessions are connection-scoped and request numbers must increase.
  The guest checks the exact expected session/request and decodes the returned
  octal word using shifts before comparing it with the original BCPL word.

Octal is an intentionally simple transport encoding, not a choice of JSON or
SQL representation. Session IDs in this test are deterministic correlation
values, **not authentication credentials**. No persona records or passwords are
sent through this probe.

## Tests and observed evidence

Run from the repository root:

```sh
.venv/bin/python -m unittest tests.test_storage_bridge -v
.venv/bin/python -m tests.integration_storage_bridge
```

The native runner accepts `--output runtime/<fresh-directory>` and refuses to
overwrite an existing output directory. It copies the stopped first-playable
checkpoint, uses tape boot, NOIDLE / 5M throttle / DZ SPEED=*8, and private
loopback ports. Boot retries are bounded by the existing harness. It compiles
only BRGP and creates test comparison files on the disposable disk.

The complete native run is retained in the ignored directory
`runtime/storage-bridge-decode-green/`. It passed these twelve cases:

| Case | Result |
|---|---|
| Normal | 40 exact word round trips; about 1.42 seconds for the complete test loop |
| Malformed reply (embedded LF) | Rejected; no successful request reported |
| Fragmented reply | First reply sent one byte at a time; all 40 words passed |
| Wrong session | Rejected |
| Wrong request number | Rejected |
| Wrong payload word | Rejected after native decoding |
| Silent responder | Native timeout; 5.047 host seconds |
| Incomplete reply | Native timeout; 5.041 host seconds |
| Host-side disconnect | Native timeout; 5.039 host seconds; controlling terminal remained usable |
| Recovery | Fresh connection/session after failures; all 40 words passed |
| Parallel job A | 40 words on line 7, session 101 |
| Parallel job B | 40 words on line 6, session 202, concurrent with A |

Each successful vector contains zero, all-ones, the sign bit, the maximum
positive signed value and each of the 36 individual bit positions. Across five
successful cases, 200 words completed native encode → host decode/encode →
native decode. Seven additional requests exercised rejected/failed responses.

Additional assertions passed:

- Thirty ordinary connections occupied lines 0–31 excluding 6 and 7; the next
  ordinary connection received “All connections busy”, even though both reserved
  bridge lines were free. This agrees with `sim_tmxr.c:1166–1187`, which excludes
  per-line listeners from the general pool.
- Sending `daytime` on the assigned, slaved bridge line produced no monitor
  output; BRGP cleared that input before starting. Protocol frames did not
  appear on either probe's controlling terminal.
- Native FILCOM `/B` found no differences between before/after persona files.
- Host SHA-256 comparisons found no changes to any original `source/` file.

`report.json` records the overall result and all cases. Per-case JSON records
decoded words, native output and duration; `*-wire.json` retains raw probe-only
traffic for diagnosis. `maintenance.txt` and each machine's `console.log` retain
compilation/setup output. The runner stops its private emulator on exit.
These stopped experiment disks are not clean-shutdown release images or backups.

The red/green evidence is also retained:

- `storage-bridge-framing-red`: the initial guest incorrectly accepted embedded
  LF. Tightening validation reproduced a second issue with CRLF host replies;
  single-CR replies resolved it.
- `storage-bridge-decode-red-2`: acceptance required native reconstruction/output
  of returned 36-bit values, which the initial byte-comparison-only probe lacked.
- Earlier `storage-bridge-first`, `-trace`, `-carrier`, `-bootstrap` and `-noecho`
  runs preserve terminal setup failures and the first successful word exchange.
- `storage-bridge-decode-red` used an incorrect eight-line assumption in the
  pool-exhaustion test. The pinned PDP-10 target has 32 lines; the corrected test
  passed. This was a test assumption, not a reserved-line routing defect.

Ten host unit tests passed. They cover exact framing, all word bits, malformed
input, bounded incomplete frames, CR-only host output, connection isolation,
duplicate/session rejection, a request deadline and truncated disconnects.

## Limits and next step

This is a viable **experimental character-channel transport**, with the following
limits still relevant before integrating it into MUD:

- Two jobs used two separately assigned lines in this initial experiment. The
  later channel-pool experiment verifies native allocation under MUDGUEST;
  production capacity selection and an unattended handover mechanism remain.
- This initial run used operator setup and RICHARD. The follow-up verified
  MUDGUEST I/O/ownership; automated production provisioning remains untested.
- Guest reply waits have a five-second native deadline and passed a ten-second
  host bound in this configuration. This does not prove bounds for a stalled
  emulator, a blocked large output, guest lock cleanup or a storage commit.
- The fixed single-word frame does not yet carry records, transaction tokens,
  durable operation IDs or commit outcomes. There is no database or persistence
  retry logic. Reconnect tests start fresh sessions, not ambiguous-write recovery.
- The raw sockets are loopback-only in the disposable runner. Authentication,
  authorization and production lifecycle management are not supplied by this
  probe. SLAVE plus listener reservation is the tested routing boundary, not a
  complete production security model.
- The exact original executable was not relinked, so this is not an authentication
  compatibility test for a future patched MUD.

The follow-ups selected a small native pool and verified a standalone R1 reader,
challenge-bound handover and full-record credit flow. The
[bounded MariaDB-backed fixture](persona-mariadb.md) is now verified as well.
The [read-only guest adapter](external-login-readonly.md) and challenge provisioning
are also now verified in the actual game. Retain the native creation buffer-order
experiment and the transaction/failure contract before broadening to writes.
