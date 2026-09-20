"""Wait for the installed gateway to serve its actual terminal page."""
import time
import urllib.error
import urllib.request

READY_TIMEOUT = 30
POLL_INTERVAL = 0.1


def main():
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/', timeout=2) as response:
                if response.status == 200 and b'id="terminal"' in response.read():
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(POLL_INTERVAL)
    raise TimeoutError('Gateway did not serve the terminal page')


if __name__ == '__main__':
    main()
