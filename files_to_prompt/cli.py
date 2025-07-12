import os
import sys
from fnmatch import fnmatch
from pathlib import Path

import click
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

global_index = 1

EXT_TO_LANG = {
    "py": "python",
    "c": "c",
    "cpp": "cpp",
    "java": "java",
    "js": "javascript",
    "ts": "typescript",
    "html": "html",
    "css": "css",
    "xml": "xml",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "sh": "bash",
    "rb": "ruby",
}


def add_line_numbers(content):
    lines = content.splitlines()
    padding = len(str(len(lines)))
    numbered_lines = [f"{i + 1:{padding}}  {line}" for i, line in enumerate(lines)]
    return "\n".join(numbered_lines)


def print_path(writer, path, content, cxml, markdown, line_numbers):
    normalized_path = Path(path).as_posix()
    if cxml:
        print_as_xml(writer, normalized_path, content, line_numbers)
    elif markdown:
        print_as_markdown(writer, normalized_path, content, line_numbers)
    else:
        print_default(writer, normalized_path, content, line_numbers)


def print_default(writer, path, content, line_numbers):
    writer(path)
    writer("---")
    if line_numbers:
        content = add_line_numbers(content)
    writer(content)
    writer("")
    writer("---")


def print_as_xml(writer, path, content, line_numbers):
    global global_index
    writer(f'<document index="{global_index}">')
    writer(f"<source>{path}</source>")
    writer("<document_content>")
    if line_numbers:
        content = add_line_numbers(content)
    writer(content)
    writer("</document_content>")
    writer("</document>")
    global_index += 1


def print_as_markdown(writer, path, content, line_numbers):
    lang = EXT_TO_LANG.get(path.split(".")[-1], "")
    backticks = "```"
    while backticks in content:
        backticks += "`"
    writer(path)
    writer(f"{backticks}{lang}")
    if line_numbers:
        content = add_line_numbers(content)
    writer(content)
    writer(f"{backticks}")


def process_path(
    path,
    extensions,
    include_hidden,
    ignore_files_only,
    ignore_gitignore,
    ignore_patterns,
    writer,
    claude_xml,
    markdown,
    line_numbers=False,
):
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                print_path(writer, path, f.read(), claude_xml, markdown, line_numbers)
        except UnicodeDecodeError:
            warning_message = f"Warning: Skipping file {path} due to UnicodeDecodeError"
            click.echo(click.style(warning_message, fg="red"), err=True)
        return

    base_path = Path(path)
    
    # FIX: Initialize all_patterns before the conditional block
    all_patterns = []
    if not ignore_gitignore:
        for root, _, _ in os.walk(base_path):
            gitignore_file = Path(root) / ".gitignore"
            if gitignore_file.is_file():
                try:
                    with open(gitignore_file, "r", encoding="utf-8") as f:
                        # Get path of .gitignore relative to the base_path
                        relative_dir = gitignore_file.parent.relative_to(base_path)
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#"):
                                # Prepend the relative directory to the pattern
                                # This makes patterns like `/foo` work correctly
                                if str(relative_dir) == ".":
                                    all_patterns.append(line)
                                else:
                                    all_patterns.append(f"{relative_dir.as_posix()}/{line}")

                except UnicodeDecodeError:
                    warning_message = f"Warning: Skipping .gitignore file {gitignore_file} due to UnicodeDecodeError"
                    click.echo(click.style(warning_message, fg="red"), err=True)

    # Create a single spec from all collected patterns
    gitignore_spec = PathSpec.from_lines(GitWildMatchPattern, all_patterns)

    files_to_process = []
    for root, dirs, files in os.walk(path, topdown=True):
        # Filter hidden files and directories first
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]
        
        # Filter based on --ignore patterns
        if ignore_patterns:
            if not ignore_files_only:
                dirs[:] = [d for d in dirs if not any(fnmatch(d, p) for p in ignore_patterns)]
            files = [f for f in files if not any(fnmatch(f, p) for p in ignore_patterns)]
        
        # Combine dirs and files for gitignore checking
        paths_to_check = [Path(root).relative_to(base_path) / item for item in dirs + files]
        
        # Filter based on the comprehensive .gitignore spec
        ignored_paths = set(gitignore_spec.match_files(paths_to_check))
        
        dirs[:] = [d for d in dirs if Path(root).relative_to(base_path) / d not in ignored_paths]
        files = [f for f in files if Path(root).relative_to(base_path) / f not in ignored_paths]

        # Filter based on extensions
        if extensions:
            files = [f for f in files if f.endswith(extensions)]

        for file in files:
            files_to_process.append(os.path.join(root, file))

    for file_path in sorted(files_to_process):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                print_path(
                    writer,
                    file_path,
                    f.read(),
                    claude_xml,
                    markdown,
                    line_numbers,
                )
        except UnicodeDecodeError:
            warning_message = f"Warning: Skipping file {file_path} due to UnicodeDecodeError"
            click.echo(click.style(warning_message, fg="red"), err=True)


def read_paths_from_stdin(use_null_separator):
    if sys.stdin.isatty():
        return []
    stdin_content = sys.stdin.read()
    if use_null_separator:
        paths = stdin_content.split("\0")
    else:
        paths = stdin_content.split()
    return [p for p in paths if p]


@click.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("extensions", "-e", "--extension", multiple=True)
@click.option(
    "--include-hidden",
    is_flag=True,
    help="Include files and folders starting with .",
)
@click.option(
    "--ignore-files-only",
    is_flag=True,
    help="--ignore option only ignores files",
)
@click.option(
    "--ignore-gitignore",
    is_flag=True,
    help="Ignore .gitignore files and include all files",
)
@click.option(
    "ignore_patterns",
    "--ignore",
    multiple=True,
    default=[],
    help="List of patterns to ignore",
)
@click.option(
    "output_file",
    "-o",
    "--output",
    type=click.Path(writable=True),
    help="Output to a file instead of stdout",
)
@click.option(
    "claude_xml",
    "-c",
    "--cxml",
    is_flag=True,
    help="Output in XML-ish format suitable for Claude's long context window.",
)
@click.option(
    "markdown",
    "-m",
    "--markdown",
    is_flag=True,
    help="Output Markdown with fenced code blocks",
)
@click.option(
    "line_numbers",
    "-n",
    "--line-numbers",
    is_flag=True,
    help="Add line numbers to the output",
)
@click.option(
    "--null",
    "-0",
    is_flag=True,
    help="Use NUL character as separator when reading from stdin",
)
@click.version_option()
def cli(
    paths,
    extensions,
    include_hidden,
    ignore_files_only,
    ignore_gitignore,
    ignore_patterns,
    output_file,
    claude_xml,
    markdown,
    line_numbers,
    null,
):
    """Docstring unchanged"""
    global global_index
    global_index = 1

    if not sys.stdin.isatty():
        sys.stdin.reconfigure(encoding='utf-8')

    stdin_paths = read_paths_from_stdin(use_null_separator=null)
    all_paths = [*paths, *stdin_paths]

    writer = click.echo
    fp = None
    if output_file:
        fp = open(output_file, "w", encoding="utf-8")
        writer = lambda s: print(s, file=fp)

    if claude_xml:
        writer("<documents>")

    for path in all_paths:
        if not os.path.exists(path):
            raise click.BadArgumentUsage(f"Path does not exist: {path}")
        process_path(
            path,
            extensions,
            include_hidden,
            ignore_files_only,
            ignore_gitignore,
            ignore_patterns,
            writer,
            claude_xml,
            markdown,
            line_numbers,
        )

    if claude_xml:
        writer("</documents>")
    if fp:
        fp.close()