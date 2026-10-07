"""Generated in-game administration; standalone POWER remains native."""
from pathlib import Path
from tools.prepare import replace_once, replace_routine

ROOT = Path(__file__).resolve().parents[1]


def enable_admin(files, original_seven):
    library = files['MUDLIB.BCL'].decode('ascii')
    five = files['MUD5.BCL'].decode('ascii')
    seven = files['MUD7.BCL'].decode('ascii')
    declarations, routines = (ROOT / 'tools/fixtures/WRADMIN.BCL').read_text().split('// ROUTINES\n', 1)
    library = replace_once(library, 'let appendfile(', declarations + '\nlet appendfile(')
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
                           routines + '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    library = replace_once(library, 'save.pending_false; xw.mode_0;', 'purge.pending_false; save.pending_false; xw.mode_0;')
    library = replace_once(library, 'if xr.calls ge 1024', 'if xr.calls ge admin.calls')
    library = replace_once(library, 'test xw.mode=1 \\/ xw.mode=3 \\/ xw.mode=4 then',
                           'test xw.mode=1 \\/ xw.mode=3 \\/ xw.mode=4 \\/ xw.mode ge 5 then')
    library = replace_once(library, 'xw.ident(xw.mode=4 -> "W1 CSTART ", xw.mode=3 -> "W1 DSTART ", "W1 BEGIN ")',
        'xw.ident(xw.mode=7 -> "W1 PDELETE ", xw.mode=6 -> "W1 NSTART ", xw.mode=5 -> "W1 PSTART ",\n'
        '         xw.mode=4 -> "W1 CSTART ", xw.mode=3 -> "W1 DSTART ", "W1 BEGIN ")')
    library = replace_once(library, 'xw.ident("W1 KEY ")', 'xw.ident(xw.mode=6 -> "W1 NEXT ", "W1 KEY ")')
    marker = '   xr.readline()\n   if xr.begins("W1 RESULT ")'
    library = replace_once(library, marker, '''   if xw.mode=6
   $( xr.readline()
      if xr.begins("W1 RESULT ") xw.result()<>xr.fail("PURGE_NEXT")
      xr.need("W1 NAME ")
      unless xr.number(12)=xr.epoch0 /\\ xr.number(12)=xr.epoch1 xr.fail("PROTOCOL")
      xr.need(" "); xr.key0_xr.number(12)
      xr.need(" "); xr.key1_xr.number(12); xr.endline()
      xw.ident("W1 FETCH "); xr.emit()
   $)
''' + marker)
    library = replace_once(library, '$( unless save.pending resultis true',
        '$( if purge.pending unless purge.recover() resultis false\n   unless save.pending resultis true')
    five = replace_once(five, '            error("Read-only external persona storage: PASSWORD unavailable.")\n', '')
    five = replace_once(five, '\t\tcase SF.PASSWORD:\n\t\t\tcheckforced()\n',
        '\t\tcase SF.PASSWORD:\n\t\t\tcheckforced()\n'
        '            if save.pending error("Resolve the pending SAVE before PASSWORD.")\n'
        '            if purge.pending error("Resolve the pending PURGE before PASSWORD.")\n')
    five = replace_once(five, '            if save.pending save.recover()\n',
        '            if purge.pending error("Resolve the pending PURGE before SAVE.")\n'
        '            if save.pending save.recover()\n')
    seven = replace_once(seven, '   if save.pending error("Resolve the pending SAVE before ATTACH.")',
        '   if purge.pending error("Resolve the pending PURGE before ATTACH.")\n'
        '   if save.pending error("Resolve the pending SAVE before ATTACH.")')
    # Preserve the native filtering, display and single-character menu verbatim;
    # only replace physical traversal and its destructive I/O block.
    original = original_seven.split('and purge() be\n', 1)[1].split('and bug()', 1)[0]
    body = original[original.index('\t$(\tif us(me)'):original.index('\t\tunless going break')]
    first = body.index('\t\t\t$(\tlet str,prevrec')
    last = body.index('\t\t\t$)', first) + len('\t\t\t$)')
    body = body[:first] + '\t\t\t$( selected_true $)' + body[last:]
    # Strip the original for-loop's opening delimiter: the new bounded loop owns it.
    body = body.replace('\t$(\tif us(me)', '\t\tif us(me)', 1)
    purge = '''and purge() be
$( let psw,going,cursor,enumerate=ps.word,true,vec 1,seq(objname,"that")
   if save.pending error("Resolve the pending SAVE before PURGE.")
   if purge.pending $( purge.recover(); flush(); return $)
   if fight!player.no error("You can't :s in the middle of a fight!",verbname)
   unsetbit(); dormant()
   cursor!0_0; cursor!1_0
   for index=1 to purge.limit
   $( let selected=false
      and found=purge.open(enumerate->cursor,objname,enumerate)
      unless found=1 break
      cursor!0_rec!2 bitand ~1; cursor!1_rec!3 bitand ~1
''' + body + '''
      unless purge.act(selected) break
      unless going /\\ enumerate break
      if index=purge.limit outs("External PURGE limit reached; listing incomplete.*C*L")
   $)
   laststream_-1
   setbit(); flush(); alive()
$)'''
    seven = replace_routine(seven, 'purge', purge)
    header = files['MUDLIB.GET'].decode('ascii')
    header += '\nMANIFEST $( purge.limit=2048; admin.calls=8192 $)\n'
    header += '\nEXTERNAL $( purge.open:XPOPEN; purge.act:XPACT; purge.pending:XPPEND; purge.recover:XPRCV $)\n'
    files.update({'MUDLIB.BCL': library.encode('ascii'), 'MUD5.BCL': five.encode('ascii'),
                  'MUD7.BCL': seven.encode('ascii'), 'MUDLIB.GET': header.encode('ascii')})
