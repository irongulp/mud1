"""W1 explicit create/update/delete and resolution; H1/R1 remain unchanged."""
import re
import time

from tools.persona_protocol import GetRequest, LogicalRecord, ReadResult, encode_result, ProtocolError, WORD_MASK, _checksum
from tools.persona_session import ReadSession, LineSocket, HELLO, ACK, IDLE_TIMEOUT, _token
from tools.persona_writes import WriteResult, operation_id

CONTROL = re.compile(rb'W1 (BEGIN|CSTART|DSTART|DELETE|PSTART|NSTART|PDELETE|NEXT|FETCH|KEY|PUT|COMMIT|ABORT|RESOLVE) ([0-7]{24})(.*)\r\n?')


def begin(epoch, operation):
    operation_id(operation)
    return f'W1 BEGIN {_token(epoch)} {operation:024o}\r'.encode()


def begin_delete(epoch, operation):
    operation_id(operation)
    return f'W1 DSTART {_token(epoch)} {operation:024o}\r'.encode()


def begin_create(epoch, operation):
    operation_id(operation)
    return f'W1 CSTART {_token(epoch)} {operation:024o}\r'.encode()


def delete(epoch):
    return f'W1 DELETE {_token(epoch)}\r'.encode()


def key_frame(epoch, name):
    request = GetRequest(epoch, 1, name)
    return f'W1 KEY {_token(epoch)} {request.name_words[0]:012o} {request.name_words[1]:012o}\r'.encode()


def put(epoch, index, word):
    if type(index) is not int or not 1 <= index <= 11 or type(word) is not int or not 0 <= word <= WORD_MASK:
        raise ProtocolError('Invalid upload word')
    return f'W1 PUT {_token(epoch)} {index:02o} {word:012o}\r'.encode()


def commit(epoch, record):
    return f'W1 COMMIT {_token(epoch)} {_checksum(record.words):012o}\r'.encode()


def resolve(epoch, operation):
    operation_id(operation)
    return f'W1 RESOLVE {_token(epoch)} {operation:024o}\r'.encode()


def admin_start(command, epoch, operation):
    if command not in ('PSTART', 'NSTART', 'PDELETE'): raise ProtocolError('Invalid administrative operation')
    operation_id(operation)
    return f'W1 {command} {_token(epoch)} {operation:024o}\r'.encode()


def next_frame(epoch, after):
    key = GetRequest(epoch, 1, after).name_words if after is not None else (0, 0)
    return f'W1 NEXT {_token(epoch)} {key[0]:012o} {key[1]:012o}\r'.encode()


def fetch(epoch):
    return f'W1 FETCH {_token(epoch)}\r'.encode()


