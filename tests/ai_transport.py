"""Provide the selection prelude for tests focused on CAD generation."""
import inspect
import json

import httpx
from cadstudio.native.cad_scope import TOOLS, SHAPES


def is_scope(request):
    return {'tools','shapes'} <= set(json.loads(request.content)['format'].get('properties', {}))


def scope_response(tools=TOOLS, shapes=SHAPES):
    return httpx.Response(200, json={'done': True, 'message': {'content': json.dumps(dict(tools=tools, shapes=shapes))}})


def cad_transport(handle):
    async def wrapped(request):
        if is_scope(request):
            return scope_response()
        result = handle(request)
        return await result if inspect.isawaitable(result) else result
    return httpx.MockTransport(wrapped)
