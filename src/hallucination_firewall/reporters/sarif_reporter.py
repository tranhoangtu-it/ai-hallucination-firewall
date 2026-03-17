"""SARIF v2.1.0 reporter for GitHub Code Scanning integration."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from ..models import IssueType, Severity, ValidationResult

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"
TOOL_NAME = "hallucination-firewall"
TOOL_VERSION = "0.2.0"


def _severity_to_sarif_level(severity: Severity) -> str:
    """Map firewall severity to SARIF level."""
    mapping = {
        Severity.ERROR: "error",
        Severity.WARNING: "warning",
        Severity.INFO: "note",
    }
    return mapping.get(severity, "warning")


def _issue_type_to_rule_id(issue_type: IssueType) -> str:
    """Map IssueType to SARIF rule ID."""
    return issue_type.value


def _build_sarif_rules() -> list[dict[str, Any]]:
    """Generate SARIF rules for all IssueType values."""
    rules = []
    rule_descriptions = {
        IssueType.NONEXISTENT_PACKAGE: "Reference to a package that does not exist in the registry",
        IssueType.NONEXISTENT_METHOD: "Reference to a method or function that does not exist",
        IssueType.WRONG_SIGNATURE: "Function or method called with incorrect signature",
        IssueType.DEPRECATED_API: "Usage of deprecated API that should be updated",
        IssueType.INVALID_IMPORT: "Import statement that cannot be resolved",
        IssueType.SYNTAX_ERROR: "Code contains syntax errors",
        IssueType.VERSION_MISMATCH: "Package version incompatibility detected",
        IssueType.MISSING_REQUIRED_ARG: "Missing required argument in function call",
        IssueType.UNKNOWN_PARAMETER: "Unknown parameter passed to function",
    }

    for issue_type in IssueType:
        rules.append({
            "id": _issue_type_to_rule_id(issue_type),
            "name": issue_type.value,
            "shortDescription": {
                "text": rule_descriptions.get(issue_type, issue_type.value),
            },
            "fullDescription": {
                "text": rule_descriptions.get(issue_type, issue_type.value),
            },
            "defaultConfiguration": {
                "level": "warning",
            },
        })

    return rules


def print_sarif(
    results: list[ValidationResult],
    output: TextIO = sys.stdout,
) -> None:
    """Output validation results in SARIF v2.1.0 format for GitHub Code Scanning."""
    sarif_results: list[dict[str, Any]] = []

    for validation_result in results:
        for issue in validation_result.issues:
            sarif_result: dict[str, Any] = {
                "ruleId": _issue_type_to_rule_id(issue.issue_type),
                "level": _severity_to_sarif_level(issue.severity),
                "message": {
                    "text": issue.message,
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": issue.location.file,
                            },
                            "region": {
                                "startLine": issue.location.line,
                                "startColumn": issue.location.column or 1,
                            },
                        },
                    },
                ],
            }

            # Add end position if available
            region = sarif_result["locations"][0]["physicalLocation"]["region"]
            if issue.location.end_line is not None:
                region["endLine"] = issue.location.end_line
            if issue.location.end_column is not None:
                region["endColumn"] = issue.location.end_column

            # Add suggestion as fix if available
            if issue.suggestion:
                sarif_result["message"]["text"] += f"\nSuggestion: {issue.suggestion}"

            sarif_results.append(sarif_result)

    # Build complete SARIF document
    sarif_doc = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": TOOL_VERSION,
                        "informationUri": "https://github.com/tranhoangtu-it/ai-hallucination-firewall",
                        "rules": _build_sarif_rules(),
                    },
                },
                "results": sarif_results,
            },
        ],
    }

    output.write(json.dumps(sarif_doc, indent=2))
    output.write("\n")
