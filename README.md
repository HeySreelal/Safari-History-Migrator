# Safari to Chrome History Migration Tool

This script allows you to migrate your browsing history from Safari to Google Chrome on macOS.

## Overview

The Safari to Chrome History Migration Tool is a Python utility that extracts browsing history data from Safari and imports it into Chrome, allowing you to transition between browsers without losing your browsing history.

## Features

- Migrates browsing history entries from Safari to Chrome
- Automatic Chrome profile detection and selection
- Handles time format conversion between browsers
- Creates automatic backups of Chrome history files before modification
- Detailed logging for troubleshooting
- Command-line options for customization
- Checks for running browsers to prevent database lock issues

## Requirements

- macOS (tested on macOS 10.15+)
- Python 3.6+
- Safari with browsing history
- Google Chrome installed

## Installation

1. Download the `main.py` file to your computer
2. Make the script executable:
   ```
   chmod +x main.py
   ```

## Usage

### Basic Usage

Run the script from the terminal:

```
./main.py
```

This will:
1. Check for Safari's history database
2. Show available Chrome profiles for selection
3. Create a backup of your Chrome history
4. Extract history from Safari
5. Import the history into your selected Chrome profile
6. Generate a detailed log file for the operation

### Command-line Options

```
usage: main.py [-h] [--safari-path SAFARI_PATH] [--chrome-path CHROME_PATH] 
              [--dry-run] [--limit LIMIT] [--verbose] 
              [--direct-copy-only] [--library-mode]

options:
  -h, --help            show this help message and exit
  --safari-path SAFARI_PATH
                        Custom path to Safari History.db (default: ~/Library/Safari/History.db)
  --chrome-path CHROME_PATH
                        Custom path to Chrome History file
  --dry-run             Dry run - do not modify Chrome history
  --limit LIMIT         Limit the number of history entries to import (0 for all)
  --verbose, -v         Verbose output
  --direct-copy-only    Only copy the Safari History.db file without querying it directly
  --library-mode        Use sqlite3 command line tool instead of Python sqlite library
```

## Example Workflows

### Migrate All History to Default Chrome Profile

```
./main.py
```
Then select the Default profile when prompted.

### Migrate Limited History for Testing

```
./main.py --limit 100 --dry-run
```

### Migrate to a Specific Chrome Profile Path

```
./main.py --chrome-path "/Users/username/Library/Application Support/Google/Chrome/Profile 2/History"
```

### Using Custom Safari History Location

```
./main.py --safari-path "/path/to/History.db"
```

## Troubleshooting

- A log file is automatically created with each run in the format `safari_history_migration_YYYYMMDD_HHMMSS.log`
- If you encounter database lock errors, ensure both Safari and Chrome are completely closed
- The script creates a backup of your Chrome history before making changes
- In case of failure, try running with the `--library-mode` flag

## Important Notes

- The script will create a backup of your Chrome history file before making any changes
- Both Safari and Chrome should be closed during migration to avoid database lock issues
- The script will confirm before finalizing changes to the Chrome history file
- Import performance may vary based on the size of your Safari history
- Some entries may be skipped if they already exist in Chrome's history

## License

This script is licensed under the GNU General Public License v3.0 (GPL-3.0).

## Acknowledgments

This tool works directly with the SQLite databases used by Safari and Chrome to store browsing history.
