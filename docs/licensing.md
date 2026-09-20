# Licensing review and distribution boundaries

Review date: 20 September 2026. This records evidence, maintainer decisions and
unresolved questions; it is not a legal clearance certificate.

## New restoration software: GPLv3 only

The maintainer selected **GPL-3.0-only** for independently authored restoration
software. [LICENSE](../LICENSE) defines its scope; [COPYING](../COPYING) is the
verbatim GNU GPL version 3 text. Commercial permissions provided by the GPL for
those contributions are not restricted by the original MUD's separate terms.
Conversely, that GPL grant cannot relicense MUD, TOPS-10, the compiler or fonts.

The host gateway, emulator and historical game run as separate processes and
communicate through terminal protocols/files. This describes the architecture;
it does not prove that every combination is legally an aggregate under GPLv3.
Review any copyrightable embedded historical snippets and native linked binaries
under their actual terms. No blanket GPL-plus-noncommercial licence is asserted.

The preferred-form Python, JavaScript, HTML and CSS are distributed as source.
Installed application snapshots include their source, setup script and licence
documents. Browser users can follow the legal/source links; vendor notices retain
their own terms. If distributing another binary/minified form, provide the exact
corresponding source and required notices, not just a link to an unrelated latest
version. Preserve the source needed for every version offered for download.

## MUD1 upstream

The base is `PDP-10/MUD1` commit
`8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1` (28 October 2024). It removed earlier
GPLv3 references with the explanation that a not-for-profit stipulation could
not be attached to GPLv3. Its headers retain a 1980 copyright/notice-retention
statement and the 18 May 2020 not-for-profit release statement. Its README says
recipients must follow the same restrictions.

Comparing inherited files against that base found changes only in README and
`.gitignore`, not in the original source/data. The separately supplied `source/`
archive predates the added release statement and is preserved byte-for-byte.
[The accompanying MUD notice](../licenses/MUD1-NOTICE.txt) records both notices.
The 24/7 patch affects generated game code; it does not change the applicable
terms. This review does not determine rights received under earlier versions'
licence grants or claim that a later commit can revoke an earlier valid grant.

## Historical runtime: unresolved permissions

The release image contains TOPS-10, DEC utilities, Essex BCPL and native libraries,
not just MUD. The DEC archive explicitly presents the relevant tapes under a
hobbyist agreement, not as unrestricted public-domain material. Its separate
statement about DECUS user-contributed tapes must not be applied to DEC's OS tapes.
See [the agreement and review notes](../licenses/DEC-HOBBYIST.txt).

The compiler investigation is recorded in [BCPL-STATUS.md](../licenses/BCPL-STATUS.md).
We have not established the exact grant for our redistribution, eligibility under
the DEC agreement, or its application to a public hosted service. Do not replace
those unresolved items with an invented licence or treat archival availability
as permission. Retaining notices and passing boot tests do not resolve them.

The maintainer chose to keep **runtime-v1 downloadable with a prominent review
notice** while these questions are clarified. Its existing bytes/checksums remain
stable; a separate notice bundle can accompany the release. No replacement disk
image is being published as a result of this review. Local packaging improvements
do not themselves authorize publication or certify licensing compliance.

Before another historical binary release, establish the relevant permissions
with supporting evidence, or redesign distribution to use only components for
which the required rights are established. Merely moving a download to another
site or adding an acceptance checkbox is not a substitute for that assessment.

Suggested questions for the archive maintainer/rights holder or qualified counsel:

1. What grant permits us to redistribute this TOPS-10 7.04 disk and boot tape,
   including the installed DEC utilities, to other hobbyists?
2. What must each recipient do to qualify under the DEC 36-bit agreement, and is
   a personal, free-to-play public MUD service within its permitted use?
3. What licence applies to this exact Essex BCPL compiler/library distribution?
4. What terms apply to native executables linked with that library, including
   the diagnostic whose source is now GPLv3?

## Packaging

New local runtime packages use manifest format 2 and include a checksummed
`NOTICES.txt` with the scope, GPL text, MUD notice and historical-runtime review.
The installer continues to recognize the original two-member format-1 image and
preserves existing mutable disks. A notice-only supplement for runtime-v1 does
not retroactively put notices inside its existing tarball or clear its permissions.

`tools/fetch_licences.py` imports the GNU text verbatim with a pinned checksum.
`tools/licensing.py` assembles the notice bundle; it does not make licensing
decisions. [THIRD_PARTY.md](../THIRD_PARTY.md) lists separately licensed assets and
where their notices are found. Keep this review with redistributed packages.
