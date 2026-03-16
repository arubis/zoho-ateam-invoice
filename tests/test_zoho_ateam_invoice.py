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
            with self.assertRaises(SystemExit):
                mod.parse_invoice_pdf("dummy.pdf")


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


if __name__ == "__main__":
    unittest.main()
