from http.server import BaseHTTPRequestHandler
import json

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🏥 Medi Hospital Platform</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background-color: #f4f6f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 20px 15px;
        }
        .app-card {
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.08);
            padding: 25px;
            margin-bottom: 20px;
            border-top: 5px solid #0066cc;
        }
        .badge-status {
            background-color: #28a745;
            color: white;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
        }
        .btn-launch {
            background: linear-gradient(135deg, #0066cc, #004499);
            color: white;
            border: none;
            border-radius: 12px;
            padding: 14px 20px;
            font-weight: 600;
            width: 100%;
            text-decoration: none;
            display: inline-block;
            text-align: center;
            margin-top: 10px;
        }
        .btn-launch:hover {
            color: white;
            opacity: 0.95;
        }
        .feature-icon {
            font-size: 1.5rem;
            margin-right: 10px;
        }
    </style>
</head>
<body>
    <div class="container max-width-md" style="max-width: 600px; margin: 0 auto;">
        <div class="text-center my-4">
            <h2 class="fw-bold text-dark">🏥 Medi Hospital Platform</h2>
            <p class="text-muted">Mobile & Web Clinical Management System</p>
            <span class="badge-status">● Live & Operational</span>
        </div>

        <div class="app-card">
            <h5 class="fw-bold text-primary mb-3">📱 Access on Mobile Phone</h5>
            <p class="text-secondary small">
                The Medi Hospital Platform is fully optimized for mobile devices. Access queue management, emergency, bed tracking, and patient records directly from your phone.
            </p>
            <a href="https://github.com/peteribunny55-ship-it/medi" target="_blank" class="btn-launch mb-2">
                📦 View Source Repository on GitHub
            </a>
            <a href="https://share.streamlit.io" target="_blank" class="btn btn-outline-primary w-100 py-2 mt-2 style-btn" style="border-radius: 12px; font-weight: 600;">
                🚀 Deploy to Streamlit Community Cloud (1-Click)
            </a>
        </div>

        <div class="app-card" style="border-top-color: #28a745;">
            <h6 class="fw-bold text-dark mb-3">⚡ Quick Local Mobile Access (Same Wi-Fi)</h6>
            <ol class="small text-muted ps-3 mb-0">
                <li class="mb-2">Run <code>deploy_mobile.bat</code> or <code>python deploy.py</code> on your PC.</li>
                <li class="mb-2">Connect phone to the same Wi-Fi network as PC.</li>
                <li class="mb-0">Open your mobile browser to the Network URL shown in terminal.</li>
            </ol>
        </div>

        <div class="text-center text-muted small mt-4">
            <p>© 2025 Medi Hospital Platform • peteribunny55-ship-it</p>
        </div>
    </div>
</body>
</html>
"""
        self.wfile.write(html_content.encode('utf-8'))
