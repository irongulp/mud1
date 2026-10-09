"""Timestamp metadata/flags, migration and transactional state transition checks."""
import argparse
from dataclasses import replace
import datetime as dt
import json
from pathlib import Path
import time

from tools.persona_timestamp_schema import upgrade_timestamps
from tools.persona_timestamps import STATE_TIMESTAMP_COLUMNS,native_datetime
from tools.persona_schema import grant_column_writer
from tools.persona_protocol import LogicalRecord,pack_name
from tools.persona_writes import isolated_writer
from tools.persona_backup import backup_database,restore_database
from tests.integration_persona_writes import enable_writes,changed
from tests.integration_persona_read import ROOT,fixture
from tests.integration_persona_migration import rejected
from tests.integration_provisioning import require
from tests.mariadb_fixture import LocalMariaDb,DATABASE


def verify(database,output):
    key=pack_name('fred'); database.seed('fred',fixture(key))
    config=enable_writes(database,allow_create=True,allow_delete=True)
    admin=replace(config,user='root',password='')
    with database.admin() as connection,connection.cursor() as cursor:
        cursor.execute('UPDATE '+DATABASE+".personas SET updated_at='2026-10-04 01:02:03.987654'")
    with isolated_writer(config) as store:
        original=store.get(key)
        require(store.begin(801,key).status=='OPEN','Pre-upgrade journal failed')
    backup_database(admin,output/'before.zip')
    result=upgrade_timestamps(admin)
    require(result['upgraded'],'Timestamp upgrade failed')
    grant_column_writer(admin,config.user)
    require(upgrade_timestamps(admin)['already_upgraded'],'Timestamp upgrade replay failed')
    with database.admin() as connection,connection.cursor() as cursor:
        cursor.execute('SHOW COLUMNS FROM '+DATABASE+'.personas')
        columns=cursor.fetchall(); names=[row[0] for row in columns]
        types={row[0]:row[1] for row in columns}
        require(names.index('created_at')+1==names.index('updated_at'),'created_at column order wrong')
        require(types['updated_at']=='timestamp' and types['created_at']=='timestamp','Host metadata retained microseconds')
        require(types['last_saved_at']=='datetime(6)','Native save time lost precision')
        require(all(types[name]=='timestamp' for name in STATE_TIMESTAMP_COLUMNS),'State markers wrong precision')
        require('wizard_mode' not in names and 'native_day' not in names,'Duplicate flag/time authority retained')
        cursor.execute('SELECT created_at,updated_at,last_saved_at,invisible_at FROM '+DATABASE+'.personas')
        created,updated,saved,observed=cursor.fetchone()
        require(created is None and updated==dt.datetime(2026,10,4,1,2,3),'Legacy metadata backfill/truncation incorrect')
        require(saved==native_datetime(original.words[5]) and observed==dt.datetime.fromisoformat(result['observed_at']),
                'Migration observation/save time incorrect')
    with isolated_writer(config) as store:
        require(store.get(key)==original,'Native words changed during migration')
        time.sleep(1.1)
        require(store.commit(801,key,original).status=='COMMITTED','Old journal no longer usable')
        with database.admin() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT invisible_at,created_at FROM '+DATABASE+'.personas')
            require(cursor.fetchone()==(observed,None),'Repeated on-state reset observation/creation time')
        require(store.commit(801,key,original).status=='COMMITTED','Committed replay failed')
        words=list(original.words); words[6]&=~64
        disabled=LogicalRecord(words)
        store.begin(802,key); require(store.commit(802,key,disabled).status=='COMMITTED','Disable failed')
        with database.admin() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT invisible_at FROM '+DATABASE+'.personas')
            require(cursor.fetchone()==(None,),'Disable did not clear timestamp')
        time.sleep(1.1)
        store.begin(803,key); require(store.commit(803,key,original).status=='COMMITTED','Re-enable failed')
        with database.admin() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT invisible_at,brief_at FROM '+DATABASE+'.personas')
            enabled,brief=cursor.fetchone()
            require(enabled>observed and brief==observed,'Re-enable disturbed other state observations')
        store.begin(804,key); store.begin(805,key)
        require(store.commit(804,key,disabled).status=='COMMITTED','Conflict winner failed')
        require(store.commit(805,key,original).status=='CONFLICT','Conflict loser published flag')
        require(store.purge(801,key).status=='REUSED','Cross-kind identity reused')
        newkey=pack_name('newborn')
        store.begin_create(806,newkey)
        new=LogicalRecord(fixture(newkey))
        require(store.create(806,newkey,new).status=='COMMITTED','New timestamp persona creation failed')
        with database.admin() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT created_at,updated_at,wizard_mode_at FROM '+DATABASE+".personas WHERE name='newborn'")
            metadata=cursor.fetchone()
            require(all(isinstance(value,dt.datetime) and not value.microsecond for value in metadata),'New creation times not whole seconds')
        time.sleep(1.1)
        store.begin(807,newkey); store.commit(807,newkey,new)
        with database.admin() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT created_at,wizard_mode_at FROM '+DATABASE+".personas WHERE name='newborn'")
            require(cursor.fetchone()==(metadata[0],metadata[2]),'SAVE modified creation/observed time')
            cursor.execute('UPDATE '+DATABASE+".personas SET invisible_at=NULL,revision=revision+1 WHERE name='newborn'")
        require(store.get(newkey).words[6]&64==0,'Manual NULL did not disable native flag')
        store.begin(808,newkey)
        database.stop()
        require(store.commit(808,newkey,new).status=='UNKNOWN','Outage falsely confirmed state transition')
        database.start(); require(store.resolve(808).status=='ABORTED','Outage recovery did not fence')
        require(store.get(newkey).words[6]&64==0,'Failed SAVE changed observed state')
    archive=output/'timestamps.zip'; backup_database(admin,archive)
    with LocalMariaDb(output/'restore') as target:
        with target.admin() as connection,connection.cursor() as cursor: cursor.execute('DROP TABLE '+DATABASE+'.personas')
        recovered=replace(admin,unix_socket=str(target.socket))
        require(restore_database(recovered,archive)['restore_verified'],'Timestamp backup restore failed')
        with isolated_writer(recovered) as store:
            require(store.get(key)==disabled,'Restored timestamp data differs')
    with LocalMariaDb(output/'invalid',column_schema=2) as invalid:
        invalid.seed('fred',fixture(key)); invalid_config=enable_writes(invalid)
        invalid_admin=replace(invalid_config,user='root',password='')
        with invalid.admin() as connection,connection.cursor() as cursor:
            cursor.execute('UPDATE '+DATABASE+'.personas SET generation=NULL')
        rejected(lambda: upgrade_timestamps(invalid_admin))
        with invalid.admin() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT format_version FROM '+DATABASE+'.personas')
            require(cursor.fetchone()==(2,),'Failed upgrade replaced the source')
            cursor.execute('SELECT COUNT(*) FROM '+DATABASE+'.personas_timestamp_upgrade')
            require(cursor.fetchone()==(0,),'Failed upgrade published staged rows')
    return {'migration':True,'native_words_preserved':True,'whole_seconds':True,'created_at_order':True,
            'on_off_reenable':True,'replay_conflict_outage':True,'creation_time_preserved':True,'backup_restore':True,
            'failed_migration_preserves_authority':True}


def run(output):
    output.mkdir(mode=0o700); report={'complete':False}
    try:
        with LocalMariaDb(output/'db',column_schema=2) as database: report.update(verify(database,output))
        report['complete']=True
    finally: (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Persona timestamp acceptance complete:',output,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime'/f'persona-times-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
