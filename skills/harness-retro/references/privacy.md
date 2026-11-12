# Harness Retro Privacy

The system is local-first, not necessarily offline. Discovery, parsing, redaction, SQLite storage, and deterministic metrics are local. Any provider-backed extraction can send selected redacted excerpts outside the machine and requires a clear data-boundary notice first.

## Redaction Before Storage And Provider Calls

Mask at least:

- API keys, bearer tokens, OAuth tokens;
- cookies, session IDs, and Authorization headers;
- private keys and PEM blocks;
- common cloud credentials;
- values assigned to variables containing `TOKEN`, `SECRET`, `PASSWORD`, or `KEY`;
- credentials embedded in URLs;
- user-configured regexes.

Record redaction tags and counts, but never reveal original values.

## Exports

Raw source JSONL is never modified or deleted. Raw payloads are not duplicated into SQLite unless a future explicit option enables it.

Reports should hide absolute project paths and private repository names by default. Enable absolute paths only when the user explicitly asks for a local debugging report and accepts that the output is not safe to share.

Do not publish reports or send them to external systems without separate permission.

## Provider Payloads

When provider analysis is enabled in the future:

- include complete user turns only within the configured limit;
- head-tail assistant turns;
- replace tool calls with name, status, and safe argument digests;
- exclude full tool outputs by default;
- exclude reasoning/thinking by default;
- keep the original instruction and subsequent user correction visible together when validating an episode.
