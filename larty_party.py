import os
from flask import Flask, render_template_string

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maintenance</title>
    <style>
        body {
            background-color: #000000;
            color: #ffffff;
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            text-align: center;
        }
        .message-box {
            background-color: #111111;
            border: 1px solid #ca8a04;
            padding: 30px;
            max-width: 500px;
            box-shadow: 0 0 15px rgba(202, 138, 4, 0.3);
        }
        h2 {
            color: #facc15;
            margin-top: 0;
        }
        p {
            color: #d1d5db;
            font-size: 1.1rem;
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <div class="message-box">
        <h2>Notice</h2>
        <p>Due to a security concern, we will temporarily have this shut down until we fix it.</p>
    </div>
</body>
</html>
"""

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def maintenance(path):
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
