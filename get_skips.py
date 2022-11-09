#!/usr/bin/env python3

import datetime
import logging
from pprint import pprint
from typing import Generator

import simplematch as sm
import pydantic
import typer

# TODO: put into __init__ file and managed by a tool
__version__ = "0.1.0"

app = typer.Typer(add_completion=False)
logger = logging.getLogger(__name__)

# Example of line to match:
# 2022-10-07 00:33:37,535 __main__ WARNING Skipping anti-tracker-test.com, error RetryError(MaxRetryError("HTTPSConnectionPool(host='crt.sh', port=443): Max retries exceeded with url: /?dNSName=anti-tracker-test.com&exclude=expired&deduplicate=Y (Caused by ResponseError('too many 502 error responses'))"))
skip_re = sm.Matcher(
    '{year:int}-{month:int}-{day:int} {hour:int}:{minute:int}*WARNING Skipping {domain}, error *(Caused by {reason})"))'
)
# pprint(skip_re.regex)


class SkipHost(pydantic.BaseModel):
    timestamp: str  # timestamp since epoch of event
    domain: str  # domain name skipped
    reason: str  # root reason


def filter_file(file: str) -> Generator[SkipHost, None, None]:
    """
    filter_file: Return skipped domain messages from file

    Parses file for error messages about skipping a domain, and returns date,
    domain, & reason

    Yields:
        SkipHost: A record containing the  skipped domain name, and the date &
        reason for being skipped
    """
    with open(file) as in_file:
        while line := in_file.readline():
            if skip_re.test(line):
                vars = skip_re.match(line)
                if not vars:
                    raise AssertionError("SimpleMatch: tested okay, but no match")
                entry_time = datetime.datetime(
                    int(vars["year"]),
                    int(vars["month"]),
                    int(vars["day"]),
                    int(vars["hour"]),
                    int(vars["minute"]),
                    tzinfo=datetime.timezone.utc,
                )
                yield SkipHost(
                    timestamp=entry_time.isoformat(),
                    domain=vars["domain"],
                    reason=vars["reason"],
                )


@app.command()
def main(
    files: list[str] = typer.Argument(None, help="stderr files to process"),
    json: bool = typer.Option(False, help="Output JSON array"),
    sep: str = typer.Option(" ", help="seperator between fields"),
):
    """main Filters stderr output from `report-tls-certs` for skipped hosts.

    Outputs skipped hosts in format specified by options
    """
    if json:
        print("[")
    for file in files:
        for skip in filter_file(file):
            if json:
                print(skip.json())
            else:
                print(f"{skip.timestamp}{sep}{skip.domain}{sep}{skip.reason}")
    if json:
        print("]")


if __name__ == "__main__":
    logging.basicConfig(
        level="DEBUG",
        format="%(asctime)s %(name)-6s %(levelname)-6s %(message)s",
    )
    # typer.run does not return
    app()
