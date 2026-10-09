"""Storage-neutral errors; messages never contain backend details or records."""


class StoreUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('Persona storage unavailable')


class InvalidRecord(ValueError):
    def __init__(self):
        super().__init__('Invalid stored persona record')