class WriteSession(ReadSession):
    def __init__(self, store, *, allow_delete=False, allow_create=False, allow_admin=False, **options):
        self.store = store
        self.allow_delete = allow_delete
        self.deleting = False
        self.allow_create = allow_create
        self.creating = False
        self.allow_admin = allow_admin
        self.admin_command = None
        self.operation = self.name = None
        self.upload = []
        super().__init__(store.get, **options)

    def retire(self):
        super().retire()
        self.operation = self.name = None
        self.upload.clear()
        self.deleting = False
        self.creating = False
        self.admin_command = None

    def result(self, answer):
        data = f'W1 RESULT {self.epoch:024o} {answer.status}\r'.encode()
        self.retire()
        return data

    def credit(self, index):
        return f'W1 ACK {self.epoch:024o} {index:02o}\r'.encode()

    def receive(self, line):
        try:
            if HELLO.fullmatch(line) or self.state in ('idle', 'offered', 'credit'):
                return super().receive(line)
            self.expire()
            if self.state == 'write_credit':
                match = ACK.fullmatch(line)
                if not match or tuple(int(part, 8) for part in match.groups()) != (self.epoch, 1, self.index):
                    raise ProtocolError('Snapshot credit mismatch')
                self.index += 1
                if self.index == len(self.rows):
                    self.rows.clear()
                    if self.admin_command in (b'PSTART', b'NSTART'):
                        self.retire()
                        return None
                    self.state = 'delete' if self.deleting else 'upload'
                    return None
                return self.rows[self.index]
            match = CONTROL.fullmatch(line)
            if not match:
                if self.state == 'ready':
                    return super().receive(line)
                raise ProtocolError('Malformed write frame')
            command, epoch, tail = match.groups()
            if int(epoch, 8) != self.epoch:
                raise ProtocolError('Write epoch mismatch')
            if self.state == 'ready':
                token = re.fullmatch(rb' ([0-7]{24})', tail)
                if command not in (b'BEGIN', b'CSTART', b'DSTART', b'RESOLVE', b'PSTART', b'NSTART', b'PDELETE') or not token:
                    raise ProtocolError('Expected write operation identity')
                if command == b'DSTART' and not self.allow_delete:
                    raise ProtocolError('Deletion disabled')
                if command == b'CSTART' and not self.allow_create:
                    raise ProtocolError('Creation disabled')
                if command in (b'PSTART', b'NSTART', b'PDELETE'):
                    if not self.allow_admin: raise ProtocolError('Administration disabled')
                    self.admin_command = command
                self.deleting = command == b'DSTART'
                self.creating = command == b'CSTART'
                self.operation = int(token[1], 8)
                operation_id(self.operation)
                self.deadline = self.clock() + self.timeout
                if command == b'RESOLVE':
                    return self.result(self.store.resolve(self.operation))
                self.state = 'key'
                return self.credit(0)
            if self.state == 'key':
                key = re.fullmatch(rb' ([0-7]{12}) ([0-7]{12})', tail)
                expected = b'NEXT' if self.admin_command == b'NSTART' else b'KEY'
                if command != expected or not key:
                    raise ProtocolError('Expected persona key')
                name = tuple(int(word, 8) for word in key.groups())
                if self.admin_command == b'NSTART':
                    after = None if name == (0, 0) else GetRequest(self.epoch, 1, name).name_words
                    answer = self.store.begin_next(self.operation, after)
                    self.expire()
                    if answer.status != 'OPEN': return self.result(answer)
                    if after is not None and answer.record.name_words <= after:
                        raise ProtocolError('Enumeration cursor did not advance')
                    self.request = GetRequest(self.epoch, 1, answer.record.name_words)
                    self.name = self.request.name_words
                    self.rows = encode_result(self.request, ReadResult('FOUND', answer.record)).splitlines(keepends=True)
                    self.index, self.state = 0, 'name_credit'
                    return f'W1 NAME {self.epoch:024o} {self.name[0]:012o} {self.name[1]:012o}\r'.encode()
                self.request = GetRequest(self.epoch, 1, name)
                self.name = self.request.name_words
                if self.admin_command == b'PDELETE':
                    answer = self.store.purge(self.operation, self.name)
                    if self.clock() >= self.deadline: answer = WriteResult('UNKNOWN')
                    return self.result(answer)
                start = (self.store.begin_purge if self.admin_command == b'PSTART' else
                         self.store.begin_create if self.creating else
                         self.store.begin_delete if self.deleting else self.store.begin)
                answer = start(self.operation, self.name)
                self.expire()
                if answer.status != 'OPEN':
                    return self.result(answer)
                self.rows = encode_result(self.request, ReadResult('FOUND', answer.record)).splitlines(keepends=True)
                self.index, self.state = 0, 'write_credit'
                return self.rows[0]
            if self.state == 'name_credit' and command == b'FETCH' and not tail:
                self.state = 'write_credit'
                return self.rows[0]
            if command == b'ABORT' and not tail:
                return self.result(self.store.resolve(self.operation))
            if self.state == 'delete' and command == b'DELETE' and not tail:
                answer = self.store.delete(self.operation, self.name)
                if self.clock() >= self.deadline:
                    answer = WriteResult('UNKNOWN')
                return self.result(answer)
            if self.state == 'upload':
                word = re.fullmatch(rb' ([0-7]{2}) ([0-7]{12})', tail)
                if command != b'PUT' or not word or int(word[1], 8) != len(self.upload) + 1:
                    raise ProtocolError('Upload order mismatch')
                self.upload.append(int(word[2], 8))
                if len(self.upload) == 11:
                    self.state = 'commit'
                return self.credit(len(self.upload))
            if self.state == 'commit' and command == b'COMMIT':
                record = LogicalRecord(self.upload)
                if record.name_words != self.name:
                    raise ProtocolError('Write persona mismatch')
                checksum = re.fullmatch(rb' ([0-7]{12})', tail)
                if not checksum or int(checksum[1], 8) != _checksum(record.words):
                    raise ProtocolError('Upload checksum mismatch')
                mutate = self.store.create if self.creating else self.store.commit
                answer = mutate(self.operation, self.name, record)
                # A commit may have happened even if its worker/session expired.
                if self.clock() >= self.deadline:
                    answer = WriteResult('UNKNOWN')
                return self.result(answer)
            raise ProtocolError('Unexpected write state')
        except (ProtocolError, TimeoutError, ValueError):
            self.retire()
            raise


def serve_personas(connection, store, *, on_event=None, allow_delete=False, allow_create=False, allow_admin=False):
    session = WriteSession(store, allow_delete=allow_delete, allow_create=allow_create, allow_admin=allow_admin)
    wire = LineSocket(connection)
    while True:
        try:
            line = wire.read(session.deadline or time.monotonic() + IDLE_TIMEOUT)
            if line is None:
                session.retire()
                return
            try:
                response = session.receive(line)
            except (ProtocolError, TimeoutError, ValueError):
                if on_event:
                    on_event('rejected')
                continue
            if response is not None:
                wire.send(response, session.deadline or time.monotonic() + session.timeout)
            if on_event:
                on_event(session.state)
        except (ProtocolError, TimeoutError):
            session.retire()
            raise
