import unittest

from syncode.parsers import create_base_parser
from syncode.parsers.grammars import Grammar


class TestCPostLex(unittest.TestCase):
    def test_postlex_state_does_not_leak_between_streams(self):
        base_parser = create_base_parser(Grammar("c"), cache_filename=None)
        list(base_parser.lex("typedef int Value;"))
        tokens = list(base_parser.lex("Value item;"))

        value_tokens = [token.type for token in tokens if token.value == "Value"]
        self.assertEqual(value_tokens, ["IDENTIFIER"])


if __name__ == "__main__":
    unittest.main()
