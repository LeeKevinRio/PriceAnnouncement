import unittest

from src.telegram_bot import _MAX_LEN, _split_message


class SplitMessageTest(unittest.TestCase):
    def test_short_message_not_split(self):
        text = "hello world"
        self.assertEqual(_split_message(text), [text])

    def test_exact_limit_not_split(self):
        text = "a" * _MAX_LEN
        self.assertEqual(_split_message(text), [text])

    def test_splits_at_double_newline(self):
        section_a = "A" * 2000
        section_b = "B" * 2000
        section_c = "C" * 2000
        text = f"{section_a}\n\n{section_b}\n\n{section_c}"
        chunks = _split_message(text)
        self.assertGreater(len(chunks), 1)
        # every chunk must stay under the Telegram limit
        for c in chunks:
            self.assertLessEqual(len(c), _MAX_LEN)
        # concatenation (via \n\n) must reproduce the original sections
        rejoined = "\n\n".join(chunks)
        self.assertEqual(rejoined, text)

    def test_splits_at_single_newline_when_no_double(self):
        # Single long block with only single-newline breakpoints
        lines = ["line " + "x" * 500 for _ in range(20)]
        text = "\n".join(lines)
        chunks = _split_message(text)
        for c in chunks:
            self.assertLessEqual(len(c), _MAX_LEN)

    def test_hard_cut_when_no_breakpoints(self):
        # Pathological: one giant unbreakable blob
        text = "x" * (_MAX_LEN * 2 + 100)
        chunks = _split_message(text)
        for c in chunks:
            self.assertLessEqual(len(c), _MAX_LEN)
        self.assertEqual("".join(chunks), text)

    def test_empty_string(self):
        self.assertEqual(_split_message(""), [""])


if __name__ == "__main__":
    unittest.main()
