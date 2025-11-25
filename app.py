from flask import Flask, render_template
import csv

app = Flask(__name__)

CSV_FILE = "files/lastfmstats.csv"   # update with actual filename

@app.route("/")
def index():
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=';')
        headers = next(reader)      # first line: column names
        for row in reader:
            rows.append(row)

    return render_template("table.html", headers=headers, rows=rows)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)