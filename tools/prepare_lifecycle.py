"""Opt-in shared live-persona state; original native builds are unchanged."""
from pathlib import Path
from tools.prepare import replace_once, replace_routine

ROOT = Path(__file__).resolve().parents[1]


def enable_lifecycle(files):
    library = files['MUDLIB.BCL'].decode('ascii')
    seven = files['MUD7.BCL'].decode('ascii')
    three = files['MUD3.BCL'].decode('ascii')
    declarations, routines = (ROOT / 'tools/fixtures/WRLIFE.BCL').read_text().split('// ROUTINES\n', 1)
    library = replace_once(library, 'manifest $( xc.slots=36 $)\nstatic $( xc.names=vec 71 $)', declarations.rstrip())
    library = replace_once(library, '$( for i=0 to xc.slots*2-1 xc.names!i_0\n', '$( life.selected_0\n')
    library = replace_routine(library, 'xc.register', '''and xc.register(nam) be
$( let entry=life.entry()
   jar(@persona.door)
   if entry!life.id=life.selected entry!life.state_life.new
   unjar(@persona.door)
$)''')
    library = replace_routine(library, 'xc.fresh', 'and xc.fresh(nam)=life.entry()!life.state=life.new')
    library = replace_routine(library, 'xc.saved', 'and xc.saved(nam) be life.end(life.saved)')
    library = replace_once(library, '/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus',
                           routines + '\n/* rda, rdb, wrb, wrdmp, rddmp all jump to errstatus')
    library = replace_once(library, '\tprofile_getmblock()\n', '\tprofile_getmblock()\n   life.init()\n')
    seven = replace_once(seven, '\t\tprofile_getmblock()\n', '\t\tprofile_getmblock()\n      life.init()\n')
    seven = replace_once(seven, '\tme_PNAME of profile\n', '\tme_PNAME of profile\n   life.select()\n')
    library = replace_once(library, '\tplynum!player_player.no\n', '\tlife.drop()\n\tplynum!player_player.no\n')
    if seven.count('\tplynum!player_player.no') != 2:
        raise ValueError('Unexpected native profile retirement paths')
    seven = seven.replace('\tplynum!player_player.no', '\tlife.drop()\n\tplynum!player_player.no')
    three = replace_once(three, '$(\tunless active!player.no=-1 return',
                         '$(\tunless active!player.no=-1 \\/ ~life.current() return')
    seven = replace_once(seven, '\tflush()\n\tdescribe(room)\n\talive()\n\tjump(mainloop)',
                         '\tlife.resume()\n\tflush()\n\tdescribe(room)\n\talive()\n\tjump(mainloop)')
    library = replace_once(library, '$( let checksum,creating=?,xc.fresh(nam)', '$( let checksum,creating=?,?')
    library = replace_once(library, '   if creating if GAMES.PLAYED of profile gr 1 resultis -2\n', '')
    library = replace_once(library,
        '$( xw.op0_0; xw.op1_0; xw.last_6; xw.mode_creating->4,1',
        '''$( xw.op0_0; xw.op1_0
      creating_life.prepare(nam)
      if creating ls 0 outs("External persona lifetime or first SAVE is unresolved.*C*L")<>resultis -2
      creating_creating=1
      if creating if GAMES.PLAYED of profile gr 1 life.end(life.new)<>resultis -2
      xw.last_6; xw.mode_creating->4,1''')
    library = replace_once(library, 'dumpersona(rec)',
        '''unless life.current()
       $( xw.ident("W1 ABORT "); xr.emit(); xw.readresult()
          xr.releasechannel(); resultis -2
       $)
       dumpersona(rec)''')
    library = replace_once(library, 'unless xw.last=3 resultis -2',
                           'life.end(life.new)\n         unless xw.last=3 resultis -2')
    library = replace_once(library, 'error("Previous SAVE did not commit. You may SAVE again.")',
                           'life.end(life.new)\n      error("Previous SAVE did not commit. You may SAVE again.")')
    header = files['MUDLIB.GET'].decode('ascii')
    header += '''
EXTERNAL $( life.table:XLTABL; life.serial:XLSEQN; life.init:XLSLOT
   life.select:XLSEL; life.current:XLCUR; life.drop:XLDROP; life.resume:XLRES $)
'''
    files.update({'MUDLIB.BCL': library.encode('ascii'), 'MUD7.BCL': seven.encode('ascii'),
                  'MUD3.BCL': three.encode('ascii'), 'MUDLIB.GET': header.encode('ascii'),
                  'XLSTATE.MAC': (ROOT / 'tools/fixtures/XLSTATE.MAC').read_bytes()})
