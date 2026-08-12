# Milestone 2 architecture notes

## Scope

Milestone 2 introduces the first webhook-driven workflow intake path for Bitbucket pull request events. The implementation is intentionally narrow: it validates incoming webhook authenticity, parses only supported PR events, applies idempotency, persists the incoming PR context, and creates a queued workflow run.

## Components

- SCM provider abstraction for future GitHub and GitLab support
- Bitbucket provider implementation for V1 webhook validation and payload parsing
- Webhook service for persistence and workflow creation
- FastAPI webhook endpoint at /api/v1/webhooks/bitbucket

## Security notes

- The raw request body is read before parsing.
- The webhook signature is validated using constant-time comparison.
- Request size is capped to 1 MB.
- Authentication headers, tokens, and full payloads are not logged.

## Persistence behavior

- Incoming events are deduplicated using provider event ID when available and payload hash as fallback.
- Supported PR events are stored as repository, pull request, webhook event, workflow run, and audit log records.
- The workflow run is created with execution status queued.
- No scanners, repository clones, merge blocking, or LLM integrations are executed in this milestone.
