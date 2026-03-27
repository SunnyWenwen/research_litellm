# LiteLLM Gateway 格式轉換 - 可行性分析報告

## 1. 摘要

本報告分析透過 LiteLLM Proxy 作為中間層，解決 Apache APISIX `ai-proxy-multi` plugin 僅支援 OpenAI `/chat/completions` 格式，無法直接對接 GCP Vertex AI、AWS Bedrock、Azure OpenAI 原生 API 的問題。

**結論：方案可行。** LiteLLM 能夠將 OpenAI 格式的請求轉換為各雲端供應商的原生 API 格式，涵蓋 3 個目標供應商，但各有功能限制需要注意。

---

## 2. 架構說明

```
Client
  │  (OpenAI /chat/completions format)
  ▼
Apache APISIX
  │  (ai-proxy-multi plugin)
  ▼
LiteLLM Proxy  (http://litellm:4000)
  │
  ├─── vertex_ai/gemini-2.5-flash ──► GCP Vertex AI (native API)
  ├─── bedrock/claude-sonnet-4.5   ──► AWS Bedrock   (boto3/Converse API)
  └─── azure/gpt-5.1               ──► Azure OpenAI  (/chat/completions or /responses)
```

APISIX 將所有請求以 OpenAI 格式送至 LiteLLM Proxy，LiteLLM 負責：
1. 解析 `model` 欄位，判斷目標供應商
2. 將請求轉換為供應商原生格式
3. 呼叫供應商 API
4. 將回應轉換回 OpenAI 格式後返回

---

## 3. GCP Vertex AI (Gemini 2.5 Flash / Pro)

### 3.1 支援情況

| 功能 | 支援 | 備註 |
|------|------|------|
| Chat Completions | ✅ | 完整支援 |
| Streaming | ✅ | Server-Sent Events |
| Function Calling / Tools | ✅ | 轉換為 FunctionDeclaration 格式 |
| Vision (圖片) | ✅ | 支援 image_url 及 base64 |
| JSON Schema / 結構化輸出 | ✅ | response_format 支援 |
| Reasoning / Thinking | ✅ | `reasoning_effort` → Gemini `thinking` 參數 |
| Embeddings | ✅ | text-embedding-004 等 |
| Context Caching | ✅ | 需設定 TTL |
| Grounding (Google Search) | ⚠️ | 需透過原生參數傳遞 |
| PDF / 影片 / 音訊 | ⚠️ | 需使用 `gs://` URI 或 base64 |

### 3.2 模型前綴

```
vertex_ai/gemini-2.5-flash
vertex_ai/gemini-2.5-pro
vertex_ai/gemini-1.5-pro
vertex_ai/gemini-1.5-flash
```

### 3.3 認證方式

```yaml
# 方式一：Application Default Credentials
# gcloud auth application-default login

# 方式二：Service Account JSON
litellm_params:
  vertex_credentials: "/path/to/service-account.json"
  vertex_project: "my-gcp-project"
  vertex_location: "us-central1"
```

環境變數：
- `VERTEXAI_PROJECT` - GCP 專案 ID
- `VERTEXAI_LOCATION` - 部署區域（如 `us-central1`）
- `GOOGLE_APPLICATION_CREDENTIALS` - Service Account JSON 路徑

### 3.4 功能轉換對照

| OpenAI 參數 | Vertex AI 原生參數 | 說明 |
|------------|-----------------|------|
| `model` | `modelId` | 模型名稱 |
| `messages[].role=system` | `systemInstruction` | 系統提示轉換 |
| `max_tokens` | `maxOutputTokens` | 最大輸出 token |
| `temperature` | `temperature` | 溫度參數 |
| `stop` | `stopSequences` | 停止序列 |
| `tools` | `tools[].functionDeclarations` | 工具定義轉換 |
| `response_format.type=json_schema` | `responseSchema` | 結構化輸出 |
| `reasoning_effort` | `thinking.thinkingBudget` | 思考預算 |

### 3.5 已知限制

1. **Grounding 工具**：`google_search_retrieval` 等 Vertex 原生工具需透過 `extra_body` 傳遞
2. **安全設定**：`safety_settings` 需使用 Vertex 原生格式
3. **多模態 Embeddings**：每次請求限一張圖片/影片
4. **批次 API**：輸出為 Gemini 原生格式，非 OpenAI 格式

---

## 4. AWS Bedrock (Claude Sonnet 4.5)

### 4.1 支援情況

