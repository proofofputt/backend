import os
import glob
import re
import argparse
from datetime import datetime
from rich.console import Console
from rich.table import Table
import data_manager
from session_reporter import SessionReporter

# Constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
PROCESSED_LOGS_FILE = os.path.join(LOG_DIR, ".backfill_processed")

def load_processed_logs():
    """Loads the set of timestamps for already processed logs."""
    if not os.path.exists(PROCESSED_LOGS_FILE):
        return set()
    try:
        with open(PROCESSED_LOGS_FILE, 'r') as f:
            return set(line.strip() for line in f)
    except IOError:
        return set()

def save_processed_log(timestamp):
    """Saves a timestamp to the processed logs file."""
    with open(PROCESSED_LOGS_FILE, 'a') as f:
        f.write(timestamp + '\n')

def find_log_pairs():
    """Finds matching pairs of debug and putt classification logs."""
    debug_logs = glob.glob(os.path.join(LOG_DIR, "debug_log_*.txt"))
    putt_logs = glob.glob(os.path.join(LOG_DIR, "putt_classification_log_*.csv"))

    putt_log_map = {
        match.group(1): log
        for log in putt_logs
        if (match := re.search(r'_(\d{8}_\d{6})\.csv$', log))
    }

    log_pairs = [
        {"timestamp": match.group(1), "debug_log": debug_log, "putt_log": putt_log_map[match.group(1)]}
        for debug_log in debug_logs
        if (match := re.search(r'_(\d{8}_\d{6})\.txt$', debug_log)) and match.group(1) in putt_log_map
    ]
    
    return sorted(log_pairs, key=lambda x: x['timestamp'])

def extract_player_info(debug_log_path):
    """Parses the debug log to find the player ID and name for the session."""
    player_info_re = re.compile(r"Session started for: (.*) \(ID: ([-]?\d+)\)")
    try:
        with open(debug_log_path, 'r') as f:
            for line in f:
                if match := player_info_re.search(line):
                    player_id = int(match.group(2))
                    player_name = match.group(1).strip()
                    return player_id, player_name
    except IOError:
        return None, None
    return None, None

def main(dry_run=False, force=False, player_name_arg=None):
    console = Console()
    console.rule("[bold cyan]Starting Stats Backfill Process[/bold cyan]")

    data_manager.initialize_database()
    processed_logs = load_processed_logs()
    if force and not dry_run:
        console.print("[bold yellow]--force flag detected. Clearing processed log history.[/bold yellow]")
        if os.path.exists(PROCESSED_LOGS_FILE):
            os.remove(PROCESSED_LOGS_FILE)
        processed_logs.clear()

    target_player_id = None
    target_player_name = None
    if player_name_arg:
        target_player_id = data_manager.get_player_by_name(player_name_arg)
        if not target_player_id:
            console.print(f"[bold red]Error: Player '{player_name_arg}' not found in the database.[/bold red]")
            return
        target_player_name = player_name_arg
        console.print(f"[bold blue]Guest logs will be assigned to player: {target_player_name} (ID: {target_player_id})[/bold blue]")

    affected_player_ids = set()

    log_pairs = find_log_pairs()
    if not log_pairs:
        console.print("[yellow]No matching debug and putt log files found.[/yellow]")
        return

    table = Table(title="Backfill Plan")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Player Name", style="magenta")
    table.add_column("Putt Log File", style="blue")
    table.add_column("Makes", style="yellow")
    table.add_column("Misses", style="red")
    table.add_column("Status")

    for pair in log_pairs:
        timestamp = pair['timestamp']
        if timestamp in processed_logs and not force:
            table.add_row(timestamp, "[dim]-[/dim]", f"[dim]{os.path.basename(pair['putt_log'])}[/dim]", "-", "-", "[dim]Skipped (Done)[/dim]")
            continue

        session_player_id, session_player_name = extract_player_info(pair['debug_log'])

        # Determine the final player ID and name to use for this log
        final_player_id = session_player_id
        final_player_name = session_player_name

        is_guest_session = (session_player_id is None or session_player_id == -1)

        if is_guest_session and target_player_id:
            # A guest/unknown log was found, and the user wants to assign it.
            final_player_id = target_player_id
            final_player_name = f"{target_player_name} (from Guest)"
        elif is_guest_session:
            # A guest/unknown log was found, but no target player was specified, so skip it.
            table.add_row(timestamp, f"[dim]{session_player_name or 'Unknown'}[/dim]", f"[dim]{os.path.basename(pair['putt_log'])}[/dim]", "-", "-", "[dim]Skipped (Guest)[/dim]")
            if not dry_run:
                save_processed_log(timestamp) # Mark as processed so we don't check it again
            continue

        try:
            reporter = SessionReporter(pair['putt_log'])
            reporter.load_and_process_data()

            status = "[bold yellow]Dry Run[/bold yellow]"
            if not dry_run:
                # Parse the timestamp from the log file to get the historical date
                session_date = datetime.strptime(timestamp, '%Y%m%d_%H%M%S')

                # Create a historical session entry
                data_manager.create_historical_session(final_player_id, session_date, reporter)

                # Add the player to the set of those needing a stats recalculation
                affected_player_ids.add(final_player_id)

                save_processed_log(timestamp)
                status = "[bold green]Processed[/bold green]"
            
            table.add_row(timestamp, final_player_name, os.path.basename(pair['putt_log']), str(reporter.total_makes), str(reporter.total_misses), status)
        except Exception as e:
            table.add_row(timestamp, final_player_name, os.path.basename(pair['putt_log']), "-", "-", f"[bold red]Error: {e}[/bold red]")

    console.print(table)

    if not dry_run and affected_player_ids:
        console.rule("[bold cyan]Recalculating All-Time Stats[/bold cyan]")
        for player_id in sorted(list(affected_player_ids)):
            try:
                player_info = data_manager.get_player_info(player_id)
                player_name = player_info['name'] if player_info else f"ID {player_id}"
                console.print(f"Recalculating for player: [magenta]{player_name}[/magenta]...")
                data_manager.recalculate_player_stats(player_id)
            except Exception as e:
                console.print(f"[bold red]Error recalculating stats for player ID {player_id}: {e}[/bold red]")
        console.print("\n[bold green]Stats recalculation complete.[/bold green]")

    console.print(f"\n[bold]Found {len(log_pairs)} total sessions.[/bold]")
    if dry_run:
        console.print("\n[bold yellow]This was a dry run. No changes were made to the database.[/bold yellow]")
        console.print("Run without the --dry-run flag to apply these changes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill player stats from historical session logs.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without updating the database.")
    parser.add_argument("--force", action="store_true", help="Force reprocessing of all log files.")
    parser.add_argument("--player-name", dest="player_name_arg",
                        help="Assign all guest session stats to this existing player.\nExample: --player-name \"wake@bubblewake.com\"")
    args = parser.parse_args()
    main(**vars(args))