from unittest.mock import patch

import pytest

from app.assistant.agent import _model, answer_agent
from app.config import settings


@pytest.mark.anyio
async def test_ollama_request_uses_supported_limit_and_timeout() -> None:
    class Intercepted(Exception):
        pass

    expected_limit = settings.chat_max_output_tokens
    expected_timeout = settings.ollama_timeout_seconds

    async def inspect(**request):
        assert request['max_tokens'] == expected_limit
        assert request['timeout'] == expected_timeout
        assert request['response_format']['type'] == 'json_schema'
        assert 'citations' in request['response_format']['json_schema']['schema']['required']
        assert request['response_format']['json_schema']['schema']['$defs']['Citation']['required'] == ['chunk_id']
        raise Intercepted

    with (
        patch.object(_model.client.chat.completions, 'create', inspect),
        pytest.raises(Intercepted),
    ):
        await answer_agent.run('Audit')
