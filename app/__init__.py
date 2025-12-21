from flask import Flask

def create_app():
    app = Flask(__name__)

    from .scrobbles import scrobbles_bp
    from .artists import artists_bp
    from .albums import albums_bp
    from .tracks import tracks_bp


    app.register_blueprint(scrobbles_bp)
    app.register_blueprint(artists_bp)
    app.register_blueprint(albums_bp)
    app.register_blueprint(tracks_bp)
    
    return app
