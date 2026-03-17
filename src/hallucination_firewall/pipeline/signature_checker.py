"""Signature validation — checks function calls against real signatures."""

from __future__ import annotations

from ..models import (
    IssueType,
    Severity,
    SourceLocation,
    ValidationIssue,
)
from ..models import Language as LangEnum
from .function_call_extractor import FunctionCall, FunctionCallExtractor
from .signature_lookup import ParamInfo, SignatureInfo, SignatureLookup

# Re-export for backward compatibility
__all__ = [
    "FunctionCall",
    "FunctionCallExtractor",
    "ParamInfo",
    "SignatureInfo",
    "SignatureLookup",
    "SignatureValidator",
    "check_signatures",
]


class SignatureValidator:
    """Compare function call arguments against signature parameters."""

    def validate(self, call: FunctionCall, sig: SignatureInfo) -> list[tuple[IssueType, str]]:
        """Return list of (issue_type, message) tuples."""
        if call.has_star_args or call.has_star_kwargs:
            return []
        if sig.has_var_positional and sig.has_var_keyword:
            return []

        errors: list[tuple[IssueType, str]] = []

        required_params = [p for p in sig.params if p.required]
        total_params = len(sig.params)

        if not sig.has_var_positional and call.positional_count > total_params:
            errors.append((
                IssueType.WRONG_SIGNATURE,
                f"Too many arguments: got {call.positional_count}, expected at most {total_params}",
            ))

        provided = call.positional_count + len(call.keywords)
        min_required = len(required_params)
        if provided < min_required:
            missing = [p.name for p in required_params[provided:]]
            errors.append((
                IssueType.MISSING_REQUIRED_ARG,
                f"Missing required argument(s): {', '.join(missing)}",
            ))

        if not sig.has_var_keyword:
            known = {p.name for p in sig.params}
            for kw in call.keywords:
                if kw not in known:
                    errors.append((
                        IssueType.UNKNOWN_PARAMETER,
                        f"Unknown keyword argument: '{kw}'",
                    ))

        return errors


async def check_signatures(
    code: str,
    language: LangEnum,
    file_path: str,
) -> list[ValidationIssue]:
    """Check function signatures in code. Entry point for pipeline."""
    if language != LangEnum.PYTHON:
        return []

    from .ast_validator import extract_import_aliases

    extractor = FunctionCallExtractor()
    lookup = SignatureLookup()
    validator = SignatureValidator()

    calls = extractor.extract_calls(code)
    aliases = extract_import_aliases(code, language)
    issues: list[ValidationIssue] = []

    for call in calls:
        resolved_name = _resolve_alias(call.name, aliases)

        sig = lookup.get_signature(resolved_name, code, call.line)
        if not sig:
            continue

        errors = validator.validate(call, sig)
        for issue_type, message in errors:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                issue_type=issue_type,
                location=SourceLocation(file=file_path, line=call.line + 1, column=0),
                message=f"{call.name}(): {message}",
                confidence=0.8,
                source="signature_checker",
            ))

    return issues


def _resolve_alias(call_name: str, aliases: dict[str, str]) -> str:
    """Resolve import alias to real module name."""
    if not aliases or "." not in call_name:
        return call_name

    parts = call_name.split(".", 1)
    prefix = parts[0]

    if prefix in aliases:
        real_module = aliases[prefix]
        if len(parts) > 1:
            return f"{real_module}.{parts[1]}"
        return real_module

    return call_name
