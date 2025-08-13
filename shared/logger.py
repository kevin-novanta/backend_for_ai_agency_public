

import logging
import os

def setup_logger(name="default_logger", log_file_path="/Users/kevinnovanta/backend_for_ai_agency/api/Google_Sheets/Lead_Registry_Sync/logs/logger_output.txt"):
    # Create logs directory if it doesn't exist
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if re-used
    if not logger.handlers:
        file_handler = logging.FileHandler(log_file_path)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger