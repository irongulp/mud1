"""Storage-neutral persona mutations and durable resolution results."""
from dataclasses import dataclass, field
import json
import sys
from typing import Optional

from tools.persona_protocol import EPOCH_LIMIT, LogicalRecord, validate_name_key
from tools.persona_errors import StoreUnavailable
from tools.persona_store import IsolatedPersonaStore

STATUSES = frozenset(('OPEN', 'COMMITTED', 'CONFLICT', 'ABORTED', 'NOT_FOUND',
                      'INVALID_RECORD', 'UNAVAILABLE', 'UNKNOWN', 'REUSED'))
UNCERTAIN_ACTIONS = frozenset(('commit', 'create', 'delete', 'purge', 'resolve'))


def operation_id(value):
    if type(value) is not int or not 0 < value < EPOCH_LIMIT:
        raise ValueError('Invalid operation identity')
    return value.to_bytes(9, 'big')


@dataclass(frozen=True)
class WriteResult:
    status: str
    record: Optional[LogicalRecord] = field(default=None, repr=False)

    def __post_init__(self):
        if (self.status not in STATUSES
                or (self.status == 'OPEN' and not isinstance(self.record, LogicalRecord))
                or (self.status != 'OPEN' and self.record is not None)):
            raise ValueError('Invalid write result')


class IsolatedWriteStore(IsolatedPersonaStore):
    def operation(self, action, operation, key=None, record=None):
        operation_id(operation)
        request = {'action': action, 'operation': operation}
        if key is not None:
            request['name_words'] = validate_name_key(key)
        if record is not None:
            if record.name_words != tuple(key):
                raise ValueError('Write identity mismatch')
            request['words'] = record.words
        def decode(raw):
            result = json.loads(raw)
            status = result['status']
            if status == 'OPEN' and set(result) == {'status', 'words'}:
                snapshot = LogicalRecord(result['words'])
                if action == 'begin_next':
                    if key is not None and snapshot.name_words <= tuple(key):
                        raise ValueError('Enumeration did not advance')
                elif snapshot.name_words != tuple(key):
                    raise ValueError('Snapshot identity mismatch')
                return WriteResult(status, snapshot)
            if set(result) != {'status'}:
                raise ValueError('Invalid worker response')
            return WriteResult(status)
        try:
            return self.call(request, decode)
        except StoreUnavailable:
            return WriteResult('UNKNOWN' if action in UNCERTAIN_ACTIONS else 'UNAVAILABLE')

    def begin(self, operation, key):
        return self.operation('begin', operation, key)

    def begin_purge(self, operation, key):
        return self.operation('begin_purge', operation, key)

    def begin_next(self, operation, after=None):
        return self.operation('begin_next', operation, after)

    def purge(self, operation, key):
        return self.operation('purge', operation, key)

    def begin_delete(self, operation, key):
        return self.operation('begin_delete', operation, key)

    def begin_create(self, operation, key):
        return self.operation('begin_create', operation, key)

    def create(self, operation, key, record):
        return self.operation('create', operation, key, record)

    def delete(self, operation, key):
        return self.operation('delete', operation, key)

    def commit(self, operation, key, record):
        return self.operation('commit', operation, key, record)

    def resolve(self, operation):
        return self.operation('resolve', operation)


def isolated_writer(config, **limits):
    from dataclasses import asdict
    return IsolatedWriteStore((sys.executable, '-m', 'tools.persona_write_worker'), asdict(config), **limits)
