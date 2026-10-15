# Local native source read-back diagnosis

## Reproduced failure and mechanism

The retained stopped `mud86-parity-10-external-fresh` fixture had a clean shutdown
marker and cutover phase `captured`. Its MUD5 source was later readable and matched
the expected generated source. A new private copy reproduced the source read-back
failure after compiling MUD7 and transferring the MUD5-sized source to a separate
fixture filename, without repeating deployment, provisioning or world compilation.

Private evidence `readback-transfer-1` records:

- Round1 failed with the same `Native snapshot timed out` exception used by the
  production shared reader (the operation here is TYPE source read-back).
- The received reply contained117877 bytes, the expected77-byte end marker, the
  complete normalized source and the trailing monitor prompt. No trace truncation.
- One polling return contained the beginning of the marker; the next returned its
  remainder **and the prompt**. Subsequent polls returned no data.
- SYSTAT, captured before touching the failed TTY, showed its PIP job in monitor
  state `^C`, with no busy devices. Native KSYS cleanup subsequently completed.

`Telnet.read_until(marker, timeout)` can return partial bytes when its poll times
out. Those bytes leave its internal queue. A subsequent call cannot recognize a
marker whose beginning was returned by the previous call, and may return the
remainder plus following data. Both host readers accumulated the reply but checked
only `data.endswith(marker)`. Thus a complete reply was incorrectly timed out.
This explains this reproduced timeout without invoking a guest execution stall,
bad file transfer, longer timeout or CI-specific CPU architecture.

## Correction

The maintenance and snapshot inspectors now share a bounded response reader:
search the accumulated reply for the marker, return through its end, and retain
surplus bytes for the next receive. Verified command input consumes owned pending
bytes before transport data, so buffering cannot hide stale prompts/bad echoes.
Connection entry/exit clears pending data. Existing maximum response sizes,
deadlines, strict snapshot ASCII decoding and no-replay behavior remain.

No game source, gameplay, persistence data/protocol, emulator or production timeout
is changed. This is a demonstrated host framing bug, not a diagnosis of OPR startup
or KSYS failures.

## Regression and native evidence

- Deterministic split-marker/trailing-prompt tests failed before the correction for
  both inspectors and the actual `read_back()` helper. They pass afterward.
- A real stdlib Telnet/socketpair test confirms partial polling returns can produce
  this framing boundary. Tests also retain response limits, deadline failure and
  strict snapshot decoding.
- All397 host/browser tests passed locally on Python3.12 after the correction.
  After refreshing against main6824190 (including the native-redraw fixes), all422
  tests passed in a worktree-local environment with pinned development dependencies.
- With the correction, `readback-transfer-green` passed two complete source
  transfer/read-back rounds with MUD7 compiler state:271.743 and272.810 host seconds.
  The final guest shutdown was confirmed clean. Expected source SHA-256:
  `dce9900847c9baa99aa4f3807a046725230b5f883c11d9d6f0f3945d5f114447`.
- The lab used the retained fixture's native ARM Linux emulator, including its
  already-installed timer correction. The host framing regression does not rely
  on that correction. No claim of unmodified-emulator or native-x86 acceptance
  is made for these local runs.
- `readback-existing-1` read the original retained file successfully but its final
  shutdown was unconfirmed; keep it as separate failed-cleanup evidence.

## Running the private lab

The donor must be stopped, private and disposable, with `shutdown.json` containing
boolean `clean:true` beside `game/guest.dsk` and `game/t10boot.tap`. The runner copies
the disk/tape to a new0700 output; all trace files are0600. Donor images contain test
password words: never publish or package them. Runtime operations stay on loopback.

```sh
python -m tests.integration_source_readback \
  --checkpoint /private/stopped-checkpoint --source /private/MUD5.BCL \
  --simh /path/to/native/pdp10 --output /private/new-readback-run \
  --compiler-state --rounds 2
```

`--read-existing` reads retained MUD5.BCL without a transfer. Otherwise the lab
writes only its fixture-owned RDTEST.BCL. `--compiler-state` recompiles existing
MUD7 source on the copied disk before each round to match the preceding build
step. The trace proxy never changes returned bytes; a recording limit only stops
copying private evidence. On the first failure it saves the reply and tries a
bounded independent-console SYSTAT before normal cleanup; it does not retry the
failed operation. A60-second observation window makes local diagnosis faster and
is explicitly distinct from the unchanged600-second production snapshot budget.

The harness and synthetic tests use no persona capture transcript. Raw source/
terminal evidence stays private. Broader deployment, OPR and KSYS reliability
still require their own reproductions; this finding must not be generalized to
all historical native timeouts.
