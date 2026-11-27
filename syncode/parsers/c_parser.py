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
    scopes: List[Dict[str, str]] = field(default_factory=lambda: [{}])
    pending_type_names: Set[str] = field(default_factory=set)
    pending_ordinary_names: Set[str] = field(default_factory=set)
    in_typedef_declaration: bool = False
    typedef_brace_depth: int = 0

    @property
    def type_names(self) -> Set[str]:
        visible = {}

        for scope in self.scopes:
            visible.update(scope)

        return {
            name
            for name, kind in visible.items()
            if kind == "typedef"
        }
    
    def copy(self) -> "CParserState":
        return CParserState(
            scopes=[scope.copy() for scope in self.scopes],
            pending_type_names=self.pending_type_names.copy(),
            pending_ordinary_names=self.pending_ordinary_names.copy(),
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
            if origin is None:
                continue

            if origin.name == "function_scope_enter":
                def enter_function_scope(children, callback=callback):
                    declarator = next(
                        (
                            value
                            for value in reversed(
                                self.interactive.parser_state.value_stack
                            )
                            if isinstance(value, Tree)
                            and value.data == "declarator"
                        ),
                        None,
                    )

                    if declarator is None:
                        raise RuntimeError("Function declarator not found.")

                    names = self._function_parameter_names(declarator)
                    tree = callback(children)

                    self.state.scopes.append(
                        {name: "ordinary" for name in names}
                    )

                    return tree

                callbacks[rule] = enter_function_scope
                continue

            if origin.name in {"scope_enter", "for_scope_enter"}:
                def enter_scope(children, callback=callback):
                    tree = callback(children)
                    self.state.scopes.append({})
                    return tree

                callbacks[rule] = enter_scope
                continue

            if origin.name in {"scope_exit", "for_scope_exit"}:
                def exit_scope(children, callback=callback):
                    tree = callback(children)

                    if len(self.state.scopes) <= 1:
                        raise RuntimeError("Cannot exit the global scope.")

                    self.state.scopes.pop()
                    return tree

                callbacks[rule] = exit_scope
                continue

            if origin.name != "init_declarator":
                continue

            def register_declarator(children, callback=callback):
                # feed_token invokes this on reduction and preserve the original tree callback.
                tree = callback(children)
                # Each reduction covers one declarator, including comma-separated typedef items.
                if isinstance(tree, Tree):
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
                        if self.state.in_typedef_declaration:
                            self.state.pending_type_names.add(name)
                        else:
                            self.state.pending_ordinary_names.add(name)
                return tree

            callbacks[rule] = register_declarator

    @classmethod
    def _function_parameter_names(cls, declarator) -> Set[str]:
        def find_clause(node):
            if not isinstance(node, Tree):
                return None

            for child in node.children:
                if isinstance(child, Tree) and child.data in {
                    "declarator",
                    "direct_declarator",
                }:
                    clause = find_clause(child)
                    if clause is not None:
                        return clause

            return next(
                (
                    child
                    for child in node.children
                    if isinstance(child, Tree)
                    and child.data == "function_parameters"
                ),
                None,
            )

        clause = find_clause(declarator)
        if clause is None:
            return set()

        names = set()

        for child in clause.children:
            if not isinstance(child, Tree):
                continue

            if child.data == "identifier_list":
                names.update(
                    token.value
                    for token in child.children
                    if isinstance(token, Token)
                    and token.type == CTokenType.IDENTIFIER.value
                )

            if child.data != "parameter_type_list":
                continue

            for parameter_list in child.children:
                if (
                    not isinstance(parameter_list, Tree)
                    or parameter_list.data != "parameter_list"
                ):
                    continue

                for parameter in parameter_list.children:
                    if (
                        not isinstance(parameter, Tree)
                        or parameter.data != "parameter_declaration"
                    ):
                        continue

                    parameter_declarator = next(
                        (
                            item
                            for item in parameter.children
                            if isinstance(item, Tree)
                            and item.data == "declarator"
                        ),
                        None,
                    )

                    name = cls._first_identifier(parameter_declarator)
                    if name is not None:
                        names.add(name)

        return names

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

    def _is_declarator_name(self, interactive) -> bool:
        from syncode.larkm.parsers.lalr_analysis import Shift

        parser_state = interactive.parser_state
        states = parser_state.parse_conf.states
        stack = parser_state.state_stack.copy()
        values = parser_state.value_stack.copy()

        def has_type(value):
            if isinstance(value, Token):
                return value.type in (
                    self._typedef_postlex._TYPE_KEYWORDS
                    | {CTokenType.TYPE_NAME.value}
                )

            if isinstance(value, Tree):
                if value.data in {
                    "struct_or_union_specifier",
                    "enum_specifier",
                    "atomic_type_specifier",
                }:
                    return True

                return any(has_type(child) for child in value.children)

            return False

        while True:
            entry = states[stack[-1]].get(CTokenType.IDENTIFIER.value)

            if entry is None:
                return False

            action, argument = entry

            if action is Shift:
                is_declarator = any(
                    next_action is not Shift
                    and rule.origin.name == "direct_declarator"
                    and len(rule.expansion) == 1
                    and rule.expansion[0].name == "IDENTIFIER"
                    for next_action, rule in states[argument].values()
                )

                if not is_declarator:
                    return False

                for value in reversed(values):
                    if isinstance(value, Tree) and value.data in {
                        "declaration_specifiers",
                        "specifier_qualifier_list",
                    }:
                        return has_type(value)

                return False

            size = len(argument.expansion)
            children = values[-size:] if size else []

            if size:
                del stack[-size:]
                del values[-size:]

            values.append(Tree(argument.origin.name, children))
            _, next_state = states[stack[-1]][argument.origin.name]
            stack.append(next_state)

    def _prepare_for_scope_exit(self, token, interactive) -> None:
        from syncode.larkm.parsers.lalr_analysis import Shift

        parser_state = interactive.parser_state
        conf = parser_state.parse_conf

        while True:
            probe_stack = parser_state.state_stack.copy()
            reductions = []

            while True:
                entry = conf.states[probe_stack[-1]].get(token.type)

                if entry is None or entry[0] is Shift:
                    return

                rule = entry[1]
                reductions.append(rule)

                size = len(rule.expansion)
                if size:
                    del probe_stack[-size:]

                _, next_state = conf.states[
                    probe_stack[-1]
                ][rule.origin.name]
                probe_stack.append(next_state)

                if rule.origin.name == "for_scope_exit":
                    break

            for rule in reductions:
                size = len(rule.expansion)
                children = (
                    parser_state.value_stack[-size:]
                    if size
                    else []
                )

                if size:
                    del parser_state.state_stack[-size:]
                    del parser_state.value_stack[-size:]

                value = conf.callbacks[rule](children)

                _, next_state = conf.states[
                    parser_state.state_stack[-1]
                ][rule.origin.name]

                parser_state.state_stack.append(next_state)
                parser_state.value_stack.append(value)

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
                self._prepare_for_scope_exit(token, interactive)

                previous = (
                    self.parsed_lexer_tokens[-1]
                    if self.parsed_lexer_tokens
                    else None
                )

                is_tag_identifier = (
                    previous is not None
                    and previous.type
                    in {
                        CTokenType.STRUCT.value,
                        CTokenType.UNION.value,
                        CTokenType.ENUM.value,
                    }
                )

                is_declarator_name = (
                    token.type == CTokenType.IDENTIFIER.value
                    and token.value in self.state.type_names
                    and self._is_declarator_name(interactive)
                )

                if not is_declarator_name:
                    token = self._typedef_postlex._classify_token(
                        token,
                        self.state.type_names,
                        is_tag_identifier,
                    )

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
                    for name in self.state.pending_type_names:
                        self.state.scopes[-1][name] = "typedef"
                    self.state.pending_type_names.clear()
                    self.state.in_typedef_declaration = False

                if (
                    token.value == ";"
                    and not self.state.in_typedef_declaration
                ):
                    for name in self.state.pending_ordinary_names:
                        self.state.scopes[-1][name] = "ordinary"

                    self.state.pending_ordinary_names.clear()

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
