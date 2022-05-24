.PHONY: help commit check_venv
REQUIREMENT_SOURCE_FILES := $(shell ls requirements*.in)
REQUIREMENT_FILES := $(REQUIREMENT_SOURCE_FILES:.in=.txt)


.DEFAULT: help


help:
	@echo "Makefile targets:"
	@echo "	help 	this message"
	@echo "	install	setup venv"
	@false

# set up dev environment
check_venv:
ifeq ($(VIRTUAL_ENV),)
	$(error "Run frost from a virtualenv (try 'make install && source venv/bin/activate')")
endif

install: venv requirements.txt
	( . venv/bin/activate && pip install -U pip && pip install -r requirements.txt )

venv:
	python3 -m venv venv

# get everything ready for a clean commit
commit: check_venv exceptions_schema.json $(REQUIREMENT_FILES)

# make sure schema is current. Will rebuild too often, but with same
# output, so no changes visible in git
exceptions_schema.json: report-tls-certs
	./report-tls-certs --generate-schema >$@

# support routines

# local build rules
%.txt: %.in
	pip-compile --quiet $<
