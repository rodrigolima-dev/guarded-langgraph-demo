# Security

This is an offline example with fictional data. It has no credentials, external endpoints, model provider, telemetry, or deployment configuration. Do not paste operational documents, prompts, keys, customer data, or private URLs into source, tests, issues, or screenshots.

The CLI profiles are examples, not user authentication. The in-memory tenant check must not be reused as a production data policy. The optional lexical retry can perform one additional read only after authorization; both reads use the same selected tenant, but membership is checked once per invocation. This is not a rate limit, a dynamic membership check, or a storage access policy. A production integration needs a trusted principal, storage-level tenant enforcement, review of retrieved content before model use, and a separate security assessment.

If you find a vulnerability, use GitHub's private vulnerability reporting for this repository when available. Do not put exploit details or sensitive values in a public issue.
