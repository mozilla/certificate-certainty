.PHONY: help commit check_venv

.DEFAULT: help


help:
	@echo "Makefile targets:"
	@echo "	help 	this message"
	@echo "	commit 	update generated files"
	@false

# set up dev environment
check_venv:
ifeq ($(VIRTUAL_ENV),)
	$(error "Run frost from a virtualenv (try 'make install && source venv/bin/activate')")
endif

install: venv
	( . venv/bin/activate && pip install -U pip && pip install -r requirements.txt && python setup.py develop && pre-commit install )

venv:
	python3 -m venv venv

# get everything ready for a clean commit
commit: check_venv requirements.txt exceptions_schema.json

# make sure schema is current. Will rebuild too often, but with same
# output, so no changes visible in git
exceptions_schema.json: report-tls-certs
	./report-tls-certs --generate-schema >$@

requirements.txt: requirements.in
	pip-compile $< 2>/dev/null
