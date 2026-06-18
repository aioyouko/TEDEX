import os

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
