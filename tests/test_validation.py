from ingestflow.validation import validate_csv


def test_valid_csv_preserves_quoted_fields():
    result = validate_csv(b'sku,name,quantity\r\nPEN-1,"Synthetic pen, blue",12\r\n')
    assert result.error_count == 0
    assert result.rows[0].name == "Synthetic pen, blue"
    assert result.rows[0].quantity == 12


def test_duplicate_sku_rejects_entire_file():
    result = validate_csv(b"sku,name,quantity\nPEN,Pen,1\nPEN,Other pen,2\n")
    assert result.rows == []
    assert result.errors == [{"row": 3, "field": "sku", "code": "duplicate_sku"}]


def test_mixed_errors_counted_but_report_bounded():
    result = validate_csv(b"sku,name,quantity\n" + b"invalid sku, ,NaN\n" * 100)
    assert result.error_count >= 300
    assert len(result.errors) == 50
    assert result.rows == []


def test_limits_encoding_and_empty_file():
    for payload in (b"", b"sku,name,quantity\n", b"\xff", b"sku,name,quantity\nP,N\x00,1", b"x" * 262145):
        assert validate_csv(payload).error_count > 0
    rows = b"sku,name,quantity\n" + b"".join(f"A{i},Name,1\n".encode() for i in range(1001))
    assert validate_csv(rows).errors[-1]["code"] == "too_many_rows"
    assert validate_csv(rows).row_count == 1001


def test_header_and_multiline_name_are_rejected():
    assert validate_csv(b"name,sku,quantity\nN,A,1\n").errors[0]["field"] == "header"
    assert validate_csv(b'sku,name,quantity\nA,"line\nbreak",1\n').errors[0]["field"] == "name"
    assert validate_csv("sku,name,quantity\nA,Name\u0085break,1\n".encode()).errors[0]["field"] == "name"
