# Security

**Der Gutachter** processes health data locally. Please report security
vulnerabilities **privately**, not as a public issue.

Use GitHub's private vulnerability reporting ("Security" tab → "Report a
vulnerability") for this repository.

This is a non-commercial research prototype maintained without any service-level
commitment (see [DISCLAIMER.md](DISCLAIMER.md)). Reports are welcome and will be
looked at on a best-effort basis; there is no guarantee of a fix or a timeline.

Scope that matters most:

- any path by which case data could leave the machine;
- access to the local API (127.0.0.1) from other processes or websites;
- integrity of downloaded models and runtime components (checksums);
- the installer and update path.
