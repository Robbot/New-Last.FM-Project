from flask import Flask, render_template, request, url_for
from datetime import datetime, timezone
import math
import db
from flask import abort

app = Flask(__name__)

from app.artists.routes import artists_bp, artists_library_bp
app.register_blueprint(artists_bp)
app.register_blueprint(artists_library_bp)


@app.route("/")
def index():
    # all_rows = load_rows()
    all_rows = db.get_latest_scrobbles()

    per_page = 50
    page = request.args.get("page", 1, type=int)

    total_rows = len(all_rows)
    total_pages = max(1, math.ceil(total_rows / per_page))

    # clamp page within range
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    page_rows = all_rows[start:end]

    print("total_rows:", total_rows)
    print("per_page:", per_page)
    print("total_pages:", total_pages)
    print("current page:", page)


    return render_template(
        "table.html",
        rows=page_rows,
        page=page,
        total_pages=total_pages,
        total_rows=total_rows,
    )


                 





if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8001)