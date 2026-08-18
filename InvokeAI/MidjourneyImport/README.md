# MidjourneyImport

Imports a Midjourney data-export archive into a local folder tree organised by date.  
Each day gets its own sub-folder containing the images, a per-image `.txt` metadata file, and a `_summary_YYYY-MM-DD.txt` overview for the whole day.

## Getting your archive

1. Log in at **midjourney.com**
2. Go to **Account → Download my data** and request an export
3. Wait for the email link, then download the ZIP file

## Setup

```bash
pip install -r requirements.txt
```

Copy `config_sample.yaml` to `config.yaml` and edit it:

```yaml
archive_path: "midjourney_export.zip"   # path to your downloaded ZIP
                                         # supports wildcards, e.g., "midjourney*.zip"
output_path:  "output"                  # where organised images are written
```

## Usage

```bash
# use config.yaml in the same folder
python MidjourneyImport.py

# override paths on the command line
python MidjourneyImport.py --archive path/to/archive.zip --output path/to/output

# process multiple archives with wildcards
python MidjourneyImport.py --archive "midjourney*.zip"

# force reprocess archives that were previously imported
python MidjourneyImport.py --force
python MidjourneyImport.py --archive "midjourney*.zip" --force

# use a custom config file
python MidjourneyImport.py --config my_config.yaml
```

## Output structure

```
output/
  2024-03-15/
    abc123_0.png
    abc123_1.png
    _metadata/
      abc123_0.txt      ← prompt + metadata for that image
      abc123_1.txt
    _summary_2024-03-15.txt   ← all jobs for the day combined
  2024-03-16/
    ...
  unknown-date/         ← jobs with no parseable timestamp
    ...
```

## Archive tracking

The tool tracks which archives have been processed in a `.midjourney_processed_archives.txt` file inside the output folder. On subsequent runs, previously processed archives are automatically skipped.

This is useful when:
- You download new Midjourney exports periodically and want to import only new ones
- Using wildcards like `midjourney*.zip` to process a folder with multiple archives
- Running incremental imports without reprocessing old data

To reprocess all archives regardless of previous imports, use the `--force` flag or set `force_reload: true` in the config.

## Metadata file format

```
Job ID:      <uuid>
Parent ID:   <uuid>     (only for variations / upscales)
Type:        imagine
Created:     2024-03-15 14:30:00 UTC
Size:        1024x1024
File:        abc123_0.png

Prompt:
a beautiful mountain landscape at sunset --v 6 --ar 16:9

Full Command:
/imagine prompt: a beautiful mountain landscape at sunset --v 6 --ar 16:9
```

## Config options

| Key | Default | Description |
|-----|---------|-------------|
| `archive_path` | *(required)* | Path to the Midjourney export ZIP or extracted folder. Supports wildcards (e.g., `midjourney*.zip`) to process multiple archives into the same output folder |
| `output_path` | `output` | Root folder for organised output |
| `date_format` | `%Y-%m-%d` | Python `strftime` format for day-folder names |
| `skip_types` | `[]` | List of job types to exclude (`imagine`, `variation`, `upscale`, `remix`, `inpaint`, `blend`) |
| `skip_existing` | `true` | Skip images already present at the destination (incremental mode) |
| `force_reload` | `false` | Reprocess archives even if previously imported. The tool tracks processed archives in `.midjourney_processed_archives.txt` and skips them by default. Can also use `--force` flag |
| `fallback_date` | `unknown-date` | Folder name for jobs with no timestamp |
