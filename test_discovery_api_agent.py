import io
import json
import unittest
from unittest.mock import patch

import discovery_api_agent


class DiscoveryApiAgentTests(unittest.TestCase):
    def test_uses_action_protocol_instead_of_expression_repair(self):
        request = {"schema": "kloop-discovery-v1", "observations": [],
                   "human_signal": "K"}
        response = {"action": {"type": "probe", "x": 0, "y": 1},
                    "message": "probe next", "metrics": {"total_tokens": 8}}
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(request))), \
                patch("sys.stdout", output), \
                patch("discovery_api_agent.call_model", return_value=response) as caller:
            self.assertEqual(discovery_api_agent.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), response)
        self.assertEqual(caller.call_args.args[0], request)
        self.assertIn('"type":"probe"', caller.call_args.kwargs["instructions"])


if __name__ == "__main__":
    unittest.main()
