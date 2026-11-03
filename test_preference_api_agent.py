import io
import json
import unittest
from unittest.mock import patch

import preference_api_agent


class PreferenceApiAgentTests(unittest.TestCase):
    def test_uses_private_preference_protocol_and_does_not_guess_from_k(self):
        request = {"schema": "kloop-private-preference-v1", "human_signal": "K",
                   "task": {"alternatives": list(range(8))}}
        response = {"action": {"type": "propose", "option": 0},
                    "message": "Request direct feedback", "metrics": {"total_tokens": 8}}
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(request))), \
                patch("sys.stdout", output), \
                patch("preference_api_agent.call_model", return_value=response) as caller:
            self.assertEqual(preference_api_agent.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), response)
        self.assertEqual(caller.call_args.args[0], request)
        instructions = caller.call_args.kwargs["instructions"]
        self.assertIn('"type":"propose"', instructions)
        self.assertIn('"type":"commit"', instructions)
        self.assertIn("K means only 'continue'", instructions)
        self.assertIn("not encoded", instructions)


if __name__ == "__main__":
    unittest.main()
