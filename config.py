import configparser


def get_api_key() -> tuple[str, str]:
    config = configparser.ConfigParser()
    config.read('config.ini')
    api = config['last.fm']['api']
    user = config['last.fm']['user']
    return api, user