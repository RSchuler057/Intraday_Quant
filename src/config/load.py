#Loads settings.yaml into python

from pathlib import Path
import yaml

def load_settings() -> dict:
    root = Path(__file__).resolve().parent

    config_path = root / "settings.yaml"

    with open(config_path, "r") as f:
        return yaml.safe_load(f)