import unittest

from syncode.parsers import create_base_parser
from syncode.parsers.c_parser import CParser
from syncode.parsers.grammars import Grammar


class TestCParser(unittest.TestCase):
    def setUp(self):
        base_parser = create_base_parser(Grammar("c"), cache_filename=None)
        self.parser = CParser(base_parser)

    def test_typedef_name_is_classified_after_declaration(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int Value; Value item;"
        )

        self.assertIn("Value", self.parser.type_names)
        value_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Value"
        ]
        self.assertEqual(value_tokens, ["IDENTIFIER", "TYPE_NAME"])

    def test_typedef_with_struct_body_registers_name_at_outer_semicolon(self):
        self.parser.get_acceptable_next_terminals(
            "typedef struct Value { int member; } Value; Value item;"
        )

        self.assertIn("Value", self.parser.type_names)
        value_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Value"
        ]
        self.assertEqual(value_tokens, ["IDENTIFIER", "IDENTIFIER", "TYPE_NAME"])

    def test_existing_typedef_is_classified_in_anonymous_struct_body(self):
        self.parser.get_acceptable_next_terminals(
            "typedef unsigned char Byte; typedef Byte Octet; "
            "typedef struct { Octet data[8]; unsigned int length; } Buffer;"
        )

        self.assertIn("Buffer", self.parser.type_names)
        octet_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Octet"
        ]
        self.assertEqual(octet_tokens, ["IDENTIFIER", "TYPE_NAME"])

    def test_function_pointer_typedef_does_not_register_parameter_name(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int (*Callback)(int argument); Callback callback;"
        )

        self.assertIn("Callback", self.parser.type_names)
        self.assertNotIn("argument", self.parser.type_names)

    def test_function_typedef_does_not_register_parameter_name(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int Handler(int context); Handler handler;"
        )

        self.assertIn("Handler", self.parser.type_names)
        self.assertNotIn("context", self.parser.type_names)

    def test_multiple_typedef_declarators_are_registered(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int Value, *ValuePtr, Values[4]; "
            "Value value; ValuePtr pointer; Values array;"
        )

        self.assertTrue({"Value", "ValuePtr", "Values"} <= self.parser.type_names)
        for name in ("Value", "ValuePtr", "Values"):
            token_types = [
                token.type
                for token in self.parser.parsed_lexer_tokens
                if token.value == name
            ]
            self.assertEqual(
                token_types,
                ["IDENTIFIER", "TYPE_NAME"],
                msg=name,
            )

    def test_existing_typedef_can_be_used_as_a_base_type(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int Base; typedef Base Alias; Alias item;"
        )

        self.assertTrue({"Base", "Alias"} <= self.parser.type_names)
        alias_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Alias"
        ]
        self.assertEqual(alias_tokens, ["IDENTIFIER", "TYPE_NAME"])

    def test_struct_tag_keeps_identifier_classification_when_name_is_a_typedef(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int Tag; typedef struct Tag Alias; "
            "Alias value; struct Tag other;"
        )

        self.assertIn("Alias", self.parser.type_names)
        tag_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Tag"
        ]
        self.assertEqual(tag_tokens, ["IDENTIFIER", "IDENTIFIER", "IDENTIFIER"])

    def test_enum_members_are_not_registered_as_typedef_names(self):
        self.parser.get_acceptable_next_terminals(
            "typedef enum Color { RED, GREEN } Color; Color item;"
        )

        self.assertIn("Color", self.parser.type_names)
        self.assertNotIn("RED", self.parser.type_names)
        self.assertNotIn("GREEN", self.parser.type_names)

    def test_typedef_names_are_restored_when_input_prefix_changes(self):
        self.parser.get_acceptable_next_terminals("typedef int OldName;")
        self.parser.get_acceptable_next_terminals(
            "typedef int NewName; NewName item;"
        )

        self.assertNotIn("OldName", self.parser.type_names)
        self.assertIn("NewName", self.parser.type_names)

    def test_cached_prefix_restores_typedef_state(self):
        self.parser.get_acceptable_next_terminals("typedef int Value;")
        self.parser.get_acceptable_next_terminals(
            "typedef int Value; Value item;"
        )

        self.assertIn("Value", self.parser.type_names)
        value_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Value"
        ]
        self.assertEqual(value_tokens, ["IDENTIFIER", "TYPE_NAME"])

    def test_cached_prefix_inside_struct_typedef_restores_brace_state(self):
        prefix = "typedef struct Value { int member;"
        self.parser.get_acceptable_next_terminals(prefix)
        self.parser.get_acceptable_next_terminals(
            prefix + " } Value; Value item;"
        )

        self.assertIn("Value", self.parser.type_names)
        value_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Value"
        ]
        self.assertEqual(value_tokens, ["IDENTIFIER", "IDENTIFIER", "TYPE_NAME"])

    def test_reset_clears_cached_typedef_state(self):
        self.parser.get_acceptable_next_terminals("typedef int Value;")
        self.parser.reset()
        self.parser.get_acceptable_next_terminals("int Value;")

        self.assertNotIn("Value", self.parser.type_names)
        value_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Value"
        ]
        self.assertEqual(value_tokens, ["IDENTIFIER"])

if __name__ == "__main__":
    unittest.main()
