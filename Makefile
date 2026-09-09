PYTHON ?= .venv/bin/python

.PHONY: check probe
check:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) scripts/check_docs.py
	git diff --check

# Opt-in fixture experiment; does not execute source-project tests.
probe:
	$(PYTHON) scripts/runtime_probe.py
