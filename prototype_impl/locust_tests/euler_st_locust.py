import datetime
import json
from locust import HttpUser, task, tag, constant_throughput


def log_response(filename: str, response, response_time_s: float):
    """Append timestamp + response time + JSON response to a log file."""
    try:
        data = response.json()
    except json.JSONDecodeError:
        data = {"error": "non-json response", "text": response.text}

    line = (
        f"{datetime.datetime.now().isoformat()},"
        f"{response_time_s:.6f},"
        f"{json.dumps(data)}\n"
    )
    with open(filename, "a") as f:
        f.write(line)


class ServerledgeUser(HttpUser):
    """
    Locust user for testing Serverledge /invoke/* endpoints.
    Change --host on the Locust command line to point to your Serverledge gateway.
    """
    # 4 requests per second per user (same as your example: 1/4 seconds between requests)
    wait_time = constant_throughput(1 / 4)

    # Common payload fields – adapt as needed for your setup
    BASE_PAYLOAD = {
        "Params": {},
        "QoSMaxRespT": 0,
        "CanDoOffloading": True,
        "ReturnOutput": True,
        "Async": False
    }

    # ---------- EXAMPLES ----------

    @tag("euler_st")
    @task
    def euler_standard_offloading(self):
        """
        Synchronous invocation of /invoke/euler_st
        with offloading enabled (similar to your original example).
        """
        payload = {
            **self.BASE_PAYLOAD,
            "QoSClass": 1,
        }

        response = self.client.post("/invoke/euler_st", json=payload)
        log_response("euler_standard_offloading_stats.txt", response)
        return response

