# Essex BCPL: permission review unresolved

Our toolchain came from `PDP-10/essex-bcpl` at
`3fe466d1327cbb5f583d7d79575dbf250d8aa461`:

- https://github.com/PDP-10/essex-bcpl/tree/3fe466d1327cbb5f583d7d79575dbf250d8aa461
- `BCPL.tap` SHA-256:
  `c5120bf8532c1c4f6cbf435515a7c18b62b32a8b9828b15d3c5d5e037176bfbd`
- https://www.quentin.org.uk/2018/02/25/installing-bcpl/

Review on 20 September 2026 found only `BCPL.tap`, `bcplcompil.tap`,
`bcpl_reference_manual.pdf`, `compil.mac` and `README.md` in that repository
revision. Its README/install guide describe installation, not a redistribution
grant. The guide identifies `COMPIL.MAC` as a revised DEC utility; it must not be
treated as automatically having a licence for independently authored Essex code.

A read-only survey of the checksum-verified BCPL tape decoded 7-bit text from
SIMH-framed PDP-10 words. It found readable compiler source, but no explicit grant
through searches for copyright, licence/license, permission, redistribution or
public-domain notices. This was a text survey, not an exhaustive file-by-file
licence determination, and absence of a match is not proof that permission does
not exist. No permission has been inferred from a public download URL.

The repository's scanned reference manual (SHA-256
`551cfec94503baedb6bff2b7245b915d9b5e81956f464ff6ab05465ae4e365a4`)
identifies Pete Gardner, University of Essex, as its author, second edition,
revised January 1978, describing compiler version 3F. Its history section credits
Martin Richards, Bernard Sufrin, Brian O'Mahoney and David Eyres, and attributes
the newer Essex compiler to Pete Gardner. These title/history pages provide
useful authorship leads, but do not establish a redistribution grant for our
later toolchain. No such grant is inferred from the manual's availability.

Remaining work: identify the original compiler/library authors and distribution
terms, inspect the complete source/manual notices, and obtain clarification from
the archive maintainer or rights holder where necessary. Retain all existing
notices. Modern BCPL distribution terms must not be applied retroactively to
this particular historical toolchain without supporting evidence.

`tools/fixtures/AUDPWD.BCL` is new diagnostic source covered by our GPLv3 grant.
Its compiled executable links the historical BCPL library. The terms of that
library and whether GPLv3's System Library provisions apply to the distribution
must be assessed before declaring the linked binary cleared. Neither this
document nor the GPL grant gives permission for somebody else's library.
