"""Extract function calls from tree-sitter AST."""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())


@dataclass
class FunctionCall:
    """A function call extracted from AST."""

    name: str
    positional_count: int
    keywords: list[str] = field(default_factory=list)
    has_star_args: bool = False
    has_star_kwargs: bool = False
    line: int = 0


class FunctionCallExtractor:
    """Extract function calls from tree-sitter AST."""

    def __init__(self) -> None:
        self.parser = Parser(PY_LANGUAGE)

    def extract_calls(self, code: str) -> list[FunctionCall]:
        """Extract all function calls from Python code."""
        tree = self.parser.parse(code.encode("utf-8"))
        calls: list[FunctionCall] = []
        self._walk(tree.root_node, calls)
        return calls

    def _walk(self, node: object, calls: list[FunctionCall]) -> None:
        """Recursively walk AST to find call nodes."""
        if node.type == "call":  # type: ignore[union-attr]
            call = self._parse_call(node)
            if call:
                calls.append(call)
        for child in node.children:  # type: ignore[union-attr]
            self._walk(child, calls)

    def _parse_call(self, node: object) -> FunctionCall | None:
        """Parse a call node into FunctionCall."""
        func_node = node.child_by_field_name("function")  # type: ignore[union-attr]
        args_node = node.child_by_field_name("arguments")  # type: ignore[union-attr]
        if not func_node:
            return None

        name = self._get_name(func_node)
        if not name or not self._is_checkable(name):
            return None

        positional = 0
        keywords: list[str] = []
        has_star_args = False
        has_star_kwargs = False

        if args_node:
            for child in args_node.children:  # type: ignore[union-attr]
                if child.type == "keyword_argument":
                    key_node = child.child_by_field_name("name")
                    if key_node:
                        keywords.append(key_node.text.decode("utf-8"))
                elif child.type == "list_splat":
                    has_star_args = True
                elif child.type == "dictionary_splat":
                    has_star_kwargs = True
                elif child.type not in ("(", ")", ","):
                    positional += 1

        return FunctionCall(
            name=name,
            positional_count=positional,
            keywords=keywords,
            has_star_args=has_star_args,
            has_star_kwargs=has_star_kwargs,
            line=func_node.start_point[0],  # type: ignore[union-attr]
        )

    def _get_name(self, node: object) -> str:
        """Get dotted function name from AST node."""
        if node.type == "identifier":  # type: ignore[union-attr]
            return node.text.decode("utf-8")  # type: ignore[union-attr]
        if node.type == "attribute":  # type: ignore[union-attr]
            obj = node.child_by_field_name("object")  # type: ignore[union-attr]
            attr = node.child_by_field_name("attribute")  # type: ignore[union-attr]
            if obj and attr:
                obj_name = self._get_name(obj)
                attr_name = attr.text.decode("utf-8")  # type: ignore[union-attr]
                return f"{obj_name}.{attr_name}" if obj_name else attr_name
        return ""

    def _is_checkable(self, name: str) -> bool:
        """Filter out names unlikely to have resolvable signatures."""
        return "." in name
