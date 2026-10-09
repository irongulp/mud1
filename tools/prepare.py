"""Prepare a traceable MUD86 build tree without changing the source archive."""
import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

MUD_REVISION = "8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".BCL", ".MAC", ".GET", ".TXT", ".SUB", ".BOX", ".MIC", ".DBA"}
SUBFILE = re.compile(rb"(?:^|\n)\\{5}\s*\x0cSUBFILE: ([A-Z0-9]+\.[A-Z]+)[^\n]*\n")


def normalize(data):
    data = data.replace(b"\r\n", b"\n").rstrip(b"\x00")
    if b"\x00" in data:
        raise ValueError("Embedded NUL in source")
    data.decode("ascii")
    return data


def split_subfiles(name, data):
    data = normalize(data)
    markers = list(SUBFILE.finditer(data))
    if not markers:
        return {name: data}
    data = re.sub(rb"\n\\{5}\s*\x0c\s*\Z", b"\n", data)
    result = {name: data[:markers[0].start()].rstrip(b"\n") + b"\n"}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(data)
        child = marker.group(1).decode("ascii")
        if child in result:
            raise ValueError("Duplicate subfile: " + child)
        result[child] = data[marker.end():end].rstrip(b"\n") + b"\n"
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_normalized(path):
    if path.suffix.upper() == ".DBA":
        # Appended historical writing contains NUL padding between entries.
        # Preserve it: these are runtime assets, not compiler source files.
        return path.read_bytes().replace(b"\r\n", b"\n")
    try:
        return normalize(path.read_bytes())
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


def always_open_library(data):
    """Bypass only the schedule gate; HOURS and DEMO retain their own semantics."""
    pattern = re.compile(rb"(?m)^and timeok\(low\)=demo\\/valof\n\$\([\s\S]*?^\$\)\n(?=and overload\(low\)=)")
    matches = list(pattern.finditer(data))
    if len(matches) != 1 or b"resultis ~overload(numbargs()->low, low1)" not in matches[0].group():
        raise ValueError("Unrecognized timeok implementation; refusing availability patch")
    replacement = (b"// Local 24/7 build: preserve HOURS data and the original load checks.\n"
                   b"and timeok(low)=demo\\/~overload(numbargs()->low, low1)\n")
    match = matches[0]
    return data[:match.start()] + replacement + data[match.end():]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Unrecognized source anchor: ' + old[:60])
    return text.replace(old, new, 1)


def replace_routine(text, name, replacement):
    pattern = re.compile(r'(?ms)^(?:let|and) ' + re.escape(name) + r'\([^\n]*\n.*?(?=^and |\Z)')
    if len(pattern.findall(text)) != 1:
        raise ValueError('Unrecognized routine: ' + name)
    return pattern.sub(lambda _: replacement + '\n', text, count=1)


