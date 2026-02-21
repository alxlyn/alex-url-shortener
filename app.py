import string
import secrets
from flask import Flask, render_template, request, redirect

app = Flask(__name__)
url_map = {}

@app.route("/")
def home():
    return render_template("index.html", short_url=None)

@app.route("/shorten", methods=["POST"])
def shorten():
    long_url = request.form.get("long_url", "").strip()
    code = generate_code()
    url_map[code] = long_url
    short_url = request.host_url + code
    return render_template("index.html", short_url=short_url, long_url=long_url)

@app.route("/<code>")
def redirect_to_url(code):
    long_url = url_map.get(code)
    if long_url:
        return redirect(long_url)
    return "URL not found", 404

def generate_code(length=6):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

if __name__ == "__main__":
    app.run(debug=True)
