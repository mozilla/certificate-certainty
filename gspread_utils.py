#!/usr/bin/env python3
# Enter data below
#
# Note: Google term usage:
# - `spreadsheet`: a document, contains one or more sheets
# - `sheet`: a "tab" in the `spreadsheet` document
# - _IDs_: no api found yet, best to use numeric ids discovered from the URL

# spreadsheet_to_use = "Copy of Certificate Certainty Report"

# sheet names
sheet_current = "Current"
sheet_history = "History"

# Import from stdlib
from dataclasses import dataclass
from pathlib import Path

# Import required modules
import google.auth
import gspread
from gspread.spreadsheet import Spreadsheet
from gspread.worksheet import Worksheet
from oauth2client.service_account import ServiceAccountCredentials

# TypeVar for methods returning self


@dataclass()
class RowRecord:
    actioned: str
    expiration: str
    renewed: str
    status: str
    host: str
    issuer: str
    notes: str
    reported: str

    def key(self) -> tuple[str, str]:
        return (self.expiration, self.host)

    def __hash__(self):
        return self.key().__hash__()

    def same_host(self, other) -> bool:
        if not isinstance(other, RowRecord):
            raise NotImplementedError
        return self.key() == other.key()

    def __lt__(self, other) -> bool:
        if other is None:
            return False
        elif not isinstance(other, RowRecord):
            raise NotImplementedError
        return self.key() < other.key()

    def update(self, other):
        if not isinstance(other, RowRecord):
            raise NotImplementedError
        # if the report is generated twice from the same input, there will be
        # duplicate "reported" dates.
        if self.reported == other.reported:
            return self
        # ToDo: add checks for unexpected transitions
        assert self.reported < other.reported  # nosec
        self.renewed = other.renewed
        self.status = other.status
        return self

    def as_dict(self, as_of: str | None = None) -> dict[str, str]:
        return {
            "Actioned": self.actioned,
            "Expiration": self.expiration,
            "Renewed": self.renewed,
            "Status": self.status,
            "Host": self.host,
            "Issuer": self.issuer,
            "Notes": self.notes,
            "First Reported": self.reported or as_of or "",
        }

    @classmethod
    def from_dict(cls, d: dict, as_of: str | None = None):
        return RowRecord(
            actioned=d["Actioned"],
            expiration=d["Expiration"],
            renewed=d["Renewed"],
            status=d["Status"],
            host=d["Host"],
            issuer=d["Issuer"],
            notes=d["Notes"],
            reported=d["First Reported"] or as_of or "",
        )

    def as_list(self) -> list[str]:
        d = self.as_dict()
        return [d[col] for col in row_record_column_order]


# Type aliases
# RowRecord = dict[str, str]
SheetData = list[RowRecord]

# Column order for output
row_record_column_order = (
    "Actioned,Expiration,Renewed,Status,Host,Issuer,Notes,First Reported".split(",")
)

# ToDo: minimize needed scope (I think just "spreadsheets")
scopes = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


# TODO: make the file name set via environment variable
__KEY_FILE_PATH = Path(".secrets/hwine-cc-dev-975260d2e5f8.json")


def open_spreadsheet(reference: str) -> Spreadsheet:
    # bit of a hack - we support service account login in 1 of 2 ways:
    #   - if there's a JSON keyfile, we use that (dev use case)
    #   - otherwise, use default service account (non-dev use case)
    # Assign credentials and path of style sheet
    if __KEY_FILE_PATH.exists():
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            ".secrets/hwine-cc-dev-975260d2e5f8.json",
            # scopes can be either a string, or an array of strings. This is
            # correctly documented in the function's __doc__ string, but not typed
            # correctly in the signature
            scopes,  # type: ignore
        )
    else:
        creds, _ = google.auth.default(
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
        )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(reference)
    return spreadsheet


def _load_sheet(worksheet: Worksheet) -> SheetData:
    # cells = current.get_all_cells() <= list of cells
    # values =  current.get_all_values() <= list of list of row values; empty cells have empty string value
    records: SheetData = [RowRecord.from_dict(x) for x in worksheet.get_all_records()]
    #    header (row 1) values must be unique or raises GSpreadException
    return records


def _get_worksheet(spreadsheet: Spreadsheet, worksheet_name: str) -> Worksheet:
    return spreadsheet.worksheet(worksheet_name)


def get_current_sheet_data(spreadsheet: Spreadsheet) -> SheetData:
    return _load_sheet(_get_worksheet(spreadsheet, sheet_current))


def sheet_data_to_rows(data: SheetData, date_str: str | None = None) -> list[list[str]]:
    rows = []
    if len(data) and date_str:
        # HACK: presence of date string also means we need an empty row :(
        rows = [
            # empty row for spacer
            ("x" * len(row_record_column_order)).split("x")
        ]
    for row in data:
        row_values = row.as_list()
        if date_str:
            row_values.append(date_str)
        rows.append(row_values)
    return rows


def set_current_sheet_data(spreadsheet: Spreadsheet, data: SheetData) -> None:
    # Need to convert SheetData to list of lists of row value data
    rows = sheet_data_to_rows(data)
    current = _get_worksheet(spreadsheet, sheet_current)
    # clear the existing data, leaving header row (frozen rows) alone
    range = f"R{current.frozen_row_count+1}C1:R{current.row_count}C{current.col_count}"
    current.batch_clear(
        [
            range,
        ]
    )
    # now append current data
    current.append_rows(rows, table_range="A:A")


def append_history_sheet(
    spreadsheet: Spreadsheet, data: SheetData, date_str: str
) -> None:
    # Need to convert SheetData to list of lists of row value data
    rows = sheet_data_to_rows(data, date_str)
    # We append the date as the final item in each row
    history = _get_worksheet(spreadsheet, sheet_history)
    # without a range, data pasted at bottom, but column I
    history.append_rows(rows, table_range="A:A")
