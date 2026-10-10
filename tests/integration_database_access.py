"""Disposable real-MariaDB acceptance for the SSH-tunnel editor account."""
import argparse
from dataclasses import replace
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import socket
import sys
import subprocess
import time

import pymysql

from server.database import PrivateDatabase
from tools.database_access import configure,CREDENTIAL_FILE,EDITOR_VIEW,EDITOR_COLUMNS
from tools.external_install import database_config
from tools.persona_backup import backup_database,restore_database
from tools.persona_mariadb import insert_persona
from tools.persona_write_mariadb import MariaDbWriteStore
from tools.persona_migrate import connect
from tools.persona_protocol import LogicalRecord,pack_name
from tests.integration_persona_read import fixture

SSH_START_TIMEOUT=10
SSH_STOP_TIMEOUT=5
SSH_POLL_INTERVAL=.05


def rejected(call):
    try: call()
    except pymysql.MySQLError: return
    raise AssertionError('SQL operation unexpectedly permitted')


def tcp(credentials,**overrides):
    values=dict(host='127.0.0.1',port=credentials['port'],user=credentials['user'],
                password=credentials['password'],database=credentials['database'],autocommit=True,
                connect_timeout=2,read_timeout=3,write_timeout=3,init_command="SET time_zone='+00:00'")
    values.update(overrides)
    return pymysql.connect(**values)


@contextmanager
def tunneled(credentials,ssh_port,identity,known_hosts):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
    process=subprocess.Popen(['ssh','-F','/dev/null','-N','-i',str(identity),
        '-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(known_hosts),'-p',str(ssh_port),
        '-L',f'127.0.0.1:{port}:127.0.0.1:{credentials["port"]}','mud86@127.0.0.1'],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+SSH_START_TIMEOUT
        while True:
            if process.poll() is not None: raise AssertionError('Disposable SSH tunnel exited')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=1): break
            except OSError:
                if time.monotonic()>=deadline: raise AssertionError('Disposable SSH tunnel timed out')
                time.sleep(SSH_POLL_INTERVAL)
        yield dict(credentials,port=port)
    finally:
        process.terminate()
        try: process.wait(timeout=SSH_STOP_TIMEOUT)
        except subprocess.TimeoutExpired: process.kill(); process.wait()


