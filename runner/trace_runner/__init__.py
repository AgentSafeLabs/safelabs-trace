"""trace_runner: the 1B traces-on benchmark runner (offline-tested; real model calls only when a real run is started on purpose).

Importing this package sets three environment variables, before any framework is imported: ADK's span-content switch (default true upstream) is forced
to false; LiteLLM is told to use its bundled model cost map instead of downloading one at import; and ADK's "Gemini via LiteLLM" warning is suppressed
(we deliberately use the LiteLLM route for every provider). None is a key or a secret.
"""

import os

ADK_CONTENT_ENV = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"
os.environ[ADK_CONTENT_ENV] = "false"  # must happen before google.adk is imported anywhere in this process
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no download of the cost map when litellm is imported
# All providers run through LiteLLM (decision D4) so that the route is the same for every provider and framework. ADK warns (UserWarning, once per ADK
# LiteLlm built for a gemini/ route) that Gemini would be better used through ADK's native integration; we do not switch routes, so the warning is noise.
os.environ.setdefault("ADK_SUPPRESS_GEMINI_LITELLM_WARNINGS", "true")  # read by google.adk.models.lite_llm; an explicit value set by the user is kept

__version__ = "0.2.0"
