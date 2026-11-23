from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional, Set

import syncode.larkm as lark
from syncode.larkm.lexer import Token
from syncode.larkm.tree import Tree
from syncode.parse_result import ParseResult
from syncode.parsers.c_postlex import CPostLex, CTokenType
from syncode.parsers.incremental_parser import IncrementalParser


@dataclass
class CParserState:
    type_names: Set[str] = field(default_factory=set)
    pending_type_names: Set[str] = field(default_factory=set)
    in_typedef_declaration: bool = False
    typedef_brace_depth: int = 0

    def copy(self) -> "CParserState":
        return CParserState(
            type_names=self.type_names.copy(),
            pending_type_names=self.pending_type_names.copy(),
            in_typedef_declaration=self.in_typedef_declaration,
            typedef_brace_depth=self.typedef_brace_depth,
        )


class CParserCheckpoint(NamedTuple):
    parsed_lexer_tokens: List[Token]
    parser_state: Any
    cur_ac_terminals: Set[str]
    next_ac_terminals: Set[str]
    indent_levels: Optional[list]
    typedef_state: CParserState

    @classmethod
    def create(
        cls,
        parsed_lexer_tokens: List[Token],
        parser_state: Any,
        cur_ac_terminals: Set[str],
        next_ac_terminals: Set[str],
        indent_levels: Optional[list],
        typedef_state: CParserState,
    ) -> "CParserCheckpoint":
        return cls(
            parsed_lexer_tokens=deepcopy(parsed_lexer_tokens),
            parser_state=parser_state.copy(),
            cur_ac_terminals=cur_ac_terminals.copy(),
            next_ac_terminals=next_ac_terminals.copy(),
            indent_levels=deepcopy(indent_levels),
            typedef_state=typedef_state.copy(),
        )


