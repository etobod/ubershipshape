"""CLI tests for skills/ush-advice/scripts/advice.py (plan 103, M1): a products file
without the map and ``--detail`` with an unknown id.

The interface is described in ``fakes.py``. PowerShell never starts; every value is
invented.
"""

import json
import unittest
from unittest import mock

from .fakes import AdviceTestCase, FakePowerShell, machine_touched


class TestCli(AdviceTestCase):
    def test_bad_data_and_detail(self):
        with self.subTest("products.json without the products map"):
            products = self.temp_file(
                "products.json",
                json.dumps({"version": 1, "items": {"25H2|AMD64": "Invented product"}}),
            )
            fake = FakePowerShell()
            with mock.patch.object(self.advice, "PRODUCTS_FILE", products):
                code, stdout, stderr = self.run_main(self.data_dir(), fake)
            self.assertEqual(code, 2, stdout[:300])
            self.assertTrue(stderr.strip(), "no message on stderr")
            self.assertEqual(fake.calls, [])

        with self.subTest("--detail with an unknown id"):
            data_dir = self.data_dir()
            self.collect(FakePowerShell(), data_dir=data_dir)
            code, stdout, stderr = self.run_main(data_dir, machine_touched,
                                                 extra=["--detail", "x99"])
            self.assertEqual(code, 1, stdout[:300])


if __name__ == "__main__":
    unittest.main()
