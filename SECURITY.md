# Security and privacy

## Report a problem

Do not open a public issue containing customer media, transcripts, source code, credentials, internal URLs, or generated reports. Send only a minimal synthetic reproduction to the repository maintainer through a private channel.

## Data handling

- Input videos and manifests stay outside the repository.
- Runtime output may contain transcripts and local paths; treat the complete output directory as private data.
- The review server listens on `127.0.0.1` by default and only serves videos explicitly listed by the loaded manifest.
- Never expose the review port directly to the internet. Use an SSH tunnel or an authenticated reverse proxy.
- Do not place API tokens in manifests, command arguments, logs, examples, issues, or commits.
- Before sharing a report, remove local paths, customer identifiers, transcript text, and media links unless the recipient is authorized.

## Production integration

Verify the SHA-256 identity of the input video, expected speech artifact, detector/model versions, and result bundle. Detection remains evidence-only and must not become a quality blocking gate.
