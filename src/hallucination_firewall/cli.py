"""Click CLI entry point for the hallucination firewall."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import click
from rich.console import Console

from .config import load_config
from .models import ValidationResult
from .pipeline.runner import ValidationPipeline
from .reporters.json_reporter import print_json
from .reporters.sarif_reporter import print_sarif
from .reporters.terminal_reporter import print_result, print_summary

console = Console()

_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|"
    r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|"
    r"192\.168\.\d+\.\d+|169\.254\.\d+\.\d+|"
    r"\[?::1\]?|0\.0\.0\.0)$",
    re.IGNORECASE,
)


@click.group()
@click.version_option(package_name="ai-hallucination-firewall")
def main() -> None:
    """AI Hallucination Firewall — validates AI-generated code against real sources."""


@main.command()
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--stdin", is_flag=True, help="Read code from stdin")
@click.option(
    "--format", "output_format",
    type=click.Choice(["terminal", "json", "sarif"]), default="terminal",
)
@click.option(
    "--language", "-l",
    type=click.Choice(["python", "javascript", "typescript"]), default=None,
)
@click.option("--ci", is_flag=True, help="Enable strict CI policy mode (fail on warnings)")
def check(
    files: tuple[str, ...],
    stdin: bool,
    output_format: str,
    language: str | None,
    ci: bool,
) -> None:
    """Validate code files for hallucinated APIs, wrong signatures, and more."""
    if not files and not stdin:
        console.print("[red]Error:[/] Provide file paths or use --stdin")
        sys.exit(1)

    results = asyncio.run(_run_check(files, stdin, language, ci))

    if output_format == "json":
        print_json(results)
    elif output_format == "sarif":
        print_sarif(results)
    else:
        for result in results:
            print_result(result, console)
        if len(results) > 1:
            print_summary(results, console)

    # Exit code: 1 if any errors found
    if any(not r.passed for r in results):
        sys.exit(1)


@main.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("--stdin", "use_stdin", is_flag=True, help="Read markdown from stdin")
@click.option("--url", "url", default=None, help="Fetch markdown from URL")
@click.option(
    "--format", "output_format",
    type=click.Choice(["terminal", "json"]), default="terminal",
)
def parse(
    file: str | None, use_stdin: bool, url: str | None, output_format: str,
) -> None:
    """Parse and validate code blocks from LLM markdown output.

    Examples:
        firewall parse response.md
        curl ... | firewall parse --stdin
        firewall parse --url https://gist.githubusercontent.com/.../response.md
    """
    from .parsers.llm_output_parser import validate_llm_output

    markdown = _read_parse_input(file, use_stdin, url)
    report = asyncio.run(validate_llm_output(markdown))

    if output_format == "json":
        print_json(report.results)
    else:
        console.print("\n[bold]LLM Output Validation Report[/]")
        console.print(f"Total blocks: {report.total_blocks}")
        console.print(f"Passed: [green]{report.blocks_passed}[/]")
        console.print(f"Failed: [red]{report.blocks_failed}[/]\n")
        for result in report.results:
            print_result(result, console)

    if not report.passed:
        sys.exit(1)


def _validate_url(url: str) -> str:
    """Validate URL is safe for fetching (prevent SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise click.BadParameter(f"Unsupported URL scheme: {parsed.scheme}")
    hostname = parsed.hostname or ""
    if _BLOCKED_HOSTS.match(hostname):
        raise click.BadParameter(f"Blocked host: {hostname}")
    return url


def _read_parse_input(file: str | None, use_stdin: bool, url: str | None) -> str:
    """Read markdown from file, stdin, or URL."""
    if use_stdin:
        return sys.stdin.read()
    if url:
        import httpx

        validated_url = _validate_url(url)
        resp = httpx.get(validated_url, timeout=10, follow_redirects=False)
        resp.raise_for_status()
        return resp.text
    if file:
        return Path(file).read_text(encoding="utf-8")
    console.print("[red]Error:[/] Provide a file path, --stdin, or --url")
    sys.exit(1)


@main.command()
@click.option("--host", default="127.0.0.1", help="Server host")
@click.option("--port", default=8000, help="Server port")
def serve(host: str, port: int) -> None:
    """Start the validation API server."""
    import uvicorn

    from .server import app

    console.print(f"[bold green]Starting firewall API server on {host}:{port}[/]")
    uvicorn.run(app, host=host, port=port)


@main.command()
def init() -> None:
    """Create a .firewall.toml config file in the current directory."""
    config_path = Path.cwd() / ".firewall.toml"
    if config_path.exists():
        console.print("[yellow]Config file already exists[/]")
        return

    config_path.write_text(
        '[firewall]\n'
        'languages = ["python", "javascript"]\n'
        'severity_threshold = "warning"\n'
        'cache_ttl_seconds = 3600\n'
        'output_format = "terminal"\n'
        '\n'
        '[firewall.registries]\n'
        'pypi_enabled = true\n'
        'npm_enabled = true\n'
        'timeout_seconds = 10\n'
    )
    console.print(f"[green]Created {config_path}[/]")


async def _run_check(
    files: tuple[str, ...],
    stdin: bool,
    language: str | None,
    ci: bool = False,
) -> list[ValidationResult]:
    """Run validation pipeline on files or stdin."""
    config = load_config()
    if ci:
        config.ci_mode = True
    pipeline = ValidationPipeline(config)

    results: list[ValidationResult] = []
    try:
        if stdin:
            code = sys.stdin.read()
            file_name = f"<stdin>.{language or 'py'}" if language else "<stdin>.py"
            result = await pipeline.validate_code(code, file_name)
            results.append(result)
        else:
            for file_path in files:
                result = await pipeline.validate_file(file_path)
                results.append(result)
    finally:
        await pipeline.close()

    return results


if __name__ == "__main__":
    main()
