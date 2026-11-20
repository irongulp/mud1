# Offline KSYS executable layout qualification

This follows the [KSYS source trace](terminal-lifecycle.md). It qualifies an
offline decoder and **candidate executable layouts**, not a live-job decoder,
a native shutdown fix or a release acceptance run.

## Media and exact byte matches

The local `runtime/release-v1/mud86-runtime.tar.gz` was checked against
`deploy/runtime.json` before reading its `guest.dsk` member:

- Archive SHA-256:
  `505708614b57fade39572dada365394a988433d637217ed041b17f79f38325bf`.
- Disk SHA-256:
  `23baaf1c2eeb0fe6633601d1e706e4835557def2410e87e2629c849de69a669c`.
- Distribution CUSP tape compressed SHA-256:
  `4c29361324c5ca7c55fb88b9c892a8e3e8e0ef2384982957a2dfb4a05a76b3b6`.
- Its decompressed `t10cusp1.tap` SHA-256:
  `1f8b39e010f620148814e6c3e6af4ce047d0d1ce1e76c41590c9e5d02e924e0d`.

The decompressed tape was compared byte-for-byte with the verified compressed
file's decompression. Its source is
<https://pdp-10.trailing-edge.com/tapes/cuspbinsrc_1of2_bb-x128c-sb.tap.bz2>.

`tapeutils` revision `c5da89fc472f3dfa560d75fe07d61f8210c504ef` lists:

| Tape file | Name | Byte size | Logical words |
| --- | --- | --- | --- |
| 352 | `dskb:10_7.galaxy.batcon..batcon.exe` | 36 | 16,384 |
| 481 | `dskb:10_7.galaxy.quasar..quasar.exe` | 36 | 53,248 |

Both files retain legacy `.JBSYM` RADIX50 tables. QUASAR's accompanying
`QUASAR.CTL:48–54` links with `/LOCALS /SYMSEG:LOW`.

Extraction used `t10backup -x -v -f <t10cusp1.tap> quasar.exe batcon.exe
quasar.ctl batcon.ctl qsrmac.unv`. Its `pars_5chars` encoding retains all36 bits,
including the low bit in the fifth character's high bit. `WriteBlock` removes
up to four trailing zero characters, including for binary files. Both extracted
executables were four bytes short of their complete word encoding.

The first strict decoder call rejected that incomplete word. A separate
read-only scan of the original SIMH tape records selected the two numbered
files and decoded each original36-bit word directly. It verified the lengths
above and equality with the extracted data plus exactly four zero bytes.
Those verified complete encodings—not guessed padding—were used below.
`backup_words()` continues to reject incomplete words.

Each **entire** executable, converted to the disk's little-endian64-bit word
storage, occurs twice in the release disk:

| Image | Complete sequence byte offsets in disk | SHA-256 of complete little-endian words |
| --- | --- | --- |
| BATCON | 84,255,744; 264,397,824 | `16251f4a72cb421f93d9deda64484c62be8243441bdde52ab858a397ae49dd46` |
| QUASAR | 96,308,224; 266,732,544 | `f50cc22815e66a4d464ec62529a23666496ca04e434ee6b5ac82f30c5da67a7d` |

This is stronger than matching separate blocks or a version label. It does not
identify directory ownership, active SYS files or a resident job. The two
matches are retained separately; neither is automatically selected.

## Decoder and independent validation

`tests/ksys_image.py` is offline fixture tooling. It has no runtime imports or
guest-control operations. It implements:

- Strict complete-word conversion from `t10backup` character encoding.
- EXE directory-based page loading, including zero pages and noncontiguous
  virtual addresses; malformed blocks, overlaps and missing pages fail.
- Legacy negative-count `.JBSYM` tables, with bounds checks and separate
  RADIX50 name/DDT flags. Missing or ambiguous typed symbols fail.
- Whole-sequence, word-aligned disk matching that returns every occurrence.

References:

- SIMH revision `47b7ddabbe5b548cfc32f2fd45f7bed238ff7921`,
  `PDP10/pdp10_sys.c:294–393` (`load_exe`).
- Tapeutils revision above, `t10backup.c:153–220,427–450`.
- Pinned Stacken DDT blob `cc66c00022f73deb2626f31bab2a42d2abd2a31f`,
  `DDT.MAC:2238–2243`: global/local/program-name/delete-input/delete-output
  flags. The decoded four-bit flags1 and2 mean global/local;12 octal is a
  local with output suppressed. Equal local names in different modules must
  not be silently merged.

Seven unit tests first failed with the missing module, then passed. They
exercise all36 individual bits, malformed EXE/table cases, name/type ambiguity,
and rejection of partial/unaligned image matches. No historical binary fixture
is committed.

