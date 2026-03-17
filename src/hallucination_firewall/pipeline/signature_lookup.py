"""Look up function signatures using Jedi + inspect fallback."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field

import jedi

logger = logging.getLogger(__name__)


@dataclass
class ParamInfo:
    """Parameter info from a function signature."""

    name: str
    required: bool = True
    kind: str = "POSITIONAL_OR_KEYWORD"


@dataclass
class SignatureInfo:
    """Resolved function signature."""

    params: list[ParamInfo] = field(default_factory=list)
    has_var_positional: bool = False
    has_var_keyword: bool = False


class SignatureLookup:
    """Look up function signatures using Jedi + inspect fallback."""

    def get_signature(self, func_name: str, code: str, line: int) -> SignatureInfo | None:
        """Get signature for function at given location in code."""
        sig = self._jedi_lookup(func_name, code, line)
        if sig:
            return sig
        return self._inspect_lookup(func_name)

    def _jedi_lookup(self, func_name: str, code: str, line: int) -> SignatureInfo | None:
        """Use Jedi to resolve signature."""
        try:
            script = jedi.Script(code)
            sigs = script.get_signatures(line + 1, 0)
            if not sigs:
                names = script.goto(line + 1, 0, follow_imports=True)
                if names:
                    for name in names:
                        try:
                            name_sigs = name.get_signatures()
                            if name_sigs:
                                return self._jedi_sig_to_info(name_sigs[0])
                        except Exception:
                            continue
                return None
            return self._jedi_sig_to_info(sigs[0])
        except Exception:
            logger.debug("Jedi lookup failed for %s", func_name)
            return None

    def _jedi_sig_to_info(self, sig: object) -> SignatureInfo:
        """Convert Jedi signature to SignatureInfo."""
        params: list[ParamInfo] = []
        has_var_pos = False
        has_var_kw = False

        for p in sig.params:  # type: ignore[union-attr]
            kind = str(getattr(p, "kind", "POSITIONAL_OR_KEYWORD"))
            if "VAR_POSITIONAL" in kind:
                has_var_pos = True
                continue
            if "VAR_KEYWORD" in kind:
                has_var_kw = True
                continue
            required = not hasattr(p, "default") or p.description.find("=") == -1  # type: ignore[union-attr]
            params.append(ParamInfo(
                name=p.name,  # type: ignore[union-attr]
                required=required,
                kind=kind,
            ))

        return SignatureInfo(
            params=params, has_var_positional=has_var_pos, has_var_keyword=has_var_kw,
        )

    # Only allow importing stdlib modules for inspect fallback (security)
    _SAFE_MODULES = frozenset({
        "os", "os.path", "sys", "json", "re", "math", "datetime",
        "pathlib", "collections", "itertools", "functools", "typing",
        "io", "csv", "hashlib", "base64", "urllib", "urllib.parse",
        "shutil", "tempfile", "logging", "string", "textwrap",
    })

    def _inspect_lookup(self, func_name: str) -> SignatureInfo | None:
        """Fallback: use inspect.signature() for safe stdlib modules only."""
        if "." not in func_name:
            return None
        try:
            parts = func_name.rsplit(".", 1)
            module_name = parts[0]
            if module_name not in self._SAFE_MODULES:
                return None
            mod = __import__(module_name, fromlist=[parts[1]])
            obj = getattr(mod, parts[1])
            sig = inspect.signature(obj)
            return self._inspect_sig_to_info(sig)
        except Exception:
            return None

    def _inspect_sig_to_info(self, sig: inspect.Signature) -> SignatureInfo:
        """Convert inspect.Signature to SignatureInfo."""
        params: list[ParamInfo] = []
        has_var_pos = False
        has_var_kw = False

        for name, p in sig.parameters.items():
            if name == "self":
                continue
            if p.kind == inspect.Parameter.VAR_POSITIONAL:
                has_var_pos = True
                continue
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                has_var_kw = True
                continue
            required = p.default is inspect.Parameter.empty
            params.append(ParamInfo(name=name, required=required))

        return SignatureInfo(
            params=params, has_var_positional=has_var_pos, has_var_keyword=has_var_kw,
        )
