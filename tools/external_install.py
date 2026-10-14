"""Verified one-way cutover using the installed guest disk and private MariaDB."""
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from tools.persona_migrate import initialize_schema,load_config,import_snapshot,verify_import,connect,quote_identifier
from tools.persona_snapshot import publish_private,write_snapshot,read_snapshot
from tools.persona_timestamps import TIMESTAMP_SQL
from tools.persona_mariadb import MariaDbConfig
from tools.persona_protocol import pack_name
from tools.persona_writes import isolated_writer
from tools.persona_bootstrap import SeedIssuer
from tools.capture_personas import capture,SnapshotInspector
from tools.prepare import prepare,MUD_REVISION
from tools.build_external_guest import build_external,rendered
from tools.terminal_config import protect_bridge_terminals
from server.runtime import Runtime

ROOT=Path(__file__).resolve().parents[1]
DATABASE='mud86_personas'
WRITER='mud86_store'


def phase(path,value):
    descriptor,temporary=tempfile.mkstemp(dir=path.parent,prefix='.cutover-')
    try:
        with os.fdopen(descriptor,'w') as stream:
            os.fchmod(stream.fileno(),0o600); json.dump(value,stream); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def database_config(state,config_dir):
    socket=str(state/'external/database/db.sock')
    runtime_path=config_dir/'personas.json'; admin_path=config_dir/'persona-admin.json'
    if runtime_path.exists():
        runtime,admin=load_config(runtime_path),load_config(admin_path)
        # A saved credential intent is not proof that interrupted DDL/grants
        # completed. Refuse to build the guest until the database is usable.
        from tools.persona_migrate import validate_schema
        with connect(admin) as connection: validate_schema(connection,admin)
        with isolated_writer(runtime) as store: store.get(pack_name('healthchk'))
        return runtime,admin
    runtime=MariaDbConfig(database=DATABASE,user=WRITER,password=secrets.token_urlsafe(32),unix_socket=socket)
    admin=replace(runtime,user='root',password='')
    # Credential intent is recorded first and retained after interruptions.
    for path,value in ((runtime_path,runtime),(admin_path,admin)):
        if not path.exists(): publish_private(path,lambda stream,value=value:stream.write(json.dumps(asdict(value)).encode()))
    import pymysql
    with pymysql.connect(unix_socket=socket,user='root',password='',autocommit=True) as connection,connection.cursor() as cursor:
        cursor.execute('CREATE DATABASE '+quote_identifier(DATABASE)+' CHARACTER SET ascii COLLATE ascii_bin')
    initialize_schema(admin)
    with connect(admin) as connection,connection.cursor() as cursor:
        cursor.execute('CREATE USER %s@localhost IDENTIFIED BY %s',(WRITER,runtime.password))
        cursor.execute('GRANT SELECT,INSERT,DELETE,UPDATE ('+TIMESTAMP_SQL+',revision) ON '+quote_identifier(DATABASE)+'.personas TO %s@localhost',(WRITER,))
        cursor.execute('GRANT SELECT,INSERT,UPDATE ON '+quote_identifier(DATABASE)+'.persona_operations TO %s@localhost',(WRITER,))
    return runtime,admin


def prepare_sources(directory):
    upstream=directory/'upstream'
    if not upstream.exists():
        subprocess.run(['git','clone','--no-checkout','https://github.com/PDP-10/MUD1.git',str(upstream)],check=True)
        subprocess.run(['git','-C',str(upstream),'fetch','--depth','1','origin',MUD_REVISION],check=True)
        subprocess.run(['git','-C',str(upstream),'checkout','--detach',MUD_REVISION],check=True)
    actual=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
    if actual!=MUD_REVISION: raise RuntimeError('Preparation assets must match the pinned revision')
    build=directory/'build'
    if not build.exists(): prepare(ROOT/'source',upstream,build,always_open=True,external_lifecycle=True)
    return build


