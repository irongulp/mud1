.PHONY: test integration browser boot serve

test:
	.venv/bin/python -m unittest discover -s tests -v

integration:
	.venv/bin/python -m tests.integration_web

browser:
	.venv/bin/python tests/browser_smoke.py

boot:
	python3 tools/boot.py

serve:
	.venv/bin/python -m server.gateway
