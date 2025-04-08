#!/usr/bin/env python3
import sqlite3
import os
import shutil
import time
import stat
import subprocess
import logging
from pathlib import Path
import tempfile

# Set up logging to file
def setup_logging():
    """Set up logging configuration."""
    log_file = f"safari_history_migration_{time.strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename=log_file,
        filemode='w'
    )
    # Create console handler with a higher log level
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console.setFormatter(console_formatter)
    logging.getLogger('').addHandler(console)
    return log_file

def parse_arguments():
    """Parse command line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate Safari browsing history to Chrome')
    parser.add_argument('--safari-path', type=str, 
                        help='Custom path to Safari History.db (default: ~/Library/Safari/History.db)')
    parser.add_argument('--chrome-path', type=str, 
                        help='Custom path to Chrome History file')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Dry run - do not modify Chrome history')
    parser.add_argument('--limit', type=int, default=0,
                        help='Limit the number of history entries to import (0 for all)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    parser.add_argument('--direct-copy-only', action='store_true',
                        help='Only copy the Safari History.db file without querying it directly')
    parser.add_argument('--library-mode', action='store_true',
                        help='Use sqlite3 command line tool instead of Python sqlite library')
    
    return parser.parse_args()

def get_chrome_profiles():
    """Find available Chrome profiles."""
    home = Path.home()
    chrome_user_data_dir = home / "Library/Application Support/Google/Chrome"
    
    if not chrome_user_data_dir.exists():
        logging.warning(f"Chrome user data directory not found at {chrome_user_data_dir}")
        return []
    
    # Look for profile directories
    profiles = []
    
    # Add Default profile if it exists
    default_profile = chrome_user_data_dir / "Default"
    if default_profile.exists() and (default_profile / "History").exists():
        profiles.append(("Default", default_profile))
    
    # Find all Profile N directories
    profile_dirs = list(chrome_user_data_dir.glob("Profile *"))
    for profile_dir in sorted(profile_dirs):
        if (profile_dir / "History").exists():
            profile_name = profile_dir.name
            profiles.append((profile_name, profile_dir))
    
    return profiles

def select_chrome_profile():
    """Let user select a Chrome profile."""
    profiles = get_chrome_profiles()
    
    if not profiles:
        logging.error("No Chrome profiles found. Please ensure Chrome is installed.")
        print("No Chrome profiles found. Please ensure Chrome is installed.")
        return None
    
    print("\nAvailable Chrome profiles:")
    for i, (name, path) in enumerate(profiles, 1):
        print(f"{i}. {name} ({path})")
    
    while True:
        try:
            print("\nSelect a Chrome profile (number) or enter a custom path to Chrome profile folder:")
            print("Tip: You can find your Chrome profile path in chrome://version")
            choice = input("Selection: ")
            
            # Check if input is a number
            if choice.isdigit() and 1 <= int(choice) <= len(profiles):
                _, profile_path = profiles[int(choice) - 1]
                return profile_path / "History"
            
            # Otherwise, treat it as a custom path
            custom_path = Path(choice)
            if custom_path.exists():
                if custom_path.is_dir() and (custom_path / "History").exists():
                    # User entered a profile directory
                    return custom_path / "History"
                elif custom_path.is_file():
                    # User directly entered a History file path
                    return custom_path
                else:
                    print("Invalid path: No History file found in this directory.")
            else:
                print("Path does not exist. Please try again.")
                
        except (ValueError, IndexError):
            print("Invalid selection. Please try again.")

def check_file_permissions(file_path):
    """Check file permissions and print detailed information."""
    try:
        if not os.path.exists(file_path):
            return f"File does not exist: {file_path}"
        
        # Get file stats
        st = os.stat(file_path)
        permissions = stat.filemode(st.st_mode)
        owner_uid = st.st_uid
        group_gid = st.st_gid
        
        # Try to get owner and group names
        import pwd
        import grp
        try:
            owner_name = pwd.getpwuid(owner_uid).pw_name
        except KeyError:
            owner_name = f"UID: {owner_uid}"
        
        try:
            group_name = grp.getgrgid(group_gid).gr_name
        except KeyError:
            group_name = f"GID: {group_gid}"
        
        # Check if the current user can read the file
        current_uid = os.getuid()
        current_user = pwd.getpwuid(current_uid).pw_name
        
        can_read = os.access(file_path, os.R_OK)
        
        result = (
            f"File: {file_path}\n"
            f"Size: {st.st_size} bytes\n"
            f"Permissions: {permissions}\n"
            f"Owner: {owner_name} (UID: {owner_uid})\n"
            f"Group: {group_name} (GID: {group_gid})\n"
            f"Current user: {current_user} (UID: {current_uid})\n"
            f"Current user can read file: {'Yes' if can_read else 'No'}"
        )
        
        logging.debug(result)
        return result
    except Exception as e:
        logging.error(f"Error checking file permissions: {e}")
        return f"Error checking file permissions: {e}"

def check_database_status(db_path):
    """Check the status of an SQLite database using command-line tools."""
    logging.debug(f"Checking database status for: {db_path}")
    if not os.path.exists(db_path):
        return "File does not exist"
    
    # Check if the database is valid
    try:
        result = subprocess.run(
            ["sqlite3", str(db_path), "PRAGMA integrity_check;"],
            capture_output=True, text=True
        )
        if "ok" in result.stdout.lower():
            logging.debug("Database integrity check passed")
        else:
            logging.warning(f"Database integrity check failed: {result.stdout}")
        
        # Try to get the list of tables
        tables_result = subprocess.run(
            ["sqlite3", str(db_path), ".tables"],
            capture_output=True, text=True
        )
        if tables_result.stdout.strip():
            logging.debug(f"Tables found: {tables_result.stdout.strip()}")
            return "Database appears to be valid"
        else:
            return "Database is empty or corrupted"
    except Exception as e:
        logging.error(f"Error checking database: {e}")
        return f"Error checking database: {e}"

def extract_safari_history_with_sqlite3(safari_path, limit=0):
    """Extract Safari history using SQLite3 command-line tool."""
    try:
        # Create a temporary directory for our work
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_db_path = os.path.join(temp_dir, "safari_history_temp.db")
            
            # Copy the database to our temporary location
            logging.info(f"Copying Safari history database...")
            logging.debug(f"Copying Safari history database to {temp_db_path}...")
            shutil.copy2(safari_path, temp_db_path)
            
            # Make it readable
            os.chmod(temp_db_path, 0o644)
            
            # Check if the copy was successful
            if not os.path.exists(temp_db_path):
                logging.error("Failed to copy Safari database")
                return None
                
            # Check if the database is valid
            check_database_status(temp_db_path)
            
            # Prepare the SQL query - limiting if needed
            limit_clause = f"LIMIT {limit}" if limit > 0 else ""
            sql_query = f"""
            SELECT hi.id, hi.url, hv.visit_time, hv.title
            FROM history_items hi
            JOIN history_visits hv ON hi.id = hv.history_item
            WHERE hi.url IS NOT NULL
            ORDER BY hv.visit_time DESC
            {limit_clause};
            """
            
            # Create a script file for sqlite3
            sql_script_path = os.path.join(temp_dir, "extract_query.sql")
            with open(sql_script_path, 'w') as f:
                f.write(sql_query)
            
            # Create an output file
            output_path = os.path.join(temp_dir, "results.csv")
            
            # Run the SQL query and save results in CSV format
            result = subprocess.run(
                ["sqlite3", "-csv", temp_db_path, f".read {sql_script_path}"],
                capture_output=True, text=True
            )
            
            if result.returncode != 0:
                logging.error(f"Error executing SQLite query: {result.stderr}")
                # Try a different command structure
                try:
                    # First, check what tables exist
                    table_result = subprocess.run(
                        ["sqlite3", temp_db_path, ".tables"],
                        capture_output=True, text=True
                    )
                    logging.debug(f"Tables in database: {table_result.stdout}")
                    
                    # Try a simpler query
                    simple_query = "SELECT * FROM history_items LIMIT 5;"
                    simple_result = subprocess.run(
                        ["sqlite3", temp_db_path, simple_query],
                        capture_output=True, text=True
                    )
                    if simple_result.returncode == 0 and simple_result.stdout:
                        logging.debug("Simple query succeeded, adjusting approach...")
                    else:
                        logging.error(f"Simple query failed: {simple_result.stderr}")
                except Exception as e:
                    logging.error(f"Error with fallback query: {e}")
                return None
            
            # Parse the CSV output
            import csv
            from io import StringIO
            
            # Process the output as CSV
            reader = csv.reader(StringIO(result.stdout))
            history_entries = []
            
            for row in reader:
                if len(row) >= 4:  # We expect at least 4 columns
                    history_entries.append((row[0], row[1], row[2], row[3]))
            
            logging.info(f"Extracted {len(history_entries)} entries from Safari history")
            logging.debug(f"Extracted {len(history_entries)} entries using sqlite3 command-line")
            
            # Log a few entries as samples
            if history_entries:
                logging.debug("\nSample entries:")
                for i, entry in enumerate(history_entries[:3]):
                    logging.debug(f"Entry {i+1}: ID={entry[0]}, URL={entry[1]}, Time={entry[2]}, Title={entry[3]}")
            
            return history_entries
    except Exception as e:
        logging.error(f"Error extracting Safari history with sqlite3: {e}")
        return None

def copy_safari_database_and_extract(safari_path, limit=0):
    """Create a copy of the Safari database and extract history."""
    try:
        # Create a temporary directory for our work
        temp_dir = tempfile.mkdtemp(prefix="safari_migration_")
        temp_db_path = os.path.join(temp_dir, "safari_history_temp.db")
        
        logging.info(f"Copying Safari history database...")
        logging.debug(f"Copying Safari history database to {temp_db_path}...")
        shutil.copy2(safari_path, temp_db_path)
        
        # Set permissions to make sure it's readable and writable
        os.chmod(temp_db_path, 0o644)
        
        # Check if the file was copied successfully
        if not os.path.exists(temp_db_path):
            logging.error("Failed to copy Safari database")
            return None
        
        # Print information about the copied file
        check_file_permissions(temp_db_path)
        
        # Connect to the copied database
        logging.debug("Connecting to copied Safari database...")
        try:
            # Set timeout to avoid hanging
            conn = sqlite3.connect(temp_db_path, timeout=5)
            cursor = conn.cursor()
            
            # Check if the connection works
            try:
                cursor.execute("PRAGMA integrity_check;")
                result = cursor.fetchone()
                if result and result[0] == "ok":
                    logging.debug("Database integrity check passed")
                else:
                    logging.warning(f"Database integrity check failed: {result}")
            except sqlite3.OperationalError as e:
                logging.error(f"Error checking database integrity: {e}")
                # Try to force database recovery
                try:
                    logging.debug("Attempting database recovery...")
                    recovery_path = os.path.join(temp_dir, "recovered.db")
                    cursor.execute(f"VACUUM INTO '{recovery_path}';")
                    
                    # Close and reopen with the recovered database
                    conn.close()
                    conn = sqlite3.connect(recovery_path)
                    cursor = conn.cursor()
                    logging.debug("Recovery completed")
                except Exception as recovery_error:
                    logging.error(f"Recovery failed: {recovery_error}")
                    return None
            
            # Get the list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            logging.debug(f"Tables found: {[table[0] for table in tables]}")
            
            # Check if we have the expected tables
            if not any('history_' in table[0] for table in tables):
                logging.error("No history tables found - database might be corrupted or empty")
                return None
            
            # Query the database for history entries
            query = """
            SELECT hi.id, hi.url, hv.visit_time, hv.title
            FROM history_items hi
            JOIN history_visits hv ON hi.id = hv.history_item
            WHERE hi.url IS NOT NULL
            ORDER BY hv.visit_time DESC
            """
            
            # Add limit if specified
            if limit > 0:
                query += f" LIMIT {limit}"
            
            cursor.execute(query)
            history_entries = cursor.fetchall()
            
            logging.info(f"Extracted {len(history_entries)} entries from Safari history")
            logging.debug(f"Extracted {len(history_entries)} entries from copied database")
            
            # Show a sample of the entries
            if history_entries:
                logging.debug("\nSample entries:")
                for i, entry in enumerate(history_entries[:3]):
                    logging.debug(f"Entry {i+1}: ID={entry[0]}, URL={entry[1]}, Time={entry[2]}, Title={entry[3]}")
            
            conn.close()
            return history_entries
            
        except sqlite3.OperationalError as e:
            logging.error(f"Error connecting to copied database: {e}")
            # Fall back to command line sqlite3
            logging.debug("Falling back to sqlite3 command-line tool...")
            return extract_safari_history_with_sqlite3(temp_db_path, limit)
            
    except Exception as e:
        logging.error(f"Error in copy_safari_database_and_extract: {e}")
        return None
    finally:
        # Clean up
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logging.error(f"Error cleaning up temporary directory: {e}")

def main():
    # Initialize count variables before any exceptions can occur
    imported_count = 0
    skipped_count = 0
    
    # Setup logging
    log_file = setup_logging()
    logging.info(f"Safari to Chrome history migration started. Logs will be saved to {log_file}")
    
    try:
        # Parse command line arguments
        args = parse_arguments()
        
        # Define paths
        home = Path.home()
        safari_history_path = Path(args.safari_path) if args.safari_path else home / "Library/Safari/History.db"
        
        # Get Chrome path either from arguments or by selection
        if args.chrome_path:
            chrome_history_path = Path(args.chrome_path)
        else:
            # Let user select a Chrome profile
            chrome_history_path = select_chrome_profile()
            if not chrome_history_path:
                logging.error("No Chrome profile selected. Exiting.")
                print("No Chrome profile selected. Exiting.")
                return
        
        # Print file information
        logging.info(f"Safari history path: {safari_history_path}")
        logging.info(f"Chrome history path: {chrome_history_path}")
        
        # Check if files exist
        if not safari_history_path.exists():
            logging.error(f"Safari history file not found at {safari_history_path}")
            print(f"ERROR: Safari history file not found at {safari_history_path}")
            return
        
        if not chrome_history_path.exists():
            logging.error(f"Chrome history file not found at {chrome_history_path}")
            print(f"ERROR: Chrome history file not found at {chrome_history_path}")
            return
        
        # Print file permissions
        logging.debug("\n--- Safari History File Permissions ---")
        logging.debug(check_file_permissions(safari_history_path))
        logging.debug("\n--- Chrome History File Permissions ---")
        logging.debug(check_file_permissions(chrome_history_path))
        
        # Check for running browsers
        logging.info("\nChecking for running browser processes...")
        
        # Check Safari
        safari_running = False
        try:
            safari_process = subprocess.run(["pgrep", "Safari"], capture_output=True, text=True)
            if safari_process.stdout.strip():
                logging.warning("Safari appears to be running.")
                safari_pids = safari_process.stdout.strip().split('\n')
                logging.debug(f"Safari process IDs: {safari_pids}")
                safari_running = True
                print("⚠️ Safari appears to be running.")
        except Exception as e:
            logging.error(f"Could not check if Safari is running: {e}")
        
        # Check Chrome
        chrome_running = False
        try:
            chrome_process = subprocess.run(["pgrep", "Chrome"], capture_output=True, text=True)
            if chrome_process.stdout.strip():
                logging.warning("Chrome appears to be running.")
                chrome_pids = chrome_process.stdout.strip().split('\n')
                logging.debug(f"Chrome process IDs: {chrome_pids}")
                chrome_running = True
                print("⚠️ Chrome appears to be running.")
        except Exception as e:
            logging.error(f"Could not check if Chrome is running: {e}")
        
        # Warn if browsers are running
        if safari_running or chrome_running:
            logging.warning("One or more browsers appear to be running.")
            print("\n⚠️ WARNING: One or more browsers appear to be running.")
            print("This may cause issues with database access or result in incomplete migration.")
            proceed = input("Do you want to proceed anyway? (yes/no): ")
            if proceed.lower() != 'yes':
                logging.info("Migration cancelled by user. Browsers still running. Please close all browsers and try again.")
                return
            logging.info("Proceeding despite browsers running. This may cause issues.")
        
        # Create backup of Chrome history
        chrome_backup_path = chrome_history_path.with_suffix('.backup')
        logging.info(f"Creating backup of Chrome history...")
        logging.debug(f"Creating backup of Chrome history at {chrome_backup_path}")
        try:
            shutil.copy2(chrome_history_path, chrome_backup_path)
        except Exception as e:
            logging.error(f"Failed to create Chrome history backup: {e}")
            print(f"ERROR: Failed to create Chrome history backup: {e}")
            return
        
        # Copy Chrome history to a temporary file
        temp_chrome_path = chrome_history_path.with_suffix('.temp')
        logging.debug(f"Creating temporary copy of Chrome history at {temp_chrome_path}")
        try:
            shutil.copy2(chrome_history_path, temp_chrome_path)
        except PermissionError:
            logging.error("Cannot access Chrome history file. Chrome might be running.")
            print("ERROR: Cannot access Chrome history file. Chrome might be running.")
            print("Please close Chrome completely and try again.")
            return
        except Exception as e:
            logging.error(f"Could not copy Chrome history: {e}")
            print(f"ERROR: Could not copy Chrome history: {e}")
            return
        
        # Extract Safari history data using the appropriate method
        logging.info("Extracting Safari history data...")
        safari_history = None
        
        if args.library_mode:
            logging.debug("Using sqlite3 command-line tool as requested...")
            safari_history = extract_safari_history_with_sqlite3(safari_history_path, args.limit)
        else:
            logging.debug("Using database copy method...")
            safari_history = copy_safari_database_and_extract(safari_history_path, args.limit)
        
        if not safari_history:
            logging.error("Failed to extract Safari history data. Cannot proceed with migration.")
            print("Failed to extract Safari history data. Cannot proceed with migration.")
            return
        
        logging.info(f"Successfully extracted {len(safari_history)} history entries from Safari")
        
        # Connect to Chrome history database
        logging.info("Connecting to Chrome history database...")
        chrome_conn = sqlite3.connect(temp_chrome_path)
        chrome_cursor = chrome_conn.cursor()
        
        # Process and insert data into Chrome
        logging.info("Processing and inserting data into Chrome...")
        
        # Dictionary to map Safari URL IDs to Chrome URL IDs
        url_id_mapping = {}
        
        # Apply limit if specified
        if args.limit > 0 and len(safari_history) > args.limit:
            safari_history = safari_history[:args.limit]
            logging.info(f"Limiting import to {args.limit} entries")
        
        total_entries = len(safari_history)
        logging.info(f"Processing {total_entries} entries...")
        
        for safari_id, url, visit_time, title in safari_history:
            # Skip empty URLs
            if not url:
                continue
                
            # Check if URL already exists in Chrome
            chrome_cursor.execute("SELECT id FROM urls WHERE url = ?", (url,))
            existing_url = chrome_cursor.fetchone()
            
            if existing_url:
                # URL exists, use existing ID
                chrome_url_id = existing_url[0]
                url_id_mapping[safari_id] = chrome_url_id
                skipped_count += 1
                if args.verbose:
                    logging.debug(f"URL already exists in Chrome: {url}")
            else:
                # URL doesn't exist, insert it
                # Convert Safari's visit_time to Chrome's format
                # Safari uses seconds since 2001-01-01, Chrome uses microseconds since 1601-01-01
                safari_epoch = 978307200  # 2001-01-01 in Unix time (seconds from 1970-01-01)
                chrome_epoch_offset = 11644473600  # Seconds between 1601-01-01 and 1970-01-01
                
                # First convert Safari time to Unix timestamp (seconds since 1970-01-01)
                try:
                    # Try to convert visit_time to float/int if it's a string
                    if isinstance(visit_time, str):
                        visit_time = float(visit_time)
                    
                    unix_time = safari_epoch + float(visit_time)
                    
                    # Then convert to Chrome time (microseconds since 1601-01-01)
                    chrome_time = int((unix_time + chrome_epoch_offset) * 1000000)  # Convert to microseconds
                except (ValueError, TypeError) as e:
                    logging.error(f"Error converting time for URL {url}: {e}")
                    # Use current time as fallback
                    chrome_time = int((time.time() + chrome_epoch_offset) * 1000000)
                
                # For debugging
                if imported_count < 5 or args.verbose:
                    safari_time_readable = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(unix_time))
                    logging.debug(f"Safari time: {visit_time} → Unix time: {unix_time} ({safari_time_readable}) → Chrome time: {chrome_time}")
                
                # Insert new URL into Chrome
                try:
                    chrome_cursor.execute("""
                        INSERT INTO urls (url, title, visit_count, typed_count, last_visit_time, hidden)
                        VALUES (?, ?, 1, 0, ?, 0)
                    """, (url, title or '', chrome_time))
                    
                    chrome_url_id = chrome_cursor.lastrowid
                    url_id_mapping[safari_id] = chrome_url_id
                    
                    # Insert visit information
                    chrome_cursor.execute("""
                        INSERT INTO visits (url, visit_time, transition, visit_duration, is_known_to_sync, 
                                        consider_for_ntp_most_visited, visited_link_id)
                        VALUES (?, ?, 805306368, 0, 1, 1, 0)
                    """, (chrome_url_id, chrome_time))
                    
                    imported_count += 1
                    
                    # Commit every 100 entries to avoid large transactions
                    if imported_count % 100 == 0 and not args.dry_run:
                        chrome_conn.commit()
                        logging.info(f"Imported {imported_count} entries so far...")
                    elif imported_count % 100 == 0 and args.dry_run:
                        logging.info(f"Would import {imported_count} entries (dry run)")
                except sqlite3.Error as sql_error:
                    logging.error(f"Error inserting URL {url}: {sql_error}")
                    continue
        
        # Commit remaining changes
        if not args.dry_run:
            chrome_conn.commit()
            logging.info(f"Successfully imported {imported_count} entries from Safari to Chrome")
            logging.info(f"Skipped {skipped_count} entries (already in Chrome history)")
        else:
            logging.info(f"Dry run completed. Would have imported {imported_count} entries")
            logging.info(f"Skipped {skipped_count} entries (already in Chrome history)")
        
    except Exception as e:
        logging.error(f'Error: {e}')
        import traceback
        error_traceback = traceback.format_exc()
        logging.error(f"An error occurred:\n{error_traceback}")
        print(f'Error: {e}')
        print("Check the log file for more details.")
        
        if 'chrome_backup_path' in locals() and os.path.exists(chrome_backup_path):
            logging.info("Restoring Chrome history from backup...")
            try:
                shutil.copy2(chrome_backup_path, chrome_history_path)
                logging.info("Chrome history backup restored.")
            except Exception as restore_error:
                logging.error(f"Error restoring backup: {restore_error}")
        
    finally:
        # Close connections
        if 'chrome_conn' in locals() and chrome_conn:
            chrome_conn.close()
        
        # Replace Chrome history with our modified version
        if 'temp_chrome_path' in locals() and os.path.exists(temp_chrome_path) and imported_count > 0 and not args.dry_run:
            # Chrome must not be running for this to work
            logging.info("Preparing to replace Chrome history with updated version...")
            print("NOTE: Make sure Chrome is completely closed before confirming.")
            confirm = input("Is Chrome closed? (yes/no): ")
            
            if confirm.lower() == 'yes':
                try:
                    shutil.copy2(temp_chrome_path, chrome_history_path)
                    logging.info("Chrome history successfully updated.")
                except Exception as e:
                    logging.error(f"Error updating Chrome history: {e}")
                    print(f"Error updating Chrome history: {e}")
                    print("Chrome might still be running. Close it completely and try again.")
            else:
                logging.info("Operation cancelled by user. Chrome history not updated.")
        elif 'args' in locals() and args.dry_run:
            logging.info("Dry run mode - not updating Chrome history file.")
            print("Dry run mode - not updating Chrome history file.")
        
        # Clean up temporary file
        if 'temp_chrome_path' in locals() and os.path.exists(temp_chrome_path):
            try:
                os.remove(temp_chrome_path)
                logging.debug("Temporary Chrome history file removed.")
            except Exception as e:
                logging.error(f"Error removing temporary Chrome history file: {e}")
            
        if 'chrome_backup_path' in locals() and os.path.exists(chrome_backup_path):
            logging.info(f"Done. Original Chrome history backup is at: {chrome_backup_path}")
if __name__ == "__main__":
    main()
