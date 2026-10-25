# Security and private evidence

Dragons Dogma Dark MCP is a local stdio development server. It is not an authenticated remote service; do not expose its transport to a network. Development mode can build code, launch the supported game and apply journaled file/save changes within configured locations. Keep it read-only unless those operations are intended.

Report suspected vulnerabilities to the repository maintainer through a private channel before disclosing exploit details. Include the package version, platform, affected tool, and a minimal synthetic reproduction. Do not attach game files, saves, minidumps, credentials, personal paths or private traces to a public issue.

Minidumps and native evidence stay in ignored private storage. Review and redact any evidence you choose to share. Recovery markers must be resolved through the recovery tools; deleting a marker bypasses ownership information and is not recovery.
