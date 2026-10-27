"""讀取 config.yaml（SPEC §7.2）。個人資訊（收件人）由環境變數 MAIL_TO 覆蓋，避免寫進版控。"""
import os
from pathlib import Path

import yaml


def load_config(path):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError(f"{path} 不是合法的設定檔")
    if os.environ.get("MAIL_TO"):
        cfg["mail"]["to"] = os.environ["MAIL_TO"]
    return cfg
