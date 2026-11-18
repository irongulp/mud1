"""Failure-only silent interval, then one census, with concurrent terminal reads."""
import asyncio
import time

from server import gateway
from tools.guest_control import completed_logout
from tests.logout_census import REQUEST_SECONDS
from tests.logout_observer import OBSERVATION_SECONDS

MAX_REPORT_BYTES = 16384


async def observe_timed_logout(original, reader, writer, *, emit, census=None,
                               seconds=OBSERVATION_SECONDS,
                               request_seconds=REQUEST_SECONDS, **kwargs):
    result = await original(reader, writer, **kwargs)
    if result:
        return result
    started = time.monotonic()
    before = gateway.terminal_response_facts(reader)
    record = dict(connection=kwargs.get('connection_id'), late_complete=False,
                  timing_mode='passive-before-census', before=before,
                  observation_started_at=started, passive_seconds=seconds,
                  line_open_before=not writer.is_closing())
    deadline = started + seconds + (request_seconds if census is not None else 0)
    reply = bytearray()

    async def collect():
        try:
            while len(reply) < MAX_REPORT_BYTES:
                data = await reader.read(min(gateway.READ_SIZE, MAX_REPORT_BYTES - len(reply)))
                observed = time.monotonic()
                if not data:
                    record['outcome'] = 'eof'
                    return
                if isinstance(data, str):
                    data = data.encode('ascii', errors='replace')
                reply.extend(data)
                if len(reply) > before['response_bytes']:
                    record.setdefault('first_new_data_at', observed)
                prompt = reply.find(b'\n.')
                if prompt >= 0:
                    record.update(outcome='prompt', prompt_observed_at=observed,
                                  late_complete=completed_logout(
                                      bytes(reply[:prompt + 2]).decode('ascii', errors='replace')))
                    return
            record['outcome'] = 'byte-limit'
        except (OSError, EOFError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
            record.update(outcome='read-error', error_type=type(error).__name__)

    collector = asyncio.create_task(collect())
    try:
        await asyncio.wait({collector}, timeout=seconds)
        if collector.done():
            record['census'] = dict(outcome='not-requested-passive-complete'
                                    if record['late_complete'] else 'not-requested-terminal-ended')
        elif census is not None:
            record['census_requested_at'] = time.monotonic()
            try:
                record['census'] = await asyncio.wait_for(
                    census(reader, kwargs.get('connection_id')),
                    max(0, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                record['census'] = dict(outcome='response-timeout')
            except Exception as error:
                record['census'] = dict(outcome='request-error', error_type=type(error).__name__)
            record['census_returned_at'] = time.monotonic()
        if not collector.done():
            await asyncio.wait_for(asyncio.shield(collector), max(0, deadline - time.monotonic()))
    except asyncio.CancelledError:
        record['outcome'] = 'cancelled'
        raise
    except asyncio.TimeoutError:
        record['outcome'] = 'timeout'
    finally:
        collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        record.update(elapsed_seconds=time.monotonic() - started,
                      after=gateway.terminal_response_facts(reader, bytes(reply)),
                      line_open_after=not writer.is_closing())
        emit(record)
    return result
