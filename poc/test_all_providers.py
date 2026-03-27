"""
LiteLLM Proxy POC 測試腳本
測試 APISIX → LiteLLM Proxy → 各雲端供應商的格式轉換

使用方式：
    python poc/test_all_providers.py

前置條件：
    1. 啟動 LiteLLM Proxy：litellm --config poc/litellm_proxy_config.yaml --port 4000
    2. 設定 .env 環境變數
"""

import os
import sys
import json
import time

try:
    from openai import OpenAI
except ImportError:
    print("請先安裝依賴：pip install -r requirements.txt")
    sys.exit(1)


LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.getenv("LITELLM_MASTER_KEY", "sk-test-key")

client = OpenAI(base_url=LITELLM_BASE_URL, api_key=LITELLM_API_KEY)


def print_separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_result(label: str, content: str, elapsed: float) -> None:
    print(f"\n[{label}]")
    print(f"回應：{content[:200]}{'...' if len(content) > 200 else ''}")
    print(f"耗時：{elapsed:.2f}s")


def test_basic_chat(model: str, label: str) -> bool:
    """測試基本 Chat Completions"""
    print(f"\n>>> 測試 {label} 基本 Chat...")
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一個助手，請用繁體中文回答。"},
                {"role": "user", "content": "請用一句話介紹你自己。"},
            ],
            max_tokens=100,
            temperature=0.7,
        )
        elapsed = time.time() - start
        content = response.choices[0].message.content or ""
        print_result(label, content, elapsed)
        print(f"Token 使用：{response.usage}")
        return True
    except Exception as e:
        print(f"[失敗] {label}: {e}")
        return False


def test_streaming(model: str, label: str) -> bool:
    """測試 Streaming 回應"""
    print(f"\n>>> 測試 {label} Streaming...")
    try:
        start = time.time()
        full_content = ""
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "請數1到5，每個數字一行。"}],
            max_tokens=100,
            stream=True,
        )
        print("串流輸出：", end="", flush=True)
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                print(delta, end="", flush=True)
                full_content += delta
        elapsed = time.time() - start
        print(f"\n耗時：{elapsed:.2f}s")
        return True
    except Exception as e:
        print(f"\n[失敗] {label} Streaming: {e}")
        return False


def test_function_calling(model: str, label: str) -> bool:
    """測試 Function Calling / Tools"""
    print(f"\n>>> 測試 {label} Function Calling...")
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "取得指定城市的天氣資訊",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名稱"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["city"],
                },
            },
        }
    ]
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "台北現在天氣如何？"}],
            tools=tools,
            tool_choice="auto",
            max_tokens=200,
        )
        elapsed = time.time() - start
        choice = response.choices[0]
        if choice.message.tool_calls:
            tool_call = choice.message.tool_calls[0]
            args = json.loads(tool_call.function.arguments)
            print(f"\n[{label}] 工具呼叫：{tool_call.function.name}({args})")
        else:
            content = choice.message.content or ""
            print(f"\n[{label}] 直接回答：{content[:100]}")
        print(f"耗時：{elapsed:.2f}s")
        return True
    except Exception as e:
        print(f"[失敗] {label} Function Calling: {e}")
        return False


def test_vision(model: str, label: str) -> bool:
    """測試 Vision（圖片理解）"""
    print(f"\n>>> 測試 {label} Vision...")
    test_image_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png"
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "這張圖片裡有什麼？請簡短描述。"},
                        {"type": "image_url", "image_url": {"url": test_image_url}},
                    ],
                }
            ],
            max_tokens=100,
        )
        elapsed = time.time() - start
        content = response.choices[0].message.content or ""
        print_result(label, content, elapsed)
        return True
    except Exception as e:
        print(f"[失敗] {label} Vision: {e}")
        return False


def test_json_response_format(model: str, label: str) -> bool:
    """測試 JSON 結構化輸出"""
    print(f"\n>>> 測試 {label} JSON 結構化輸出...")
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "請回傳一個 JSON 物件，包含 name（城市名稱）和 country（國家）兩個欄位，以台北為例。",
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=100,
        )
        elapsed = time.time() - start
        content = response.choices[0].message.content or ""
        try:
            parsed = json.loads(content)
            print(f"\n[{label}] JSON 輸出：{parsed}")
        except json.JSONDecodeError:
            print(f"\n[{label}] 非標準 JSON：{content[:100]}")
        print(f"耗時：{elapsed:.2f}s")
        return True
    except Exception as e:
        print(f"[失敗] {label} JSON Format: {e}")
        return False


