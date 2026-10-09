"""Single lookup worker. Credentials arrive over stdin, never process arguments."""
import json
import sys

from tools.persona_errors import InvalidRecord
from tools.persona_mariadb import MariaDbConfig, MariaDbPersonaStore
from tools.persona_store import MAX_REQUEST_BYTES


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError()
        request = json.loads(raw)
        if set(request) != {'config', 'name_words'}:
            raise ValueError()
        store = MariaDbPersonaStore(MariaDbConfig(**request['config']))
        record = store.get(request['name_words'])
        result = ({'status': 'FOUND', 'words': record.words} if record is not None
                  else {'status': 'NOT_FOUND'})
    except InvalidRecord:
        result = {'status': 'INVALID_RECORD'}
    except Exception:
        result = {'status': 'UNAVAILABLE'}
    sys.stdout.write(json.dumps(result, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
