# LiteLLM Gateway 格式轉換 - 可行性分析與 POC

## 專案背景

目前規劃開發基於 Apache APISIX 的 LLM Gateway，使用 `ai-proxy-multi` plugin 作為核心。
該 plugin 僅支援 OpenAI Compatible API (`/chat/completions`)，無法直接對接以下雲端服務：

- **GCP Vertex AI**: Gemini 2.5 Flash / Pro（原生 Vertex AI API 格式）
- **AWS Bedrock**: Claude Sonnet 4.5（原生 Bedrock API 格式）
- **Azure OpenAI**: GPT-5.1（原生支援 `/responses` API，需確認 `/chat/completions` 相容性）

**Data Flow**: `Client → APISIX (ai-proxy-multi) → LiteLLM Proxy → Cloud Provider`

本專案透過 LiteLLM Proxy 作為中間層，將統一的 OpenAI `/chat/completions` 格式轉換為各雲端供應商原生 API 格式。

## 詳細分析報告

請參閱 [analysis_report.md](./docs/analysis_report.md)

## POC 程式碼

請參閱 [poc/](./poc/) 目錄

## 快速開始

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 設定環境變數
cp .env.example .env

# 3. 啟動 LiteLLM Proxy
litellm --config poc/litellm_proxy_config.yaml --port 4000

# 4. 測試
python poc/test_all_providers.py
```