def test_prompt_caching(label: str = "Bedrock Claude 4.5") -> bool:
    """測試 Bedrock Prompt Caching（Claude 4.5 專屬）"""
    print(f"\n>>> 測試 {label} Prompt Caching...")
    long_system_prompt = "你是一個專業助手。" * 200
    try:
        start = time.time()
        response = client.chat.completions.create(
            model="claude-sonnet-4-5",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": long_system_prompt},
                        {"cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": "請用一句話回答：你好嗎？"},
                    ],
                }
            ],
            max_tokens=50,
        )
        elapsed = time.time() - start
        content = response.choices[0].message.content or ""
        print_result(label, content, elapsed)
        if hasattr(response.usage, "cache_creation_input_tokens"):
            print(f"快取建立 tokens：{response.usage.cache_creation_input_tokens}")
        if hasattr(response.usage, "cache_read_input_tokens"):
            print(f"快取讀取 tokens：{response.usage.cache_read_input_tokens}")
        return True
    except Exception as e:
        print(f"[失敗] {label} Prompt Caching: {e}")
        return False


def test_azure_responses_api() -> bool:
    """測試 Azure Responses API（GPT-5.1 特殊路由）"""
    print(f"\n>>> 測試 Azure Responses API...")
    try:
        start = time.time()
        response = client.chat.completions.create(
            model="azure-responses",
            messages=[{"role": "user", "content": "請簡短介紹 Azure OpenAI。"}],
            max_tokens=150,
        )
        elapsed = time.time() - start
        content = response.choices[0].message.content or ""
        print_result("Azure Responses API", content, elapsed)
        return True
    except Exception as e:
        print(f"[失敗] Azure Responses API: {e}")
        return False


def run_all_tests() -> dict:
    """執行所有測試並彙整結果"""
    results = {}

    print_separator("GCP Vertex AI - Gemini 2.5 Flash")
    model, label = "gemini-2.5-flash", "Vertex AI Gemini 2.5 Flash"
    results[f"{label}_basic"] = test_basic_chat(model, label)
    results[f"{label}_stream"] = test_streaming(model, label)
    results[f"{label}_tools"] = test_function_calling(model, label)
    results[f"{label}_vision"] = test_vision(model, label)
    results[f"{label}_json"] = test_json_response_format(model, label)

    print_separator("AWS Bedrock - Claude Sonnet 4.5")
    model, label = "claude-sonnet-4-5", "Bedrock Claude Sonnet 4.5"
    results[f"{label}_basic"] = test_basic_chat(model, label)
    results[f"{label}_stream"] = test_streaming(model, label)
    results[f"{label}_tools"] = test_function_calling(model, label)
    results[f"{label}_vision"] = test_vision(model, label)
    results[f"{label}_json"] = test_json_response_format(model, label)
    results[f"{label}_cache"] = test_prompt_caching(label)

    print_separator("Azure OpenAI - GPT-5.1")
    model, label = "azure-gpt-5-1", "Azure GPT-5.1"
    results[f"{label}_basic"] = test_basic_chat(model, label)
    results[f"{label}_stream"] = test_streaming(model, label)
    results[f"{label}_tools"] = test_function_calling(model, label)
    results[f"{label}_vision"] = test_vision(model, label)
    results[f"{label}_json"] = test_json_response_format(model, label)
    results["azure_responses_api"] = test_azure_responses_api()

    return results


def print_summary(results: dict) -> None:
    print_separator("測試結果摘要")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n通過：{passed}/{total}\n")
    for test_name, ok in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {status}  {test_name}")
    print(f"\n{'='*60}")
    if passed == total:
        print("  全部測試通過！LiteLLM Proxy 格式轉換正常運作。")
    else:
        print(f"  {total - passed} 個測試失敗，請檢查環境變數與雲端服務設定。")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    print(f"LiteLLM Proxy 端點：{LITELLM_BASE_URL}")
    print("開始執行 POC 測試...\n")
    try:
        models = client.models.list()
        available = [m.id for m in models.data]
        print(f"可用模型：{available}")
    except Exception as e:
        print(f"無法連接 LiteLLM Proxy（{LITELLM_BASE_URL}）：{e}")
        print("請確認 LiteLLM Proxy 已啟動：litellm --config poc/litellm_proxy_config.yaml --port 4000")
        sys.exit(1)
    results = run_all_tests()
    print_summary(results)
