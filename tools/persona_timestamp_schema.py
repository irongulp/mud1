"""Offline v2 -> v3 timestamp persona schema upgrade, with exact word verification."""
from tools.persona_columns import DATA_COLUMNS
from tools.persona_timestamps import (TIMESTAMP_FORMAT,TIMESTAMP_SQL,timestamp_values,table_ddl)
from tools.persona_mariadb import payload_projection,decode_row
from tools.persona_migrate import connect
from tools.persona_snapshot import MigrationError
from tools.persona_protocol import WORD_MASK
from tools.persona_schema import MAX_UPGRADE_ROWS

STAGING='personas_timestamp_upgrade'
ARCHIVE='personas_columns_v2_archive'
METADATA={'namespace','name_key','format_version','generation','revision','updated_at'}


def upgrade_timestamps(config):
    """Requires offline writers/DDL. Preserve failed staging for investigation."""
    with connect(config) as connection,connection.cursor() as cursor:
        projection,params,version=payload_projection(cursor)
        if version==TIMESTAMP_FORMAT: return {'already_upgraded':True,'upgraded':False}
        if version!=2: raise MigrationError('Timestamp migration requires the complete v2 column schema')
        cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='personas'")
        if {row[0] for row in cursor.fetchall()}!=set(DATA_COLUMNS)|METADATA:
            raise MigrationError('Unexpected persona fields require an explicit extended timestamp migration')
        cursor.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='personas'")
        if cursor.fetchone()!=('InnoDB',): raise MigrationError('Timestamp upgrade requires InnoDB')
        cursor.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() AND EVENT_OBJECT_TABLE='personas'")
        if cursor.fetchone(): raise MigrationError('Persona triggers require an explicit migration')
        cursor.execute("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND (TABLE_NAME='personas' AND REFERENCED_TABLE_NAME IS NOT NULL OR REFERENCED_TABLE_NAME='personas')")
        if cursor.fetchone(): raise MigrationError('Persona foreign keys require an explicit migration')
        cursor.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s)',(STAGING,ARCHIVE))
        if cursor.fetchone(): raise MigrationError('Previous timestamp staging/archive exists; inspect before retrying')
        cursor.execute('SELECT UTC_TIMESTAMP()'); observed=cursor.fetchone()[0]
        cursor.execute(table_ddl(STAGING))
        select='SELECT namespace,name_key,'+projection+',generation,revision,updated_at FROM personas ORDER BY namespace,name_key LIMIT %s'
        cursor.execute('LOCK TABLES personas WRITE,'+STAGING+' WRITE')
        try:
            cursor.execute(select,(*params,MAX_UPGRADE_ROWS+1)); source=cursor.fetchall()
            if len(source)>MAX_UPGRADE_ROWS: raise MigrationError('Timestamp migration exceeds row bound')
            expected=[]
            for row in source:
                namespace,name=row[:2]; generation,revision,updated=row[-3:]
                if (not isinstance(name,bytes) or len(name)!=9 or not isinstance(generation,bytes) or len(generation)!=9
                        or not any(generation) or type(revision) is not int or revision<1):
                    raise MigrationError('Invalid legacy identity metadata')
                number=int.from_bytes(name,'big'); key=(number>>36,number&WORD_MASK)
                try:
                    record=decode_row(key,row[2:-3]); timestamped=timestamp_values(record,observed)
                    truncated=updated.replace(microsecond=0)
                except Exception: raise MigrationError('Timestamp conversion failed without changing source rows') from None
                columns='namespace,name_key,format_version,'+TIMESTAMP_SQL+',generation,revision,created_at,updated_at'
                values=(namespace,name,TIMESTAMP_FORMAT,*timestamped,generation,revision,None,truncated)
                cursor.execute('INSERT INTO '+STAGING+'('+columns+') VALUES ('+','.join(['%s']*len(values))+')',values)
                expected.append((namespace,name,record,generation,revision,None,truncated))
            cursor.execute('SELECT namespace,name_key,format_version,'+TIMESTAMP_SQL+',generation,revision,created_at,updated_at '
                           'FROM '+STAGING+' ORDER BY namespace,name_key')
            actual=[]
            for row in cursor.fetchall():
                number=int.from_bytes(row[1],'big')
                record=decode_row((number>>36,number&WORD_MASK),row[2:-4])
                actual.append((row[0],row[1],record,*row[-4:]))
            if actual!=expected: raise MigrationError('Timestamp migration failed exact record/metadata verification')
        finally: cursor.execute('UNLOCK TABLES')
        cursor.execute(select,(*params,MAX_UPGRADE_ROWS+1))
        if cursor.fetchall()!=source: raise MigrationError('Source changed; timestamp table swap was not performed')
        cursor.execute('RENAME TABLE personas TO '+ARCHIVE+','+STAGING+' TO personas')
        return {'upgraded':True,'format_version':TIMESTAMP_FORMAT,'personas':len(source),
                'observed_at':observed.isoformat(),'legacy_archive':ARCHIVE,'created_at_backfill':'unknown/NULL',
                'updated_at_precision':'truncated to seconds'}
