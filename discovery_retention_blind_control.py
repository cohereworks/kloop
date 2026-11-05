#!/usr/bin/env python3
"""State-blind deterministic control for retention stress calibration."""

import json
import sys

from discovery_retention_control import respond_state_blind


if __name__ == "__main__":
    json.dump(respond_state_blind(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
