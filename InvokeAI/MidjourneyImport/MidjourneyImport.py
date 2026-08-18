#!/usr/bin/env python3
"""
MidjourneyImport.py
Imports a Midjourney data export archive to a local output folder, organized by date.
Supports wildcards for processing multiple archives (e.g., midjourney*.zip).
Tracks processed archives and skips them by default (use --force to reprocess).

Usage:
    python MidjourneyImport.py
    python MidjourneyImport.py --config path/to/config.yaml
    python MidjourneyImport.py --archive path/to/archive.zip --output path/to/output
    python MidjourneyImport.py --archive "midjourney*.zip"
    python MidjourneyImport.py --archive "midjourney*.zip" --force
"""

import os
import json
import zipfile
import shutil
import yaml
import argparse
import glob
from datetime import datetime
from pathlib import Path
from tqdm import tqdm

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(config_path):
    print(f">> Loading configuration from {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Metadata parsing helpers
# ---------------------------------------------------------------------------

_TS_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]

def parse_timestamp(value):
    """Return a datetime from an ISO-style string, or None on failure."""
    if not value:
        return None
    s = str(value)
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def job_timestamp(job):
    """Try several field names to extract a datetime from a job record."""
    for field in ("created_at", "enqueue_time", "timestamp", "date", "createdAt"):
        ts = parse_timestamp(job.get(field))
        if ts:
            return ts
    return None


def job_type(job):
    for field in ("event_type", "type", "jobType", "job_type"):
        v = job.get(field)
        if v:
            return str(v).lower()
    return "unknown"


def job_image_paths(job):
    """Return the list of relative image paths declared by the job."""
    for field in ("image_paths", "imagePaths", "images", "files"):
        v = job.get(field)
        if v:
            return v if isinstance(v, list) else [v]
    # Fall back to deriving a path from the job UUID
    jid = job.get("id", "")
    if jid:
        return [f"images/{jid}_0.png"]
    return []


