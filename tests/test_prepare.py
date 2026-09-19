import tempfile
import unittest
import hashlib
from pathlib import Path

from tools.prepare import normalize, split_subfiles, prepare


class SourcePreparationTests(unittest.TestCase):
    def test_always_open_is_an_audited_build_only_change(self):
        source = Path(__file__).resolve().parents[1] / 'source'
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.iterdir() if p.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / 'upstream'
            upstream.mkdir()
            historical = root / 'historical'
            output = root / 'always-open'
            prepare(source, upstream, historical)
            report = prepare(source, upstream, output, always_open=True)
            changed = [name for name in report['files']
                       if (historical / name).read_bytes() != (output / name).read_bytes()]
            self.assertEqual(changed, ['MUDLIB.BCL'])
            library = (output / 'MUDLIB.BCL').read_text()
            timeok = library.split('and timeok(low)=', 1)[1].split('and overload(low)=', 1)[0]
            self.assertNotIn('times!day', timeok)
            self.assertIn('overload(numbargs()->low, low1)', timeok)
            self.assertIn('demo', timeok)
            self.assertEqual((output / 'TXTHRS.GET').read_bytes(), normalize((source / 'TXTHRS.GET').read_bytes()))
            self.assertEqual((output / 'MUD5.BCL').read_bytes(), normalize((source / 'MUD5.BCL').read_bytes()))
            self.assertEqual(report['availability'], 'always-open')
            patch = (output / 'local.diff').read_text()
            self.assertIn('MUDLIB.BCL', patch)
            self.assertIn('-\tday_times!day', patch)
            self.assertEqual(report['files']['MUDLIB.BCL']['sha256'],
                             hashlib.sha256((output / 'MUDLIB.BCL').read_bytes()).hexdigest())
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in source.iterdir() if p.is_file()})

    def test_always_open_rejects_unknown_time_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, upstream = root / 'source', root / 'upstream'
            local.mkdir()
            upstream.mkdir()
            (local / 'MUD.TXT').write_text('*rooms 0\n')
            (local / 'MUDLIB.BCL').write_text('and timeok()=false\n')
            with self.assertRaisesRegex(ValueError, 'timeok'):
                prepare(local, upstream, root / 'output', always_open=True)
            self.assertFalse((root / 'output').exists())

    def test_missing_master_database_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            (root / "upstream").mkdir()
            with self.assertRaisesRegex(ValueError, "MUD.TXT"):
                prepare(root / "source", root / "upstream", root / "output")

    def test_removes_terminal_subfil_archive_marker(self):
        files = split_subfiles("MBOOTS.MAC", b"END\n\\\\\\\\\\\n\fSUBFILE: DBADAT.MAC @date\nEND\n\n\\\\\\\\\\\n\f\n")
        self.assertEqual(files["DBADAT.MAC"], b"END\n")

    def test_normalization_preserves_tabs_spaces_and_text(self):
        self.assertEqual(normalize(b"a\t b  \r\n\x00\x00"), b"a\t b  \n")
        with self.assertRaises(ValueError):
            normalize(b"a\x00b")

    def test_extracts_embedded_sources_without_archive_delimiters(self):
        archive = b"TITLE BOOTS\nEND\n\n\\\\\\\\\\\n\fSUBFILE: POWER.BCL @date\nlet start() be finish\n\\\\\\\\\\\n\fSUBFILE: DBADAT.MAC @date\nEND\n"
        files = split_subfiles("MBOOTS.MAC", archive)
        self.assertEqual(files["MBOOTS.MAC"], b"TITLE BOOTS\nEND\n")
        self.assertEqual(files["POWER.BCL"], b"let start() be finish\n")
        self.assertEqual(files["DBADAT.MAC"], b"END\n")

    def test_prepare_preserves_local_rules_and_records_upstream_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, upstream, output = [root / name for name in ("local", "upstream", "output")]
            local.mkdir()
            upstream.mkdir()
            (local / "MUD.TXT").write_bytes(b"*rooms\t1\n@txtrms\n")
            (local / "TXTRMS.GET").write_bytes(b"room\tlight\n\tOriginal.\n")
            (upstream / "TXTRMS.GET").write_bytes(b"room\tlight\n\tChanged.\n")
            (upstream / "MUD.MIC").write_bytes(b".r bcpl\r\n")
            (upstream / "BOOK.DBA").write_bytes(b"Book\r\n\x00More\r\n")
            report = prepare(local, upstream, output)
            self.assertEqual((output / "TXTRMS.GET").read_bytes(), (local / "TXTRMS.GET").read_bytes())
            self.assertEqual((output / "BOOK.DBA").read_bytes(), b"Book\n\x00More\n")
            self.assertEqual(report["files"]["TXTRMS.GET"]["upstream_comparison"], "different")
            self.assertEqual(report["includes"], ["TXTRMS.GET"])
            with self.assertRaises(FileExistsError):
                prepare(local, upstream, output)

    def test_missing_include_fails_before_output_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local, upstream = root / "local", root / "upstream"
            local.mkdir()
            upstream.mkdir()
            (local / "MUD.TXT").write_bytes(b"@missing\n")
            with self.assertRaisesRegex(ValueError, "MISSING.GET"):
                prepare(local, upstream, root / "output")
            self.assertFalse((root / "output").exists())

    def test_conflicting_embedded_duplicate_is_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "local").mkdir()
            (root / "upstream").mkdir()
            (root / "local" / "MBOOTS.MAC").write_bytes(b"END\n\\\\\\\\\\\n\fSUBFILE: DBADAT.MAC @date\nwrong\n")
            (root / "local" / "DBADAT.MAC").write_bytes(b"right\n")
            with self.assertRaisesRegex(ValueError, "Conflicting.*DBADAT"):
                prepare(root / "local", root / "upstream", root / "output")


if __name__ == "__main__":
    unittest.main()
