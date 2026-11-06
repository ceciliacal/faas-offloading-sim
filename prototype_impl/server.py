from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from prototype_impl.qos_co2_aware_optimizer import OptCarbonAwareProblemParams, MyLPOptimizer


# === HTTP request handler ===
class RequestHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        print(post_data)

        # try:
        params = OptCarbonAwareProblemParams.from_json(post_data)

        # result: dict[(func, class)] -> {decisionName: prob}
        # decision_fc_probability_var:
        #     dict[func][variant][class] -> PuLP variable
        result, decision_fc_probability_var = MyLPOptimizer(params).solve()

        # Nest the main decision probs as: func -> class -> decision -> prob
        probs_nested = self.probs_to_nested(result)

        # Nest variant probs as: func -> variant -> class -> float
        var_probs_nested = self.var_probs_to_nested(decision_fc_probability_var)

        # Build the combined response object expected by Go:
        # {
        #   "probs": {...},
        #   "decision_fc_probability_var": {...}
        # }
        resp = {
            "probs": probs_nested,
            "decision_fc_probability_var": var_probs_nested,
        }

        response = json.dumps(resp).encode('utf-8')
        self.send_response(200)
        # except Exception as e:
        #     response = json.dumps({"error": str(e)}).encode('utf-8')
        #     self.send_response(400)

        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def probs_to_nested(self, probs):
        out = {}
        for (func, klass), decisions in probs.items():
            out.setdefault(func, {})[klass] = decisions
        return out

    def var_probs_to_nested(self, decision_fc_probability_var):
        """
        Convert decision_fc_probability_var (dict: func -> variant -> class -> LpVar)
        into a plain nested dict: func -> variant -> class -> float
        suitable for JSON serialization.
        """
        out = {}
        for func, by_variant in decision_fc_probability_var.items():
            func_dict = out.setdefault(func, {})
            for variant_name, by_class in by_variant.items():
                variant_dict = func_dict.setdefault(variant_name, {})
                for klass, lp_var in by_class.items():
                    # lp_var is a PuLP variable, extract its value
                    variant_dict[klass] = float(lp_var.varValue)
        return out


# === Start server ===
def run(server_class=HTTPServer, handler_class=RequestHandler, port=8080):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"Server running on http://localhost:{port}/")
    httpd.serve_forever()

if __name__ == "__main__":
    run()

