"""Explicit diagnostic runtime entry point for disposable CI installations."""
from server.runtime import main
from tools.batcon_diagnostics import ProbeRuntime


if __name__ == '__main__':
    main(runtime_class=ProbeRuntime)
