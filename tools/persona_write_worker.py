"""One bounded write-store operation, credentials and results on private pipes."""
import json
import sys
from tools.persona_errors import InvalidRecord
from tools.persona_mariadb import MariaDbConfig
from tools.persona_protocol import LogicalRecord
from tools.persona_store import MAX_REQUEST_BYTES
from tools.persona_write_mariadb import MariaDbWriteStore
from tools.persona_writes import UNCERTAIN_ACTIONS


def main():
    action = 'get'
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError()
        request = json.loads(raw)
        action = request.get('action', 'get')
        store = MariaDbWriteStore(MariaDbConfig(**request['config']))
        if action == 'get':
            record = store.get(request['name_words'])
            result = {'status': 'FOUND', 'words': record.words} if record else {'status': 'NOT_FOUND'}
        else:
            op = request['operation']
            if action == 'begin':
                answer = store.begin(op, request['name_words'])
            elif action == 'begin_purge':
                answer = store.begin_purge(op, request['name_words'])
            elif action == 'begin_next':
                answer = store.begin_next(op, request.get('name_words'))
            elif action == 'purge':
                answer = store.purge(op, request['name_words'])
            elif action == 'begin_delete':
                answer = store.begin_delete(op, request['name_words'])
            elif action == 'begin_create':
                answer = store.begin_create(op, request['name_words'])
            elif action == 'create':
                answer = store.create(op, request['name_words'], LogicalRecord(request['words']))
            elif action == 'delete':
                answer = store.delete(op, request['name_words'])
            elif action == 'commit':
                answer = store.commit(op, request['name_words'], LogicalRecord(request['words']))
            elif action == 'resolve':
                answer = store.resolve(op)
            else:
                raise ValueError()
            result = {'status': answer.status}
            if answer.record:
                result['words'] = answer.record.words
    except InvalidRecord:
        result = {'status': 'INVALID_RECORD'}
    except Exception:
        result = {'status': 'UNKNOWN' if action in UNCERTAIN_ACTIONS else 'UNAVAILABLE'}
    sys.stdout.write(json.dumps(result, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