def cutover(state,config_dir,executable,port=2020):
    directory=state/'external'; directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    marker=directory/'cutover.json'
    current=json.loads(marker.read_text()) if marker.exists() else {'phase':'planned'}
    runtime_config,admin_config=database_config(state,config_dir)
    if current['phase']=='prepared':
        return runtime_config
    phase(marker,current)
    backup=directory/'native-before-cutover.dsk'
    if not backup.exists():
        def copy(stream):
            with (state/'game/guest.dsk').open('rb') as original: shutil.copyfileobj(original,stream)
        publish_private(backup,copy)
    snapshot_path=directory/'native-personas.json'
    build=prepare_sources(directory)
    machine=Runtime(state,executable,port=port)
    try:
        # Until capture/build is finished this is a controlled native runtime,
        # not a public service; the maintenance lock must be held by the caller.
        machine.boot()
        with SnapshotInspector(port) as native:
            if not snapshot_path.exists():
                snapshot=capture(native,install=True); write_snapshot(snapshot_path,snapshot)
                phase(marker,{'phase':'captured','snapshot_sha256':snapshot.sha256})
            snapshot=read_snapshot(snapshot_path)
            if current['phase']!='built':
                source=native.command('type mud.txt').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
                expected=(build/'MUD.TXT').read_text()
                if ''.join(source.split())!=''.join(expected.split()):
                    raise RuntimeError('Custom guest world needs explicit prepared sources; refusing to replace its world definitions')
                build_external(native,build)
                phase(marker,{'phase':'built','snapshot_sha256':snapshot.sha256})
        protect_bridge_terminals(machine)
    finally:
        if not machine.stop(): raise RuntimeError('Cutover guest shutdown not confirmed; preserve state before admission')
    # Imports are atomic and receipt-idempotent; no public guest can write yet.
    import_snapshot(admin_config,snapshot); verify_import(admin_config,snapshot)
    with isolated_writer(runtime_config) as store:
        for key,record in snapshot.records.items():
            if store.get(key)!=record: raise RuntimeError('Runtime account failed exact import read-back')
    phase(marker,{'phase':'prepared','snapshot_sha256':snapshot.sha256,'namespace':runtime_config.namespace})
    return runtime_config


def verify_archwizards(config):
    from tools.audit_archwizards import ARCHWIZARDS
    with isolated_writer(config) as store:
        for name in ARCHWIZARDS:
            record=store.get(pack_name(name.lower()))
            if record is None or not record.words[7]: raise RuntimeError('External archwizard is absent or has no password; reconciliation required')
    return True


def persona_report(config,name=None):
    from tools.persona_mariadb import payload_projection,decode_row
    from tools.persona_protocol import WORD_MASK
    from tools.persona_columns import ColumnPersona
    with connect(config) as connection,connection.cursor() as cursor:
        projection,parameters,_=payload_projection(cursor)
        predicate=' AND name_key=%s' if name else ''
        params=(*parameters,config.namespace.encode(),*((((pack_name(name.lower())[0]<<36)|pack_name(name.lower())[1]).to_bytes(9,'big'),) if name else ()))
        cursor.execute('SELECT name_key,'+projection+',revision FROM personas WHERE namespace=%s'+predicate+' ORDER BY name_key LIMIT 2049',params)
        rows=cursor.fetchall()
        if len(rows)>2048: raise RuntimeError('Persona report exceeds record bound')
        result=[]
        for row in rows:
            key=int.from_bytes(row[0],'big'); record=decode_row((key>>36,key&WORD_MASK),row[1:-1])
            fields=ColumnPersona.from_record(record)
            result.append({'name':fields.name,'score':fields.score,'games_played':fields.games_played,
                           'sex':fields.sex,'strength':fields.strength,'stamina':fields.stamina,
                           'wizard_mode':fields.wizard_mode,'wizard_eligible':fields.wizard_eligible,
                           'has_password':bool(fields.password_word),'revision':row[-1]})
        return result
