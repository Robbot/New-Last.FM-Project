from flask import Flask, render_template
from datetime import datetime, timezone
import csv

app = Flask(__name__)

CSV_FILE = "files/lastfmstats.csv"   # update with actual filename

def ms_epoch_to_date(ms_str: str) -> str:
    ms_str = ms_str.strip().strip('"')
    if not ms_str:
        return ""
    try:
        ms = int(ms_str)
    except ValueError:
        return ""

    # convert milliseconds → seconds
    seconds = ms / 1000.0

    # UTC; if you prefer local time, use datetime.fromtimestamp(seconds)
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    # format to your desired style
    return dt.strftime("%Y-%m-%d %H:%M:%S")

@app.route("/")
def index():
    filtered_rows = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=';')
         # Skip the first CSV row
        next(reader, None)
        
        for row in reader:
            try:
                artist = row[0]  # first column
                album = row[1]  # second column
                track = row[3]  # skip row with album id
                epoch_raw= row[4] # epoch time column to convert
            # Convert epoch to human-readable date
                
                date_str = ms_epoch_to_date(epoch_raw)
                filtered_rows.append([artist, album, track, date_str])
            except (IndexError, ValueError):
                continue  # skip malformed rows
    headers = ["Artist", "Album", "Track", "Date"]

    return render_template("table.html", headers=headers, rows=filtered_rows)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8001)