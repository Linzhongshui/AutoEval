"""Pinned native multimodal requests; HTTP is intercepted, no paid inference."""

import base64
import copy
import hashlib
import json
import os
import struct
import subprocess
import zlib

import pytest
from test_mmmu_native_live import bridge, fixture, invoke

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_MMMU_NATIVE_TEST"), reason="Pinned native Docker tool required"
)


@pytest.fixture(scope="module")
def sample_payload():
    fixture()
    sample = bridge(
        {
            "operation": "prepare_mmmu_pro_options10",
            "tsv_path": "/work/tools/aisbench/mmmu-fixture/fixture.tsv",
        }
    )["samples"][0]
    return {
        "sample": sample["native_sample"],
        "images": sample["images"],
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "max_tokens": 32,
    }


def normalize(body):
    body = copy.deepcopy(body)
    for message in body["messages"]:
        for part in message["content"]:
            if part["type"] == "image_url":
                url = part["image_url"]["url"]
                raw = base64.b64decode(url.split(",", 1)[1], validate=True)
                part["image_url"]["url"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return body


def test_wire_matches_native_template_parser_and_model_body_without_materialized_files(
    sample_payload,
):
    adapted = bridge({**sample_payload, "operation": "request_mmmu_pro_options10_cot"})
    direct = invoke(
        [
            "-c",
            """
import asyncio,contextlib,hashlib,json,sys
from pathlib import Path
with contextlib.redirect_stdout(sys.stderr):
 from ais_bench.benchmark.datasets.mmmu_pro import MMMUProOptions10Dataset
 from ais_bench.benchmark.configs.datasets.mmmu_pro.mmmu_pro_options10_cot_gen import mmmu_pro_infer_cfg
 from ais_bench.benchmark.openicl.icl_prompt_template import MMPromptTemplate
 from ais_bench.benchmark.models.api_models.vllm_custom_api_chat import VLLMCustomAPIChat
 from ais_bench.benchmark.models.output import RequestOutput
 row=MMMUProOptions10Dataset.load('/work/tools/aisbench/mmmu-fixture/fixture.tsv',is_cot=True)[0]
 prompt=MMPromptTemplate(template=mmmu_pro_infer_cfg['prompt_template']['template']).generate_item({'content':row['content']},output_field='answer')
 model=VLLMCustomAPIChat(model='deepseek-flash',url='https://api.deepseek.com',retry=1,max_out_len=32,generation_kwargs={'temperature':0,'top_p':1,'thinking':{'type':'disabled'}})
 body=asyncio.run(model.get_request_body(model.parse_template(prompt,mode='gen'),32,RequestOutput()))
 for message in body['messages']:
  for part in message['content']:
   if part['type']=='image_url':
    raw=Path(part['image_url']['url'][7:]).read_bytes()
    part['image_url']['url']='sha256:'+hashlib.sha256(raw).hexdigest()
print(json.dumps(body))
""",
        ],
        {},
    )
    assert normalize(adapted["request_body"]) == json.loads(direct.stdout)
    assert "data:" not in adapted["prompt"] and "/work/" not in adapted["prompt"]
    assert "file://image:" in adapted["prompt"]
    assert adapted["input_images"][0]["sha256"] == sample_payload["images"][0]["sha256"]
    assert adapted["input_images"][0]["mime_type"] in {"image/jpeg", "image/png"}
    assert "base64" not in adapted["input_images"][0]


@pytest.mark.parametrize("invalid", ["hash", "external", "extra_image", "format"])
def test_invalid_or_unbound_images_are_rejected_before_any_request(sample_payload, invalid):
    payload = copy.deepcopy(sample_payload)
    if invalid == "hash":
        payload["images"][0]["sha256"] = "0" * 64
    elif invalid == "external":
        payload["sample"]["content"] = payload["sample"]["content"].replace(
            "image:" + payload["images"][0]["sha256"], "https://unapproved.invalid/image.png"
        )
    elif invalid == "format":
        payload["images"][0]["base64"] = base64.b64encode(b"not-an-image").decode()
        payload["images"][0]["sha256"] = hashlib.sha256(b"not-an-image").hexdigest()
    else:
        # Valid 1x1 RGB PNG, intentionally absent from the sample's native tags.
        def chunk(kind, data):
            return (
                struct.pack("!I", len(data))
                + kind
                + data
                + struct.pack("!I", zlib.crc32(kind + data))
            )

        raw = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b"")
        )
        payload["images"].append(
            {"base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    with pytest.raises(subprocess.CalledProcessError):
        bridge({**payload, "operation": "request_mmmu_pro_options10_cot"})


HTTP_FIXTURE = """
import asyncio,contextlib,importlib.util,json,sys
from pathlib import Path
import aiohttp
request=json.load(sys.stdin)
spec=importlib.util.spec_from_file_location('bridge','/work/tools/aisbench/bridge.py')
bridge=importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)
bridge.verify_source(Path('/work/tools/aisbench/source'),json.loads(Path('/work/tools/aisbench/lock.json').read_text()))
calls=[]
class Response:
 status=200
 async def __aenter__(self): return self
 async def __aexit__(self,*args): pass
 async def text(self):
  content=request.pop('fixture_response')
  return json.dumps({'choices':[{'message':{'content':content},'finish_reason':'length'}]*request.pop('fixture_choices'),'usage':{'prompt_tokens':3,'completion_tokens':0}})
class Session:
 def __init__(self,**kwargs): pass
 async def __aenter__(self): return self
 async def __aexit__(self,*args): pass
 def post(self,**kwargs):
  calls.append(kwargs)
  assert kwargs['allow_redirects'] is False
  assert kwargs['url']=='https://api.deepseek.com/v1/chat/completions'
  assert kwargs['headers']['Authorization']=='Bearer fixture-only-key'
  assert any(part['type']=='image_url' and part['image_url']['url'].startswith('data:image/') for m in kwargs['json']['messages'] for part in m['content'])
  if request.get('fixture_timeout'): raise TimeoutError('intercepted transport timeout')
  return Response()
aiohttp.ClientSession=Session
with contextlib.redirect_stdout(sys.stderr):
 result=asyncio.run(bridge.native_infer_mmmu(request))
assert len(calls)==1, 'No implicit HTTP retry is permitted'
print(json.dumps(result))
"""


@pytest.mark.parametrize(
    ("response", "choices", "timeout", "state"),
    [
        ("Answer: A", 1, False, "succeeded"),
        ("", 1, False, "succeeded"),
        ("Answer: A", 2, False, "failed"),
        ("", 1, True, "failed"),
    ],
)
def test_native_http_boundary_preserves_empty_and_truncated_results_without_retry(
    sample_payload, response, choices, timeout, state
):
    request = {
        **sample_payload,
        "api_key": "fixture-only-key",
        "fixture_response": response,
        "fixture_choices": choices,
        "fixture_timeout": timeout,
    }
    result = invoke(["-c", HTTP_FIXTURE], request)
    body = json.loads(result.stdout)
    assert body["state"] == state
    assert b"fixture-only-key" not in result.stdout
    assert "data:" not in body["prompt"]
    assert body["input_images"][0]["sha256"] == sample_payload["images"][0]["sha256"]
    if state == "succeeded":
        assert body["response"] == response and body["finish_reason"] == "length"
        expected = bridge(
            {
                "operation": "score_mmmu_pro_options10_cot",
                "predictions": [response],
                "references": [sample_payload["sample"]["answer"]],
            }
        )
        assert body["scoring"]["native_result"] == expected["native_result"]
    else:
        assert body["response"] is None and "scoring" not in body
