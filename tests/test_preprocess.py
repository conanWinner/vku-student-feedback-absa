import unicodedata
import unittest

from absa.preprocess import normalize, preprocess


class PreprocessTest(unittest.TestCase):
    def test_normalize_matches_notebook_rules(self):
        self.assertEqual(normalize(" . - Thầy dạy hay ."), "Thầy dạy hay .")
        decomposed = unicodedata.normalize("NFD", "giảng viên")
        self.assertEqual(normalize(decomposed), unicodedata.normalize("NFC", "giảng viên"))

    def test_raw_mode_does_not_segment(self):
        self.assertEqual(preprocess("giảng viên dạy hay .", "raw"), "giảng viên dạy hay .")

    def test_underthesea_mode_joins_compound_words(self):
        self.assertIn("giảng_viên", preprocess("giảng viên dạy hay .", "underthesea"))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            preprocess("a", "khong_co")


if __name__ == "__main__":
    unittest.main()
