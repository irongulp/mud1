"""Read guest job/terminal ownership before a disposable CI instance is stopped."""
from tools.inspect_game import NativeInspector


def main():
    # Independent maintenance job, no persona login, source installation, or
    # credential inspection. The context manager logs this job off on failure.
    with NativeInspector() as native:
        print(native.command('systat'), flush=True)


if __name__ == '__main__':
    main()
