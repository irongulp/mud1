# MUD86 starter runtime v1

## Licensing review incomplete

**The project's right to redistribute the historical software in this disk/tape
combination has not been established by the licensing review.** The maintainer
has chosen to keep this release downloadable with this prominent review notice.
No replacement binary image is being published as part of the notice update.

The GPLv3 grant for independently authored restoration software does not
relicense the original MUD, TOPS-10, DEC utilities, BCPL compiler or its libraries.
MUD retains its upstream custom not-for-profit terms. The DEC hobbyist agreement
and exact BCPL distribution terms require further clarification for our use and
redistribution. This is an unresolved assessment, not a finding that all such
use is prohibited. Functional checks and checksums are not licence clearance.

The supplementary `LICENSING-NOTICES.txt` asset records the terms, sources and
unresolved questions. It accompanies the unchanged version-1 archive; it does not
put notices inside that existing archive or change its checksum. Current details:
https://github.com/irongulp/mud1/blob/main/docs/licensing.md

## Technical contents

Persona-free TOPS-10 7.04 disk and original boot tape for the AlmaLinux installer.
The original BCPL/MACRO-10 MUD engine was rebuilt with the existing availability-only
24/7 change; original DBASE generated the world (25247 words). Native inspection
reported zero persona records before an orderly KSYS shutdown and packaging.

The installer verifies the archive and both extracted files against the pinned
`deploy/runtime.json` manifest. It provisions all seven archwizards locally with
different generated initial passwords. This archive contains no installation's
archwizard credentials. Existing installations retain their mutable disk.

Build input: the stopped first-playable checkpoint recorded in
`docs/provenance.json`. Original source files are preserved; build procedure and
media provenance are in `docs/restoration.md` and `tools/package_runtime.py`.

## Attribution and terms

MUD is by Roy Trubshaw, Richard Bartle and the authors credited in the original
source. Richard Bartle's 18 May 2020 release terms, recorded by PDP-10/MUD1, allow
use and redistribution on a not-for-profit basis; recipients must follow the
same restrictions. TOPS-10, the Essex BCPL compiler and other historical software
retain their respective notices and terms. Original files/notices are retained
in the guest image. SIMH is downloaded and built separately from its pinned
revision; browser/font license notices remain with the repository assets.

This is a local-restoration-derived starter, not a DEC-supported OS distribution.
See the deployment documentation for tested platforms and remaining limitations.
