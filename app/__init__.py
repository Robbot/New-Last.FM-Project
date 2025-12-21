from flask import Flask

def create_app():
    app = Flask(__name__)

    # register blueprints
    # example:
    # from .artists.routes import bp as artists_bp
    # app.register_blueprint(artists_bp, url_prefix="/artists")

    return app
