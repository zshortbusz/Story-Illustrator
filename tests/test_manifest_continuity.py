import unittest
from pipeline.build_manifest import match_bible_entity

class TestManifestContinuity(unittest.TestCase):
    def setUp(self):
        self.bible_chars = {
            'Kaelen': 'tall athletic man in his 20s, scarred cheek, brass mechanical left arm with visible gears and rotary wrist joint, tattered canvas duster coat',
            'Lyra': 'slender pilot, blonde hair tied back, aviator goggles, flight jacket'
        }
        self.bible_settings = {
            'The Rust Catwalks': 'towers of decaying iron girders, swaying cables, dense industrial fog, flying electrical sparks',
            'The Crane Cabin': 'cramped operator cabin, cracked glass, dust dancing in sunlight, old console'
        }

    def test_match_exact_case_insensitive(self):
        matched = match_bible_entity('kaelen', self.bible_chars)
        self.assertIsNotNone(matched)
        name, desc = matched
        self.assertEqual(name, 'Kaelen')
        self.assertIn('brass mechanical left arm', desc)

    def test_match_substring(self):
        matched = match_bible_entity('Catwalks', self.bible_settings)
        self.assertIsNotNone(matched)
        name, desc = matched
        self.assertEqual(name, 'The Rust Catwalks')
        self.assertIn('decaying iron girders', desc)

    def test_match_token_overlap(self):
        matched = match_bible_entity('Crane Cabin Interior', self.bible_settings)
        self.assertIsNotNone(matched)
        name, desc = matched
        self.assertEqual(name, 'The Crane Cabin')
        self.assertIn('cracked glass', desc)

    def test_match_unknown_entity(self):
        matched = match_bible_entity('Unknown Wanderer', self.bible_chars)
        self.assertIsNone(matched)

if __name__ == '__main__':
    unittest.main()
