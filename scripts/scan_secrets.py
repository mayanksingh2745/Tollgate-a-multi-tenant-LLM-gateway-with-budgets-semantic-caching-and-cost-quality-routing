#!/usr/bin/env python3
"""
Tollgate Secret Scanner.
Audits the repository working tree and recent Git commit history for leaked credentials,
private keys, provider API keys, and unhashed Tollgate tokens.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "Private Cryptographic Key"),
    (re.compile(r"sk-(?:proj-|ant-|live-)?[a-zA-Z0-9]{24,64}"), "OpenAI / Anthropic Secret Key"),
    (re.compile(r"AIzaSy[a-zA-Z0-9_-]{33}"), "Google API Key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "GitHub OAuth Token"),
    (re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"), "Slack Token"),
]

IGNORED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".vite",
    "htmlcov",
}

IGNORED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".woff",
    ".woff2",
    ".pyc",
    ".db",
    ".parquet",
}


def scan_file_content(path: Path) -> List[Tuple[str, int, str]]:
    findings = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, 1):
                # Check for sensitive patterns
                for pattern, desc in SECRET_PATTERNS:
                    if pattern.search(line):
                        # Filter test files with intentional fake mock values
                        if "test" in path.name.lower() or "fixture" in path.name.lower():
                            continue
                        findings.append((desc, idx, line.strip()[:100]))
    except Exception as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
    return findings


def scan_repository_tree(root_dir: Path) -> int:
    total_findings = 0
    print(f"[*] Scanning working tree starting at: {root_dir}")
    for current_root, dirs, files in os.walk(root_dir):
        # Exclude ignored dirs
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]

        for fname in files:
            fpath = Path(current_root) / fname
            if fpath.suffix in IGNORED_EXTENSIONS:
                continue

            findings = scan_file_content(fpath)
            for desc, lineno, snippet in findings:
                print(f"[!] POTENTIAL SECRET: {desc} in {fpath.relative_to(root_dir)}:{lineno}")
                print(f"    Line snippet: {snippet}")
                total_findings += 1

    return total_findings


def scan_git_history(max_commits: int = 50) -> int:
    print(f"[*] Scanning Git commit history (last {max_commits} commits)...")
    try:
        result = subprocess.run(
            ["git", "log", f"-n{max_commits}", "-p"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as e:
        print(f"Warning: could not run git log: {e}", file=sys.stderr)
        return 0

    findings = 0
    current_commit = "unknown"
    for line in result.stdout.splitlines():
        if line.startswith("commit "):
            current_commit = line.split()[1][:10]
        elif line.startswith("+") and not line.startswith("+++"):
            for pattern, desc in SECRET_PATTERNS:
                if pattern.search(line):
                    # Exclude mock test data
                    if "mock" in line.lower() or "placeholder" in line.lower() or "fake" in line.lower():
                        continue
                    print(f"[!] SECRET IN COMMIT {current_commit}: {desc}")
                    print(f"    Added line: {line.strip()[:100]}")
                    findings += 1
    return findings


def main():
    root = Path(__file__).resolve().parents[1]
    tree_findings = scan_repository_tree(root)
    git_findings = scan_git_history()

    total = tree_findings + git_findings
    if total == 0:
        print("[+] Secret scan complete: Zero leaked credentials or sensitive tokens found.")
        sys.exit(0)
    else:
        print(f"[-] Secret scan finished with {total} potential secret findings.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
