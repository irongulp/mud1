# Component licences and attribution

This is a component inventory, not a declaration that every redistributed
combination is cleared. **Historical runtime redistribution review is incomplete.**
The GPL licence for the new restoration software does not cover the whole image.

| Component | Applicable notice / evidence | Distribution and status |
|---|---|---|
| Original MUD86 source/world | [MUD1 notice](licenses/MUD1-NOTICE.txt); original file headers | Inherited source/data and generated game derivatives: upstream custom not-for-profit terms. Not labelled GPLv3 by our pinned upstream revision. |
| New restoration software | [LICENSE](LICENSE), [COPYING](COPYING) | Independently authored contributions: GPL-3.0-only, as selected by the maintainer. Scope/exclusions are explicit. |
| TOPS-10 / DEC utilities / boot media | [Archive agreement](licenses/DEC-HOBBYIST.txt), [media provenance](docs/restoration.md#historical-media) | Included in runtime-v1. Personal/non-commercial licence reference located; our public-image redistribution permission remains unverified. |
| Essex BCPL compiler and native libraries | [BCPL review](licenses/BCPL-STATUS.md) | Included in runtime-v1; exact redistribution grant remains unresolved. |
| Native AUDPWD diagnostic | `tools/fixtures/AUDPWD.BCL`, [BCPL review](licenses/BCPL-STATUS.md) | New source is GPLv3; assessment of its linked historical-library binary is still required. |
| SIMH | Pinned upstream `LICENSE.txt` and per-file notices | Downloaded and built separately by setup, with its source tree retained. MIT-like text **with additional restrictions**; do not label it plain MIT. No SIMH source modifications are made here. |
| xterm.js | [MIT notice](web/vendor/LICENSE), [source provenance](web/vendor/xterm-source-NOTICE.txt) | Bundled browser library; copyright/permission/warranty text retained. Preferred-form source and build files for version 5.5.0 are bundled in `web/vendor/xterm-source-5.5.0.tar.gz`. |
| GlassTTY VT220 | [Author dedication](web/vendor/GlassTTY-LICENSE.txt) | Bundled unmodified; Unlicense/public-domain dedication retained. |
| Bedstead | [Author statement](web/vendor/Bedstead-LICENSE.txt) | Public-domain dedication for new work; the author's stated uncertainty about historical SAA5050 glyph rights is retained, not converted into an unconditional clearance. |
| VT52 font | [Upstream MIT notice](web/vendor/VT52-LICENSE.txt) | Bundled unmodified; ROM provenance and upstream notice retained. The upstream grant is not represented as a separate DEC rights-holder release. |
| BBC Master 512 / IBM MDA / CGA fonts | [BBC notice](web/vendor/BBCBitmap-LICENSE.txt), [IBM notice](web/vendor/IBMPC-LICENSE.txt) | Bundled unmodified; VileR attribution, provenance and CC BY-SA 4.0 licence links retained. |
| Python dependencies | `requirements.lock`, `requirements-deploy.txt`, `requirements-dev.txt`; installed distribution metadata/licence files | Downloaded during installation, not included in the historical runtime archive. They retain their individual licences; a lockfile is version provenance, not a licence grant. |
| Linux packages, Nginx, Certbot | Distribution RPM metadata and packaged licence texts | Installed through DNF; separate components under their own terms. |

SIMH source licence at the exact pinned revision:
https://github.com/simh/simh/blob/47b7ddabbe5b548cfc32f2fd45f7bed238ff7921/LICENSE.txt

Its general permission notice is followed by restrictions concerning changes to
`sim_disk.c`/`scp.c` and subsequent Mark Pizzolato contributions. Its final
paragraphs also warn that some repository binaries may lack formal releases;
the SIMH licence is not a grant for those binaries or the guest OS. Retaining
the downloaded source tree preserves its actual notice rather than paraphrasing
it as an unrestricted MIT grant.

Browser asset notices are served under `/static/vendor/`. GPL text, the new-code
licensing scope and the MUD notice are linked from the browser's legal page.
Including unmodified font assets does not change the terms on the original MUD.

Review evidence and follow-up questions: [docs/licensing.md](docs/licensing.md).
