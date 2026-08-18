# InvokeDBToFiles

A Python utility that reads an [InvokeAI](https://github.com/invoke-ai/InvokeAI) SQLite database and exports generated images into an organized file-based archive. It also supports syncing images from the archive back into an InvokeAI database.

---

## What it does

InvokeAI stores information about generated images (metadata, board assignments, timestamps) in a local SQLite database (`invokeai.db`). Image files themselves live in InvokeAI's `images/` folder but are not organized in any meaningful folder structure.

This script solves two related problems:

### 1. Backup mode (default)

Copies images out of the InvokeAI `images/` folder and organizes them into two parallel directory trees inside a target archive folder:

- **Sessions folder** (e.g., `_SESSIONS/`) — images grouped by creation date:
  ```
  _SESSIONS/
    2024-01-15/
      abc123.png
      def456.png
    2024-01-16/
      ghi789.png
  ```

- **Boards folder** (e.g., `_BOARDS/`) — images grouped by their InvokeAI board name:
  ```
  _BOARDS/
    Portraits/
      abc123.png
    Landscapes/
      def456.png
  ```

Non-board images (not assigned to any board) are only copied to the sessions folder.

The script performs **incremental backups** by default — it checks the timestamp of the last `images_catalog.json` and only processes images created or updated since then. Set `full_update: true` in the manifest to force a full re-scan.

After copying, it generates an `images_catalog.json` file in the archive root with metadata for every image (name, board, file paths, generation metadata).

The script also creates a **timestamped backup** of `invokeai.db` in the configured backup directory before processing.

### 2. Sync mode (`sync_boards: true`)

> [!WARNING]
> **Sync mode is potentially destructive and should be used with caution.**
>
> - **Back up your InvokeAI database and `images/` folder before running sync mode.** The script writes directly to InvokeAI's database and image directories. Mistakes are difficult to undo.
> - **Back up your archive folders** (`_BOARDS/`, `_SESSIONS/`) as well — the recommended workflow requires emptying them after a successful sync, and you do not want to lose your only copy.
> - Run sync mode **only once** per migration. After it completes, empty your archive folder and switch `sync_boards` back to `false` before the next normal backup run. Failing to do so will cause duplicate processing and potential data inconsistency.
> - **Do not run InvokeAI while sync mode is active.** Writing to the database while InvokeAI is open may corrupt it.

Reads images from the archive's boards and sessions folders and imports them back into a target InvokeAI database. Useful for:

- Migrating images between InvokeAI installations or versions
- Restoring images after a database reset

In sync mode the script:
- Scans every subfolder of the boards/sessions archive directories
- Skips images that already exist in the target database
- Copies new images into InvokeAI's `images/` folder (updating metadata format to `invokeai_metadata` 3.0+ if needed)
- Generates WebP thumbnails in InvokeAI's `thumbnails/` folder
- Creates boards in the database if they don't already exist
- Adds each image to its board

> **Note:** Run sync mode once, then empty your archive folder and set `sync_boards` back to `false` before the next backup run to avoid duplicate processing.

---

## Files

| File | Description |
|---|---|
| `InvokeDBToFiles.py` | Main script — entry point and all backup/sync logic |
| `InvokeDBAPI.py` | Database and image utility module (SQLite access, metadata parsing, file helpers) |
| `invokedb_manifest_sample.json` | Template configuration file — copy and rename to `invokedb_manifest.json` |
| `invokedb_manifest.json` | Your local configuration (not committed to source control) |
| `requirements.txt` | Python package dependencies |

---

## Requirements

- Python 3.8+
- Install dependencies:

```bash
pip install -r requirements.txt
```

Dependencies: `pandas`, `Pillow`, `tqdm`

---

## Setup

1. Copy `invokedb_manifest_sample.json` to `invokedb_manifest.json`.
2. Edit `invokedb_manifest.json` with your actual paths (see [Configuration](#configuration) below).
3. Run the script:

```bash
python InvokeDBToFiles.py
```

---

## Configuration

The script reads all settings from `invokedb_manifest.json`. The file must be present in the same directory as the script.

### Top-level keys

| Key | Type | Description |
|---|---|---|
| `target_path` | string | Root folder where the archive will be written |
| `sessions_folder_name` | string | Name of the date-organized subfolder (e.g. `_SESSIONS`) |
| `boards_folder_name` | string | Name of the board-organized subfolder (e.g. `_BOARDS`) |
| `invokedb_list` | array | One entry per InvokeAI installation to process |

### Per-instance keys (`invokedb_list` entries)

| Key | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Display name shown in progress output |
| `db_file` | string | Yes | Full path to `invokeai.db` |
| `source_path` | string | Yes | Full path to InvokeAI's `images/` folder |
| `backup_path` | string | Yes | Folder where timestamped database backups are saved |
| `thumbnail_path` | string | Sync only | Full path to InvokeAI's `images/thumbnails/` folder |
| `full_update` | boolean | Yes | `true` = process all images; `false` = incremental since last run |
| `sync_boards` | boolean | Yes | `true` = sync archive → database; `false` = backup database → archive |

### Example `invokedb_manifest.json`

```json
{
    "target_path": "E:\\Documents\\GenerativeAI\\_InvokeAI-Archive\\",
    "sessions_folder_name": "_SESSIONS",
    "boards_folder_name": "_BOARDS",
    "invokedb_list": [
        {
            "name": "InvokeAI-5.0",
            "db_file": "E:\\Documents\\GenerativeAI\\Invoke\\databases\\invokeai.db",
            "source_path": "E:\\Documents\\GenerativeAI\\Invoke\\images\\",
            "thumbnail_path": "E:\\Documents\\GenerativeAI\\Invoke\\images\\thumbnails\\",
            "backup_path": "E:\\Documents\\GenerativeAI\\Invoke\\databases\\_backups\\",
            "full_update": false,
            "sync_boards": false
        }
    ]
}
```

Multiple InvokeAI installations can be listed in `invokedb_list` and will be processed sequentially.

---

## Output

### Archive folder structure

```
<target_path>/
  images_catalog.json        ← full image catalog with metadata
  _SESSIONS/
    2024-01-15/
      abc123.png
    2024-01-16/
      def456.png
      ghi789.png
  _BOARDS/
    Portraits/
      abc123.png
    Landscapes/
      def456.png
```

Images assigned to a board appear in **both** `_BOARDS/<BoardName>/` and `_SESSIONS/<date>/`.  
Images not assigned to any board appear only in `_SESSIONS/<date>/`.

Non-general image categories (e.g., `control`, `mask`, `user`) are placed in a matching subfolder under their date or board folder.

### `images_catalog.json`

A JSON file written to `target_path` containing:

```json
{
  "last_updated": "2024-01-16",
  "images": [
    {
      "name": "abc123.png",
      "board": "Portraits",
      "session_file_path": "...\\_SESSIONS\\2024-01-15\\abc123.png",
      "board_file_path": "...\\_BOARDS\\Portraits\\abc123.png",
      "type": "general",
      "metadata": { ... }
    }
  ]
}
```

---

## Metadata compatibility

`InvokeDBAPI.py` can read and convert image metadata from all InvokeAI versions:

| Metadata field | InvokeAI version |
|---|---|
| `dream` / `Dream` | Pre-1.15 |
| `sd-metadata` | 1.15 – 2.3.5 |
| `invokeai` | 2.x |
| `invokeai_metadata` | 3.0+ (no conversion needed) |

Older metadata formats are converted to the 3.0+ `invokeai_metadata` format when copying files during sync mode.

---

## Known limitations

- Incremental updates do not detect board assignment changes for existing images (only new or updated images are re-evaluated for board membership).
- `sync_boards` mode requires `thumbnail_path` to be set in the manifest; the script will fail without it.
- The `repair_image_dates_db` function is present in the code but commented out in the main execution block — it is an internal maintenance helper and not part of the normal workflow.