An independent offline invocation of the local SIMH binary performed only
`LOAD`, `EXAMINE` and `QUIT`, with no attached disks, listeners, boot or guest
instruction execution. Its binary SHA-256 is
`f813e22023347141d0618e5cdcfb3d37a49928b17e3d3938d2e8945cc50beec1`.
All15,872 mapped BATCON words and52,736 mapped QUASAR words matched the Python
decoder exactly. SIMH compresses repeated examination values as `thru ...
same as above`; the initial comparison omitted those rows and failed. The
corrected comparison expanded only that explicit syntax and compared every
address/value. The first output is retained.

## Candidate layouts

All addresses and values here are **octal user virtual addresses**, not
physical memory addresses. They are valid for the byte-identified images above.
No current CI job identity has been bound to them.

| Image | Symbol | DDT type | Address |
| --- | --- | --- | --- |
| BATCON | `G$KSYS` | global | `457` |
| BATCON | `KSYCNT` | local | `553` |
| BATCON | `KSYMAP` | local | `562` |
| BATCON | `KSYFIN` | local | `1605` |
| BATCON | `KSYJOB` | local | `2673` |
| QUASAR | `HDRPSB` | global | `60035` |
| QUASAR | `G$NOW` | global | `102624` |
| QUASAR | `G$KSYS` | global | `102647` |
| QUASAR | `G$WTIM` | global | `102754` |
| QUASAR | `A$HELL` | global | `333` |
| QUASAR | `A$PSBC` | global | `4601` |
| QUASAR | `KSYS2A` | local | `77643` |
| QUASAR | `I$SKSM` | global | `77731` |

BATCON's `.JBVER` is `010500005027`, its symbol table has2,299 entries;
QUASAR's is `000500001512`, with7,907 entries. Their `.JBSYM` words are
`767012026007` and `741072107077`, respectively.

QUASAR constants in the table give PSB offsets `PSBPID=1`, `PSBNAM=2`,
`PSBFLG=4`, `PSBUDT=5`, and states `PS.RUN=0`, `PS.WAT=1`, `PS.FIR=2`,
`PS.KSY=3`. These are field values/offsets, not standalone addresses.
Several constants repeat in module tables; these observations do not relax
the decoder's unique-symbol lookup.

Independent disassembly of the byte-matched image corroborates specific source
boundaries:

- `77701–77710` deposits status3, clears retry count, obtains time, adds the
  literal at `102333`, and stores PSB offset5. That literal is `132` octal,
  decimal90 UDT units (~30 guest seconds).
- `77731–77745` takes PID from PSB offset1 and constructs/sends message type
  `66` octal (`.QOKSY`).
- `4605` starts the PSB traversal from `60036` (`HDRPSB+.QHLNK`); `4622–4624`
  compares the PSB deadline against `102624` (`G$NOW`).

This corroborates those routines in the candidate image, not full source/binary
equivalence. It cannot explain the previously captured monitor PC354741.

## Remaining live-mapping gate

The source addresses above are enough to describe a targeted capture **after
identifying and mapping the actual jobs**. The current diagnostic has no
validated mapping from the deployed monitor's job table/UPTs to those virtual
pages. `t10mon.tap`'s directory offers no monitor MAP/SYM or built monitor EXE
with which to establish that mapping. The earlier monitor scope correction
fingerprints a different, limited code boundary and does not establish job-table
addresses.

Before adding failure-time reads:

1. Bind the actual monitor layout and job/context identity to its page tables.
   The halted CPU's UBR alone may belong to another job.
2. Validate the target jobs' code pages against the identified executable,
   accounting explicitly for load-time changes. Reject missing, nonresident,
   stale or ambiguous mappings.
3. Only then traverse the bounded QUASAR PSB list and read the named BATCON
   state. A missing mapping must remain unknown, not “BATCON absent”.
4. Qualify that mapping in a separate known-healthy disposable fixture before
   relying on it after a failed KSYS. The failure capture still must not resume
   the guest or submit another KSYS.

No new CI run, runtime instrumentation or monitor change was made. The previous
shutdown remains unclean and the logout-timing question remains open.

## Private evidence and reproduction

Evidence is local to the isolated diagnostic worktree's `build/ksys-layout/`:
verified release disk copy, original extractions, complete character encodings,
`layout-report.json`, `simh-decoder-check.json`, full examination outputs and
`quasar-ksys-disassembly.txt`. `resident_job_verified` remains false.
Historical images are neither committed nor published.

With those verified private files available:

```python
from pathlib import Path
from tests.ksys_image import backup_words, load_exe, symbols, unique_symbol, disk_matches

root = Path("build/ksys-layout")
words = backup_words((root / "quasar.complete-characters").read_bytes())
memory = load_exe(words)
assert unique_symbol(symbols(memory), "HDRPSB", flags=1) == 0o60035
assert disk_matches((root / "release-guest.dsk").read_bytes(), words) == [
    96308224, 266732544,
]
```

Host validation: `python -m unittest tests.test_ksys_image` plus the existing
guest-control/deployment/lifecycle diagnostic regressions: **96 tests passed**.
No post-green refactor was needed; the reader remains separate from runtime
capture.