def readonly_adapter():
    """Generate library-local routines from the already native-tested R1 reader."""
    probe = (ROOT / 'tools/fixtures/PRREAD.BCL').read_text()
    declarations = probe.split('manifest\n', 1)[1].split('let start()', 1)[0]
    body = probe.split('   unless trm(TOECHO,0)', 1)[1].split('   // This executable', 1)[0]
    body = '   unless trm(TOECHO,0)' + body
    body = replace_once(body, '   writes(tty,"R1RD BOUND*C*L")\n', '')
    routines = probe[probe.index('and expected(i)'):]
    for name in ('expected', 'controlword', 'controlspace'):
        routines = replace_routine(routines, name, '')
    routines = replace_routine(routines, 'fail', '''and fail(reason) be
$( xr.outcome_seq(reason,"NOT_FOUND")->0,2
   jump(xr.escape)
$)''')
    routines = replace_routine(routines, 'claim', '''and claim(line)=valof
$( let args=vec 2
   args!0_0; args!1_$6"tty6"+((line-FIRSTLINE)<<12); args!2_0
   resultis hopen(xr.channel,args)
$)''')
    routines = replace_routine(routines, 'releasechannel', '''and releasechannel() be if leased ne -1
$( release(xr.channel,0)
   leased_-1; xr.channel_-1
$)''')
    names = ('LIMIT WORDS WAITMS DAYMS STALELIMIT FIRSTLINE LASTLINE SENTINEL '
             'TOINPUT TOCLEAR TOOUTPUT TOREAD TOECHO udx trmval leased started '
             'challenge0 challenge1 epoch0 epoch1 key0 key1 incoming received cursor '
             'outgoing used scratch committed fail claim releasechannel millis nextchar '
             'readline begins need number endline handover readidentity status build '
             'identity credit put text putoct emit trm').split()
    replacements = {name.lower(): 'xr.' + name.lower() for name in names}
    # Underscore is BCPL assignment, not part of an identifier.
    token = re.compile(r'//[^\n]*|"(?:\*[^\n]|[^"])*"|[A-Za-z][A-Za-z0-9.]*')
    def rename(text):
        return token.sub(lambda match: replacements.get(match[0].lower(), match[0]), text)
    declarations = 'manifest\n' + rename(declarations)
    declarations += '''static $( xr.outcome=2; xr.escape=0; xr.calls=0; xr.base0=0; xr.base1=0; xr.channel=-1 $)
'''
    wrapper = '''and xr.lookup(nam)=valof
$( let own=?
   xr.escape_label(done); xr.outcome_2
   if xr.calls=0
      xr.seed()
   if xr.calls ge 1024 xr.fail("REKEY")
   xr.calls+_1
   xr.challenge0_xr.base0; xr.challenge1_xr.base1 neqv xr.calls
   xr.key0_!nam bitand ~1
   xr.key1_LENGTH of nam>4 -> (1!nam bitand ~1),0
   xr.channel_findchannel()
   if xr.channel ls 0 xr.fail("NO_CHANNEL")
   own_valof $[ $seto ac,0; $trmno. ac,0; $trn $]
   for candidate=xr.firstline to xr.lastline
      if candidate ne (own bitand #777) if xr.claim(candidate)
      $( xr.leased_candidate; break $)
   if xr.leased=-1 xr.fail("NO_CHANNEL")
   xr.udx_(own bitand ~#777) bitor xr.leased
   xr.read()
done: xr.releasechannel()
   resultis xr.outcome=1 -> xr.committed,0
$)
and xr.seed() be
$( let seed=vec 1 and args=vec 1 and count=?
   args!0_$6"rse"; args!1_(-2<<18) bitor (seed-1)
   count_valof
   $[ $move ac,args
      $hrli ac,2
      $tmpcor ac,0
      $setz ac,0
   $]
   unless count=2 /\\ seed!0 ne 0 xr.fail("SEED")
   xr.base0_seed!0; xr.base1_seed!1
$)
and xr.read() be
$(
'''
    return declarations, wrapper + rename(body) + '   xr.outcome_1\n$)\n' + rename(routines)


