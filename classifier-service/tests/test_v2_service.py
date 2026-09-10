import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
from v2_service import AnalysisError, V2WalletService, validate_ckb_address  # noqa: E402


VALID = "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqg239ffgrtl3mf4m6s02eweangtpe0gy9cph6u05"
LIVE_FIXTURE = "ckb1qyqvkel34xpgrdtja8fddy93fgkp6lduy90q2u385q"


class V2ServiceTests(unittest.TestCase):
    def test_address_validation_rejects_invalid_and_accepts_known_mainnet_address(self):
        self.assertTrue(validate_ckb_address(VALID))
        self.assertTrue(validate_ckb_address(LIVE_FIXTURE))
        self.assertFalse(validate_ckb_address("ckb1not-an-address"))
        self.assertFalse(validate_ckb_address(VALID.upper()))

    def test_live_mode_reports_collection_failure_without_explorer_evidence(self):
        fake_explorer = mock.MagicMock()
        fake_explorer.get_address.return_value = {"data": {"attributes": {}}}
        with patch("v2_service.ExplorerClient", return_value=fake_explorer), \
             self.assertRaisesRegex(AnalysisError, "lock identifier") as raised:
            V2WalletService().analyze(VALID, live=True)
        self.assertEqual(raised.exception.status, "COLLECTION_FAILED")

    def test_live_collection_stops_pagination_at_window_boundary(self):
        fake_explorer = mock.MagicMock()
        fake_explorer.get_address.return_value = {
            "data": [{"attributes": {"lock_script": {
                "code_hash": "0x" + "11" * 32, "hash_type": "data1", "args": "0x"
            }}}]
        }
        fake_explorer.get_address_transactions.return_value = {
            "data": [{"attributes": {"block_timestamp": "1", "transaction_hash": "0xold"}}],
            "meta": {"total": 4000000},
        }
        with patch("v2_service.ExplorerClient", return_value=fake_explorer):
            result = V2WalletService().analyze("ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqg239ffgrtl3mf4m6s02eweangtpe0gy9cph6u05", live=True)
        self.assertEqual(result["evidence"]["transactions"], 0)
        self.assertEqual(fake_explorer.get_address_transactions.call_count, 1)
        fake_explorer.get_transaction.assert_not_called()

    def test_active_service_has_no_legacy_model_dependency(self):
        active = "\n".join((SERVICE_DIR / name).read_text(encoding="utf-8")
                             for name in ("app.py", "v2_service.py", "inference_cli.py"))
        for forbidden in ("inference_service", "model_trainer", "registry_client",
                          "RandomForest", "predict_proba", "joblib.load", "bot_probability"):
            self.assertNotIn(forbidden, active)

    def test_invalid_address_has_stable_status_without_database_access(self):
        with patch("v2_service.sqlite3.connect") as connect:
            with self.assertRaises(AnalysisError) as raised:
                V2WalletService().analyze("ckb1invalid", live=False)
        self.assertEqual(raised.exception.status, "INVALID_ADDRESS")
        connect.assert_not_called()

    def test_frozen_path_delegates_to_authoritative_v2_pipeline(self):
        service = V2WalletService(Path("/tmp/frozen.sqlite"))
        fake_conn = mock.MagicMock()
        fake_conn.execute.side_effect = [
            mock.MagicMock(fetchone=lambda: ("obs-1",)),
            mock.MagicMock(fetchone=lambda: ("COMPLETE",)),
        ]
        fake_observation = {
            "metadata": {"source_version": "test", "window_start_timestamp": 1,
                         "window_end_timestamp": 2},
            "transactions": [],
        }
        fake_result = {"features": {family: {"support_state": "INSUFFICIENT_EVIDENCE"}
                                     for family in ("temporal", "periodicity", "topology", "lifecycle",
                                                    "templates", "scripts", "typed_assets", "capacity", "lineage")},
                      "rules": []}
        with patch("v2_service.sqlite3.connect") as connect, \
             patch("v2_service.load_observation_v2", return_value=fake_observation) as load, \
             patch("v2_service.assess_observation_v2", return_value=fake_result) as assess:
            connect.return_value.__enter__.return_value = fake_conn
            service.db_path = Path(__file__).resolve().parents[2] / "ckb_data/ckb_data_v2/ckb_explorer.sqlite"
            result = service.analyze(VALID)
        load.assert_called_once()
        assess.assert_called_once_with(fake_observation)
        self.assertEqual(result["version"], "wallet-behaviour-v2")
        self.assertNotIn("wallet_type", result)
        self.assertEqual(result["feature_support"]["temporal"], "INSUFFICIENT_EVIDENCE")

    def test_frozen_profile_is_deterministic_after_package_relocation(self):
        service = V2WalletService()
        first = service.analyze(VALID)
        second = service.analyze(VALID)
        self.assertEqual(first, second)
        self.assertEqual(first["version"], "wallet-behaviour-v2")
        self.assertEqual(len(first["behaviors"]), 12)


if __name__ == "__main__":
    unittest.main()
