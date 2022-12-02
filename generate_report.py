#!/usr/bin/env python3
"""generate the latest actionable report Google Spreadsheet.

This is done by
- adding in all new entries (from run of `report-tls-certs`)
- updating old entries with newer data (current contents of "Current" worksheet)
- moving all handled data to the "History" worksheet
"""

from pathlib import Path
from datetime import datetime, timedelta
import json
import os
import shutil

from google.cloud import storage
from google.api_core.page_iterator import HTTPIterator
from google.cloud.storage.blob import Blob
import typer
import dtyper

import gspread_utils
from gspread_utils import RowRecord, Spreadsheet, open_spreadsheet, Worksheet, SheetData
import merge_jobs


# globals (common prefix allows grouping in debugger)
g_spreadsheet: Spreadsheet
g_new_actionable: SheetData | None = None
g_additional_history: SheetData | None = None
g_local_new_data: Path = Path(
    "/tmp/report.json"  # nosec -- we're in a short running container
)
g_cutoff_date: str = ""  # cutoff date for report (e.g. today+3w)
g_as_of_date: str = ""  # date when data collected
g_today: str


app = typer.Typer(add_completion=False)


def _date_callback(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"Invalid date format '{value}', must be 'yyyy-mm-dd'")
    return value


ValidatedCutoffDate = typer.Option(
    (datetime.now() + timedelta(weeks=3)).date().isoformat(),
    callback=_date_callback,
    help="report cutoff date in ISO format",
)
ValidatedAsOfDate = typer.Option(
    datetime.now().date().isoformat(),
    callback=_date_callback,
    help="report as-of date in ISO format",
)


@app.callback()
def _shared_options(
    ctx: typer.Context,
    report_date: str = ValidatedCutoffDate,
    as_of_date: str = ValidatedAsOfDate,
):
    if ctx.resilient_parsing:
        # see https://typer.tiangolo.com/tutorial/options/callback-and-context/#fix-completion-using-the-context
        return
    global g_cutoff_date
    g_cutoff_date = report_date
    global g_as_of_date
    g_as_of_date = as_of_date


from google.cloud import storage


# from https://cloud.google.com/storage/docs/listing-objects#prereq-code-samples
def list_blobs_with_prefix(
    gcp_project: str, bucket_name: str, prefix: str | None, delimiter: str | None = None
) -> HTTPIterator:
    """Lists all the blobs in the bucket that begin with the prefix.

    This can be used to list all blobs in a "folder", e.g. "public/".

    The delimiter argument can be used to restrict the results to only the
    "files" in the given "folder". Without the delimiter, the entire tree under
    the prefix is returned. For example, given these blobs:

        a/1.txt
        a/b/2.txt

    If you specify prefix ='a/', without a delimiter, you'll get back:

        a/1.txt
        a/b/2.txt

    However, if you specify prefix='a/' and delimiter='/', you'll get back
    only the file directly under 'a/':

        a/1.txt

    As part of the response, you'll also get back a blobs.prefixes entity
    that lists the "subfolders" under `a/`:

        a/b/
    """

    storage_client = storage.Client(gcp_project)

    # Note: Client.list_blobs requires at least package version 1.17.0.
    blobs = storage_client.list_blobs(bucket_name, prefix=prefix, delimiter=delimiter)

    return blobs


@app.command()
def fetch(
    ctx: typer.Context,
    gcp_project: str = typer.Option(None, envvar="GCP_PROJECT"),
    gcs_bucket: str = typer.Option(None, envvar="GCS_BUCKET"),
    gcs_prefix: str = typer.Option(None, envvar="GCS_PREFIX"),
) -> None:
    """fetch the most recent "valid" output.

    The data collection doesn't always work properly, so look back until we find a non-zero byte json file

    Download that file for use locally

    Assumes:
        - environment variable GOOGLE_APPLICATION_CREDENTIALS points to service account credentials
    N.B. the underlying service account needs these permissions:
        storage.objects.delete <== unsure about this one
        storage.objects.get
        storage.objects.list
    """
    global g_as_of_date
    report_date: datetime = datetime.fromisoformat(g_as_of_date)
    reports: list[Blob] = []
    valid_blobs: list[Blob] = []
    report_date_str = report_date.date().isoformat()
    for _ in range(14):
        prefix = gcs_prefix + report_date_str
        reports = [
            blob
            for blob in list_blobs_with_prefix(gcp_project, gcs_bucket, prefix)
            if blob.name.endswith(".json")
        ]
        if len(reports) > 0:
            # check to ensure there's data
            valid_blobs = [x for x in reports if x.size]
            if len(valid_blobs) > 1:
                typer.echo(
                    f"WARNING! found {len(valid_blobs)} data files for {report_date_str}"
                )
            if valid_blobs:
                break
        # not found, look on prior date
        report_date = report_date - timedelta(days=1)
        report_date_str = report_date.date().isoformat()
    else:
        raise typer.BadParameter(
            f"no data file found from {g_as_of_date} back to {report_date_str}"
        )
    if report_date_str != g_as_of_date:
        typer.echo(
            f"WARNING! using data from {report_date_str} instead of {g_as_of_date}"
        )
        g_as_of_date = report_date_str

    if len(valid_blobs) == 1:
        b = valid_blobs[0]
        b.download_to_filename(g_local_new_data)
        typer.echo(f"downloaded {b.name} ({b.size}) to {g_local_new_data}")
    else:
        # download all blobs, then merge
        temp_directory = str(g_local_new_data) + ".d"
        shutil.rmtree(temp_directory, ignore_errors=True)
        os.mkdir(temp_directory)
        files_to_merge: list[Path] = []
        for b in valid_blobs:
            f_out = Path(temp_directory, Path(b.name).name)
            b.download_to_filename(f_out)
            typer.echo(f"downloaded {b.name} ({b.size}) to {f_out}")
            files_to_merge.append(f_out)
        merge_jobs.main(files_to_merge)
    return


