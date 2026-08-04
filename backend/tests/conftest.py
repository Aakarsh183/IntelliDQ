"""Test environment setup.

This runs before any test module is imported, which matters: main_app.py builds a
GrokClient() at module scope, and GrokClient.__init__ constructs an AzureOpenAI
client. The openai SDK raises if api_key or azure_endpoint is missing, so importing
main_app with no Azure config set fails outright.

Placeholders are enough - constructing an AzureOpenAI client performs no network
I/O. No test here may call a live LLM: that would be slow, cost money and make CI
flaky. If a real key is already in the environment (or a local .env), it is left
alone, but nothing in this suite reaches the API either way.
"""

import os

_PLACEHOLDER_ENV = {
    "AZURE_OPENAI_API_KEY": "placeholder-key-not-used-by-tests",
    "AZURE_OPENAI_ENDPOINT": "https://placeholder.invalid/",
    "AZURE_OPENAI_API_VERSION": "2024-02-01",
    "AZURE_OPENAI_DEPLOYMENT": "placeholder-deployment",
    "GROK_API_KEY": "placeholder-key-not-used-by-tests",
    "GROK_BASE_URL": "https://placeholder.invalid/",
}

for _name, _value in _PLACEHOLDER_ENV.items():
    os.environ.setdefault(_name, _value)
