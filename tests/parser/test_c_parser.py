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

    def test_local_typedef_expires_after_block(self):
        self.parser.get_acceptable_next_terminals(
            "void f(void) { typedef int Local; Local inside; }"
        )

        local_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Local"
        ]

        self.assertEqual(local_tokens, ["IDENTIFIER", "TYPE_NAME"])
        self.assertNotIn("Local", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_expired_typedef_cannot_be_used_outside_block(self):
        from syncode.larkm.exceptions import UnexpectedToken

        with self.assertRaises(UnexpectedToken):
            self.parser.get_acceptable_next_terminals(
                "void f(void) { typedef int Local; } Local outside;"
            )

    def test_outer_typedef_survives_inner_block(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int Outer; "
            "void f(void) { typedef int Local; Local inside; } "
            "Outer outside;"
        )

        self.assertIn("Outer", self.parser.type_names)
        self.assertNotIn("Local", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_cached_prefix_preserves_local_scope(self):
        prefix = "void f(void) { typedef int Local;"

        self.parser.get_acceptable_next_terminals(prefix)

        self.assertIn("Local", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 2)

        self.parser.get_acceptable_next_terminals(
            prefix + " Local inside; }"
        )

        local_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Local"
        ]

        self.assertEqual(local_tokens, ["IDENTIFIER", "TYPE_NAME"])
        self.assertNotIn("Local", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_backtracking_restores_local_scope(self):
        prefix = "void f(void) { typedef int Local;"

        self.parser.get_acceptable_next_terminals(
            prefix + " Local first; }"
        )

        self.assertNotIn("Local", self.parser.type_names)

        self.parser.get_acceptable_next_terminals(prefix)

        self.assertIn("Local", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 2)

        self.parser.get_acceptable_next_terminals(
            prefix + " Local second; }"
        )

        local_tokens = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "Local"
        ]

        self.assertEqual(local_tokens, ["IDENTIFIER", "TYPE_NAME"])
        self.assertNotIn("Local", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_local_variable_shadows_outer_typedef(self):
        prefix = "typedef int T; void f(void) { int T;"

        self.parser.get_acceptable_next_terminals(prefix)

        self.assertNotIn("T", self.parser.type_names)
        self.assertEqual(self.parser.state.scopes[-1]["T"], "ordinary")

        self.parser.get_acceptable_next_terminals(
            prefix + " T = 1; } T outside;"
        )

        token_types = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "T"
        ]

        self.assertEqual(
            token_types,
            ["IDENTIFIER", "IDENTIFIER", "IDENTIFIER", "TYPE_NAME"],
        )
        self.assertIn("T", self.parser.type_names)

    def test_typedef_can_declare_same_named_local_variable(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int T; "
            "void f(void) { T T; T = 1; } "
            "T outside;"
        )

        token_types = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "T"
        ]

        self.assertEqual(
            token_types,
            [
                "IDENTIFIER",
                "TYPE_NAME",
                "IDENTIFIER",
                "IDENTIFIER",
                "TYPE_NAME",
            ],
        )
        self.assertIn("T", self.parser.type_names)

    def test_for_scope_restores_outer_typedef(self):
        bodies = {
            "unbraced": "T++;",
            "braced": "{ T++; }",
            "nested": (
                "{ for (int T = 0; T < 2; T++) T++; T++; }"
            ),
            "if_else": "if (T) T++; else T--;",
        }

        for label, body in bodies.items():
            with self.subTest(case=label):
                self.parser.reset()

                self.parser.get_acceptable_next_terminals(
                    "typedef int T; void f(void) { "
                    "for (int T = 0; T < 2; T++) "
                    + body
                    + " T after; }"
                )

                token_types = [
                    token.type
                    for token in self.parser.parsed_lexer_tokens
                    if token.value == "T"
                ]

                self.assertEqual(token_types[0], "IDENTIFIER")
                self.assertTrue(
                    all(
                        kind == "IDENTIFIER"
                        for kind in token_types[1:-1]
                    )
                )
                self.assertEqual(token_types[-1], "TYPE_NAME")
                self.assertIn("T", self.parser.type_names)
                self.assertEqual(len(self.parser.state.scopes), 1)

    def test_backtracking_restores_for_scope(self):
        prefix = (
            "typedef int T; void f(void) { "
            "for (int T = 0; T < 2; T++)"
        )

        self.parser.get_acceptable_next_terminals(
            prefix + " T++; T after; }"
        )
        self.assertIn("T", self.parser.type_names)

        self.parser.get_acceptable_next_terminals(prefix)

        self.assertNotIn("T", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 3)
        self.assertEqual(
            self.parser.state.scopes[-1]["T"],
            "ordinary",
        )

        self.parser.get_acceptable_next_terminals(
            prefix + " { T--; } T after; }"
        )

        self.assertIn("T", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_function_parameter_shadows_outer_typedef(self):
        prefix = "typedef int T; void f(int T) {"

        self.parser.get_acceptable_next_terminals(prefix)

        self.assertNotIn("T", self.parser.type_names)
        self.assertEqual(self.parser.state.scopes[-1]["T"], "ordinary")

        self.parser.get_acceptable_next_terminals(
            prefix + " T = 1; } T outside;"
        )

        token_types = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "T"
        ]

        self.assertEqual(
            token_types,
            ["IDENTIFIER", "IDENTIFIER", "IDENTIFIER", "TYPE_NAME"],
        )
        self.assertIn("T", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_prototype_parameter_does_not_hide_outer_typedef(self):
        self.parser.get_acceptable_next_terminals(
            "typedef int T; void f(int T); T outside;"
        )

        token_types = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "T"
        ]

        self.assertEqual(
            token_types,
            ["IDENTIFIER", "IDENTIFIER", "TYPE_NAME"],
        )
        self.assertIn("T", self.parser.type_names)
        self.assertEqual(len(self.parser.state.scopes), 1)

    def test_callback_parameter_names_do_not_enter_function_scope(self):
        prefix = (
            "typedef int T; "
            "void f(int (*callback)(int T)) {"
        )

        self.parser.get_acceptable_next_terminals(prefix)

        self.assertIn("T", self.parser.type_names)
        self.assertEqual(
            self.parser.state.scopes[-1],
            {"callback": "ordinary"},
        )

        self.parser.get_acceptable_next_terminals(
            prefix + " T inside; callback(1); } T outside;"
        )

        token_types = [
            token.type
            for token in self.parser.parsed_lexer_tokens
            if token.value == "T"
        ]

        self.assertEqual(
            token_types,
            ["IDENTIFIER", "IDENTIFIER", "TYPE_NAME", "TYPE_NAME"],
        )

if __name__ == "__main__":
    unittest.main()
