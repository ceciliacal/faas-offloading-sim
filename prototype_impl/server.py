from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from prototype_impl.qos_co2_aware_optimizer import OptCarbonAwareProblemParams, MyLPOptimizer


# === HTTP request handler ===
class RequestHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        print(post_data)

        #try:
        params = OptCarbonAwareProblemParams.from_json(post_data)
        result = MyLPOptimizer().solve(params)
        resp = self.probs_to_nested(result)
        response = json.dumps(resp).encode('utf-8')
        self.send_response(200)
        #except Exception as e:
        #    response = json.dumps({"error": str(e)}).encode('utf-8')
        #    self.send_response(400)

        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def probs_to_nested(self, probs):
        out = {}
        for (func, klass), decisions in probs.items():
            out.setdefault(func, {})[klass] = decisions
        return out

# === Start server ===
def run(server_class=HTTPServer, handler_class=RequestHandler, port=8080):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Server running on http://localhost:{port}/")
    httpd.serve_forever()

if __name__ == "__main__":
    run()