class CParser(IncrementalParser):
    """Incremental C parser with a global table of typedef names."""

    def __init__(self, base_parser, **kwargs) -> None:
        super().__init__(base_parser, **kwargs)
        postlex = getattr(base_parser.lexer_conf, "postlex", None)
        assert isinstance(postlex, CPostLex)
        self._typedef_postlex = postlex
        self.state = CParserState()
        self.cur_pos_to_parser_state: Dict[int, CParserCheckpoint] = {} # pyright: ignore[reportIncompatibleVariableOverride]
        self._install_typedef_callback()

    @property
    def type_names(self) -> Set[str]:
        return self.state.type_names

    def _install_typedef_callback(self) -> None:
        """Record typedef declarator names from LALR parse-tree reductions."""
        callbacks = self.interactive.parser_state.parse_conf.callbacks
        for rule, callback in list(callbacks.items()):
            origin = getattr(rule, "origin", None)
            if origin is None or origin.name != "init_declarator":
                continue

            def register_declarator(children, callback=callback):
                # feed_token invokes this on reduction and preserve the original tree callback.
                tree = callback(children)
                # Each reduction covers one declarator, including comma-separated typedef items.
                if self.state.in_typedef_declaration and isinstance(tree, Tree):
                    declarator = next(
                        (
                            child
                            for child in tree.children
                            if isinstance(child, Tree) and child.data == "declarator"
                        ),
                        None,
                    )
                    name = self._first_identifier(declarator)
                    if name is not None:
                        self.state.pending_type_names.add(name)
                return tree

            callbacks[rule] = register_declarator

    @classmethod
    def _first_identifier(cls, value) -> Optional[str]:
        if isinstance(value, Token):
            return (
                value.value
                if value.type == CTokenType.IDENTIFIER.value
                else None
            )
        if isinstance(value, Tree):
            for child in value.children:
                name = cls._first_identifier(child)
                if name is not None:
                    return name
        return None

    def _set_initial_parser_state(self) -> None:
        super()._set_initial_parser_state()
        self.state = CParserState()

    def _store_parser_state(
        self,
        pos,
        lexer_tokens,
        parser_state,
        accepts,
        indent_levels=None,
    ) -> None:
        # Typedef state must be restored with the LR state for a reused input prefix.
        key = self._get_hash(lexer_tokens[: pos + 1]) # pyright: ignore[reportIndexIssue]
        self.cur_pos_to_parser_state[key] = CParserCheckpoint.create(
            parsed_lexer_tokens=self.parsed_lexer_tokens,
            parser_state=parser_state,
            cur_ac_terminals=self.next_ac_terminals,
            next_ac_terminals=accepts,
            indent_levels=indent_levels,
            typedef_state=self.state,
        )
        self.cur_ac_terminals = self.next_ac_terminals.copy()
        self.next_ac_terminals = accepts.copy()

    def _restore_parser_state(self, key: int) -> None:
        state = self.cur_pos_to_parser_state[key]
        self.interactive.parser_state = state.parser_state.copy()
        self.parsed_lexer_tokens = deepcopy(state.parsed_lexer_tokens)
        self.cur_ac_terminals = state.cur_ac_terminals.copy()
        self.next_ac_terminals = state.next_ac_terminals.copy()
        self.state = state.typedef_state.copy()

        if state.indent_levels is not None:
            self.indent_level = deepcopy(state.indent_levels)

    def _lex_code(self, code):
        interactive = self.base_parser.parse_interactive(code)
        lexer_state = interactive.lexer_thread.state
        lexer_tokens: List[Token] = []
        lexing_incomplete = False

        try:
            # Collect raw tokens first, then run postlex as a complete stream.
            blexer = interactive.lexer_thread.lexer
            if hasattr(blexer, "lexer"):
                blexer = blexer.lexer
            while lexer_state.line_ctr.char_pos < len(lexer_state.text):
                lexer_tokens.append(blexer.next_token(lexer_state))
        except lark.exceptions.UnexpectedCharacters:
            lexing_incomplete = True
            self.lexer_pos = lexer_state.line_ctr.char_pos
        except EOFError:
            pass

        lexer_tokens = list(self._typedef_postlex.process(iter(lexer_tokens)))
        return lexer_tokens, lexing_incomplete

    def get_acceptable_next_terminals(self, partial_code) -> ParseResult:
        lexer_tokens, lexing_incomplete = self._lex_code(partial_code)
        self.next_ac_terminals = self._accepts(self.interactive)
        self._restore_recent_parser_state(lexer_tokens)
        interactive = self.interactive

        parse_incomplete = False
        token = None

        try:
            while self.cur_pos < len(lexer_tokens):
                token = lexer_tokens[self.cur_pos]
                self.cur_pos += 1

                if token.type == CTokenType.TYPEDEF.value:
                    self.state.in_typedef_declaration = True
                    self.state.pending_type_names.clear()
                    self.state.typedef_brace_depth = 0

                if self.state.in_typedef_declaration:
                    if token.value == "{":
                        self.state.typedef_brace_depth += 1
                    elif token.value == "}":
                        self.state.typedef_brace_depth -= 1

                self.parsed_lexer_tokens.append(token)
                interactive.feed_token(token)

                if (
                    self.state.in_typedef_declaration
                    and token.value == ";"
                    and self.state.typedef_brace_depth == 0
                ):
                    self.state.type_names.update(self.state.pending_type_names)
                    self.state.pending_type_names.clear()
                    self.state.in_typedef_declaration = False

                self._store_parser_state(
                    self.cur_pos - 1,
                    lexer_tokens,
                    interactive.parser_state,
                    self._accepts(interactive),
                )
        except lark.exceptions.UnexpectedToken as error:
            parse_incomplete = True
            self._handle_parsing_error(lexer_tokens, token, error)

        remainder_state, current_term_str, final_terminal = self._get_remainder(
            partial_code,
            lexing_incomplete=lexing_incomplete,
            parse_incomplete=parse_incomplete,
        )

        return ParseResult.from_accept_terminals(
            self.cur_ac_terminals,
            self.next_ac_terminals,
            current_term_str,
            remainder_state,
            final_terminal=final_terminal,
            ignore_terminals=self.base_parser.lexer_conf.ignore,
        )
