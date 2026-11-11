export const modelIdentities: Record<string, { vendor: string; huggingface_id: string }> = {
  "Qwen/Qwen2.5-VL-3B-Instruct": {
    "vendor": "阿里通义千问",
    "huggingface_id": "Qwen/Qwen2.5-VL-3B-Instruct"
  },
  "Qwen/Qwen2.5-VL-7B-Instruct": {
    "vendor": "阿里通义千问",
    "huggingface_id": "Qwen/Qwen2.5-VL-7B-Instruct"
  },
  "Qwen/Qwen2.5-VL-72B-Instruct": {
    "vendor": "阿里通义千问",
    "huggingface_id": "Qwen/Qwen2.5-VL-72B-Instruct"
  },
  "Qwen/Qwen2.5-VL-32B-Instruct": {
    "vendor": "阿里通义千问",
    "huggingface_id": "Qwen/Qwen2.5-VL-32B-Instruct"
  },
  "Qwen/Qwen3-235B-A22B-Instruct-2507": {
    "vendor": "阿里通义千问",
    "huggingface_id": "Qwen/Qwen3-235B-A22B-Instruct-2507"
  },
  "Qwen/Qwen3-30B-A3B-Instruct-2507": {
    "vendor": "阿里通义千问",
    "huggingface_id": "Qwen/Qwen3-30B-A3B-Instruct-2507"
  },
  "deepseek-ai/DeepSeek-R1": {
    "vendor": "DeepSeek",
    "huggingface_id": "deepseek-ai/DeepSeek-R1"
  },
  "deepseek-ai/DeepSeek-R1-0528": {
    "vendor": "DeepSeek",
    "huggingface_id": "deepseek-ai/DeepSeek-R1-0528"
  },
  "deepseek-ai/DeepSeek-V3.1": {
    "vendor": "DeepSeek",
    "huggingface_id": "deepseek-ai/DeepSeek-V3.1"
  },
  "ZhipuAI/GLM-4.7": {
    "vendor": "智谱 AI",
    "huggingface_id": "zai-org/GLM-4.7"
  },
  "moonshotai/Kimi-K2-Thinking": {
    "vendor": "Moonshot AI（月之暗面）",
    "huggingface_id": "moonshotai/Kimi-K2-Thinking"
  },
  "moonshotai/Kimi-K2-Instruct-0905": {
    "vendor": "Moonshot AI（月之暗面）",
    "huggingface_id": "moonshotai/Kimi-K2-Instruct-0905"
  },
  "MiniMax/MiniMax-M2": {
    "vendor": "MiniMax",
    "huggingface_id": "MiniMaxAI/MiniMax-M2"
  },
  "MiniMax/MiniMax-M2.1": {
    "vendor": "MiniMax",
    "huggingface_id": "MiniMaxAI/MiniMax-M2.1"
  }
};

// Test fixture identities remain in storage for historical task references.
export function isTestModel(id: string): boolean {
  return /^(?:navigation-[a-f0-9]{32}|model-browser-[a-f0-9]{10})$/.test(id);
}
export function isModelScopeId(id: string): boolean {
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(id) && !isTestModel(id);
}
