"""呼叫 agy 蒐集撰寫 draft（SPEC §3 步驟 2–3、§8.1、§8.4）。"""
import logging
from pathlib import Path

from agents.runner import run_agent
from schemas import extract_json, validate_draft

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "collector.md"


def render_prompt(start_date, end_date, path=PROMPT):
    text = Path(path).read_text(encoding="utf-8")
    return text.replace("{start_date}", start_date).replace("{end_date}", end_date)


def build_args(c, prompt):
    """組 agy 參數：設了 json_schema 就用 --output-format json 強制結構；model / effort 有設才帶。"""
    args = ["-p", prompt]
    if c.get("json_schema"):
        schema = Path(c["json_schema"])
        args += ["--output-format", "json", "--json-schema", str(schema if schema.is_absolute() else ROOT / schema)]
    if c.get("model"):
        args += ["--model", c["model"]]
    if c.get("effort"):
        args += ["--effort", c["effort"]]
    return args


def _parse(out):
    data = extract_json(out)
    # --output-format json 的外層：{"status", "structured_output", "response", "usage", ...}
    if isinstance(data, dict) and "status" in data and ("structured_output" in data or "response" in data):
        if data.get("status") != "SUCCESS":
            raise ValueError(f"agy 狀態不是 SUCCESS: {data.get('status')}")
        logging.info("agy 用量：%s", data.get("usage"))
        data = data.get("structured_output")
        if not isinstance(data, dict):
            raise ValueError("agy 外層缺少 structured_output")
    errors = validate_draft(data)
    if errors:
        raise ValueError("draft 結構錯誤: " + "; ".join(errors[:5]))
    return data


def collect(cfg, start_date, end_date):
    c = cfg["agents"]["collector"]
    return run_agent(c["command"], build_args(c, render_prompt(start_date, end_date)), _parse,
                     c["timeout_seconds"], c["retries"])
