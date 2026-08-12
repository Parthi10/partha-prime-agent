from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from ...config import get_settings
from ...integrations.bitbucket import BitbucketProvider
from ...integrations.github import GitHubProvider
from ...integrations.scm import SCMProviderConfig, SCMProviderType
from ...schemas import WebhookResponse
from ...services.webhook_service import WebhookService

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

MAX_REQUEST_SIZE = 1024 * 1024
settings = get_settings()


@router.post("/bitbucket", response_model=WebhookResponse)
async def bitbucket_webhook(
    request: Request,
    x_hub_signature: str | None = Header(default=None, alias="X-Hub-Signature"),
    x_event_key: str | None = Header(default=None, alias="X-Event-Key"),
) -> JSONResponse | WebhookResponse:
    body = await request.body()
    if len(body) > MAX_REQUEST_SIZE:
        raise HTTPException(status_code=413, detail="request_too_large")

    correlation_id = request.headers.get("X-Correlation-ID", "generated")

    service = WebhookService(
        provider=BitbucketProvider(
            SCMProviderConfig(
                provider_type=SCMProviderType.BITBUCKET,
                webhook_secret=settings.bitbucket_webhook_secret,
            )
        )
    )
    try:
        result = await service.handle_webhook(body, x_hub_signature, correlation_id)
    except PermissionError:
        raise HTTPException(status_code=401, detail="authentication_failed") from None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json") from None
    except ValueError as exc:
        if str(exc) == "empty_body":
            raise HTTPException(status_code=400, detail="empty_body") from None
        raise HTTPException(status_code=400, detail="invalid_payload") from None

    return WebhookResponse(status=result["status"], message=result["message"])


@router.post("/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    x_hub_signature: str | None = Header(default=None, alias="X-Hub-Signature"),
) -> JSONResponse | WebhookResponse:
    body = await request.body()
    if len(body) > MAX_REQUEST_SIZE:
        raise HTTPException(status_code=413, detail="request_too_large")

    correlation_id = request.headers.get("X-Correlation-ID", "generated")

    service = WebhookService(
        provider=GitHubProvider(
            SCMProviderConfig(
                provider_type=SCMProviderType.GITHUB,
                webhook_secret=settings.github_webhook_secret,
            )
        )
    )
    try:
        result = await service.handle_webhook(body, x_hub_signature, correlation_id)
    except PermissionError:
        raise HTTPException(status_code=401, detail="authentication_failed") from None
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json") from None
    except ValueError as exc:
        if str(exc) == "empty_body":
            raise HTTPException(status_code=400, detail="empty_body") from None
        raise HTTPException(status_code=400, detail="invalid_payload") from None

    return WebhookResponse(status=result["status"], message=result["message"])
