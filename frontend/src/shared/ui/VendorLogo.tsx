const vendors: { pattern: RegExp; name: string; icon: string }[] = [
  { pattern: /^(deepseek-ai\/|deepseek[-/])/i, name: "DeepSeek", icon: "deepseek-color" },
  { pattern: /^(zhipuai\/|zai-org\/|glm[-/])/i, name: "智谱 GLM", icon: "zhipu-color" },
  { pattern: /^(moonshotai\/|moonshot[-/]|kimi[-/])/i, name: "Moonshot AI", icon: "moonshot" },
  { pattern: /^(minimax[-/])/i, name: "MiniMax", icon: "minimax-color" },
  { pattern: /^(qwen[-/]|qwen\d)/i, name: "Qwen", icon: "qwen-color" },
  { pattern: /^(openai\/|gpt[-/]|o[134](?:-|$))/i, name: "OpenAI", icon: "openai" },
  { pattern: /^(anthropic\/|claude[-/])/i, name: "Anthropic", icon: "anthropic" },
  { pattern: /^(google\/|gemini[-/]|gemma[-/])/i, name: "Google", icon: "google-color" },
  { pattern: /^(xai\/|x-ai\/|grok[-/])/i, name: "xAI", icon: "xai" },
  { pattern: /^(meta[-/]|meta-llama\/|llama[-/]|muse[-/])/i, name: "Meta", icon: "meta-color" },
];

export function VendorLogo({ model }: { model: string }) {
  const vendor = vendors.find(({ pattern }) => pattern.test(model.trim()));
  if (!vendor) return null;
  return <img className="vendor-logo" src={`/brand/vendors/${vendor.icon}.svg`} alt={vendor.name} title={vendor.name} width={18} height={18} loading="lazy" />;
}