def _merge_them(current: SheetData, update: SheetData) -> SheetData:
    """Merge the 2 lists according to criteria.

    only one entry per Expiration, Host tuple
    Most recent (update) state is used

    ToDo: add error checks
    """
    c_index = u_index = 0
    merged: SheetData = []
    while c_index < len(current) and u_index < len(update):
        if update[u_index].key() == current[c_index].key():
            merged.append(current[c_index].update(update[u_index]))
            c_index += 1
            u_index += 1
        elif update[u_index].key() < current[c_index].key():
            merged.append(update[u_index])
            u_index += 1
        else:
            merged.append(current[c_index])
            c_index += 1
    # we're at the end of at least one list, but there may be more in the other
    # append those to the end
    append_count = 0
    if c_index < len(current):
        append_count += 1
        merged.extend(current[c_index:])
    if u_index < len(update):
        append_count += 1
        merged.extend(update[u_index:])
    if append_count > 1:
        typer.echo(f"CRITICAL!! Merge failed: {append_count} extensions!")
        typer.echo(f"current: {c_index=}; {len(current)=}")
        typer.echo(f"update:  {u_index=}; {len(update)=}")
        raise typer.Exit(3)

    return merged


def _add_and_update(current: SheetData, update: SheetData) -> SheetData:
    """Create a single list of certs.

    Sort each by (expiration, host), then merge, modifying:
    - on match of expiration, host:
        - update "Actioned" field conditionally (heuristic)
        - update expiration, current renewed, deployed from update
    """

    # Sort each
    update.sort(key=lambda x: x.key())
    current.sort(key=lambda x: x.key())

    # merge in update
    new_current = _merge_them(current, update)

    return new_current


def _extract_history(data: SheetData) -> None:
    """Split combined list into relevant parts.

    There are 2 piles:
    - hosts still needing action
    - hosts no longer needing action, for one of 3 reasons
        - new cert successfully deployed
        - host "actioned" manually
        - now past expiration date
    - Only hosts past expiration date, or with successful deployment, can be
      moved to history. Otherwise they can show up again
    """
    global g_additional_history
    global g_new_actionable
    if g_additional_history or g_new_actionable:
        raise typer.BadParameter("Internal error, outputs already exist")
    g_additional_history = []
    g_new_actionable = []

    last_actionable: RowRecord | None = None
    for host in data:
        if host.status == "Deployed":
            g_additional_history.append(host)
        elif host.expiration < g_as_of_date:
            if not host.actioned:
                host.actioned = "aged out"
            g_additional_history.append(host)
        elif host.expiration > g_cutoff_date:
            # too far in future, clear from report by ignoring
            pass
        else:
            if host == last_actionable:
                # BUG - duplicating rows
                pass
            elif host < last_actionable:
                # BUG - expect these to be sorted
                pass
            else:
                g_new_actionable.append(host)
                last_actionable = host


# `merge` needs to be called both from typer, and from "normal" python code.
# `dtyper.function` provides that for us.
# See [discussion](https://github.com/tiangolo/typer/issues/106#issuecomment-1150179817)
@dtyper.function
@app.command()
def merge(
    ctx: typer.Context,
    spreadsheet_guid: str = typer.Option(None, envvar="SPREADSHEET_GUID"),
) -> None:
    """merge the new data into existing data.

    Process the existing data and the new data into:
    - a new list of need-to-be-actioned
    - updates for the history of items already done
    """

    if not g_local_new_data.exists():
        raise typer.BadParameter("fetch failed (did you run it?)")

    global g_spreadsheet
    g_spreadsheet = open_spreadsheet(spreadsheet_guid)
    cur_data: SheetData = gspread_utils.get_current_sheet_data(g_spreadsheet)
    raw_data = json.loads(open(g_local_new_data).read())
    # convert the json dictionaries to RowRecords
    # work with older json files
    global g_as_of_date
    # report_date = ctx.obj["report_date"]
    report_date = g_as_of_date
    if not g_as_of_date:
        g_as_of_date = report_date
    if isinstance(raw_data, list):
        # older format, only SheetData
        new_data = raw_data
    else:
        # assume dictionary
        new_data = raw_data["data"]
        # ToDo: grab report_date once it's provided
        # ToDo: grap as_of_date once it's provided
    new_data = [
        RowRecord(
            actioned="",
            expiration=x["current_expiration"],
            renewed="Y" if x["renewal_issued"] else "N",
            status=x["deployment_status"].title(),
            host=x["common_name"],
            issuer=x["issuer"],
            notes="",
            reported=report_date,
        )
        for x in new_data
    ]

    all_data: SheetData = _add_and_update(cur_data, new_data)
    _extract_history(all_data)

    return


@app.command()
def update(
    ctx: typer.Context,
    spreadsheet_guid: str = typer.Option(None, envvar="SPREADSHEET_GUID"),
) -> None:
    """Update the worksheet.

    Now that we have all the information, we can update the file

    Note that invoking update redoes the merge
    """
    global g_today
    g_today = datetime.now().strftime("%F")
    merge(ctx, spreadsheet_guid)
    assert isinstance(  # nosec -- used to help static typing analysis
        g_additional_history, list
    )  # nosec -- used to help static typing analysis
    assert isinstance(  # nosec -- used to help static typing analysis
        g_new_actionable, list
    )  # nosec -- used to help static typing analysis

    # Append the new history
    gspread_utils.append_history_sheet(g_spreadsheet, g_additional_history, g_today)

    # Replace the current
    gspread_utils.set_current_sheet_data(g_spreadsheet, g_new_actionable)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(Path("config.env"))
    app()
