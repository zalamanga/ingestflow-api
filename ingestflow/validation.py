import csv
import io
import re
import unicodedata
from dataclasses import dataclass

MAX_BYTES = 256 * 1024
MAX_ROWS = 1000
MAX_ERRORS = 50
SKU = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,31}")
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    quantity: int


@dataclass(frozen=True)
class Validation:
    rows: list[Product]
    errors: list[dict]
    error_count: int
    row_count: int


def validate_csv(payload: bytes) -> Validation:
    errors: list[dict] = []
    error_count = 0
    row_count = 0
    rows: list[Product] = []
    seen: set[str] = set()

    def reject(row: int, field: str, code: str):
        nonlocal error_count
        error_count += 1
        if len(errors) < MAX_ERRORS:
            errors.append({"row": row, "field": field, "code": code})

    if len(payload) > MAX_BYTES:
        reject(0, "file", "file_too_large")
        return Validation([], errors, error_count, 0)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        reject(0, "file", "invalid_utf8")
        return Validation([], errors, error_count, 0)
    if "\x00" in text:
        reject(0, "file", "null_byte")
        return Validation([], errors, error_count, 0)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        if next(reader, None) != ["sku", "name", "quantity"]:
            reject(1, "header", "expected_sku_name_quantity")
            return Validation([], errors, error_count, 0)
        for number, columns in enumerate(reader, start=2):
            row_count += 1
            if row_count > MAX_ROWS:
                reject(number, "file", "too_many_rows")
                break
            if len(columns) != 3:
                reject(number, "row", "expected_three_columns")
                continue
            sku, name, quantity = columns
            before = error_count
            if not SKU.fullmatch(sku):
                reject(number, "sku", "invalid_sku")
            elif sku in seen:
                reject(number, "sku", "duplicate_sku")
            seen.add(sku)
            if not 1 <= len(name) <= 100 or name != name.strip() or any(unicodedata.category(c).startswith("C") or unicodedata.category(c) in ("Zl", "Zp") for c in name):
                reject(number, "name", "invalid_name")
            if not re.fullmatch(r"0|[1-9][0-9]{0,5}", quantity):
                reject(number, "quantity", "expected_integer_0_to_999999")
            if error_count == before:
                rows.append(Product(sku, name, int(quantity)))
    except csv.Error:
        reject(reader.line_num or 1, "file", "malformed_csv")
    if row_count == 0 and error_count == 0:
        reject(2, "file", "empty_import")
    return Validation(rows if error_count == 0 else [], errors, error_count, row_count)
