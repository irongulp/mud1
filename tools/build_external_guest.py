"""Compile an external persona engine with original guest BCPL/DBASE tools."""
from pathlib import Path
import re
import socket
import time

DATA_BASE=0o520000
MARKER_BASE=0o140
COPY_DELAY=.1


def rendered(text): return '\n'.join(line.expandtabs(8).rstrip() for line in text.splitlines()).strip()


def transfer(native,filename,text):
    native.connection.get_socket().setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    native.send('copy '+filename+'=tty:'); native.receive(('copy '+filename+'=tty:\r\n').encode())
    for line in text.splitlines():
        native.send(line)
        if not native.connection.read_until(b'\n',10).endswith(b'\n'): raise RuntimeError('Paced guest transfer stalled')
        time.sleep(COPY_DELAY)
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor=True
    actual=native.command('type '+filename).replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    if rendered(actual)!=rendered(text): raise RuntimeError('Guest source verification failed: '+filename)


def compile_bcpl(native,name):
    native.command('r bcpl',b'\n*'); result=native.command(name+'/o',b'\n*')
    if re.search(r'\([WE]\d+-\d+\)|undefined global|error',result,re.I): raise RuntimeError('Guest compiler rejected '+name)
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor=True


def compile_macro(native,name):
    native.command('r macro',b'\n*'); result=native.command(name+'='+name,b'\n*')
    if re.search(r'(?m)^\?',result): raise RuntimeError('Guest assembler rejected '+name)
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor=True


def build_external(native,prepared):
    native.command('assign dsk: bcl:'); native.command('set tty no altmode')
    transfer(native,'mudlib.get',(prepared/'MUDLIB.GET').read_text())
    for name in ('mud3','mudlib','mud7','mud5'):
        print('Preparing external guest module: '+name,flush=True)
        transfer(native,name+'.bcl',(prepared/(name.upper()+'.BCL')).read_text())
        compile_bcpl(native,name)
    for name in ('roboot','xlstate','mboots'):
        transfer(native,name+'.mac',(prepared/(name.upper()+'.MAC')).read_text()); compile_macro(native,name)
    for name in ('roseed','seedck'):
        transfer(native,name+'.bcl',(prepared/(name.upper()+'.BCL')).read_text() if name=='roseed'
                 else (Path(__file__).resolve().parent/'fixtures/SEEDCK.BCL').read_text())
        compile_bcpl(native,name)
        native.command('r link',b'\n*'); native.command(name+'/g'); native.command('save '+name)
        native.command('protect '+name+'.exe<055>')
    native.command('run roseed',b'ROSEED READY\r\n')
    if 'ROSEED SET' not in native.command('777777777777777777777777'): raise RuntimeError('Seed fixture failed')
    native.command('get seedck'); checked=native.command('start')
    if 'SEEDCK MATCH' not in checked or 'SEEDCK CONSUMED' not in checked: raise RuntimeError('Guest seed is not lossless/read-once')
    native.command('copy mudnat.exe=mud.exe')
    native.command('r link',b'\n*'); native.command(f'/set:.low.:{MARKER_BASE:o}',b'\n*')
    result=native.command('roboot,mud0,mud1,mud2,mud3,mud4,mud5,mud6,mud7,mud8,mudlib,mboots,xlstate/counter',b'\n*')
    counters=re.findall(r'\.HIGH\.\s+([0-7]+)',result)
    if not counters or int(counters[-1],8)>=DATA_BASE: raise RuntimeError('External code overlaps native world database')
    native.command(f'/set:.high.:{DATA_BASE:o}',b'\n*'); native.command('dbadat/g'); native.command('ssave mud')
    native.command('r link',b'\n*'); native.command('/set:.high.:430000',b'\n*')
    native.command(f'dbase,sys:bcplib/search/set:.high.:{DATA_BASE:o},dbadat/g'); native.command('save dbase')
    native.send('run dbase'); generated=native.connection.read_until(b'MUD saved',120)
    if b'Total space used 25247' not in generated or not generated.endswith(b'MUD saved'):
        raise RuntimeError('Original DBASE did not regenerate the expected world')
    native.receive(b'\n.'); native.at_monitor=True
    native.command('protect mud.exe<055>')
    for kind in 'rtomcg': native.command('protect mud.?'+kind+'m<055>')
