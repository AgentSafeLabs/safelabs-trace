"""trace_runner: the 1B traces-on benchmark runner (offline-tested; real model calls only when a real run is started on purpose).

Importing this package sets two environment variables, before any framework is imported, that keep span content and cost-map
downloads off: ADK's span-content switch (default true upstream) is forced to false, and LiteLLM is told to use its bundled
model cost map instead of downloading one at import. Neither is a key or a secret.
"""

import os

ADK_CONTENT_ENV = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"
os.environ[ADK_CONTENT_ENV] = "false"  # must happen before google.adk is imported anywhere in this process
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no download of the cost map when litellm is imported

__version__ = "0.1.0"
