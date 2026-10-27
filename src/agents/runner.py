"""以 subprocess 呼叫 agy / claude 的共用邏輯（SPEC §8.4、§9.2）。"""
import shutil
import subprocess

DENIED_MARKERS = ("no output produced", "auto-denied")
# 訂閱用量耗盡時，CLI 回的是一句提示而不是 JSON（實測：「You've hit your session limit · resets 7:50am」）
QUOTA_MARKERS = ("hit your session limit", "hit your usage limit", "usage limit reached", "hit your limit")


class AgentError(Exception):
    pass


class AgentPermissionError(AgentError):
    """無頭模式權限被拒；重試結果相同，不重試。"""


class AgentQuotaError(AgentError):
    """訂閱用量耗盡；重試也沒用，整個階段應中止並寄失敗通知。"""


def run_agent(command, args, parse, timeout, retries, input_text=None):
    """執行 Agent；stdout 空或 parse 拋 ValueError 時重試，權限被拒、用量耗盡與逾時直接失敗。回傳 parse 的結果。"""
    exe = shutil.which(command)
    if not exe:
        raise AgentError(f"找不到執行檔: {command}")
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run([exe, *args], input=input_text, capture_output=True, text=True,
                               encoding="utf-8", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AgentError(f"{command} 逾時（{timeout} 秒）")
        except OSError as e:
            raise AgentError(f"{command} 無法執行: {e}")
        out, err = r.stdout or "", r.stderr or ""
        if any(m in out + err for m in DENIED_MARKERS):
            raise AgentPermissionError(f"{command} 權限被拒，請檢查 SPEC §9.1 設定: {(out + err).strip()[:300]}")
        if any(m in (out + err).lower() for m in QUOTA_MARKERS):
            raise AgentQuotaError(f"{command} 訂閱用量已耗盡: {(out + err).strip()[:200]}")
        if not out.strip():
            last = f"{command} 輸出為空（結束碼 {r.returncode}，stderr: {err.strip()[:200]}）"
            continue
        try:
            return parse(out)
        except ValueError as e:
            last = f"{command} 輸出不合法（第 {attempt + 1} 次）: {e}；輸出開頭: {out.strip()[:120]!r}"
    raise AgentError(last)