def external_persona_files(files):
    library = files['MUDLIB.BCL'].decode('ascii')
    seven = files['MUD7.BCL'].decode('ascii')
    five = files['MUD5.BCL'].decode('ascii')
    library = replace_once(library, 'and initialise() be\n$(\tlvmdoor_@message.door',
        'and initialise() be\n$( xr.calls_0; xr.base0_0; xr.base1_0; xr.leased_-1; xr.channel_-1\n'
        '\tlvmdoor_@message.door')
    start = '\tperput_dofile($6"all",ps6,$6".pm",MAINTA,label(drat),#17,1,lookup,rdb,wrb,closefile)\n\tassign()\n\t$(\tsearchrec(name)\n\t\tdeassign()\n\t\tclose(perput)\n'
    library = replace_once(library, start, '''\t$( let found=searchrec(name)
        unless found=1
        $( test found=0 then outs("External persona not found; creation is unavailable in this read-only build.*C*L")
           or outs("External persona lookup unavailable.*C*L")
           giveback()
        $)
''')
    library = replace_once(library, '\t\t$(\trec_(rec rem WDSPERBUF)+dmpbuf\n', '\t\t$( // rec is a detached logical record, not a file offset.\n')
    # The original password comparison and profile conversion remain verbatim.
    library = replace_routine(library, 'searchrec', '''and searchrec(nam)=valof
$( rec_xr.lookup(nam)
   resultis xr.outcome
$)''')
    for name in ('saverec', 'deleterec', 'addrec'):
        library = replace_routine(library, name,
            f'and {name}(nam) be error("Read-only external persona storage: operation unavailable.")')
    begin = library.index('\ttest (ATTED of profile=0)', library.index('and writeprofile('))
    end = library.index('\toutput_tty\n$)', begin)
    library = library[:begin] + '\touts("Read-only external persona storage: persona not saved.*C*L")\n' + library[end:]
    begin = library.index('\tif false\n\t$(\nwhoops:', library.index('and access()'))
    end = library.index('\tunless hsname=mud6', begin)
    library = library[:begin] + '\t// External mode does not open or create a native persona file.\n' + library[end:]
    library = replace_once(library, '\tperput_true\n', '')
    library = replace_once(library, 'perput->ps6,mud6,perput->$6".pm",mapput->$6".mm",', 'mud6,mapput->$6".mm",')
    for name, keyword in (('save', 'let'), ('purge', 'and')):
        seven = replace_routine(seven, name,
            f'{keyword} {name}() be error("Read-only external persona storage: {name.upper()} unavailable.")')
    seven = replace_once(seven, '$(\tlet block, logs,dest = ?, logstr,who.copy\n',
        '$(\tlet block, logs,dest = ?, logstr,who.copy\n'
        '   if numbargs() if nextgame ne true /\\ nextgame ne false\n'
        '      error("Read-only external persona storage: chaining unavailable.")\n')
    seven = replace_once(seven,
        '\t$(\tperput_dofile($6"all",ps6,$6".pm",mainta,label(hmph),#17,1,lookup,rdb,wrb,closefile)\n\t\tquitflg_true\n\t\tassign()\n\t\tsearchrec(objname)\n\t\tdeassign()\n\t\tclose(perput)\n',
        '\t$( quitflg_true\n        unless searchrec(objname)=1 error("External ATTACH persona unavailable or not found.")\n')
    seven = replace_once(seven, 'let pw=PSWD of (rec rem 128+dmpbuf)\n\t\t\trec_rec rem 128+dmpbuf',
                         'let pw=PSWD of rec')
    for operation in ('SAVE', 'PASSWORD'):
        five = replace_once(five, '\t\tcase SF.' + operation + ':\n',
            '\t\tcase SF.' + operation + ':\n            error("Read-only external persona storage: ' + operation + ' unavailable.")\n')
    declarations, routines = readonly_adapter()
    library = replace_once(library, 'let appendfile(', declarations + '\nlet appendfile(')
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
        '// Independent restoration R1 adapter, generated for this experimental build.\n' + routines +
        '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    files.update({'MUDLIB.BCL': library.encode('ascii'), 'MUD7.BCL': seven.encode('ascii'),
                  'MUD5.BCL': five.encode('ascii'), 'ROBOOT.MAC': (ROOT / 'tools/fixtures/ROBOOT.MAC').read_bytes(),
                  'ROSEED.BCL': (ROOT / 'tools/fixtures/ROSEED.BCL').read_bytes()})


