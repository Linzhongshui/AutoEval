"""Operator-invoked native AISBench bridge. No API accepts source or Python paths."""

import asyncio
import base64
import contextlib
import hashlib
import json
import re
import sys
from pathlib import Path


def verify_source(root: Path, lock: dict):
    # Linux slim executors need no git executable. The operator-generated lock
    # covers the complete upstream ais_bench tree, not only the scorer file.
    actual_python = {p.relative_to(root).as_posix() for p in (root / "ais_bench").rglob("*.py")}
    expected_python = {p for p in lock["files"] if p.endswith(".py")}
    if actual_python != expected_python:
        raise ValueError("AISBench Python source tree differs from lock")
    for relative, digest in lock["files"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("AISBench source checksum differs from lock")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def native_score(request):
    from ais_bench.benchmark.datasets.gpqa import GPQAEvaluator
    from ais_bench.benchmark.utils.postprocess.text_postprocessors import first_option_postprocess

    predictions, references = request["predictions"], request["references"]
    if not predictions or len(predictions) != len(references) or len(predictions) > 20000:
        raise ValueError("Scoring requires a nonempty, aligned sample set")
    if any(not isinstance(text, str) for text in predictions) or any(
        ref not in "ABCD" or len(ref) != 1 for ref in references
    ):
        raise ValueError("Invalid native GPQA scoring inputs")
    processed = [first_option_postprocess(text, options="ABCD") for text in predictions]
    result = GPQAEvaluator().score(processed, references)
    return {
        "native_result": result,
        "processed_predictions": processed,
        "diagnostics": {
            "empty_outputs": [i for i, text in enumerate(predictions) if not text.strip()]
        },
        "scoring_rules_changed": False,
    }


def native_prepare(request):
    from ais_bench.benchmark.datasets.gpqa import GPQADataset

    path = Path(request["csv_path"]).resolve(strict=True)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Dataset import exceeds current bridge limit")
    # Always load the full native dataset before selecting Lite. Re-loading a
    # filtered CSV would change this loader's row-dependent option permutation.
    dataset = GPQADataset.load(str(path.parent), path.name)
    rows = []
    for index, sample in enumerate(dataset):
        rows.append(
            {
                "sample_id": f"gpqa_diamond:{index}",
                "sha256": hashlib.sha256(canonical(sample)).hexdigest(),
                "native_sample": sample,
            }
        )
    return {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "samples": rows}


def native_prepare_mmmu(request):
    from ais_bench.benchmark.datasets.mmmu_pro import MMMUProOptions10Dataset

    path = Path(request["tsv_path"]).resolve(strict=True)
    if path.stat().st_size > 8 * 1024 * 1024 * 1024:
        raise ValueError("Dataset import exceeds current bridge limit")
    dataset = MMMUProOptions10Dataset.load(str(path), is_cot=True)
    image_root = (path.parent / "MMMU_Pro_options10_images").resolve()
    rows = []
    for sample in dataset:
        content = sample["content"]
        paths = re.findall(r"<AIS_IMAGE_START>(.*?)<AIS_CONTENT_TAG>", content)
        if not paths:
            raise ValueError("MMMU-Pro sample has no native image")
        images = []
        for image_path in paths:
            source = Path(image_path).resolve(strict=True)
            if source.parent != image_root:
                raise ValueError("Native image escaped the dataset image directory")
            raw = source.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            images.append({"sha256": digest, "base64": base64.b64encode(raw).decode()})
            content = content.replace(image_path, f"image:{digest}")
        source_index = Path(paths[0]).stem.split("_")[0]
        if not source_index.isdigit():
            raise ValueError("MMMU-Pro source index is not stable")
        native_sample = {"content": content, "answer": sample["answer"]}
        rows.append(
            {
                "sample_id": f"mmmu_pro_options10:{source_index}",
                "sha256": hashlib.sha256(
                    canonical({"native_sample": native_sample, "images": images})
                ).hexdigest(),
                "native_sample": native_sample,
                "images": images,
            }
        )
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("MMMU-Pro source indices are not unique")
    return {"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "samples": rows}


def native_prompt_mmmu(request):
    from ais_bench.benchmark.configs.datasets.mmmu_pro.mmmu_pro_options10_cot_gen import (
        mmmu_pro_infer_cfg,
    )
    from ais_bench.benchmark.openicl.icl_prompt_template import MMPromptTemplate

    sample = request["sample"]
    if set(sample) != {"content", "answer"}:
        raise ValueError("Invalid MMMU-Pro sample fields")
    content = sample["content"]
    for image in request["images"]:
        raw = base64.b64decode(image["base64"], validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != image["sha256"] or f"image:{digest}" not in content:
            raise ValueError("MMMU-Pro image identity changed")
        path = Path("/work/mmmu-runtime-images") / f"{digest}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Materialized image identity changed")
        path.write_bytes(raw)
        content = content.replace(f"image:{digest}", str(path))
    if re.search(r"image:[0-9a-f]{64}", content):
        raise ValueError("MMMU-Pro sample has unresolved image references")
    return MMPromptTemplate(template=mmmu_pro_infer_cfg["prompt_template"]["template"]).generate_item(
        {"content": content}, output_field="answer"
    )


def native_score_mmmu(request):
    from ais_bench.benchmark.datasets.mmmu_pro import MMMUProCotEvaluator
    from ais_bench.benchmark.utils.postprocess.text_postprocessors import last_option_postprocess

    predictions, references = request["predictions"], request["references"]
    if not predictions or len(predictions) != len(references) or len(predictions) > 20000:
        raise ValueError("Scoring requires a nonempty, aligned sample set")
    if any(not isinstance(text, str) for text in predictions):
        raise ValueError("Invalid native MMMU-Pro scoring inputs")
    for reference in references:
        choices, answer, category = json.loads(reference)
        if not isinstance(choices, dict) or answer not in choices or not isinstance(category, str):
            raise ValueError("Invalid native MMMU-Pro reference")
    processed = [last_option_postprocess(text, options="ABCDEFGHIJ") for text in predictions]
    return {
        "native_result": MMMUProCotEvaluator().score(processed, references),
        "processed_predictions": processed,
        "diagnostics": {
            "empty_outputs": [i for i, text in enumerate(predictions) if not text.strip()]
        },
        "scoring_rules_changed": False,
    }


def native_prompt(request):
    from ais_bench.benchmark.configs.datasets.gpqa.gpqa_gen_0_shot_str import gpqa_infer_cfg
    from ais_bench.benchmark.openicl.icl_prompt_template import PromptTemplate

    sample = request["sample"]
    if set(sample) != {"question", "A", "B", "C", "D", "answer"}:
        raise ValueError("Invalid GPQA sample fields")
    if any(not isinstance(value, str) or len(value) > 100000 for value in sample.values()):
        raise ValueError("Invalid GPQA sample value")
    return PromptTemplate(template=gpqa_infer_cfg["prompt_template"]["template"]).generate_item(
        sample, output_field="answer"
    )


async def native_infer(request):
    import aiohttp
    from ais_bench.benchmark.models.api_models.vllm_custom_api_chat import VLLMCustomAPIChat
    from ais_bench.benchmark.models.output import RequestOutput

    if request["base_url"] != "https://api.deepseek.com" or request["model"] != "deepseek-flash":
        raise ValueError("Native smoke target is restricted to the configured official model")
    maximum = request["max_tokens"]
    if type(maximum) is not int or not 1 <= maximum <= 64:
        raise ValueError("Native smoke output budget exceeded")
    prompt = native_prompt(request)

    class EvidenceOutput(RequestOutput):
        def update_extra_details_data_from_text_response(self, response):
            choices = response.get("choices", [])
            self.extra_details_data["choice_count"] = len(choices)
            self.extra_details_data["finish_reason"] = (
                choices[0].get("finish_reason") if choices else None
            )

    class RestrictedSession:
        def __init__(self, session):
            self.session = session

        def post(self, **kwargs):
            return self.session.post(**kwargs, allow_redirects=False)

    model = VLLMCustomAPIChat(
        model=request["model"],
        url=request["base_url"],
        api_key=request["api_key"],
        retry=1,
        max_out_len=maximum,
        generation_kwargs={"temperature": 0, "top_p": 1, "thinking": {"type": "disabled"}},
    )
    output = EvidenceOutput()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        await model.generate(prompt, maximum, output, session=RestrictedSession(session))
    success = output.success and output.extra_details_data.get("choice_count") == 1
    result = {
        "prompt": prompt,
        "state": "succeeded" if success else "failed",
        "response": output.content if success else None,
        "finish_reason": output.extra_details_data.get("finish_reason"),
        "error_code": None if success else "NATIVE_INFERENCE_FAILED",
        "usage": {"input_tokens": output.input_tokens, "output_tokens": output.output_tokens},
    }
    if success:
        result["scoring"] = native_score(
            {"predictions": [output.content], "references": [request["sample"]["answer"]]}
        )
    return result


def main():
    root, lock_path = Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2])
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    verify_source(root, lock)
    sys.path.insert(0, str(root))
    request = json.loads(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))
    with contextlib.redirect_stdout(sys.stderr):
        if request["operation"] == "score_gpqa_0shot":
            result = native_score(request)
        elif request["operation"] == "prepare_gpqa_diamond":
            result = native_prepare(request)
        elif request["operation"] == "prompt_gpqa_0shot":
            result = {"prompt": native_prompt(request)}
        elif request["operation"] == "prepare_mmmu_pro_options10":
            result = native_prepare_mmmu(request)
        elif request["operation"] == "prompt_mmmu_pro_options10_cot":
            result = {"prompt": native_prompt_mmmu(request)}
        elif request["operation"] == "score_mmmu_pro_options10_cot":
            result = native_score_mmmu(request)
        elif request["operation"] == "infer_gpqa_smoke":
            result = asyncio.run(native_infer(request))
        else:
            raise ValueError("Unsupported native operation")
    print(
        json.dumps(
            {"tool_revision": lock["revision"], **result}, ensure_ascii=False, allow_nan=False
        )
    )


if __name__ == "__main__":
    main()