def run(output,ssh_port=None,ssh_key=None,ssh_known_hosts=None):
    output=Path(output).resolve(); output.mkdir(mode=0o700)
    configdir=output/'config'; configdir.mkdir(mode=0o700)
    (output/'external').mkdir(mode=0o700)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
    report={'complete':False,'cases':[]}
    key=pack_name('editcheck'); original=LogicalRecord(fixture(key))
    try:
        with PrivateDatabase(output/'external/database') as database:
            config,admin=database_config(output,configdir)
            with connect(admin) as connection,connection.cursor() as cursor:
                cursor.execute('SELECT VERSION()'); report['version']=cursor.fetchone()[0]
                insert_persona(cursor,b'mud',key,original,b'editgen01')
                cursor.execute("CREATE USER IF NOT EXISTS ''@'127.0.0.1'")
            credentials=configure(output,configdir,port)
            require_private=configdir/CREDENTIAL_FILE
            assert require_private.stat().st_mode & 0o077==0
            assert configure(output,configdir,port)==credentials
            database.stop(); database.start()
            assert configure(output,configdir,port)==credentials
            report['cases'].append('credential-preservation-and-restart')
            with connect(admin) as connection,connection.cursor() as cursor:
                changed=','.join('`'+column+'`'+(' AS `generation`' if column=='score' else
                                               ' AS `score`' if column=='generation' else '')
                                 for column in EDITOR_COLUMNS)
                cursor.execute('CREATE OR REPLACE SQL SECURITY DEFINER VIEW persona_editor AS SELECT '+changed+' FROM personas')
                try:
                    configure(output,configdir,port)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Renamed view columns bypassed protected-field validation')
                cursor.execute('CREATE OR REPLACE SQL SECURITY DEFINER VIEW persona_editor AS SELECT '+
                               ','.join('`'+column+'`' for column in EDITOR_COLUMNS)+' FROM personas')
            report['cases'].append('renamed-view-columns-refused-without-replacing')
            with connect(admin) as connection,connection.cursor() as cursor:
                cursor.execute('GRANT SELECT ON personas TO %s@%s',(credentials['user'],credentials['host']))
                try:
                    configure(output,configdir,port)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Unexpected editor privileges were accepted')
                cursor.execute('REVOKE SELECT ON personas FROM %s@%s',(credentials['user'],credentials['host']))
            report['cases'].append('unexpected-editor-privileges-refused')
            with connect(admin) as connection,connection.cursor() as cursor:
                cursor.execute('REVOKE UPDATE (score) ON persona_editor FROM %s@%s',(credentials['user'],credentials['host']))
                try:
                    configure(output,configdir,port)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Revoked editor privileges were silently restored')
                cursor.execute('GRANT UPDATE (score) ON persona_editor TO %s@%s',(credentials['user'],credentials['host']))
            report['cases'].append('revoked-editor-privileges-preserved-and-refused')
            with connect(admin) as connection,connection.cursor() as cursor:
                cursor.execute('ALTER USER %s@%s ACCOUNT LOCK',(credentials['user'],credentials['host']))
                try:
                    configure(output,configdir,port)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Locked editor account was accepted')
                cursor.execute('ALTER USER %s@%s ACCOUNT UNLOCK',(credentials['user'],credentials['host']))
            report['cases'].append('locked-editor-account-refused-without-unlocking')
            for user,password in (('root',''),(config.user,config.password),('unknown_editor','')):
                rejected(lambda user=user,password=password:tcp(credentials,user=user,password=password,database=None))
            if sys.platform.startswith('linux'):
                rejected(lambda:tcp(credentials,user='root',password='',database=None,bind_address='127.0.0.2'))
            rejected(lambda:tcp(credentials,password='incorrect'))
            report['cases'].append('tcp-admin-writer-anonymous-and-wrong-password-rejected')
            if ssh_port is not None:
                with tunneled(credentials,ssh_port,ssh_key,ssh_known_hosts) as forwarded:
                    with tcp(forwarded) as connection,connection.cursor() as cursor:
                        cursor.execute('SELECT name FROM persona_editor'); assert cursor.fetchone()==('editcheck',)
                    rejected(lambda:tcp(forwarded,user='root',password='',database=None))
                report['cases'].append('actual-ssh-forward-editor-login-and-root-rejection')
            with database.admin() as connection,connection.cursor() as cursor:
                cursor.execute("SHOW VARIABLES WHERE Variable_name IN ('bind_address','port','skip_name_resolve','skip_networking')")
                settings=dict(cursor.fetchall())
                assert settings['bind_address']=='127.0.0.1' and int(settings['port'])==port
                assert settings['skip_name_resolve']=='ON' and settings['skip_networking']=='OFF'
            report['cases'].append('listener-is-ipv4-loopback-only')
            # This acceptance targets SQL grants/triggers/transaction semantics.
            # Bounded worker transport is exercised separately by its unit tests
            # and the real production-service browser SAVE/PASSWORD/re-entry test.
            with tcp(credentials) as editor,editor.cursor() as sql:
                store=MariaDbWriteStore(config)
                sql.execute('SELECT * FROM '+EDITOR_VIEW)
                assert 'password_word' not in [column[0] for column in sql.description]
                assert len(sql.fetchall())==1
                for statement in (
                    'SELECT password_word FROM personas','SELECT * FROM persona_operations',
                    "UPDATE persona_editor SET name='renamed'",'UPDATE persona_editor SET revision=99',
                    'UPDATE persona_editor SET generation=NULL','UPDATE persona_editor SET created_at=NULL',
                    "UPDATE persona_editor SET namespace='elsewhere'",'DELETE FROM persona_editor',
                    "INSERT INTO persona_editor(name) VALUES ('new')",'DROP VIEW persona_editor',
                    'ALTER TABLE personas ADD COLUMN injected INT'):
                    rejected(lambda statement=statement:sql.execute(statement))
                report['cases'].append('protected-fields-base-tables-and-ddl-rejected')
                assert store.begin(901,key).status=='OPEN'
                sql.execute("UPDATE persona_editor SET score=123 WHERE namespace='mud' AND name='editcheck' AND revision=1")
                assert sql.rowcount==1
                sql.execute('SELECT score,revision FROM persona_editor'); assert sql.fetchone()==(123,2)
                assert store.commit(901,key,original).status=='CONFLICT'
                report['cases'].append('gui-edit-increments-revision-and-fences-pending-save')
                current=store.get(key); assert current.words[3]==123
                words=list(current.words); words[3]=124
                assert store.begin(902,key).status=='OPEN'
                assert store.commit(902,key,LogicalRecord(words)).status=='COMMITTED'
                sql.execute('SELECT revision FROM persona_editor'); assert sql.fetchone()==(3,)
                report['cases'].append('game-socket-write-increments-exactly-once')
                current=store.get(key); assert store.begin(903,key).status=='OPEN'
                sql.execute("UPDATE persona_editor SET invisible_at='2026-10-09 12:00:00' WHERE name='editcheck'")
                assert store.get(key)==current
                sql.execute('SELECT revision FROM persona_editor'); assert sql.fetchone()==(4,)
                assert store.commit(903,key,current).status=='CONFLICT'
                report['cases'].append('timestamp-only-edit-also-fences-pending-save')
                assert store.begin(904,key).status=='OPEN'
                sql.execute("UPDATE persona_editor SET score=score WHERE name='editcheck'")
                sql.execute('SELECT revision FROM persona_editor'); assert sql.fetchone()==(5,)
                assert store.get(key)==current,'No-op UPDATE changed logical persona words'
                outcome=store.commit(904,key,current)
                assert outcome.status=='CONFLICT','No-op conflict returned '+outcome.status
                report['cases'].append('no-op-editor-update-fences-pending-save')
                sql.execute("UPDATE persona_editor SET score=125 WHERE name='editcheck' AND revision=3")
                assert sql.rowcount==0
                report['cases'].append('stale-editor-revision-guard-rejected')
            archive=output/'database.zip'; backup_database(admin,archive)
            expected=store_record(config,key)
            database.stop()
            recovery=output/'recovery'; recovery.mkdir(mode=0o700)
            (recovery/'external').mkdir(mode=0o700); recovered_config=recovery/'config'; recovered_config.mkdir(mode=0o700)
            with PrivateDatabase(recovery/'external/database') as target:
                with target.admin() as connection,connection.cursor() as cursor:
                    cursor.execute('CREATE DATABASE '+admin.database)
                recovered_admin=replace(admin,unix_socket=str(target.socket))
                assert restore_database(recovered_admin,archive)['restore_verified']
                # SQL archives retain views/triggers; paired configuration retains
                # credentials. Server users/grants are deliberately reprovisioned.
                for filename in ('persona-admin.json',CREDENTIAL_FILE):
                    shutil.copyfile(configdir/filename,recovered_config/filename)
                    (recovered_config/filename).chmod(0o600)
                value=json.loads((recovered_config/'persona-admin.json').read_text())
                value['unix_socket']=str(target.socket)
                (recovered_config/'persona-admin.json').write_text(json.dumps(value))
                assert configure(recovery,recovered_config,port)==credentials
                target.stop(); target.start()
                with tcp(credentials) as editor,editor.cursor() as sql:
                    sql.execute('SELECT score,revision FROM persona_editor'); assert sql.fetchone()==(124,5)
                    sql.execute("UPDATE persona_editor SET score=126 WHERE name='editcheck'")
                    sql.execute('SELECT score,revision FROM persona_editor'); assert sql.fetchone()==(126,6)
                assert expected.words[3]==124
                report['cases'].append('whole-database-backup-restore-and-editor-reprovision')
        report['complete']=True
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def store_record(config,key):
    return MariaDbWriteStore(config).get(key)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ssh-port',type=int)
    parser.add_argument('--ssh-key',type=Path)
    parser.add_argument('--ssh-known-hosts',type=Path)
    args=parser.parse_args()
    if any(value is not None for value in (args.ssh_port,args.ssh_key,args.ssh_known_hosts)) and not all(
            value is not None for value in (args.ssh_port,args.ssh_key,args.ssh_known_hosts)):
        parser.error('All disposable SSH fixture options are required together')
    run(args.output,args.ssh_port,args.ssh_key,args.ssh_known_hosts)