def prepare(local, upstream, output, *, always_open=False, external_readonly=False, external_save_existing=False,
            external_exit_existing=False, external_death_existing=False, external_creation=False, external_admin=False,
            external_lifecycle=False, chain_targets=()):
    if sum((external_readonly, external_save_existing, external_exit_existing, external_death_existing, external_creation, external_admin, external_lifecycle)) > 1:
        raise ValueError('Choose one external persona mode')
    if chain_targets and not external_lifecycle:
        raise ValueError('Chaining requires the external lifecycle variant')
    if output.exists():
        raise FileExistsError("Output already exists: " + str(output))
    files, origins, originals = {}, {}, {}
    for path in sorted(local.iterdir()):
        if path.suffix.upper() not in SOURCE_SUFFIXES:
            continue
        raw = path.read_bytes()
        originals[path.name] = digest(raw)
        for name, data in split_subfiles(path.name, raw).items():
            # Archive boundaries can contribute blank lines; no code/content
            # normalization is permitted when comparing duplicate sections.
            if name in files and files[name].strip(b"\n") != data.strip(b"\n"):
                raise ValueError("Conflicting embedded source: " + name)
            if name not in files:
                files[name] = data
                origins[name] = "source/" + path.name
    for path in sorted(upstream.iterdir()):
        if path.name == "MUD.MIC" or path.suffix.upper() == ".DBA":
            if path.name not in files:
                files[path.name] = read_normalized(path)
                origins[path.name] = "PDP-10/MUD1@" + MUD_REVISION + "/" + path.name

    if "MUD.TXT" not in files:
        raise ValueError("Missing master database: MUD.TXT")
    includes = []
    for name in re.findall(rb"^@([a-zA-Z0-9]+)", files["MUD.TXT"], re.M):
        include = name.decode("ascii").upper() + ".GET"
        if include not in files:
            raise ValueError("Missing include: " + include)
        if re.search(rb"^@", files[include], re.M):
            raise ValueError("DBASE disallows nested includes: " + include)
        includes.append(include)

    local_changes = []
    historical_files = dict(files)
    if always_open:
        original = files.get("MUDLIB.BCL", b"")
        modified = always_open_library(original)
        files["MUDLIB.BCL"] = modified
        local_changes = list(difflib.unified_diff(
            original.decode("ascii").splitlines(True), modified.decode("ascii").splitlines(True),
            fromfile="historical/MUDLIB.BCL", tofile="always-open/MUDLIB.BCL"))

    if external_readonly or external_save_existing or external_exit_existing or external_death_existing or external_creation or external_admin or external_lifecycle:
        external_persona_files(files)
        if external_save_existing or external_exit_existing or external_death_existing or external_creation or external_admin or external_lifecycle:
            from tools.prepare_writes import enable_existing_saves
            enable_existing_saves(files)
        if external_exit_existing or external_death_existing or external_creation or external_admin or external_lifecycle:
            from tools.prepare_writes import enable_existing_exits
            enable_existing_exits(files, historical_files['MUDLIB.BCL'].decode('ascii'))
        if external_death_existing or external_creation or external_admin or external_lifecycle:
            from tools.prepare_writes import enable_existing_deaths
            enable_existing_deaths(files)
        if external_creation or external_admin or external_lifecycle:
            from tools.prepare_writes import enable_creation
            enable_creation(files)
        if external_admin or external_lifecycle:
            from tools.prepare_admin import enable_admin
            enable_admin(files, historical_files['MUD7.BCL'].decode('ascii'))
        if external_lifecycle:
            from tools.prepare_lifecycle import enable_lifecycle
            enable_lifecycle(files)
            origins['XLSTATE.MAC'] = 'tools/fixtures/XLSTATE.MAC'
            if chain_targets:
                from tools.prepare_chaining import enable_chaining
                enable_chaining(files, chain_targets)
        origins['ROBOOT.MAC'] = 'tools/fixtures/ROBOOT.MAC'
        origins['ROSEED.BCL'] = 'tools/fixtures/ROSEED.BCL'
        local_changes = []
        for name in sorted(files):
            if files[name] != historical_files.get(name, b''):
                local_changes.extend(difflib.unified_diff(
                    historical_files.get(name, b'').decode('ascii').splitlines(True), files[name].decode('ascii').splitlines(True),
                    fromfile='historical/' + name,
                    tofile=('external-lifecycle/' if external_lifecycle else
                            'external-admin/' if external_admin else
                            'external-creation/' if external_creation else
                            'external-death-existing/' if external_death_existing else
                            'external-exit-existing/' if external_exit_existing else
                            'external-save-existing/' if external_save_existing else 'external-readonly/') + name))

    report = {"upstream_revision": MUD_REVISION, "original_sha256": originals,
              "availability": "always-open" if always_open else "historical",
              "persona_storage": "external-lifecycle" if external_lifecycle else
                                 "external-admin" if external_admin else
                                 "external-creation" if external_creation else
                                 "external-death-existing" if external_death_existing else
                                 "external-exit-existing" if external_exit_existing else
                                 "external-save-existing" if external_save_existing else "external-readonly" if external_readonly else "native",
               "includes": includes, "chain_targets": list(chain_targets), "files": {}}
    differences = []
    for name, data in sorted(files.items()):
        reference = upstream / name
        comparison = "absent"
        if reference.is_file():
            other = read_normalized(reference)
            comparison = "identical" if data == other else "different"
            if comparison == "different":
                differences.extend(difflib.unified_diff(
                    data.decode("ascii").splitlines(True), other.decode("ascii").splitlines(True),
                    fromfile="prepared/" + name, tofile="upstream/" + name))
        report["files"][name] = {"origin": origins[name], "sha256": digest(data),
                                  "upstream_comparison": comparison}
    output.mkdir(parents=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "upstream.diff").write_text("".join(differences))
    (output / "local.diff").write_text("".join(local_changes))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "source")
    parser.add_argument("--upstream", type=Path, default=ROOT / "upstream/mud1")
    parser.add_argument("--output", type=Path, default=ROOT / "build/mud86")
    parser.add_argument("--always-open", action="store_true",
                        help="Bypass opening-hours enforcement in generated code; preserve HOURS output")
    parser.add_argument('--external-readonly', action='store_true',
                        help='Experimental MariaDB/R1 persona lookup; disables persona persistence')
    parser.add_argument('--external-save-existing', action='store_true',
                        help='Experimental explicit SAVE for existing external personas; no creation/deletion/automatic save')
    parser.add_argument('--external-exit-existing', action='store_true',
                         help='Experimental SAVE and eligible exit updates for existing external personas; deletion remains gated')
    parser.add_argument('--external-death-existing', action='store_true',
                        help='Experimental existing-persona SAVE, exit and death deletion; no creation or PURGE')
    parser.add_argument('--external-creation', action='store_true',
                        help='Experimental external personas including new-persona creation; no PASSWORD or PURGE')
    parser.add_argument('--external-admin', action='store_true',
                        help='Experimental external personas including in-game PASSWORD and PURGE; POWER remains native')
    parser.add_argument('--external-lifecycle', action='store_true',
                        help='Experimental external personas with shared cross-job creation recovery')
    parser.add_argument('--chain-target', action='append', default=[],
                        help='Approved compatible external image sharing this persona namespace; repeat for each target')
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.upstream, text=True).strip()
    if revision != MUD_REVISION:
        parser.error("Upstream checkout must be pinned to " + MUD_REVISION)
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=args.upstream, check=True)
    report = prepare(args.source, args.upstream, args.output, always_open=args.always_open,
                     external_readonly=args.external_readonly, external_save_existing=args.external_save_existing,
                     external_exit_existing=args.external_exit_existing,
                     external_death_existing=args.external_death_existing, external_creation=args.external_creation,
                     external_admin=args.external_admin, external_lifecycle=args.external_lifecycle,
                     chain_targets=args.chain_target)
    print(f"Prepared {len(report['files'])} files in {args.output}")
    for name, info in report["files"].items():
        if info["upstream_comparison"] != "identical":
            print(f"  {name}: upstream {info['upstream_comparison']}")


if __name__ == "__main__":
    main()
