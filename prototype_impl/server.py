from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from optimizer import OptimizerParams, LPOptimizer

# === HTTP request handler ===
class RequestHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        print(post_data)

        #try:
        params = OptimizerParams.from_json(post_data)
        result = LPOptimizer().solve(params)
        response = json.dumps(result).encode('utf-8')
        self.send_response(200)
        #except Exception as e:
        #    response = json.dumps({"error": str(e)}).encode('utf-8')
        #    self.send_response(400)

        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

# === Start server ===
def run(server_class=HTTPServer, handler_class=RequestHandler, port=8080):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"🚀 Server running on http://localhost:{port}/")
    httpd.serve_forever()

if __name__ == "__main__":
    run()