| 功能 | 支援 | 備註 |
|------|------|------|
| Chat Completions | ✅ | 完整支援 |
| Streaming | ✅ | converse-stream API |
| Function Calling / Tools | ✅ | 轉換為 Bedrock ToolUseBlock |
| Vision (圖片) | ✅ | base64 或檔案路徑 |
| Document Understanding | ✅ | PDF, CSV, DOC, DOCX, XLS, HTML, TXT, MD |
| Extended Thinking | ✅ | `reasoning_effort` → Claude thinking 參數 |
| Prompt Caching | ✅ | 支援 1 小時 TTL（Claude 4.5 模型） |
| Structured Output | ✅ | `response_format` 支援 |
| Guardrails | ✅ | `guardrailConfig` 內容過濾 |
| Cross-Region Inference | ✅ | `us.`, `eu.` 前綴 |

### 4.2 模型前綴

```
# 標準端點
bedrock/anthropic.claude-sonnet-4-5-20251001-v1:0

# 跨區域推論
bedrock/us.anthropic.claude-sonnet-4-5-20251001-v1:0
bedrock/eu.anthropic.claude-sonnet-4-5-20251001-v1:0

# Converse API（推薦）
bedrock/converse/anthropic.claude-sonnet-4-5-20251001-v1:0
```

### 4.3 認證方式

```bash
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION_NAME=us-east-1

# Bearer Token（新方式）
AWS_BEARER_TOKEN_BEDROCK=your_token
```

### 4.4 Prompt Caching 重要說明

Claude 4.5 on Bedrock 支援 Prompt Caching：
- 預設 TTL：5 分鐘
- 最長 TTL：1 小時（需指定 `ttl: "1h"`）
- 每次對話最多 4 個訊息可設快取
- 透過 `cache_control` 參數標記快取點

```python
messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "長系統提示..."},
            {"cache_control": {"type": "ephemeral"}}  # 快取此位置
        ]
    }
]
```

### 4.5 功能轉換對照

| OpenAI 參數 | Bedrock Converse 參數 | 說明 |
|------------|---------------------|------|
| `max_tokens` | `inferenceConfig.maxTokens` | 最大 token 數 |
| `temperature` | `inferenceConfig.temperature` | 溫度 |
| `stop` | `inferenceConfig.stopSequences` | 停止序列 |
| `tools` | `toolConfig.tools` | 工具配置 |
| `system` role | `system[]` | 系統訊息 |

### 4.6 已知限制

1. **交替訊息**：Bedrock 要求 User/Assistant 交替，LiteLLM 自動處理
2. **Beta 功能**：Extended output (128K tokens)、Computer Use 需特定 AWS 區域及帳號權限
3. **`eager_input_streaming` 參數**：Claude Haiku 4.5 拒絕此參數，LiteLLM 未過濾（僅 Claude 4 接受）
4. **Thinking blocks**：Extended thinking 的 signature 需在後續工具呼叫中傳遞

---

## 5. Azure OpenAI (GPT-5.1)

### 5.1 支援情況

| 功能 | 支援 | 備註 |
|------|------|------|
| Chat Completions | ✅ | `/chat/completions` |
| Responses API | ✅ | `/v1/responses` 獨立端點 |
| Streaming | ✅ | 完整支援 |
| Function Calling | ✅ | 包含 parallel function calling |
| Vision | ✅ | 可加 Azure Vision 增強（OCR） |
| Embeddings | ✅ | text-embedding-ada-002 等 |
| Audio | ✅ | TTS 和 STT |
| Batch Processing | ✅ | 24 小時完成視窗 |
| Load Balancing | ✅ | 跨多個部署平衡負載 |

### 5.2 GPT-5.1 相容性說明

**Azure OpenAI 目前狀態（截至 2026-03-27）：**
- Azure 已推出 GPT-5 系列（透過 `azure/gpt5_series/` 路由）
- GPT-5.1 若可用，需確認部署名稱後以 `azure/<deployment-name>` 格式呼叫
- `/responses` API 完整支援，可透過 `azure/responses/<deployment-name>` 存取

### 5.3 `/chat/completions` vs `/responses` API

| 特性 | `/chat/completions` | `/responses` API |
|------|-------------------|----------------|
| OpenAI 相容性 | 完整相容 | 獨立端點 |
| APISIX 支援 | ✅ 直接支援 | ❌ 需透過 LiteLLM 轉換 |
| LiteLLM 支援 | ✅ 原生支援 | ✅ 支援（需特殊路由格式） |
| Codex 模型 | ⚠️ | ✅ `api_version="preview"` |
| 推薦做法 | 一般用途 | o1-pro、Codex 等特殊模型 |

**LiteLLM Responses API 呼叫方式：**
```python
# 方式一：直接使用 responses()
import litellm
response = litellm.responses(
    model="azure/o1-pro",
    input="你好",
    api_key="...",
    api_base="https://xxx.openai.azure.com"
)

# 方式二：透過 completion() 使用特殊模型格式
response = litellm.completion(
    model="azure/responses/my-o1-pro-deployment",
    messages=[{"role": "user", "content": "你好"}]
)
```

### 5.4 認證方式

