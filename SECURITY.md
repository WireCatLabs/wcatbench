# Reporting a vulnerability

Please report a security problem privately, never in a public issue:

- by email to [hello@wirecat.dev](mailto:hello@wirecat.dev),
- or through [GitHub's private vulnerability reporting](https://github.com/WireCatLabs/wcatbench/security/advisories/new).

Say what you saw, how to repeat it, and the version (`wcatbench --version`). Never send an API key, a token, a session
or anyone's private content.

What wcatbench handles: keys for hosted memory services, read from the system keyring into its own process and removed
from every log line, and agent transcripts, kept under your data folder (`WCATBENCH_HOME`). See the Security section of
the [README](README.md).
