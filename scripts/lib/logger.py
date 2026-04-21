# ============================================================
# LOGGER — Centralized logging for all agents.
#
# WHAT IT PROVIDES:
#   - Timestamps on every line
#   - Log levels: DEBUG, INFO, WARN, ERROR, SUCCESS
#   - Agent name in every message
#   - Color-coded console output
#   - Log file output (logs/ directory)
#
# USAGE:
#   from lib.logger import create_logger
#   log = create_logger("Issue-to-PR")
#
#   log.info("Starting agent...")
#   log.warn("Branch already exists")
#   log.error("API call failed")
#   log.success("PR created: #42")
#   log.section("STEP 1: Reading Issue")
#   log.summary("Agent COMPLETED", {"PR": "#42", "Branch": "ai-fix/issue-1"})
# ============================================================

import os
import sys
import json
from datetime import datetime

# -----------------------------------------------------------
# Fix Windows console encoding — allows Unicode characters
# like ═, ✅, 🤖 to print without crashing.
# -----------------------------------------------------------
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# -----------------------------------------------------------
# LOG LEVELS — Controls which messages are shown.
#
# Set LOG_LEVEL env var to control verbosity:
#   LOG_LEVEL=DEBUG  → show everything
#   LOG_LEVEL=INFO   → show info, warn, error (default)
#   LOG_LEVEL=WARN   → show only warnings and errors
#   LOG_LEVEL=ERROR  → show only errors
# -----------------------------------------------------------
LOG_LEVELS = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "SUCCESS": 4}
CURRENT_LEVEL = LOG_LEVELS.get(os.environ.get("LOG_LEVEL", "INFO").upper(), 1)

# -----------------------------------------------------------
# COLORS — ANSI escape codes for terminal coloring.
# -----------------------------------------------------------
COLORS = {
    "RESET": "\033[0m",
    "GRAY": "\033[90m",
    "BLUE": "\033[34m",
    "YELLOW": "\033[33m",
    "RED": "\033[31m",
    "GREEN": "\033[32m",
    "CYAN": "\033[36m",
    "BOLD": "\033[1m",
}

# -----------------------------------------------------------
# Level styles — emoji, color, and label for each level.
# -----------------------------------------------------------
LEVEL_STYLE = {
    "DEBUG":   {"emoji": "🔍", "color": COLORS["GRAY"],   "label": "DEBUG"},
    "INFO":    {"emoji": "ℹ️ ", "color": COLORS["BLUE"],   "label": "INFO "},
    "WARN":    {"emoji": "⚠️ ", "color": COLORS["YELLOW"], "label": "WARN "},
    "ERROR":   {"emoji": "❌", "color": COLORS["RED"],    "label": "ERROR"},
    "SUCCESS": {"emoji": "✅", "color": COLORS["GREEN"],  "label": "OK   "},
}


def create_logger(agent_name: str):
    """
    Factory function that creates a logger for a specific agent.

    Parameters:
        agent_name — Name shown in every log line (e.g., "Issue-to-PR")

    Returns:
        Logger object with methods: debug, info, warn, error, success, section, summary
    """

    # Create logs/ directory if it doesn't exist
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Log file: logs/issue-to-pr_2026-04-17.log
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_name = agent_name.lower().replace(" ", "-")
    log_file_path = os.path.join(log_dir, f"{safe_name}_{date_str}.log")

    def _write_log(level: str, *args):
        """Core logging function — writes to console + file."""
        # Skip messages below current level (SUCCESS always shows)
        if level != "SUCCESS" and LOG_LEVELS.get(level, 1) < CURRENT_LEVEL:
            return

        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        style = LEVEL_STYLE.get(level, LEVEL_STYLE["INFO"])

        # Convert all args to strings
        message = " ".join(
            json.dumps(a, indent=2) if isinstance(a, (dict, list)) else str(a)
            for a in args
        )

        # Console output — with colors
        console_line = (
            f"{COLORS['GRAY']}{timestamp}{COLORS['RESET']} "
            f"{style['color']}{style['emoji']} [{style['label']}]{COLORS['RESET']} "
            f"{COLORS['CYAN']}[{agent_name}]{COLORS['RESET']} "
            f"{style['color']}{message}{COLORS['RESET']}"
        )
        print(console_line)

        # File output — plain text (no colors)
        file_line = f"{timestamp} [{style['label']}] [{agent_name}] {message}\n"
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(file_line)
        except Exception:
            pass  # Don't crash the agent if logging fails

    def section(title: str):
        """Prints a visual separator for major steps."""
        separator = "═" * 50
        print(f"\n{COLORS['BOLD']}{COLORS['CYAN']}{separator}{COLORS['RESET']}")
        print(f"{COLORS['BOLD']}{COLORS['CYAN']}  {title}{COLORS['RESET']}")
        print(f"{COLORS['BOLD']}{COLORS['CYAN']}{separator}{COLORS['RESET']}\n")
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 50}\n  {title}\n{'=' * 50}\n\n")
        except Exception:
            pass

    def summary(title: str, data: dict):
        """Prints a summary table at the end of an agent run."""
        print(f"\n{COLORS['BOLD']}{COLORS['GREEN']}{'═' * 50}{COLORS['RESET']}")
        print(f"{COLORS['BOLD']}{COLORS['GREEN']}  {title}{COLORS['RESET']}")
        print(f"{COLORS['BOLD']}{COLORS['GREEN']}{'═' * 50}{COLORS['RESET']}")

        file_output = f"\n{'=' * 50}\n  {title}\n{'=' * 50}\n"
        for key, value in data.items():
            line = f"   {key:<12} {value}"
            print(f"{COLORS['GREEN']}{line}{COLORS['RESET']}")
            file_output += f"{line}\n"

        print(f"{COLORS['BOLD']}{COLORS['GREEN']}{'═' * 50}{COLORS['RESET']}\n")
        file_output += f"{'=' * 50}\n"

        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(file_output)
        except Exception:
            pass

    # -----------------------------------------------------------
    # Return a simple object with all logging methods.
    # Using a class-like namespace via type().
    # -----------------------------------------------------------
    class Logger:
        pass

    logger = Logger()
    logger.debug = lambda *args: _write_log("DEBUG", *args)
    logger.info = lambda *args: _write_log("INFO", *args)
    logger.warn = lambda *args: _write_log("WARN", *args)
    logger.error = lambda *args: _write_log("ERROR", *args)
    logger.success = lambda *args: _write_log("SUCCESS", *args)
    logger.section = section
    logger.summary = summary
    logger.log_file_path = log_file_path

    return logger
