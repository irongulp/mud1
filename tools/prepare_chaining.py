"""Explicit compatible-image handover; no native persona-file fallback."""
from pathlib import Path
import re
from tools.prepare import replace_once

ROOT = Path(__file__).resolve().parents[1]


def enable_chaining(files, targets):
    if not targets or any(not re.fullmatch(r'[a-z][a-z0-9]{0,5}', target) for target in targets):
        raise ValueError('Chain targets must be explicit lowercase TOPS-10 image names')
    library = files['MUDLIB.BCL'].decode('ascii')
    seven = files['MUD7.BCL'].decode('ascii')
    declarations, routines = (ROOT / 'tools/fixtures/WRCHAIN.BCL').read_text().split('// ROUTINES\n', 1)
    library = replace_once(library, 'let appendfile(', declarations + '\nlet appendfile(')
    allowed = ' \\/ '.join('seq(target,"' + target + '")' for target in targets)
    routines += '\nand chain.allowed(target)=' + allowed + '\n'
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
                           routines + '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    first = library.index('\tchain_findtmp(', library.index('and initialise()'))
    last = library.index('\taccess()', first)
    library = library[:first] + '\tchain.in()\n' + library[last:]
    library = replace_once(library, '        if found=2\n',
        '        if chain if found=0 outs("Chained persona is missing; handover stopped.*C*L")<>giveback()\n'
        '        if found=2\n')
    library = replace_once(library, '$( let result=saverec(profile+14)\n',
                           '$( let result=saverec(profile+14)\n   if result gr 0 chain.ready_true\n')
    library = replace_once(library, '\t$) or outz($az"*C*LNot updating persona.*C*L")',
                           '\t$) or $( chain.ready_true; outz($az"*C*LNot updating persona.*C*L") $)')
    seven = replace_once(seven, '      error("Read-only external persona storage: chaining unavailable.")',
                         '      unless chain.permitted(nextgame) error("External handover unavailable; resolve pending persistence first.")')
    seven = replace_once(seven, '\twriteprofile(nextgame)', '\tchain.ready_false\n\twriteprofile(nextgame)')
    first = seven.index('\t$(\toutput_createtmp(')
    last = seven.index('\t$) or\n', first)
    seven = seven[:first] + '''\t$( unless chain.out(nextgame,nextrm,logs)
      $( writes(tty,"External handover not confirmed; session will close.*C*L")
         freemblock(profile); finish
      $)
''' + seven[last:]
    header = files['MUDLIB.GET'].decode('ascii')
    header += '\nEXTERNAL $( chain.ready:XCHRDY; chain.permitted:XCHPER; chain.out:XCHOUT $)\n'
    files.update({'MUDLIB.BCL': library.encode('ascii'), 'MUD7.BCL': seven.encode('ascii'), 'MUDLIB.GET': header.encode('ascii')})
    files['MBOOTS.MAC'] = chaining_startup(files['MBOOTS.MAC'])


def chaining_startup(data):
    """7.04 RUN can supply the lookup-block pointer 77, not the older 75."""
    text = data.decode('ascii')
    text = replace_once(text, '\tCAIN\t.SGPPN,\t75',
                        '\tCAIN\t.SGPPN,\t77\n\tMOVE\t.SGPPN,\t101\n\tCAIN\t.SGPPN,\t75')
    text = replace_once(text, '\tCAIN\t.SGDEV,\t75',
                        '\tCAIN\t.SGDEV,\t77\n\tMOVE\t.SGDEV,\t77\n\tCAIN\t.SGDEV,\t75')
    return text.encode('ascii')
