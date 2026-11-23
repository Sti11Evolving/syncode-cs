from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set

from syncode.larkm.lexer import Token
from syncode.larkm.lark import PostLex


@dataclass
class CPostLexState:
    type_names: Set[str] = field(default_factory=set)
    pending_type_names: Set[str] = field(default_factory=set)
    in_typedef_declaration: bool = False
    typedef_brace_depth: int = 0
    specifier_done: bool = False
    after_closing_brace: bool = False
    in_parameter_list: bool = False
    parameter_paren_depth: int = 0
    previous_type: Optional[str] = None
    previous_token_type: Optional[str] = None
    previous_token_value: Optional[str] = None


class CTokenType(str, Enum):
    TYPEDEF = "TYPEDEF"
    IDENTIFIER = "IDENTIFIER"
    TYPE_NAME = "TYPE_NAME"
    VOID = "VOID"
    CHAR = "CHAR"
    SHORT = "SHORT"
    INT = "INT"
    LONG = "LONG"
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    SIGNED = "SIGNED"
    UNSIGNED_ALT = "_UNSIGNED"
    UNSIGNED = "UNSIGNED"
    BOOL = "BOOL"
    COMPLEX = "COMPLEX"
    IMAGINARY = "IMAGINARY"
    ATOMIC = "ATOMIC"
    STRUCT = "STRUCT"
    UNION = "UNION"
    ENUM = "ENUM"


