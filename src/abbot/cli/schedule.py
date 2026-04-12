"""CLI commands for managing scheduled ingestion."""

import click


@click.group()
def schedule() -> None:
    """Manage scheduled tasks."""


@schedule.command()
def install() -> None:
    """Install the ingest cron job (every 6 hours).

    Creates a launchd plist on macOS that runs:
        abbot ingest run --market-pages 10 --event-pages 50 --trade-limit 5000

    Every 6 hours (00:00, 06:00, 12:00, 18:00).
    """
    import os
    import subprocess
    from pathlib import Path

    # Find the abbot executable
    venv_bin = Path(__file__).resolve().parents[3] / ".venv" / "bin"
    uv_path = os.path.expanduser("~/.local/bin/uv")

    project_dir = Path(__file__).resolve().parents[3]

    plist_label = "com.abbot.ingest"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{plist_label}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{uv_path}</string>
        <string>run</string>
        <string>abbot</string>
        <string>ingest</string>
        <string>run</string>
        <string>--market-pages</string>
        <string>10</string>
        <string>--event-pages</string>
        <string>50</string>
        <string>--trade-limit</string>
        <string>5000</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{project_dir}</string>

    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    </array>

    <key>StandardOutPath</key>
    <string>{project_dir}/logs/ingest.log</string>

    <key>StandardErrorPath</key>
    <string>{project_dir}/logs/ingest.err</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{os.path.expanduser("~/.local/bin")}:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""

    # Create logs dir
    logs_dir = project_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    # Write plist
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist_content)

    # Load it
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)

    if result.returncode == 0:
        click.echo(f"Scheduled ingest installed.")
        click.echo(f"  Runs every 6 hours (00:00, 06:00, 12:00, 18:00)")
        click.echo(f"  Plist: {plist_path}")
        click.echo(f"  Logs:  {logs_dir}/ingest.log")
        click.echo()
        click.echo("To uninstall: abbot schedule uninstall")
    else:
        click.echo(f"Failed to load: {result.stderr}")


@schedule.command()
def uninstall() -> None:
    """Remove the ingest cron job."""
    import subprocess
    from pathlib import Path

    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.abbot.ingest.plist"

    if not plist_path.exists():
        click.echo("No scheduled ingest found.")
        return

    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    plist_path.unlink()
    click.echo("Scheduled ingest removed.")


@schedule.command()
def status() -> None:
    """Check if the ingest schedule is active."""
    import subprocess
    from pathlib import Path

    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.abbot.ingest.plist"

    if not plist_path.exists():
        click.echo("Not installed. Run: abbot schedule install")
        return

    result = subprocess.run(
        ["launchctl", "list", "com.abbot.ingest"],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        click.echo("Ingest schedule is ACTIVE")
        click.echo(f"  Runs every 6 hours (00:00, 06:00, 12:00, 18:00)")
        click.echo(f"  Plist: {plist_path}")

        # Show last ingest from DB
        try:
            from sqlalchemy import select
            from sqlalchemy.orm import Session
            from abbot.db.engine import get_engine
            from abbot.db.models.raw import IngestLog

            engine = get_engine()
            with Session(engine) as session:
                last = session.execute(
                    select(IngestLog).order_by(IngestLog.started_at.desc()).limit(1)
                ).scalar_one_or_none()
                if last:
                    click.echo(
                        f"  Last ingest: {last.ingest_type} — {last.status} — "
                        f"{last.records_count} records — {last.started_at:%Y-%m-%d %H:%M}"
                    )
        except Exception:
            pass
    else:
        click.echo("Plist exists but schedule is NOT loaded.")
        click.echo("Run: abbot schedule install")
