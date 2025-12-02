import configparser
from pathlib import Path


def get_api_key() -> tuple[str, str]:
    config = configparser.ConfigParser()

    # Path to config.ini next to this file, regardless of current working dir
    config_path = Path(__file__).resolve().parent / "config.ini"

    read_files = config.read(config_path)
    if not read_files:
        raise FileNotFoundError(f"config.ini not found at: {config_path}")

    section = config["last.fm"]          # your existing section name
    api_key = section["api"]
    username = section["user"]

    return api, user