class CPostLex(PostLex):
    """Classify C identifiers as TYPE_NAME after typedef declarations."""

    _TYPE_KEYWORDS = frozenset(
        token_type.value
        for token_type in (
            CTokenType.VOID,
            CTokenType.CHAR,
            CTokenType.SHORT,
            CTokenType.INT,
            CTokenType.LONG,
            CTokenType.FLOAT,
            CTokenType.DOUBLE,
            CTokenType.SIGNED,
            CTokenType.UNSIGNED_ALT,
            CTokenType.UNSIGNED,
            CTokenType.BOOL,
            CTokenType.COMPLEX,
            CTokenType.IMAGINARY,
            CTokenType.ATOMIC,
        )
    )
    _TAG_KEYWORDS = frozenset(
        token_type.value
        for token_type in (CTokenType.STRUCT, CTokenType.UNION, CTokenType.ENUM)
    )

    @staticmethod
    def _classify_token(
        token: Token, type_names: Set[str], is_tag_identifier: bool = False
    ) -> Token:
        """Reclassify identifiers that have been declared as type names by a previous typedef."""
        if (
            token.type
            in {CTokenType.IDENTIFIER.value, CTokenType.TYPE_NAME.value}
            and not is_tag_identifier
            and token.value in type_names
        ):
            # Reclassify the token as a TYPE_NAME if it matches a known typedef alias.
            return Token.new_borrow_pos(
                CTokenType.TYPE_NAME.value, token.value, token
            )

        # Otherwise, the token is a standard identifier or other token type, so return it unchanged.
        return token

    def _update_declaration_context(
        self, token: Token, state: CPostLexState
    ) -> None:
        """Track parameter clauses and aggregate bodies that contain non-alias names."""
        if token.value == "(":
            if state.in_parameter_list:
                # Nested parentheses belong to the same parameter clause.
                state.parameter_paren_depth += 1
            elif (
                state.previous_token_type
                in {CTokenType.IDENTIFIER.value, CTokenType.TYPE_NAME.value}
                or state.previous_token_value == ")"
            ):
                # A function declarator's parameter clause follows its name or grouped declarator.
                state.in_parameter_list = True
                state.parameter_paren_depth = 1
        elif token.value == ")" and state.in_parameter_list:
            state.parameter_paren_depth -= 1
            if state.parameter_paren_depth == 0:
                # Only leave parameter context when the outer clause closes.
                state.in_parameter_list = False

        if token.value == "{":
            # Aggregate members must not be mistaken for typedef declarators.
            state.typedef_brace_depth += 1
            state.specifier_done = True
            if state.previous_type in self._TAG_KEYWORDS:
                # The tag specifier is complete; the next identifier may be a member type.
                state.previous_type = None
        elif token.value == "}":
            state.typedef_brace_depth -= 1
            if state.typedef_brace_depth == 0:
                # The typedef declarator can follow the aggregate's closing brace.
                state.after_closing_brace = True
                state.specifier_done = True
                state.previous_type = None

    def _collect_typedef_candidate(
        self, token: Token, state: CPostLexState
    ) -> None:
        """Use token context to identify likely typedef names for this stream."""
        if token.type in self._TAG_KEYWORDS:
            # The next identifier names the aggregate tag, not a typedef.
            state.specifier_done = True
            state.previous_type = token.type
        elif token.type in self._TYPE_KEYWORDS:
            # Built-in type specifiers allow a following declarator name.
            state.specifier_done = True
            state.previous_type = token.type
        elif (
            token.type == CTokenType.IDENTIFIER.value
            and state.previous_type in self._TAG_KEYWORDS
        ):
            # Consume a tag name without treating it as the underlying typedef type.
            state.previous_type = None
        elif token.type == CTokenType.TYPE_NAME.value:
            if token.value in state.type_names:
                # A previously declared typedef can be the base type in this typedef.
                state.specifier_done = True
                state.previous_type = token.type
        elif (
            token.type == CTokenType.IDENTIFIER.value
            and token.value in state.type_names
            and state.typedef_brace_depth == 0
        ):
            # The stream lexer may still label a known type as IDENTIFIER.
            state.specifier_done = True
            state.previous_type = CTokenType.TYPE_NAME.value
        elif (
            token.type == CTokenType.IDENTIFIER.value
            and state.typedef_brace_depth == 0
            and not state.in_parameter_list
        ):
            # Only top-level declarator identifiers after type specifiers are candidates.
            is_tag = state.previous_type in self._TAG_KEYWORDS
            if not is_tag and (state.specifier_done or state.after_closing_brace):
                state.pending_type_names.add(token.value)

    def process(self, stream):
        # This speculative scan is per stream; CParser separately checkpoints confirmed names.
        state = CPostLexState()

        for token in stream:
            if token.type == CTokenType.TYPEDEF.value:
                # Begin collecting candidate alias names for this declaration.
                state.pending_type_names.clear()
                state.in_typedef_declaration = True
                state.typedef_brace_depth = 0
                state.specifier_done = False
                state.after_closing_brace = False
                state.in_parameter_list = False
                state.parameter_paren_depth = 0
                state.previous_type = token.type
                state.previous_token_type = token.type
                state.previous_token_value = token.value
                yield token
                continue

            if state.in_typedef_declaration:
                # Track delimiters that distinguish declarators from nested names.
                self._update_declaration_context(token, state)

                # Use type specifiers and context to collect possible alias names.
                is_tag_identifier = (
                    token.type == CTokenType.IDENTIFIER.value
                    and state.previous_type in self._TAG_KEYWORDS
                )
                self._collect_typedef_candidate(token, state)

                # Reclassify names already declared by an earlier typedef in this stream.
                parsed_token = self._classify_token(
                    token, state.type_names, is_tag_identifier
                )

                # Only the outer semicolon completes the typedef declaration.
                if token.value == ";" and state.typedef_brace_depth == 0:
                    state.type_names.update(state.pending_type_names)
                    state.pending_type_names.clear()
                    state.in_typedef_declaration = False
                    state.specifier_done = False
                    state.after_closing_brace = False
                    state.previous_type = None

                yield parsed_token
                state.previous_token_type = token.type
                state.previous_token_value = token.value
                continue

            # Outside typedef declarations, classify previously collected aliases.
            is_tag_identifier = (
                token.type == CTokenType.IDENTIFIER.value
                and state.previous_token_type in self._TAG_KEYWORDS
            )
            yield self._classify_token(
                token, state.type_names, is_tag_identifier
            )
            state.previous_token_type = token.type
            state.previous_token_value = token.value
