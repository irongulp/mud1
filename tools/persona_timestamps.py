"""Civil native-save time and nullable observed-state timestamps (storage v3)."""
import datetime as dt
from tools.persona_columns import ColumnPersona,DATA_COLUMNS,FLAG_COLUMNS,HALF_MASK
from tools.persona_protocol import WORD_MASK

TIMESTAMP_FORMAT=3
NATIVE_EPOCH=dt.datetime(1858,11,17)
FRACTIONS_PER_DAY=1<<18
MICROSECONDS_PER_SECOND=1000000
SECONDS_PER_DAY=86400
MICROSECONDS_PER_DAY=SECONDS_PER_DAY*MICROSECONDS_PER_SECOND
TIMESTAMP_COLUMNS=tuple('last_saved_at' if name=='native_day' else name+'_at' if name in FLAG_COLUMNS else name
                        for name in DATA_COLUMNS if name!='native_day_fraction')
TIMESTAMP_SQL=','.join('`'+name+'`' for name in TIMESTAMP_COLUMNS)
STATE_TIMESTAMP_COLUMNS=tuple(name+'_at' for name in FLAG_COLUMNS)


def native_datetime(word):
    if type(word) is not int or not 0<=word<=WORD_MASK: raise ValueError('Invalid native timestamp word')
    if word==0: return None
    day,fraction=word>>18,word&HALF_MASK
    micros=(fraction*MICROSECONDS_PER_DAY+FRACTIONS_PER_DAY//2)//FRACTIONS_PER_DAY
    return NATIVE_EPOCH+dt.timedelta(days=day,microseconds=micros)


def datetime_native(value):
    if value is None: return 0
    if not isinstance(value,dt.datetime): raise ValueError('Invalid saved datetime')
    if value.tzinfo is not None: value=value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    if value<NATIVE_EPOCH or value>native_datetime(WORD_MASK): raise ValueError('Saved datetime outside native range')
    elapsed=value-NATIVE_EPOCH
    micros=elapsed.seconds*MICROSECONDS_PER_SECOND+elapsed.microseconds
    fraction=(micros*FRACTIONS_PER_DAY+MICROSECONDS_PER_DAY//2)//MICROSECONDS_PER_DAY
    day=elapsed.days
    if fraction==FRACTIONS_PER_DAY: day+=1; fraction=0
    if not 0<=day<=HALF_MASK: raise ValueError('Saved datetime outside native range')
    return (day<<18)|fraction


def state_date(value):
    if value is not None and (not isinstance(value,dt.datetime) or value.tzinfo is not None or value.microsecond):
        raise ValueError('State observation must be whole-second UTC datetime or NULL')
    return value


def timestamp_values(record,observation):
    state_date(observation)
    if observation is None: raise ValueError('An observation time is required for persistence')
    persona=ColumnPersona.from_record(record)
    values=dict(zip(DATA_COLUMNS,persona.values()))
    values['last_saved_at']=native_datetime(record.words[5])
    for name in FLAG_COLUMNS: values[name+'_at']=observation if getattr(persona,name) else None
    return tuple(values[name] for name in TIMESTAMP_COLUMNS)


def timestamp_record(values):
    if len(values)!=len(TIMESTAMP_COLUMNS): raise ValueError('Incomplete timestamp persona row')
    data=dict(zip(TIMESTAMP_COLUMNS,values))
    native=datetime_native(data.pop('last_saved_at'))
    data['native_day']=native>>18; data['native_day_fraction']=native&HALF_MASK
    for name in FLAG_COLUMNS: data[name]=int(state_date(data.pop(name+'_at')) is not None)
    return ColumnPersona.from_values(tuple(data[name] for name in DATA_COLUMNS)).to_record()


def table_ddl(table='personas'):
    from tools.persona_columns import table_ddl as column_ddl
    if table not in ('personas','personas_timestamp_upgrade'): raise ValueError('Invalid timestamp schema name')
    result=column_ddl().replace('CREATE TABLE `personas`','CREATE TABLE `'+table+'`',1)
    result=result.replace('DEFAULT 2 CHECK (format_version=2)','DEFAULT 3 CHECK (format_version=3)')
    result=result.replace(f'native_day INT UNSIGNED NOT NULL CHECK (native_day BETWEEN 0 AND {HALF_MASK}),'
                          f'native_day_fraction INT UNSIGNED NOT NULL CHECK (native_day_fraction BETWEEN 0 AND {HALF_MASK})',
                          "last_saved_at DATETIME(6) NULL CHECK (last_saved_at IS NULL OR last_saved_at BETWEEN '"
                          +NATIVE_EPOCH.isoformat(sep=' ') + "' AND '"+native_datetime(WORD_MASK).isoformat(sep=' ')+"')")
    for name in FLAG_COLUMNS:
        result=result.replace(f'{name} TINYINT UNSIGNED NOT NULL CHECK ({name} IN (0,1))',
                              f'{name}_at TIMESTAMP NULL DEFAULT NULL')
    result=result.replace('updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)',
        'created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,'
        'updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')
    return result
