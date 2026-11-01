# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue.

Use GitHub's private reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Only the
maintainer can see the report.

Please include what you found, how to reproduce it, and what an attacker could do with it. You will get a reply as
soon as possible, and credit in the fix if you want it.

## Scope

Mainframe reads system information and, if you configure them, connects to your own machines over your existing SSH
setup and runs Omarchy's own agent-usage collectors. Issues that matter most:

- anything that lets Mainframe write to, change or run things on a machine beyond reading its status;
- anything that exposes credentials, tokens or private data on screen, in logs or over the network;
- anything that leaves processes running after Mainframe closes.

## Supported versions

Only the latest release receives security fixes.
