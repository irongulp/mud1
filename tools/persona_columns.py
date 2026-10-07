"""Named persona model, lossless at the BCPL boundary, independent of SQL."""
from dataclasses import dataclass, fields, field
from tools.persona_protocol import LogicalRecord, pack_name, WORD_MASK, LENGTH_SHIFT, CHAR_BITS, CHAR_MASK

COLUMN_FORMAT = 2
WORD_SIGN = 1 << 35
WORD_RANGE = 1 << 36
HALF_MASK = (1 << 18) - 1
ATTRIBUTE_MASK = (1 << 9) - 1
FLAG_COLUMNS = ('wizard_mode', 'operator_mode', 'berserk', 'snoop', 'attached',
                'brief', 'invisible', 'ignore_messages', 'wizard_eligible')
KNOWN_STATE_MASK = (1 << len(FLAG_COLUMNS)) - 1


@dataclass(frozen=True)
class ColumnPersona:
    name: str
    programmer_number: int
    games_played: int
    sex: str
    asleep: bool
    score: int
    strength: int
    dexterity: int
    stamina: int
    maximum_stamina: int
    native_day: int
    native_day_fraction: int
    wizard_mode: bool
    operator_mode: bool
    berserk: bool
    snoop: bool
    attached: bool
    brief: bool
    invisible: bool
    ignore_messages: bool
    wizard_eligible: bool
    unknown_state_bits: int
    password_word: int = field(repr=False)
    opaque_9: int
    opaque_10: int
    opaque_11: int

    def __post_init__(self):
        pack_name(self.name)
        if self.sex not in ('male', 'female'): raise ValueError('Invalid persona sex')
        for name in ('asleep', *FLAG_COLUMNS):
            if type(getattr(self, name)) is not bool: raise ValueError('Invalid persona boolean')
        limits = {name: (0, HALF_MASK) for name in ('programmer_number','games_played','native_day','native_day_fraction')}
        limits.update({name: (0, ATTRIBUTE_MASK) for name in ('strength','dexterity','stamina','maximum_stamina')})
        limits.update({name: (0, WORD_MASK) for name in ('unknown_state_bits','password_word','opaque_9','opaque_10','opaque_11')})
        limits['score'] = (-WORD_SIGN, WORD_SIGN-1)
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high: raise ValueError('Persona column outside native range: ' + name)
        if self.unknown_state_bits & KNOWN_STATE_MASK: raise ValueError('Unknown flags overlap named flags')

    @classmethod
    def from_record(cls, record):
        words = record.words
        first, second = record.name_words
        length = first >> LENGTH_SHIFT
        name = ''.join(chr(((first, second)[index // 5] >> (LENGTH_SHIFT-CHAR_BITS*(index % 5))) & CHAR_MASK)
                       for index in range(1, length+1))
        flags = {name: bool(words[6] & (1 << bit)) for bit, name in enumerate(FLAG_COLUMNS)}
        return cls(name=name, programmer_number=words[0] >> 18, games_played=words[0] & HALF_MASK,
                   sex='female' if words[1] & 1 else 'male', asleep=bool(words[2] & 1),
                   score=words[3]-WORD_RANGE if words[3] & WORD_SIGN else words[3],
                   strength=words[4] >> 27, dexterity=(words[4] >> 18) & ATTRIBUTE_MASK,
                   stamina=(words[4] >> 9) & ATTRIBUTE_MASK, maximum_stamina=words[4] & ATTRIBUTE_MASK,
                   native_day=words[5] >> 18, native_day_fraction=words[5] & HALF_MASK,
                   unknown_state_bits=words[6] & ~KNOWN_STATE_MASK, password_word=words[7],
                   opaque_9=words[8], opaque_10=words[9], opaque_11=words[10], **flags)

    def to_record(self):
        name = pack_name(self.name)
        states = self.unknown_state_bits | sum(int(getattr(self, name)) << bit for bit, name in enumerate(FLAG_COLUMNS))
        return LogicalRecord(((self.programmer_number << 18) | self.games_played,
            name[0] | int(self.sex == 'female'), name[1] | int(self.asleep), self.score & WORD_MASK,
            (self.strength << 27) | (self.dexterity << 18) | (self.stamina << 9) | self.maximum_stamina,
            (self.native_day << 18) | self.native_day_fraction, states, self.password_word,
            self.opaque_9, self.opaque_10, self.opaque_11))

    def values(self):
        return tuple(int(getattr(self, name)) if name in ('asleep', *FLAG_COLUMNS) else getattr(self, name)
                     for name in DATA_COLUMNS)

    @classmethod
    def from_values(cls, values):
        if len(values) != len(DATA_COLUMNS): raise ValueError('Incomplete persona column row')
        data = dict(zip(DATA_COLUMNS, values))
        for name in ('asleep', *FLAG_COLUMNS):
            if type(data[name]) is not int or data[name] not in (0, 1): raise ValueError('Invalid stored boolean')
            data[name] = bool(data[name])
        return cls(**data)


DATA_COLUMNS = tuple(item.name for item in fields(ColumnPersona))
DATA_SQL = ','.join('`' + name + '`' for name in DATA_COLUMNS)


def key_expression():
    first = '(CHAR_LENGTH(name)<<29)' + ''.join(f'|(IF(CHAR_LENGTH(name)>={i},ASCII(SUBSTRING(name,{i},1)),0)<<{LENGTH_SHIFT-CHAR_BITS*i})' for i in range(1,5))
    second = '|'.join(f'(IF(CHAR_LENGTH(name)>={i},ASCII(SUBSTRING(name,{i},1)),0)<<{LENGTH_SHIFT-CHAR_BITS*(i%5)})' for i in range(5,10))
    return f"UNHEX(CONCAT(LPAD(HEX({first}),9,'0'),LPAD(HEX({second}),9,'0')))"


def data_definitions():
    definitions = ["name VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL CHECK (BINARY name REGEXP '^[a-z0-9]{1,9}$')"]
    for name in ('programmer_number','games_played'):
        definitions.append(f'{name} INT UNSIGNED NOT NULL CHECK ({name} BETWEEN 0 AND {HALF_MASK})')
    definitions += ["sex VARCHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL CHECK (sex IN ('male','female'))",
                    'asleep TINYINT UNSIGNED NOT NULL CHECK (asleep IN (0,1))',
                    f'score BIGINT NOT NULL CHECK (score BETWEEN {-WORD_SIGN} AND {WORD_SIGN-1})']
    for name in ('strength','dexterity','stamina','maximum_stamina'):
        definitions.append(f'{name} SMALLINT UNSIGNED NOT NULL CHECK ({name} BETWEEN 0 AND {ATTRIBUTE_MASK})')
    for name in ('native_day','native_day_fraction'):
        definitions.append(f'{name} INT UNSIGNED NOT NULL CHECK ({name} BETWEEN 0 AND {HALF_MASK})')
    for name in FLAG_COLUMNS:
        definitions.append(f'{name} TINYINT UNSIGNED NOT NULL CHECK ({name} IN (0,1))')
    for name in ('unknown_state_bits','password_word','opaque_9','opaque_10','opaque_11'):
        definitions.append(f'{name} BIGINT UNSIGNED NOT NULL CHECK ({name} BETWEEN 0 AND {WORD_MASK})')
    definitions += [f'CHECK ((unknown_state_bits & {KNOWN_STATE_MASK})=0)',
                    f'CHECK (name_key={key_expression()})', 'UNIQUE KEY persona_name (namespace,name)']
    return definitions


def table_ddl(table='personas'):
    if table not in ('personas', 'personas_column_upgrade'): raise ValueError('Invalid schema table name')
    return f'CREATE TABLE `{table}` (' + ','.join([
        'namespace VARBINARY(64) NOT NULL', 'name_key BINARY(9) NOT NULL',
        f'format_version SMALLINT UNSIGNED NOT NULL DEFAULT {COLUMN_FORMAT} CHECK (format_version={COLUMN_FORMAT})',
        *data_definitions(), 'generation BINARY(9) NULL', 'revision BIGINT UNSIGNED NOT NULL DEFAULT 1',
        'updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)',
        'PRIMARY KEY(namespace,name_key)']) + ') ENGINE=InnoDB'
