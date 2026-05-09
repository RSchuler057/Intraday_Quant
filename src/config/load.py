#Loads settings.yaml into python
from pathlib import Path
import yaml

def load_settings() -> dict:
    root = Path(__file__).resolve().parent

    config_path = root / "settings.yaml"

    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)