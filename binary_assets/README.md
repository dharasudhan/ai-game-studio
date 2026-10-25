Binary files (images, audio, fonts, Android plugin libraries, PDFs) are stored here base64-encoded because they were pushed through the GitHub MCP text API.

Restore them after cloning:

    python3 binary_assets/restore.py

Each `<path>.b64` decodes to `<path>` relative to the repo root. iOS plugin libraries and store screenshots/art renders are not included (re-download the poing-godot-admob iOS libs from its release if ever needed).
