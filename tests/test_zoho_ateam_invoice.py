"""
Tests for zoho-ateam-invoice pipeline.

Run: pytest tests/
     uv run pytest tests/
"""

import csv
import os
import sys
import textwrap
import unittest
from unittest.mock import MagicMock, patch

# The script is named with a hyphen — load it manually
import importlib.util

_script_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts", "zoho-ateam-invoice")
)
spec = importlib.util.spec_from_loader(
    "zoho_ateam_invoice",
    importlib.machinery.SourceFileLoader("zoho_ateam_invoice", _script_path),
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Test fixtures — stand-ins for env-supplied IDs
TEST_ORG_ID = "test_org_123"
TEST_CUSTOMER_ID = "test_customer_456"
TEST_BANK_ACCOUNT_ID = "test_bank_789"
TEST_ENV = {
    "ZOHO_CLIENT_ID": "test_client",
    "ZOHO_CLIENT_SECRET": "test_secret",
    "ZOHO_REFRESH_TOKEN": "test_token",
    "ZOHO_ORG_ID": TEST_ORG_ID,
    "ZOHO_CUSTOMER_ID": TEST_CUSTOMER_ID,
    "ZOHO_BANK_ACCOUNT_ID": TEST_BANK_ACCOUNT_ID,
    "ZOHO_INVOICE_PREFIX": "INV",
    "ZOHO_RATE": "90",
}


class TestParseDate(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(mod.parse_date("11/01/2025"), "2025-11-01")

    def test_leading_zeros(self):
        self.assertEqual(mod.parse_date("03/05/2026"), "2026-03-05")

    def test_year_boundary(self):
        self.assertEqual(mod.parse_date("12/31/2025"), "2025-12-31")


class TestParseCsvHours(unittest.TestCase):
    def test_hhmm_format(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Type", "Task", "Initiative", "Hours"])
            writer.writeheader()
            writer.writerows([
                {"Date": "2025-11-01", "Type": "Work", "Task": "Foo", "Initiative": "Bar", "Hours": "8:00"},
                {"Date": "2025-11-02", "Type": "Work", "Task": "Foo", "Initiative": "Bar", "Hours": "6:30"},
            ])
            name = f.name
        result = mod.parse_csv_hours(name)
        self.assertAlmostEqual(result, 14.5, places=2)
        os.unlink(name)

    def test_decimal_format(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Type", "Task", "Initiative", "Hours"])
            writer.writeheader()
            writer.writerows([
                {"Date": "2025-11-01", "Type": "Work", "Task": "Foo", "Initiative": "Bar", "Hours": "4.5"},
                {"Date": "2025-11-02", "Type": "Work", "Task": "Foo", "Initiative": "Bar", "Hours": "3.0"},
            ])
            name = f.name
        result = mod.parse_csv_hours(name)
        self.assertAlmostEqual(result, 7.5, places=2)
        os.unlink(name)

    def test_skips_blank_hours(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Type", "Task", "Initiative", "Hours"])
            writer.writeheader()
            writer.writerows([
                {"Date": "2025-11-01", "Type": "Work", "Task": "Foo", "Initiative": "Bar", "Hours": "8:00"},
                {"Date": "2025-11-02", "Type": "Work", "Task": "Foo", "Initiative": "Bar", "Hours": ""},
            ])
            name = f.name
        result = mod.parse_csv_hours(name)
        self.assertAlmostEqual(result, 8.0, places=2)
        os.unlink(name)


class TestParsePdfText(unittest.TestCase):
    SAMPLE_PDF_TEXT = textwrap.dedent("""\
        Invoice

        Earnings Statement #82231
        Date of issue: 01/15/2026

        SUMMARY FOR PERIOD  January 1 – January 15, 2026

        TOTAL HOURS     82h
        HOURLY RATE     $90
        TOTAL PAYMENT   $7,380
    """)

    def test_parses_all_fields(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self.SAMPLE_PDF_TEXT

        with patch("subprocess.run", return_value=mock_result):
            result = mod.parse_invoice_pdf("dummy.pdf")

        self.assertEqual(result["stmt_number"], "82231")
        self.assertEqual(result["date_us"], "01/15/2026")
        self.assertEqual(result["hours"], 82)
        self.assertEqual(result["rate"], 90)
        self.assertAlmostEqual(result["total"], 7380.0)
        self.assertIn("January", result["period"])

    def test_total_with_no_decimal(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self.SAMPLE_PDF_TEXT.replace("$7,380", "$6,840")

        with patch("subprocess.run", return_value=mock_result):
            result = mod.parse_invoice_pdf("dummy.pdf")

        self.assertAlmostEqual(result["total"], 6840.0)

    def test_exits_on_missing_required_fields(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Totally empty PDF text"

        with patch("subprocess.run", return_value=mock_result):
            with self.assertRaises(mod.InvoiceError):
                mod.parse_invoice_pdf("dummy.pdf")


class TestFractionalHours(unittest.TestCase):
    """
    ATEAM-82924 is $8,595 = 95.5h × $90. An integer-only hours pattern found
    nothing, fell back to 0 hours, and the invoice had to be voided and redone.
    """

    PDF_TEXT = textwrap.dedent("""\
        Earnings Statement #82924
        Date of issue: 02/05/2026
        SUMMARY FOR PERIOD  February 1 - February 15, 2026
        TOTAL HOURS     95.5h
        HOURLY RATE     $90
        TOTAL PAYMENT   $8,595
    """)

    def _parse(self, text):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = text
        with patch("subprocess.run", return_value=mock):
            return mod.parse_invoice_pdf("dummy.pdf")

    def test_parses_half_hours(self):
        self.assertAlmostEqual(self._parse(self.PDF_TEXT)["hours"], 95.5)

    def test_whole_hours_still_parse(self):
        text = self.PDF_TEXT.replace("95.5h", "95h").replace("$8,595", "$8,550")
        self.assertAlmostEqual(self._parse(text)["hours"], 95.0)

    def test_half_hour_invoice_reconciles(self):
        """95.5 × 90 = 8595 — the guard must let this through, not refuse it."""
        calls = []

        def mock_api(method, path, token, org_id, data=None, extra_params=""):
            calls.append(data)
            return {"code": 0, "invoice": {"invoice_id": "inv_001"}}

        with patch.object(mod, "api", side_effect=mock_api):
            mod.create_invoice("tok", TEST_ORG_ID, TEST_CUSTOMER_ID, "ATEAM-82924",
                               "2026-02-05", 95.5, 90, 8595.0, "Feb 1-15 2026")
        line = calls[0]["line_items"][0]
        self.assertEqual(round(line["rate"] * line["quantity"], 2), 8595.0)

    def test_whole_hours_render_without_a_trailing_zero(self):
        calls = []

        def mock_api(method, path, token, org_id, data=None, extra_params=""):
            calls.append(data)
            return {"code": 0, "invoice": {"invoice_id": "inv_001"}}

        with patch.object(mod, "api", side_effect=mock_api):
            mod.create_invoice("tok", TEST_ORG_ID, TEST_CUSTOMER_ID, "ATEAM-1",
                               "2026-02-05", 82.0, 90, 7380.0, "Feb 2026")
        self.assertIn("82h", calls[0]["line_items"][0]["description"])


class TestExtractPeriod(unittest.TestCase):
    def test_real_layout_takes_value_from_next_line(self):
        """In the actual exports SUMMARY FOR PERIOD is a column header."""
        text = (
            "SUMMARY FOR PERIOD                       FROM                    TO\n"
            "01/01-01/15/2026                         ATeams Inc.             Arboreal Studios, Inc.\n"
            "                                         88 University Place     201 Milwaukee Street\n"
        )
        self.assertEqual(mod.extract_period(text), "01/01-01/15/2026")

    def test_value_on_same_line_is_used_when_present(self):
        text = "SUMMARY FOR PERIOD  January 1 - January 15, 2026\n\nTOTAL HOURS 82h\n"
        self.assertEqual(mod.extract_period(text), "January 1 - January 15, 2026")

    def test_missing_period_is_empty(self):
        self.assertEqual(mod.extract_period("no period here\n"), "")

    def test_never_returns_the_column_headers(self):
        text = "SUMMARY FOR PERIOD   FROM   TO\n02/16-02/28/2026   ATeams Inc.\n"
        self.assertNotIn("FROM", mod.extract_period(text))


class TestIdempotency(unittest.TestCase):
    def test_returns_none_when_not_found(self):
        with patch.object(mod, "api", return_value={"invoices": []}):
            result = mod.find_invoice_by_number("token", TEST_ORG_ID, "INV-99999")
        self.assertIsNone(result)

    def test_returns_invoice_when_found(self):
        existing = {"invoice_id": "abc123", "invoice_number": "INV-82231", "status": "paid"}
        with patch.object(mod, "api", return_value={"invoices": [existing]}):
            result = mod.find_invoice_by_number("token", TEST_ORG_ID, "INV-82231")
        self.assertEqual(result["invoice_id"], "abc123")


class TestLoadEnv(unittest.TestCase):
    def test_env_vars_take_precedence(self):
        with patch.dict(os.environ, {
            "ZOHO_CLIENT_ID": "env_client_id",
            "ZOHO_CLIENT_SECRET": "env_secret",
            "ZOHO_REFRESH_TOKEN": "env_token",
            "ZOHO_ORG_ID": "env_org",
            "ZOHO_CUSTOMER_ID": "env_customer",
            "ZOHO_BANK_ACCOUNT_ID": "env_bank",
        }):
            env = mod.load_env()

        self.assertEqual(env["ZOHO_CLIENT_ID"], "env_client_id")
        self.assertEqual(env["ZOHO_ORG_ID"], "env_org")

    def test_falls_back_to_env_file(self):
        import tempfile
        env_content = (
            "ZOHO_CLIENT_ID=file_client\nZOHO_CLIENT_SECRET=file_secret\n"
            "ZOHO_REFRESH_TOKEN=file_token\nZOHO_ORG_ID=file_org\n"
            "ZOHO_CUSTOMER_ID=file_customer\nZOHO_BANK_ACCOUNT_ID=file_bank\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(env_content)
            env_path = f.name

        try:
            clean_env = {k: v for k, v in os.environ.items()
                         if k not in mod.ZOHO_KEYS}
            with patch.dict(os.environ, clean_env, clear=True):
                env = mod.load_env(env_file=env_path)
        finally:
            os.unlink(env_path)

        self.assertEqual(env["ZOHO_CLIENT_ID"], "file_client")
        self.assertEqual(env["ZOHO_CUSTOMER_ID"], "file_customer")

    def test_env_var_overrides_file(self):
        import tempfile
        env_content = (
            "ZOHO_CLIENT_ID=file_client\nZOHO_CLIENT_SECRET=file_secret\n"
            "ZOHO_REFRESH_TOKEN=file_token\nZOHO_ORG_ID=file_org\n"
            "ZOHO_CUSTOMER_ID=file_customer\nZOHO_BANK_ACCOUNT_ID=file_bank\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(env_content)
            env_path = f.name

        try:
            with patch.dict(os.environ, {"ZOHO_CLIENT_ID": "env_wins"}):
                env = mod.load_env(env_file=env_path)
        finally:
            os.unlink(env_path)

        self.assertEqual(env["ZOHO_CLIENT_ID"], "env_wins")


class TestDiscrepancyDetection(unittest.TestCase):
    SAMPLE_PDF_TEXT = textwrap.dedent("""\
        Earnings Statement #82231
        Date of issue: 01/15/2026
        SUMMARY FOR PERIOD  January 1 – January 15, 2026
        TOTAL HOURS     74h
        HOURLY RATE     $90
        TOTAL PAYMENT   $7,380
    """)

    def test_dry_run_warns_on_mismatch(self):
        """74h × $90 = $6,660 but PDF says $7,380 — should flag mismatch."""
        import tempfile
        from io import StringIO

        mock_pdf = MagicMock()
        mock_pdf.returncode = 0
        mock_pdf.stdout = self.SAMPLE_PDF_TEXT

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Type", "Task", "Initiative", "Hours"])
            writer.writeheader()
            writer.writerow({"Date": "2026-01-01", "Type": "Work", "Task": "x", "Initiative": "x", "Hours": "74:00"})
            csv_name = f.name

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_name = f.name

        captured = StringIO()
        try:
            with patch("subprocess.run", return_value=mock_pdf), \
                 patch.object(mod, "load_env", return_value=TEST_ENV), \
                 patch.object(mod, "get_access_token", return_value="tok"), \
                 patch("sys.stdout", captured), \
                 patch("sys.argv", ["zoho-ateam-invoice", "--csv", csv_name, pdf_name, "--dry-run"]):
                with self.assertRaises(SystemExit):
                    mod.main()
        finally:
            os.unlink(csv_name)
            os.unlink(pdf_name)

        output = captured.getvalue()
        self.assertIn("mismatch", output.lower())
        self.assertIn("7,380", output)

    def test_dry_run_no_warn_when_match(self):
        """82h × $90 = $7,380 — no mismatch warning."""
        import tempfile
        from io import StringIO

        pdf_text = self.SAMPLE_PDF_TEXT.replace("TOTAL HOURS     74h", "TOTAL HOURS     82h")
        mock_pdf = MagicMock()
        mock_pdf.returncode = 0
        mock_pdf.stdout = pdf_text

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Type", "Task", "Initiative", "Hours"])
            writer.writeheader()
            writer.writerow({"Date": "2026-01-01", "Type": "Work", "Task": "x", "Initiative": "x", "Hours": "82:00"})
            csv_name = f.name

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_name = f.name

        captured = StringIO()
        try:
            with patch("subprocess.run", return_value=mock_pdf), \
                 patch.object(mod, "load_env", return_value=TEST_ENV), \
                 patch.object(mod, "get_access_token", return_value="tok"), \
                 patch("sys.stdout", captured), \
                 patch("sys.argv", ["zoho-ateam-invoice", "--csv", csv_name, pdf_name, "--dry-run"]):
                mod.main()
        finally:
            os.unlink(csv_name)
            os.unlink(pdf_name)

        self.assertNotIn("mismatch", captured.getvalue().lower())


class TestCreateInvoicePayload(unittest.TestCase):
    def test_invoice_payload_structure(self):
        calls = []

        def mock_api(method, path, token, org_id, data=None, extra_params=""):
            calls.append({"method": method, "path": path, "data": data,
                          "org_id": org_id, "params": extra_params})
            return {"code": 0, "invoice": {"invoice_id": "inv_001"}}

        with patch.object(mod, "api", side_effect=mock_api):
            invoice_id = mod.create_invoice(
                "tok", TEST_ORG_ID, TEST_CUSTOMER_ID,
                "INV-82231", "2026-01-15", 82, 90, 7380.0, "Jan 1–15 2026"
            )

        self.assertEqual(invoice_id, "inv_001")
        call = calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["org_id"], TEST_ORG_ID)
        self.assertIn("ignore_auto_number_generation=true", call["params"])
        payload = call["data"]
        self.assertEqual(payload["invoice_number"], "INV-82231")
        self.assertEqual(payload["customer_id"], TEST_CUSTOMER_ID)
        self.assertEqual(len(payload["line_items"]), 1)
        self.assertEqual(payload["line_items"][0]["quantity"], 82)

    def test_org_id_used_in_api_call(self):
        """Verifies ZOHO_ORG_ID from env is passed through — not a hardcoded constant."""
        calls = []

        def mock_api(method, path, token, org_id, data=None, extra_params=""):
            calls.append({"org_id": org_id})
            return {"code": 0, "invoice": {"invoice_id": "inv_001"}}

        with patch.object(mod, "api", side_effect=mock_api):
            mod.create_invoice("tok", "my_custom_org", TEST_CUSTOMER_ID,
                               "INV-1", "2026-01-15", 10, 90, 900.0, "Jan 2026")

        self.assertEqual(calls[0]["org_id"], "my_custom_org")


class TestRecordPayment(unittest.TestCase):
    def test_payment_routed_to_correct_account(self):
        calls = []

        def mock_api(method, path, token, org_id, data=None, extra_params=""):
            calls.append({"data": data, "org_id": org_id})
            return {"code": 0}

        with patch.object(mod, "api", side_effect=mock_api):
            mod.record_payment("tok", TEST_ORG_ID, TEST_CUSTOMER_ID,
                               TEST_BANK_ACCOUNT_ID, "inv_001", 7380.0, "2026-01-15")

        data = calls[0]["data"]
        self.assertEqual(data["account_id"], TEST_BANK_ACCOUNT_ID)
        self.assertEqual(data["customer_id"], TEST_CUSTOMER_ID)
        self.assertAlmostEqual(data["amount"], 7380.0)
        self.assertEqual(data["invoices"][0]["invoice_id"], "inv_001")
        self.assertEqual(calls[0]["org_id"], TEST_ORG_ID)


class TestCsvOptional(unittest.TestCase):
    SAMPLE_PDF_TEXT = textwrap.dedent("""\
        Earnings Statement #82231
        Date of issue: 01/15/2026
        SUMMARY FOR PERIOD  January 1 – January 15, 2026
        TOTAL HOURS     82h
        HOURLY RATE     $90
        TOTAL PAYMENT   $7,380
    """)

    def test_dry_run_without_csv_succeeds(self):
        import tempfile
        from io import StringIO

        mock_pdf = MagicMock()
        mock_pdf.returncode = 0
        mock_pdf.stdout = self.SAMPLE_PDF_TEXT

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_name = f.name

        captured = StringIO()
        try:
            with patch("subprocess.run", return_value=mock_pdf), \
                 patch.object(mod, "load_env", return_value=TEST_ENV), \
                 patch.object(mod, "get_access_token", return_value="tok"), \
                 patch("sys.stdout", captured), \
                 patch("sys.argv", ["zoho-ateam-invoice", pdf_name, "--dry-run"]):
                mod.main()
        finally:
            os.unlink(pdf_name)

        output = captured.getvalue()
        self.assertNotIn("mismatch", output.lower())
        self.assertIn("7,380", output)
        self.assertIn("dry-run", output.lower())

    def test_csv_still_triggers_mismatch_when_provided(self):
        import tempfile
        from io import StringIO

        mock_pdf = MagicMock()
        mock_pdf.returncode = 0
        mock_pdf.stdout = self.SAMPLE_PDF_TEXT

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date", "Type", "Task", "Initiative", "Hours"])
            writer.writeheader()
            writer.writerow({"Date": "2026-01-01", "Type": "Work", "Task": "x", "Initiative": "x", "Hours": "74:00"})
            csv_name = f.name

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_name = f.name

        captured = StringIO()
        try:
            with patch("subprocess.run", return_value=mock_pdf), \
                 patch.object(mod, "load_env", return_value=TEST_ENV), \
                 patch.object(mod, "get_access_token", return_value="tok"), \
                 patch("sys.stdout", captured), \
                 patch("sys.argv", ["zoho-ateam-invoice", "--csv", csv_name, pdf_name, "--dry-run"]):
                mod.main()
        finally:
            os.unlink(csv_name)
            os.unlink(pdf_name)

        self.assertIn("mismatch", captured.getvalue().lower())


class TestInvoiceTotalGuard(unittest.TestCase):
    """The invoice raised and the payment recorded must be the same number."""

    def _mock_api(self, calls):
        def mock_api(method, path, token, org_id, data=None, extra_params=""):
            calls.append(data)
            return {"code": 0, "invoice": {"invoice_id": "inv_001"}}
        return mock_api

    def test_refuses_when_hours_times_rate_disagrees_with_total(self):
        calls = []
        with patch.object(mod, "api", side_effect=self._mock_api(calls)):
            with self.assertRaises(mod.InvoiceError):
                # 74h × $90 = $6,660, but the PDF says $7,380.
                mod.create_invoice("tok", TEST_ORG_ID, TEST_CUSTOMER_ID,
                                   "INV-82231", "2026-01-15", 74, 90, 7380.0, "Jan 2026")
        self.assertEqual(calls, [], "no invoice should be POSTed when totals disagree")

    def test_refuses_when_hours_missing_defaults_to_zero(self):
        """A PDF with no TOTAL HOURS line must not book a $0 invoice with a full payment."""
        calls = []
        with patch.object(mod, "api", side_effect=self._mock_api(calls)):
            with self.assertRaises(mod.InvoiceError):
                mod.create_invoice("tok", TEST_ORG_ID, TEST_CUSTOMER_ID,
                                   "INV-82231", "2026-01-15", 0, 90, 7380.0, "Jan 2026")
        self.assertEqual(calls, [])

    def test_creates_when_totals_agree(self):
        calls = []
        with patch.object(mod, "api", side_effect=self._mock_api(calls)):
            mod.create_invoice("tok", TEST_ORG_ID, TEST_CUSTOMER_ID,
                               "INV-82231", "2026-01-15", 82, 90, 7380.0, "Jan 2026")
        line = calls[0]["line_items"][0]
        self.assertEqual(round(line["rate"] * line["quantity"], 2), 7380.0)

    def test_dry_run_flags_what_the_real_run_would_refuse(self):
        import tempfile
        from io import StringIO

        mock_pdf = MagicMock()
        mock_pdf.returncode = 0
        mock_pdf.stdout = textwrap.dedent("""\
            Earnings Statement #82231
            Date of issue: 01/15/2026
            SUMMARY FOR PERIOD  January 1 – January 15, 2026
            TOTAL HOURS     74h
            HOURLY RATE     $90
            TOTAL PAYMENT   $7,380
        """)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_name = f.name

        captured = StringIO()
        try:
            with patch("subprocess.run", return_value=mock_pdf), \
                 patch.object(mod, "load_env", return_value=TEST_ENV), \
                 patch("sys.stdout", captured), \
                 patch("sys.argv", ["zoho-ateam-invoice", pdf_name, "--dry-run"]):
                # A blocked invoice makes the run exit non-zero.
                with self.assertRaises(SystemExit):
                    mod.main()
        finally:
            os.unlink(pdf_name)

        self.assertIn("will refuse", captured.getvalue().lower())

    def test_dry_run_needs_no_network(self):
        """A dry run parses only — it must not reach for an access token."""
        import tempfile
        from io import StringIO

        mock_pdf = MagicMock()
        mock_pdf.returncode = 0
        mock_pdf.stdout = TestCsvOptional.SAMPLE_PDF_TEXT

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_name = f.name

        def explode(env):
            raise AssertionError("dry run must not request an access token")

        try:
            with patch("subprocess.run", return_value=mock_pdf), \
                 patch.object(mod, "load_env", return_value=TEST_ENV), \
                 patch.object(mod, "get_access_token", side_effect=explode), \
                 patch("sys.stdout", StringIO()), \
                 patch("sys.argv", ["zoho-ateam-invoice", pdf_name, "--dry-run"]):
                mod.main()
        finally:
            os.unlink(pdf_name)


class TestIdempotencyExactMatch(unittest.TestCase):
    def test_ignores_substring_matches(self):
        """Zoho's invoice_number filter matches substrings; INV-812 must not match INV-81212."""
        with patch.object(mod, "api", return_value={"invoices": [
            {"invoice_id": "abc", "invoice_number": "INV-81212", "status": "paid"},
        ]}):
            self.assertIsNone(mod.find_invoice_by_number("tok", TEST_ORG_ID, "INV-812"))

    def test_picks_exact_match_from_several(self):
        with patch.object(mod, "api", return_value={"invoices": [
            {"invoice_id": "abc", "invoice_number": "INV-81212", "status": "paid"},
            {"invoice_id": "xyz", "invoice_number": "INV-812", "status": "sent"},
        ]}):
            found = mod.find_invoice_by_number("tok", TEST_ORG_ID, "INV-812")
        self.assertEqual(found["invoice_id"], "xyz")


class TestEnvFileMerging(unittest.TestCase):
    def test_later_files_fill_gaps_left_by_earlier_ones(self):
        """An unrelated ~/.env must not shadow ~/.openclaw/.env entirely."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("ZOHO_CLIENT_ID=from_first\n")
            first = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("ZOHO_CLIENT_ID=from_second\nZOHO_ORG_ID=from_second\n")
            second = f.name

        try:
            clean = {k: v for k, v in os.environ.items() if not k.startswith("ZOHO_")}
            with patch.dict(os.environ, clean, clear=True), \
                 patch.object(mod, "_DEFAULT_ENV_PATHS", [second]):
                env = mod.load_env(env_file=first)
        finally:
            os.unlink(first)
            os.unlink(second)

        self.assertEqual(env["ZOHO_CLIENT_ID"], "from_first", "earlier file wins on conflict")
        self.assertEqual(env["ZOHO_ORG_ID"], "from_second", "later file fills the gap")

    def test_strips_quotes_around_values(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('ZOHO_CLIENT_ID="quoted_id"\nZOHO_ORG_ID=\'single\'\n')
            path = f.name

        try:
            clean = {k: v for k, v in os.environ.items() if not k.startswith("ZOHO_")}
            with patch.dict(os.environ, clean, clear=True):
                env = mod.load_env(env_file=path)
        finally:
            os.unlink(path)

        self.assertEqual(env["ZOHO_CLIENT_ID"], "quoted_id")
        self.assertEqual(env["ZOHO_ORG_ID"], "single")


class TestPeriodKey(unittest.TestCase):
    """Real A.Team export filenames — the two formats don't share a stem."""

    def test_invoice_pdf_format(self):
        self.assertEqual(
            mod.period_key("A.Team Invoice - 2026 Jan. 01-15 (82231).pdf"),
            ("jan", 1, 15))

    def test_timesheet_csv_format(self):
        self.assertEqual(
            mod.period_key("Dylan Fitzgerald's Timesheet - Jan 1 - Jan 15.csv"),
            ("jan", 1, 15))

    def test_second_half_of_month(self):
        self.assertEqual(
            mod.period_key("A.Team Invoice - 2025 Dec. 16-31 (81706).pdf"),
            ("dec", 16, 31))
        self.assertEqual(
            mod.period_key("Dylan Fitzgerald's Timesheet - Dec 16 - Dec 31.csv"),
            ("dec", 16, 31))

    def test_unrelated_file_has_no_period(self):
        self.assertIsNone(mod.period_key("BankStatement1130200222.pdf"))
        self.assertIsNone(mod.period_key("Azlo Statement November 2020.pdf"))


class TestPairCsvs(unittest.TestCase):
    def test_pairs_matching_periods(self):
        pdfs = ["A.Team Invoice - 2026 Jan. 01-15 (82231).pdf",
                "A.Team Invoice - 2025 Nov. 16-30 (80962).pdf"]
        csvs = ["Dylan Fitzgerald's Timesheet - Jan 1 - Jan 15.csv",
                "Dylan Fitzgerald's Timesheet - Nov 16 - Nov 30.csv"]
        pairs, ambiguous = mod.pair_csvs(pdfs, csvs)
        self.assertEqual(pairs[pdfs[0]], csvs[0])
        self.assertEqual(pairs[pdfs[1]], csvs[1])
        self.assertEqual(ambiguous, [])

    def test_refuses_when_two_years_share_a_period(self):
        """Timesheet names carry no year, so Dec 16-31 can't be attributed."""
        pdfs = ["A.Team Invoice - 2025 Dec. 16-31 (81706).pdf",
                "A.Team Invoice - 2026 Dec. 16-31 (99999).pdf"]
        csvs = ["Dylan Fitzgerald's Timesheet - Dec 16 - Dec 31.csv"]
        pairs, ambiguous = mod.pair_csvs(pdfs, csvs)
        self.assertEqual(pairs, {}, "must not guess which year the timesheet covers")
        self.assertCountEqual(ambiguous, pdfs)

    def test_unmatched_pdf_is_not_ambiguous(self):
        pdfs = ["A.Team Invoice - 2026 Jan. 01-15 (82231).pdf"]
        pairs, ambiguous = mod.pair_csvs(pdfs, [])
        self.assertEqual((pairs, ambiguous), ({}, []))

    def test_ignores_unrelated_csvs(self):
        pdfs = ["A.Team Invoice - 2026 Jan. 01-15 (82231).pdf"]
        csvs = ["TaxStatement_2023_1099B_DIV_268011228819193.csv"]
        pairs, ambiguous = mod.pair_csvs(pdfs, csvs)
        self.assertEqual((pairs, ambiguous), ({}, []))


class TestCollectPdfs(unittest.TestCase):
    def test_expands_directory_and_ignores_other_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for name in ["b.pdf", "a.pdf", "notes.txt", "sheet.csv", "c.PDF"]:
                open(os.path.join(d, name), "w").close()
            found = mod.collect_pdfs([d])
        self.assertEqual([os.path.basename(f) for f in found], ["a.pdf", "b.pdf", "c.PDF"])

    def test_passes_explicit_files_through(self):
        self.assertEqual(mod.collect_pdfs(["one.pdf", "two.pdf"]), ["one.pdf", "two.pdf"])


class TestBatchRun(unittest.TestCase):
    PDF_TEXT = textwrap.dedent("""\
        Earnings Statement #{n}
        Date of issue: 01/15/2026
        SUMMARY FOR PERIOD  January 1 – January 15, 2026
        TOTAL HOURS     {h}h
        HOURLY RATE     $90
        TOTAL PAYMENT   ${t}
    """)

    def _run(self, pdf_texts):
        """Run a directory batch; returns (stdout, exit_code)."""
        import tempfile
        from io import StringIO

        d = tempfile.mkdtemp()
        for name in pdf_texts:
            open(os.path.join(d, name), "w").close()

        def fake_pdftotext(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = pdf_texts[os.path.basename(cmd[-2])]
            return r

        captured = StringIO()
        code = 0
        with patch("subprocess.run", side_effect=fake_pdftotext), \
             patch.object(mod, "load_env", return_value=TEST_ENV), \
             patch("sys.stdout", captured), \
             patch("sys.argv", ["zoho-ateam-invoice", d, "--dry-run"]):
            try:
                mod.main()
            except SystemExit as e:
                code = e.code
        return captured.getvalue(), code

    def test_one_bad_export_does_not_strand_the_batch(self):
        out, code = self._run({
            "A.Team Invoice - 2026 Jan. 01-15 (82231).pdf": self.PDF_TEXT.format(n=82231, h=82, t="7,380"),
            "A.Team Invoice - 2026 Feb. 01-15 (82999).pdf": self.PDF_TEXT.format(n=82999, h=74, t="7,380"),
            "A.Team Invoice - 2026 Mar. 01-15 (83111).pdf": self.PDF_TEXT.format(n=83111, h=10, t="900"),
        })
        # The middle PDF is internally inconsistent; the other two still process.
        self.assertIn("would create: 2", out)
        self.assertIn("blocked: 1", out)
        self.assertIn("82999", out)
        self.assertEqual(code, 1, "a blocked invoice must fail the run")

    def test_unrelated_pdf_in_folder_is_ignored_not_failed(self):
        """~/Downloads is full of bank statements; they must not fail the run."""
        out, code = self._run({
            "A.Team Invoice - 2026 Jan. 01-15 (82231).pdf": self.PDF_TEXT.format(n=82231, h=82, t="7,380"),
            "BankStatement1130200222.pdf": "not an earnings statement at all",
        })
        self.assertIn("would create: 1", out)
        self.assertIn("failed: 0", out)
        self.assertIn("ignored 1", out)
        self.assertNotIn("BankStatement", out, "no per-file noise for unrelated PDFs")
        self.assertEqual(code, 0)

    def test_damaged_invoice_export_is_a_failure(self):
        """Some markers present means it IS an export — and we couldn't read it."""
        out, code = self._run({
            "A.Team Invoice - 2026 Jan. 01-15 (82231).pdf": self.PDF_TEXT.format(n=82231, h=82, t="7,380"),
            "A.Team Invoice - 2026 Feb. 01-15 (82999).pdf": "Earnings Statement #82999\n(rest of the page is garbled)",
        })
        self.assertIn("would create: 1", out)
        self.assertIn("failed: 1", out)
        self.assertEqual(code, 1)

    def test_dry_run_batch_needs_no_token(self):
        def explode(env):
            raise AssertionError("dry run must not request an access token")

        with patch.object(mod, "get_access_token", side_effect=explode):
            out, code = self._run({
                "A.Team Invoice - 2026 Jan. 01-15 (82231).pdf": self.PDF_TEXT.format(n=82231, h=82, t="7,380"),
            })
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
