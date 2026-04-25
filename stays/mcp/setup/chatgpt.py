"""ChatGPT MCP setup — instructions only.

ChatGPT (Desktop + web) supports ONLY remote HTTPS MCP endpoints.
Local stdio servers cannot be registered, and there is no local config
file to edit. This module emits copy-pasteable instructions + a
deep-link into the ChatGPT Connectors settings page.

`stays` is a read-only tool with no per-user state, so it can be
registered as an **unauthenticated** connector — ChatGPT Developer Mode
explicitly allows "No authentication" for anonymous/read-only servers.
OAuth 2.1 + Dynamic Client Registration (RFC 7591) is only required
when the server needs to access per-user credentials.

Confirmed 2026-04 against:
- https://developers.openai.com/apps-sdk/deploy/connect-chatgpt
- https://developers.openai.com/apps-sdk/build/auth
- https://help.openai.com/en/articles/12584461-developer-mode-apps-and-full-mcp-connectors-in-chatgpt-beta
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Settings URL — use the stable settings root rather than a fragment that
# OpenAI has renamed in the past ("Connectors" -> "Apps & Connectors" -> "Apps").
# Users navigate to Settings -> Apps & Connectors themselves.
SETTINGS_URL = "https://chatgpt.com/#settings"


@dataclass
class ChatGPTInstructions:
    settings_url: str = SETTINGS_URL
    messages: list[str] = field(default_factory=list)


def build() -> ChatGPTInstructions:
    out = ChatGPTInstructions()
    out.messages = [
        "`stays` can be connected to ChatGPT as an unauthenticated (read-only)",
        "connector. No OAuth implementation is required.",
        "",
        "ChatGPT does NOT support plain HTTP on 127.0.0.1 — you must expose",
        "`stays mcp-http` over a public HTTPS URL first.",
        "",
        "To set up a ChatGPT connector for `stays`:",
        "",
        "  1. Start the HTTP server:",
        "        stays mcp-http",
        "     (Listens on http://127.0.0.1:8000 by default.)",
        "",
        "  2. Expose it over public HTTPS. Easiest options:",
        "        a) cloudflared tunnel (free, no account required):",
        "              cloudflared tunnel --url http://127.0.0.1:8000",
        "        b) ngrok:",
        "              ngrok http 8000",
        "     Either prints a public URL like https://<id>.trycloudflare.com.",
        "",
        "     Security note: anyone who discovers this URL can call the server.",
        "     Tear down the tunnel when you are not actively using it.",
        "",
        "  3. Ensure you are on a paid ChatGPT plan that includes Developer",
        "     Mode (Plus, Pro, Business, Enterprise, or Edu; workspace plans",
        "     may require an admin to enable it). Toggle Developer Mode ON:",
        "        Settings → Apps & Connectors → Advanced → Developer Mode.",
        "",
        f"     Settings root: {SETTINGS_URL}",
        "     (Navigate to 'Apps & Connectors' from there — the exact",
        "     tab label has changed more than once and may differ.)",
        "",
        "  4. In that panel, click 'Create':",
        "       • Name: stays",
        "       • URL:  https://<your-tunnel>/mcp",
        "       • Auth: No authentication",
        "     Save and verify that the tool list appears in a new chat.",
    ]
    return out