def format_metadata(job, image_filename=""):
    """Format a job's metadata as a human-readable text block."""
    lines = []
    lines.append(f"Job ID:      {job.get('id', 'N/A')}")

    parent = job.get("parent_id") or job.get("parentId", "")
    if parent:
        lines.append(f"Parent ID:   {parent}")

    lines.append(f"Type:        {job_type(job)}")

    ts = job_timestamp(job)
    if ts:
        lines.append(f"Created:     {ts.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    w = job.get("width") or job.get("image_width", "")
    h = job.get("height") or job.get("image_height", "")
    if w and h:
        lines.append(f"Size:        {w}x{h}")

    if image_filename:
        lines.append(f"File:        {image_filename}")

    prompt = job.get("prompt") or job.get("clean_prompt", "")
    if prompt:
        lines.append(f"\nPrompt:\n{prompt}")

    full_cmd = (
        job.get("full_command")
        or job.get("fullCommand", "")
        or (job.get("event") or {}).get("full_command", "")
    )
    if full_cmd and full_cmd != prompt:
        lines.append(f"\nFull Command:\n{full_cmd}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Archive loading
# ---------------------------------------------------------------------------

def _load_jobs_from_data(data):
    """Normalise various JSON structures to a plain list of job dicts."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("jobs", "data", "items", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


def _find_jobs_file(names):
    """Return the best candidate jobs/metadata filename from a list."""
    priority = []
    for n in names:
        base = Path(n).name.lower()
        if base == "jobs.json":
            priority.insert(0, n)
        elif "job" in base and base.endswith(".json"):
            priority.append(n)
        elif "metadata" in base and base.endswith(".json"):
            priority.append(n)
    if not priority:
        # last resort: any JSON at the root level
        priority = [n for n in names if n.endswith(".json") and "/" not in n.lstrip("/")]
    return priority[0] if priority else None


def load_jobs(archive_path):
    """Load and return a list of job dicts from a ZIP or extracted folder.
    Returns an empty list if no metadata is found (allowing image-only imports)."""
    archive_path = Path(archive_path)

    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            candidate = _find_jobs_file(zf.namelist())
            if not candidate:
                print(">> No metadata JSON found in archive - will import images only")
                return []
            print(f">> Reading metadata: {candidate}")
            with zf.open(candidate) as f:
                data = json.load(f)

    elif archive_path.is_dir():
        candidates = (
            list(archive_path.glob("*jobs*.json"))
            + list(archive_path.glob("*metadata*.json"))
            + list(archive_path.glob("*.json"))
        )
        if not candidates:
            print(f">> No JSON metadata file found in {archive_path} - will import images only")
            return []
        candidate = candidates[0]
        print(f">> Reading metadata: {candidate}")
        with open(candidate, "r", encoding="utf-8") as f:
            data = json.load(f)

    else:
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    jobs = _load_jobs_from_data(data)
    print(f">> Found {len(jobs)} jobs in metadata")
    return jobs


# ---------------------------------------------------------------------------
# Archive image index
# ---------------------------------------------------------------------------

def build_image_index(archive_path):
    """
    Return a dict mapping bare filename -> full path within the archive.
    For a folder, maps bare filename -> absolute Path on disk.
    """
    archive_path = Path(archive_path)
    index = {}

    if archive_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_path, "r") as zf:
            for name in zf.namelist():
                if not name.endswith("/"):
                    index[Path(name).name] = name
    elif archive_path.is_dir():
        for p in archive_path.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                index[p.name] = p

    return index


# ---------------------------------------------------------------------------
# Archive tracking
# ---------------------------------------------------------------------------

def get_processed_archives_file(output_path):
    """Return the path to the file tracking processed archives."""
    return Path(output_path) / ".midjourney_processed_archives.txt"


def load_processed_archives(output_path):
    """Load the set of previously processed archive paths."""
    processed_file = get_processed_archives_file(output_path)
    if not processed_file.exists():
        return set()
    with open(processed_file, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_archive_processed(archive_path, output_path):
    """Mark an archive as processed by appending to the tracking file."""
    processed_file = get_processed_archives_file(output_path)
    archive_path = str(Path(archive_path).resolve())
    with open(processed_file, "a", encoding="utf-8") as f:
        f.write(archive_path + "\n")


def is_archive_processed(archive_path, output_path):
    """Check if an archive has been processed before."""
    processed = load_processed_archives(output_path)
    archive_path = str(Path(archive_path).resolve())
    return archive_path in processed


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_archive(archive_path, output_path, config):
    archive_path = Path(archive_path)
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    date_format = config.get("date_format", "%Y-%m-%d")
    skip_types_cfg = {s.lower() for s in config.get("skip_types", [])}
    skip_existing = config.get("skip_existing", True)
    fallback_date = config.get("fallback_date", "unknown-date")

    jobs = load_jobs(archive_path)

    # Filter by job type
    if skip_types_cfg and jobs:
        before = len(jobs)
        jobs = [j for j in jobs if job_type(j) not in skip_types_cfg]
        print(f">> Skipped {before - len(jobs)} jobs by type filter")

    # Build filename index for fast lookup
    print(">> Building image index...")
    image_index = build_image_index(archive_path)
    print(f">> Indexed {len(image_index)} image files")

    is_zip = archive_path.suffix.lower() == ".zip"

    # daily_entries: date_str -> [(image_filenames, metadata_text)]
    daily_entries = {}

    stats = {"copied": 0, "skipped": 0, "missing": 0}

    with (
        zipfile.ZipFile(archive_path, "r") if is_zip else _NullContext()
    ) as zf:

        # If no jobs metadata, import all images directly
        if not jobs:
            print(">> Importing images without metadata...")
            for bare_name, src in tqdm(image_index.items(), desc="Importing images", unit="file"):
                # Use file modification time if available, otherwise fallback date
                try:
                    if is_zip:
                        info = zf.getinfo(src)
                        file_time = datetime(*info.date_time) if info.date_time else None
                    else:
                        file_time = datetime.fromtimestamp(src.stat().st_mtime)
                    date_str = file_time.strftime(date_format) if file_time else fallback_date
                except:
                    date_str = fallback_date
                
                day_folder = output_path / date_str
                day_folder.mkdir(parents=True, exist_ok=True)
                target = day_folder / bare_name

                if skip_existing and target.exists():
                    stats["skipped"] += 1
                    continue

                if is_zip:
                    with zf.open(src) as fsrc, open(target, "wb") as fdst:
                        shutil.copyfileobj(fsrc, fdst)
                else:
                    shutil.copy2(str(src), str(target))

                stats["copied"] += 1
        
        else:
            # Process with metadata
            for job in tqdm(jobs, desc="Importing images", unit="job"):
                ts = job_timestamp(job)
                date_str = ts.strftime(date_format) if ts else fallback_date
                day_folder = output_path / date_str
                day_folder.mkdir(parents=True, exist_ok=True)

                img_paths = job_image_paths(job)
                saved_names = []
                meta_folder = day_folder / "_metadata"

                for img_path in img_paths:
                    bare_name = Path(img_path).name
                    target = day_folder / bare_name

                    if skip_existing and target.exists():
                        stats["skipped"] += 1
                        saved_names.append(bare_name)
                        continue

                    src = image_index.get(bare_name)
                    if src is None:
                        tqdm.write(f"  [WARN] Not found in archive: {img_path}")
                        stats["missing"] += 1
                        continue

                    if is_zip:
                        with zf.open(src) as fsrc, open(target, "wb") as fdst:
                            shutil.copyfileobj(fsrc, fdst)
                    else:
                        shutil.copy2(str(src), str(target))

                    stats["copied"] += 1
                    saved_names.append(bare_name)

                    meta_folder.mkdir(exist_ok=True)
                    meta_path = meta_folder / (target.stem + ".txt")
                    with open(meta_path, "w", encoding="utf-8") as f:
                        f.write(format_metadata(job, bare_name))

                # Accumulate for daily summary
                if saved_names:
                    if date_str not in daily_entries:
                        daily_entries[date_str] = []
                    daily_entries[date_str].append((saved_names, format_metadata(job)))

    # Write per-day summary files (only if we have metadata)
    if daily_entries:
        print("\n>> Writing daily summaries...")
        for date_str, entries in sorted(daily_entries.items()):
            summary_path = output_path / date_str / f"_summary_{date_str}.txt"
            total_imgs = sum(len(e[0]) for e in entries)
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"Midjourney Import — {date_str}\n")
                f.write(f"Jobs: {len(entries)}  |  Images: {total_imgs}\n")
                f.write("=" * 60 + "\n\n")
                for img_names, meta in entries:
                    f.write(f"Files: {', '.join(img_names)}\n")
                    f.write(meta + "\n")
                    f.write("-" * 60 + "\n\n")

    total_days = len(daily_entries)
    print(
        f"\n>> Done."
        f"\n   Imported : {stats['copied']} images"
        f"\n   Skipped  : {stats['skipped']} (already existed)"
        f"\n   Missing  : {stats['missing']} (not found in archive)"
        f"\n   Days     : {total_days}"
        f"\n   Output   : {output_path.resolve()}"
    )
    
    # Mark this archive as processed
    mark_archive_processed(archive_path, output_path)


class _NullContext:
    """Context manager no-op for the folder case."""
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Import a Midjourney data export archive into dated local folders."
    )
    parser.add_argument(
        "--config", default=CONFIG_FILE,
        help="Path to config YAML (default: config.yaml next to this script)"
    )
    parser.add_argument("--archive", help="Override archive_path from config")
    parser.add_argument("--output", help="Override output_path from config")
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Force reprocessing of archives that have already been imported"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    archive_pattern = args.archive or config.get("archive_path")
    output_path = args.output or config.get("output_path", "output")

    if not archive_pattern:
        parser.error(
            "archive_path not set. Provide it in config.yaml or with --archive."
        )

    # Expand wildcards in the archive path
    matched_archives = glob.glob(archive_pattern)
    
    if not matched_archives:
        # If no matches, check if it's a literal path that exists
        if os.path.exists(archive_pattern):
            matched_archives = [archive_pattern]
        else:
            parser.error(
                f"No archives found matching pattern: {archive_pattern}"
            )
    
    print(f">> Found {len(matched_archives)} archive(s) matching pattern: {archive_pattern}")
    
    # Check for force flag from config or command line
    force_reload = args.force or config.get("force_reload", False)
    
    # Filter out already-processed archives unless force is enabled
    archives_to_process = []
    skipped_count = 0
    
    for archive_path in sorted(matched_archives):
        if not force_reload and is_archive_processed(archive_path, output_path):
            skipped_count += 1
            print(f">> Skipping already processed: {archive_path}")
        else:
            archives_to_process.append(archive_path)
    
    if skipped_count > 0:
        print(f">> Skipped {skipped_count} previously processed archive(s) (use --force to reprocess)")
    
    if not archives_to_process:
        print(">> No archives to process. All matched archives have been previously imported.")
        print(">> Use --force to reprocess them.")
        return
    
    print(f">> Will process {len(archives_to_process)} archive(s)\n")
    
    # Process each matched archive
    for idx, archive_path in enumerate(archives_to_process, 1):
        if len(archives_to_process) > 1:
            print(f"\n{'='*70}")
            print(f">> Processing archive {idx}/{len(archives_to_process)}: {archive_path}")
            print(f"{'='*70}")
        
        process_archive(archive_path, output_path, config)


if __name__ == "__main__":
    main()
