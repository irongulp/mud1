"""Provision a loopback-only SQL editor for the private deployed persona database."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets

from server.database import LISTENER_CONFIG,listener_options
from tools.persona_migrate import connect,load_config,quote_identifier
from tools.persona_mariadb import payload_projection
from tools.persona_snapshot import private_read,publish_private,strict_json
from tools.persona_timestamps import STATE_TIMESTAMP_COLUMNS,TIMESTAMP_FORMAT

DEFAULT_PORT=3307
EDITOR_USER='mud86_editor'
EDITOR_HOST='127.0.0.1'
EDITOR_VIEW='persona_editor'
REVISION_TRIGGER='mud86_editor_revision'
CREDENTIAL_FILE='database-editor.json'
CONFIG_LIMIT=4096
PASSWORD_ENTROPY_BYTES=32
MIN_PASSWORD_CHARACTERS=32
EDITABLE_COLUMNS=('programmer_number','games_played','sex','asleep','score','strength',
                  'dexterity','stamina','maximum_stamina','last_saved_at',*STATE_TIMESTAMP_COLUMNS)
EDITOR_COLUMNS=('namespace','name_key','name',*EDITABLE_COLUMNS,'generation','revision','created_at','updated_at')


def revision_statement():
    return ("BEGIN IF SUBSTRING_INDEX(USER(),'@',1)='"+EDITOR_USER+"' THEN "
            'SET NEW.revision=OLD.revision+1; END IF; END')


def read_credentials(path):
    path=Path(path)
    if path.is_symlink(): raise ValueError('Editor credentials must not be a symlink')
    value=strict_json(private_read(path,CONFIG_LIMIT))
    if (not isinstance(value,dict) or set(value)!={'format_version','database','user','host','port','password'}
            or type(value['format_version']) is not int or value['format_version']!=1
            or value['user']!=EDITOR_USER or value['host']!=EDITOR_HOST
            or not isinstance(value['password'],str) or len(value['password'])<MIN_PASSWORD_CHARACTERS):
        raise ValueError('Unrecognized database editor credentials')
    quote_identifier(value['database']); listener_options(value['port'])
    if value['port'] is None: raise ValueError('Editor requires a TCP port')
    return value


def normalized_view(value,database):
    value=value.replace('`','').lower()
    value=value.replace(database.lower()+'.','').replace('personas.','')
    value=re.sub(r'\b([a-z_][a-z_0-9]*)\s+as\s+\1\b',r'\1',value)
    return re.sub(r'\s+',' ',value).strip().replace(', ', ',')


def ensure_objects(cursor,database,definer):
    cursor.execute('SELECT VIEW_DEFINITION,SECURITY_TYPE,IS_UPDATABLE,DEFINER FROM information_schema.VIEWS '
                   'WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s',(database,EDITOR_VIEW))
    view=cursor.fetchone()
    expected='select '+','.join(EDITOR_COLUMNS)+' from personas'
    if view is None:
        cursor.execute('CREATE SQL SECURITY DEFINER VIEW '+quote_identifier(EDITOR_VIEW)+' AS SELECT '+
                       ','.join(quote_identifier(name) for name in EDITOR_COLUMNS)+' FROM personas')
    elif (normalized_view(view[0],database)!=expected or view[1:]!=('DEFINER','YES',definer)):
        raise RuntimeError('Existing persona editor view differs; preserve it for reconciliation')
    cursor.execute('SELECT ACTION_STATEMENT,ACTION_TIMING,EVENT_MANIPULATION,EVENT_OBJECT_TABLE,DEFINER '
                   'FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s AND TRIGGER_NAME=%s',
                   (database,REVISION_TRIGGER))
    trigger=cursor.fetchone()
    if trigger is None:
        cursor.execute('CREATE TRIGGER '+quote_identifier(REVISION_TRIGGER)+' BEFORE UPDATE ON personas '
                       'FOR EACH ROW '+revision_statement())
    elif (trigger[0].replace('`','')!=revision_statement()
          or trigger[1:]!=('BEFORE','UPDATE','personas',definer)):
        raise RuntimeError('Existing editor revision trigger differs; preserve it for reconciliation')


def isolate_local_accounts(cursor):
    # skip-name-resolve makes TCP clients numeric identities. Explicit locked
    # loopback identities fence the historical empty-password local accounts.
    cursor.execute("SELECT User,Host,JSON_UNQUOTE(JSON_EXTRACT(Priv,'$.account_locked')) "
                   "FROM mysql.global_priv WHERE User IN ('root','mud86_store','')")
    for user,host,locked in cursor.fetchall():
        if host!='localhost' and locked!='true': cursor.execute('ALTER USER %s@%s ACCOUNT LOCK',(user,host))
    for user,host in (('root',EDITOR_HOST),('root','127.%'),('mud86_store','127.%'),('','127.%')):
        cursor.execute('CREATE USER IF NOT EXISTS %s@%s ACCOUNT LOCK',(user,host))
        cursor.execute("SELECT JSON_UNQUOTE(JSON_EXTRACT(Priv,'$.account_locked')) FROM mysql.global_priv "
                       'WHERE User=%s AND Host=%s',(user,host))
        if cursor.fetchone()!=('true',): cursor.execute('ALTER USER %s@%s ACCOUNT LOCK',(user,host))


def verify_privileges(cursor,database):
    grantee="'"+EDITOR_USER+"'@'"+EDITOR_HOST+"'"
    expected={
        'USER_PRIVILEGES':{('USAGE','NO')},
        'SCHEMA_PRIVILEGES':set(),
        'TABLE_PRIVILEGES':{(database,EDITOR_VIEW,'SELECT','NO')},
        'COLUMN_PRIVILEGES':{(database,EDITOR_VIEW,column,'UPDATE','NO') for column in EDITABLE_COLUMNS},
    }
    for table,columns in (
        ('USER_PRIVILEGES','PRIVILEGE_TYPE,IS_GRANTABLE'),
        ('SCHEMA_PRIVILEGES','TABLE_SCHEMA,PRIVILEGE_TYPE,IS_GRANTABLE'),
        ('TABLE_PRIVILEGES','TABLE_SCHEMA,TABLE_NAME,PRIVILEGE_TYPE,IS_GRANTABLE'),
        ('COLUMN_PRIVILEGES','TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,PRIVILEGE_TYPE,IS_GRANTABLE')):
        cursor.execute('SELECT '+columns+' FROM information_schema.'+table+' WHERE GRANTEE=%s',(grantee,))
        if set(cursor.fetchall())!=expected[table]:
            raise RuntimeError('Editor privileges differ; preserve them for reconciliation')
    cursor.execute('SELECT Host FROM mysql.user WHERE User=%s',(EDITOR_USER,))
    if cursor.fetchall()!=((EDITOR_HOST,),): raise RuntimeError('Unexpected editor account host')
    for table in ('roles_mapping','proxies_priv'):
        cursor.execute('SELECT User FROM mysql.'+table+' WHERE User=%s AND Host=%s',(EDITOR_USER,EDITOR_HOST))
        if cursor.fetchone(): raise RuntimeError('Editor role/proxy privileges are unsupported')


def configure(state,config_dir,port=DEFAULT_PORT):
    """Call with writers stopped under the installed management lock."""
    state,config_dir=Path(state),Path(config_dir)
    listener_options(port)
    if port is None: raise ValueError('Editor requires a TCP port')
    admin=load_config(config_dir/'persona-admin.json')
    if not admin.unix_socket or Path(admin.unix_socket).resolve()!=(state/'external/database/db.sock').resolve():
        raise ValueError('Editor setup must use this installation\'s private database socket')
    path=config_dir/CREDENTIAL_FILE
    with connect(admin) as connection,connection.cursor() as cursor:
        _,_,layout=payload_projection(cursor)
        if layout!=TIMESTAMP_FORMAT: raise RuntimeError('SQL editing requires persona storage format 3')
        if path.exists():
            credentials=read_credentials(path)
            if credentials['database']!=admin.database or credentials['port']!=port:
                raise RuntimeError('Existing editor configuration differs; preserve it for reconciliation')
        else:
            cursor.execute('SELECT User FROM mysql.user WHERE User=%s',(EDITOR_USER,))
            if cursor.fetchone(): raise RuntimeError('Editor account already exists without managed credentials')
            cursor.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s',
                           (admin.database,EDITOR_VIEW))
            if cursor.fetchone(): raise RuntimeError('Editor view already exists without managed credentials')
            cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s AND TRIGGER_NAME=%s',
                           (admin.database,REVISION_TRIGGER))
            if cursor.fetchone(): raise RuntimeError('Editor trigger already exists without managed credentials')
            credentials={'format_version':1,'database':admin.database,'user':EDITOR_USER,'host':EDITOR_HOST,
                          'port':port,'password':secrets.token_urlsafe(PASSWORD_ENTROPY_BYTES)}
            publish_private(path,lambda stream:stream.write(json.dumps(credentials).encode()))
        cursor.execute('SELECT CURRENT_USER()'); definer=cursor.fetchone()[0]
        ensure_objects(cursor,admin.database,definer)
        cursor.execute('SELECT plugin,authentication_string FROM mysql.user WHERE User=%s AND Host=%s',
                       (EDITOR_USER,EDITOR_HOST))
        account=cursor.fetchone()
        if account is None:
            cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s',(EDITOR_USER,EDITOR_HOST,credentials['password']))
        else:
            cursor.execute('SELECT PASSWORD(%s)',(credentials['password'],))
            if account!=('mysql_native_password',cursor.fetchone()[0]):
                raise RuntimeError('Editor credentials drifted; preserve them for reconciliation')
        cursor.execute("SELECT JSON_UNQUOTE(JSON_EXTRACT(Priv,'$.account_locked')) FROM mysql.global_priv "
                       'WHERE User=%s AND Host=%s',(EDITOR_USER,EDITOR_HOST))
        if cursor.fetchone()==('true',): raise RuntimeError('Editor account is locked; reconciliation required')
        # These grants apply to the updatable view, not its password-bearing base
        # table. Identity fields are readable but cannot be changed by this user.
        target=quote_identifier(admin.database)+'.'+quote_identifier(EDITOR_VIEW)
        if account is None:
            cursor.execute('GRANT SELECT,UPDATE ('+','.join(quote_identifier(name) for name in EDITABLE_COLUMNS)+') ON '+
                           target+' TO %s@%s',(EDITOR_USER,EDITOR_HOST))
        verify_privileges(cursor,admin.database)
        isolate_local_accounts(cursor)
    listener=state/'external/database'/LISTENER_CONFIG
    value={'format_version':1,'port':port}
    if listener.exists():
        if listener.is_symlink() or strict_json(private_read(listener,CONFIG_LIMIT))!=value:
            raise RuntimeError('Existing database listener differs; preserve it for reconciliation')
    else:
        publish_private(listener,lambda stream:stream.write(json.dumps(value).encode()))
        owner=listener.parent.stat(); os.chown(listener,owner.st_uid,owner.st_gid)
    return credentials


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--state',type=Path,default=Path('/var/lib/mud86'))
    parser.add_argument('--config-dir',type=Path,default=Path('/etc/mud86'))
    parser.add_argument('--configure',action='store_true')
    parser.add_argument('--show-credentials',action='store_true')
    args=parser.parse_args(argv)
    try:
        credentials=(configure(args.state,args.config_dir) if args.configure
                     else read_credentials(args.config_dir/CREDENTIAL_FILE))
    except FileNotFoundError:
        raise SystemExit('Database editor is not configured; run MariaDB setup during maintenance') from None
    if not args.show_credentials: credentials={key:value for key,value in credentials.items() if key!='password'}
    print(json.dumps(credentials,indent=2))


if __name__=='__main__': main()