```bash
AZURE_API_KEY=your_key
AZURE_API_BASE=https://xxx.openai.azure.com
AZURE_API_VERSION=2024-02-15-preview

# Azure AD / Entra ID
AZURE_AD_TOKEN=your_token
```

### 5.5 多部署負載平衡

```yaml
model_list:
  - model_name: gpt-5-pool
    litellm_params:
      model: azure/gpt5-deployment-eastus
      api_base: https://xxx-eastus.openai.azure.com
      api_key: ${AZURE_KEY_1}
  - model_name: gpt-5-pool
    litellm_params:
      model: azure/gpt5-deployment-westus
      api_base: https://xxx-westus.openai.azure.com
      api_key: ${AZURE_KEY_2}
```

---

## 6. LiteLLM Router 多區域路由

### 6.1 路由策略

| 策略 | 說明 | 推薦場景 |
|------|------|---------|
| `simple-shuffle` | 依 RPM/TPM 限制隨機選擇（**預設，推薦**） | 一般生產環境 |
| `least-busy` | 選擇 in-flight 請求最少的部署 | 高並發場景 |
| `latency-based-routing` | 選擇平均延遲最低的部署 | 延遲敏感 |
| `usage-based-routing-v2` | 依剩餘 TPM/RPM 容量路由 | 精確流量控制（**不推薦生產**） |
| `cost-based` | 選擇成本最低的部署 | 成本優化 |
| Custom | 繼承 `CustomRoutingStrategyBase` | 自訂邏輯 |

### 6.2 Fallback 機制

```
請求失敗
  │
  ├─ Retry（num_retries 次，同一部署）
  ├─ 嘗試同 model group 其他部署
  ├─ 套用 fallback_models（跨 group）
  └─ 最終失敗，回傳綜合錯誤
```

**Cooldown 觸發條件：**
- HTTP 429 (Rate Limit)：立即觸發
- 當前分鐘失敗率 > 50%
- 不可重試錯誤（401, 404, 408）

### 6.3 多區域配置範例

```yaml
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 3
  fallback_models:
    gemini-2.5-flash:
      - claude-sonnet-4-5

model_list:
  - model_name: gemini-2.5-flash
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: my-project
      vertex_location: us-central1
  - model_name: gemini-2.5-flash
    litellm_params:
      model: vertex_ai/gemini-2.5-flash
      vertex_project: my-project
      vertex_location: asia-northeast1
```

---

## 7. 已知問題與風險

### 7.1 功能轉換損失

| 供應商 | 損失的原生功能 | 嚴重程度 |
|--------|------------|----------|
| Vertex AI | Grounding 工具（Google Search 等） | 中 |
| Vertex AI | 安全設定細粒度控制 | 低 |
| Vertex AI | 批次 API 輸出格式 | 低 |
| Bedrock | `eager_input_streaming`（Haiku 4.5 衝突） | 中 |
| Bedrock | Extended thinking signature 需手動傳遞 | 高 |
| Azure | Vision 增強（OCR）需特殊 base URL | 低 |

### 7.2 版本依賴

- **LiteLLM 版本**：建議固定版本，避免供應商 API 更新造成不相容
- **boto3 版本**：AWS Bedrock 需 `boto3>=1.28.57`
- **認證輪替**：需實作自動更新機制

### 7.3 效能考量

- LiteLLM Proxy 引入額外一層網路跳躍
- 實測可達 **1,500+ req/s**（官方壓測數據）
- 建議生產環境配置 Redis 以支援分散式狀態追蹤

---

## 8. 建議配置

### 8.1 生產環境建議

```
APISIX  ──(HTTP)──►  LiteLLM Proxy Cluster  ──►  Cloud Providers
                        │
                        └─── Redis (分散式狀態)
                        └─── PostgreSQL (Key/User/Budget 管理)
```

### 8.2 LiteLLM 功能建議啟用

- **Virtual Keys**：每個 APISIX 路由使用不同 Key，便於追蹤費用
- **Budget Controls**：設定每個 Key 的每月預算上限
- **Router with Redis**：多個 LiteLLM 實例間共享使用量資料
- **Observability**：整合 Langfuse 或 Helicone 進行請求追蹤

---

## 9. 結論

| 供應商 | 可行性 | 主要風險 |
|--------|--------|----------|
| GCP Vertex AI (Gemini 2.5) | ✅ 可行 | Grounding 工具需額外處理 |
| AWS Bedrock (Claude Sonnet 4.5) | ✅ 可行 | Extended thinking 有限制 |
| Azure OpenAI (GPT-5.1) | ✅ 可行 | `/responses` API 需特殊路由 |

**整體方案可行**，LiteLLM Proxy 能夠有效作為 APISIX 與各雲端 LLM 供應商之間的格式轉換中間層。建議先完成 POC 驗證各供應商的連線與基本功能，再逐步評估進階功能（Prompt Caching、Extended Thinking 等）的相容性。
