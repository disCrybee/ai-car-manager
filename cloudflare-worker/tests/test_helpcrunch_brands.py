import unittest
from pathlib import Path
from sys import path

path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from helpcrunch_brands import configured_brands, brand_for_application, brand_instruction


class BrandingTests(unittest.TestCase):
    def test_brand_mapping(self):
        brands = configured_brands('{"101":"Auction Auto","102":"Atlantic Express"}')
        self.assertEqual(brand_for_application("101", brands), "Auction Auto")
        self.assertEqual(brand_for_application(102, brands), "Atlantic Express")
        self.assertIsNone(brand_for_application(999, brands))

    def test_unsafe_config_rejected(self):
        for sample in ('[]', '{"abc":"Auction Auto"}', '{"12":""}'):
            with self.assertRaises(ValueError):
                configured_brands(sample)

    def test_branded_and_unbranded_instructions(self):
        self.assertIn("Atlantic Auto", brand_instruction("Atlantic Auto"))
        self.assertIn("не називай конкретну компанію", brand_instruction(None))


if __name__ == "__main__":
    unittest.main()
