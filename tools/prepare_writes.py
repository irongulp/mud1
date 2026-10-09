"""Extend only a generated read-only image with existing-persona explicit SAVE."""
from pathlib import Path
from tools.prepare import replace_once, replace_routine

ROOT = Path(__file__).resolve().parents[1]


def enable_existing_saves(files):
    library = files['MUDLIB.BCL'].decode('ascii')
    seven = files['MUD7.BCL'].decode('ascii')
    five = files['MUD5.BCL'].decode('ascii')
    header = files['MUDLIB.GET'].decode('ascii')
    header += '\nEXTERNAL $( save.pending:XSPEND; save.recover:XSRCOV $)\n'
    declarations, routines = (ROOT / 'tools/fixtures/WRSAVE.BCL').read_text().split('// ROUTINES\n', 1)
    library = replace_once(library, 'let appendfile(', declarations + '\nlet appendfile(')
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
                           routines + '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    library = replace_once(library, '$( xr.calls_0; xr.base0_0;', '$( save.pending_false; xw.mode_0; xr.calls_0; xr.base0_0;')
    library = replace_once(library, '$( rec_xr.lookup(nam)', '$( xw.mode_0\n   rec_xr.lookup(nam)')
    library = replace_once(library, 'done: xr.releasechannel()\n   resultis xr.outcome',
                           'done: unless xw.mode=1 /\\ xr.outcome=1 xr.releasechannel()\n   resultis xr.outcome')
    original_get = '   xr.identity("R1 GET "); xr.put(\'*S\'); xr.putoct(xr.key0,12); xr.put(\'*S\'); xr.putoct(xr.key1,12); xr.emit()\n'
    replacement = '''   if xw.mode=2
   $( xw.ident("W1 RESOLVE "); xr.put('*S'); xr.putoct(xw.op0,12); xr.putoct(xw.op1,12)
      xr.emit(); xw.readresult(); jump(xr.escape)
   $)
   test xw.mode=1 then
   $( if xw.op0=0 xw.op0_xr.challenge0<>xw.op1_xr.challenge1
      xw.ident("W1 BEGIN "); xr.put('*S'); xr.putoct(xw.op0,12); xr.putoct(xw.op1,12)
      xr.emit(); xw.waitack(0)
      xw.ident("W1 KEY "); xr.put('*S'); xr.putoct(xr.key0,12); xr.put('*S'); xr.putoct(xr.key1,12); xr.emit()
   $) or
   $( xr.identity("R1 GET "); xr.put('*S'); xr.putoct(xr.key0,12); xr.put('*S'); xr.putoct(xr.key1,12); xr.emit() $)
'''
    library = replace_once(library, original_get, replacement)
    library = replace_once(library, '   xr.readline()\n   xr.status("R1 NOT_FOUND ","NOT_FOUND")',
                           '   xr.readline()\n   if xr.begins("W1 RESULT ") xw.result()<>xr.fail("WRITE_BEGIN")\n'
                           '   xr.status("R1 NOT_FOUND ","NOT_FOUND")')
    library = replace_routine(library, 'saverec', 'and saverec(nam)=xw.save(nam)')
    library = library.replace('Read-only external persona storage: persona not saved.',
                              'External explicit-SAVE storage: automatic persistence unavailable.')
    seven = replace_routine(seven, 'save', '''let save() be
$( let testsaved=?
   if save.pending save.recover()
   testsaved_saverec(profile+14)
   if testsaved=-1 save.recover()
   if testsaved ls 0 error("External SAVE did not complete; try SAVE again to resolve or retry.")
   if testsaved
   $( out("*C*L:P saved.*C*L",me)
      savedp+_1
   $)
$)''')
    # Pending recovery must bypass unchanged-score admission without claiming a
    # new save. Recovery itself jumps through error(), so it cannot fall through.
    five = replace_once(five, '            error("Read-only external persona storage: SAVE unavailable.")\n',
                        '')
    five = replace_once(five, '\t\tcase SF.SAVE:\n\t\t\tcheckforced()\n\t\t\tspcheck()\n',
                        '\t\tcase SF.SAVE:\n\t\t\tcheckforced()\n\t\t\tspcheck()\n'
                        '            if save.pending save.recover()\n')
    seven = replace_once(seven, '$(\tlet oldname, real, oldp.no=player.names!player.no,false,player.no\n',
        '$(\tlet oldname, real, oldp.no=player.names!player.no,false,player.no\n'
        '   if save.pending error("Resolve the pending SAVE before ATTACH.")\n')
    files.update({'MUDLIB.BCL': library.encode('ascii'), 'MUD7.BCL': seven.encode('ascii'),
                  'MUD5.BCL': five.encode('ascii'), 'MUDLIB.GET': header.encode('ascii')})


def enable_existing_exits(files, original_library):
    """Preserve native eligibility/promotion; replace only the persistence scope."""
    start = original_library.index('and writeprofile(chaining)')
    end = original_library.index('and load.block(', start)
    writer = original_library[start:end]
    begin_io = writer.index('\t$(\tif false\ncurses:')
    end_io = writer.index('\t$) or outz', begin_io)
    writer = (writer[:begin_io] + '''\t$( test STAMINA of profile le 0 then
         writes(tty,"External persona deletion unavailable; saved record retained.*C*L")
      or xw.exitsave()
''' + writer[end_io:])
    writer = replace_once(writer, '\ttest (ATTED of profile=0)',
        '   output_tty\n   unless xw.exitready() $( output_tty; return $)\n\ttest (ATTED of profile=0)')
    library = files['MUDLIB.BCL'].decode('ascii')
    library = replace_routine(library, 'writeprofile', writer.rstrip())
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
        (ROOT / 'tools/fixtures/WREXIT.BCL').read_text() +
        '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    library = replace_once(library, 'Retry SAVE to resolve it; new saves and ATTACH are blocked. QUIT does not save.',
        'Retry SAVE to resolve it; new saves and ATTACH are blocked. QUIT first resolves this operation.')
    files['MUDLIB.BCL'] = library.encode('ascii')


def enable_existing_deaths(files):
    library = files['MUDLIB.BCL'].decode('ascii')
    library = replace_once(library,
        'writes(tty,"External persona deletion unavailable; saved record retained.*C*L")',
        'deleterec(profile+14)')
    library = replace_routine(library, 'deleterec', 'and deleterec(nam) be xd.delete(nam)')
    library = replace_once(library, 'unless xw.mode=1 /\\ xr.outcome=1 xr.releasechannel()',
        'unless (xw.mode=1 \\/ xw.mode=3) /\\ xr.outcome=1 xr.releasechannel()')
    library = replace_once(library, 'test xw.mode=1 then', 'test xw.mode=1 \\/ xw.mode=3 then')
    library = replace_once(library, 'xw.ident("W1 BEGIN ")',
        'xw.ident(xw.mode=3 -> "W1 DSTART ", "W1 BEGIN ")')
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
        (ROOT / 'tools/fixtures/WRDEAD.BCL').read_text() +
        '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    files['MUDLIB.BCL'] = library.encode('ascii')


def enable_creation(files):
    library = files['MUDLIB.BCL'].decode('ascii')
    seven = files['MUD7.BCL'].decode('ascii')
    declarations, routines = (ROOT / 'tools/fixtures/WRCREATE.BCL').read_text().split('// ROUTINES\n', 1)
    library = replace_once(library, 'let appendfile(', declarations + '\nlet appendfile(')
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
                           routines + '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    library = replace_once(library, '$( save.pending_false; xw.mode_0;',
                           '$( for i=0 to xc.slots*2-1 xc.names!i_0\n   save.pending_false; xw.mode_0;')
    library = replace_once(library, '''        unless found=1
        $( test found=0 then outs("External persona not found; creation is unavailable in this read-only build.*C*L")
           or outs("External persona lookup unavailable.*C*L")
           giveback()
        $)''', '''        if found=2
        $( outs("External persona lookup unavailable.*C*L")
           giveback()
        $)''')
    library = replace_once(library, '\tif SEX of profile sexify(1)\n',
                           '\tif SEX of profile sexify(1)\n   xc.register(name)\n')
    seven = replace_once(seven, 'unless searchrec(objname)=1 error("External ATTACH persona unavailable or not found.")',
                         'if searchrec(objname)=2 error("External ATTACH persona lookup unavailable.")')
    library = replace_once(library, '$( let checksum=?\n   xw.name',
                           '$( let checksum,creating=?,xc.fresh(nam)\n'
                           '   if creating if GAMES.PLAYED of profile gr 1 resultis -2\n   xw.name')
    library = replace_once(library, 'xw.last_6; xw.mode_1\n', 'xw.last_6; xw.mode_creating->4,1\n')
    library = replace_once(library, 'unless SCRE of rec ge savescr', 'unless creating \\/ SCRE of rec ge savescr')
    library = replace_once(library, 'External persona missing; creation is unavailable.',
                           'External persona missing; a saved identity will not be recreated.')
    library = replace_once(library, '(xw.mode=1 \\/ xw.mode=3) /\\ xr.outcome=1',
                           '(xw.mode=1 \\/ xw.mode=3 \\/ xw.mode=4) /\\ xr.outcome=1')
    library = replace_once(library, 'test xw.mode=1 \\/ xw.mode=3 then',
                           'test xw.mode=1 \\/ xw.mode=3 \\/ xw.mode=4 then')
    library = replace_once(library, 'xw.ident(xw.mode=3 -> "W1 DSTART ", "W1 BEGIN ")',
                           'xw.ident(xw.mode=4 -> "W1 CSTART ", xw.mode=3 -> "W1 DSTART ", "W1 BEGIN ")')
    library = replace_once(library, 'if xw.last=1 save.pending_false<>resultis rec',
                           'if xw.last=1 xc.saved(xw.name)<>save.pending_false<>resultis rec')
    # Both explicit recovery and exit recovery must retire creation authority.
    library = library.replace('$( save.pending_false; savedp+_1; savescr_xw.savedscore',
                              '$( xc.saved(xw.name); save.pending_false; savedp+_1; savescr_xw.savedscore')
    files.update({'MUDLIB.BCL': library.encode('ascii'), 'MUD7.BCL': seven.encode('ascii')})
