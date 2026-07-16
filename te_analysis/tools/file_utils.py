import os
import shutil
from pathlib import Path

def setup_batch_directories(batch_id):
    """
    Locate the raw folder and create the processed output folder for a batch.
    """
    base_dir = os.getcwd()
    
    raw_dir = os.path.join(base_dir, "data", "raw", batch_id)
    processed_dir = os.path.join(base_dir, "data", "processed", f"{batch_id}-processed")
    
    if not os.path.exists(processed_dir):
        os.makedirs(processed_dir)
        print(f"Created processed data folder: {processed_dir}")
    else:
        print(f"Using existing processed data folder: {processed_dir}")
        
    return raw_dir, processed_dir


def flatten_saved_figure_paths(saved_paths):
    if not saved_paths:
        return []
    if isinstance(saved_paths, dict):
        values = saved_paths.values()
    elif isinstance(saved_paths, (list, tuple, set)):
        values = saved_paths
    else:
        values = [saved_paths]
    return [Path(path) for path in values if path]


def copy_saved_figure_outputs(saved_paths, target_dir, formats=None):
    """
    Copy saved figure files to a second output folder.

    Plot helpers usually return only the first saved format even when multiple
    formats were written. This helper derives sibling files for every requested
    format from each returned path and copies the files that exist.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied_paths = []
    seen_sources = set()

    for saved_path in flatten_saved_figure_paths(saved_paths):
        candidate_paths = []
        if formats:
            for file_format in formats:
                suffix = str(file_format).strip().lstrip(".")
                if suffix:
                    candidate_paths.append(saved_path.with_suffix(f".{suffix}"))
        else:
            candidate_paths.append(saved_path)

        for source_path in candidate_paths:
            if not source_path.exists():
                continue
            source_key = str(source_path.resolve())
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)

            target_path = target_dir / source_path.name
            if source_path.resolve() == target_path.resolve():
                continue
            shutil.copy2(source_path, target_path)
            copied_paths.append(str(target_path))

    return copied_paths
