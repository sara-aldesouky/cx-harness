"""Deterministic UTF-8 ZIP-of-CSV renderer."""

import csv
import io
import zipfile
from typing import Any

from .tables import comparison_tables, run_tables


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class CsvZipExporter:
    media_type = "application/zip"

    def render_run(self, report) -> bytes:
        return self._render(run_tables(report))

    def render_comparison(self, report) -> bytes:
        return self._render(comparison_tables(report))

    def _render(self, tables) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, (name, rows) in enumerate(tables, start=1):
                columns = tuple(dict.fromkeys(key for row in rows for key in row))
                text = io.StringIO(newline="")
                writer = csv.DictWriter(text, fieldnames=columns or ("status",), lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: safe_cell(row.get(key, "")) for key in columns})
                filename = name.lower().replace(" ", "_") + ".csv"
                info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, text.getvalue().encode("utf-8"))
        return output.getvalue()
