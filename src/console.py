import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
    TotalFileSizeColumn,
)

# Ensure Windows terminal doesn't crash on non-ASCII chars
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Custom color theme for pipeline stages
CUSTOM_THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "timestamp": "dim white",
    "stage": "bold magenta",
    "stat_key": "bold blue",
    "stat_val": "bold bright_white",
    "highlight": "bold yellow",
})

console = Console(theme=CUSTOM_THEME, safe_box=True)


def get_timestamp() -> str:
    """Return formatted current time with milliseconds."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def print_banner() -> None:
    """Display modern pipeline banner."""
    banner_text = Text()
    banner_text.append("=" * 72 + "\n", style="magenta")
    banner_text.append("  YOUTUBE SHORTS VIRAL AUTOMATION PIPELINE\n", style="bold bright_cyan")
    banner_text.append("  AI Moment Detection * Computer Vision Reframing * Karaoke Subtitles\n", style="italic white")
    banner_text.append("=" * 72, style="magenta")
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def log_stage(stage_num: int, title: str, subtitle: str = "") -> None:
    """Print high-visibility stage header."""
    ts = get_timestamp()
    text = Text()
    text.append(f"[{ts}] ", style="timestamp")
    text.append(f"STAGE {stage_num}: ", style="bold bright_yellow")
    text.append(title.upper(), style="bold bright_white")
    if subtitle:
        text.append(f" - {subtitle}", style="italic dim white")
    console.print("\n" + "-" * 70, style="dim cyan")
    console.print(text)
    console.print("-" * 70, style="dim cyan")


def log_info(stage: str, message: str) -> None:
    """Print an informational log line with timestamp and stage tag."""
    ts = get_timestamp()
    console.print(f"[{ts}] [{stage.upper()}] {message}", style="info")


def log_success(stage: str, message: str) -> None:
    """Print a success log line."""
    ts = get_timestamp()
    console.print(f"[{ts}] [{stage.upper()}] [OK] {message}", style="success")


def log_warning(stage: str, message: str) -> None:
    """Print a warning log line."""
    ts = get_timestamp()
    console.print(f"[{ts}] [{stage.upper()}] [!] {message}", style="warning")


def log_error(stage: str, message: str) -> None:
    """Print an error log line."""
    ts = get_timestamp()
    console.print(f"[{ts}] [{stage.upper()}] [X] {message}", style="error")


def log_table(title: str, data: Dict[str, Any]) -> None:
    """Render key-value metrics or metadata in a clean Rich table."""
    table = Table(title=title, show_header=True, header_style="bold magenta", border_style="dim cyan")
    table.add_column("Property", style="stat_key", width=25)
    table.add_column("Value", style="stat_val")
    for key, val in data.items():
        table.add_row(str(key), str(val))
    console.print(table)


def log_viral_moment(data: Dict[str, Any]) -> None:
    """Render selected viral moment analysis panel."""
    start = data.get("start_time", 0.0)
    end = data.get("end_time", 0.0)
    duration = end - start
    hook_score = data.get("hook_score", "N/A")
    title = data.get("hook_title", "Untitled")
    reasoning = data.get("viral_reasoning", "N/A")
    tags = ", ".join(data.get("tags", []))

    content = Text()
    content.append(f"Title: ", style="bold yellow")
    content.append(f"{title}\n", style="bold white")
    content.append(f"Timestamps: ", style="bold cyan")
    content.append(f"{start:.2f}s -> {end:.2f}s ({duration:.1f}s duration)\n", style="bright_white")
    content.append(f"Hook Score: ", style="bold green")
    content.append(f"{hook_score}/10\n", style="bold bright_green")
    content.append(f"Tags: ", style="bold magenta")
    content.append(f"{tags}\n", style="dim white")
    content.append(f"Viral Reasoning: ", style="bold blue")
    content.append(f"{reasoning}", style="italic white")

    console.print(Panel(content, title="[SELECTED VIRAL MOMENT]", border_style="bright_yellow"))


def create_progress_bar(description: str = "Processing") -> Progress:
    """Create a standardized rich progress bar for downloads and tasks."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40, style="dim cyan", complete_style="bold bright_cyan"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


def create_download_progress_bar() -> Progress:
    """Create a specialized progress bar for yt-dlp file downloads."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=35, complete_style="bold green"),
        TaskProgressColumn(),
        TransferSpeedColumn(),
        TotalFileSizeColumn(),
        TimeRemainingColumn(),
        console=console,
    )
