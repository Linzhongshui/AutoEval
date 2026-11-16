// Presentation aliases only: source labels and execution identities remain immutable.
export function datasetIdentity(name: string): string {
  const key = name.trim().toLowerCase().replace(/[ _-]+/g, "");
  const aliases: Record<string, string> = {
    "mmmupro": "MMMU-Pro",
    "multiswebench": "Multi-SWE-bench",
    "simpleqa": "SimpleQA", "simpleqa(correct)": "SimpleQA",
    "swebenchmultilingual": "SWE-bench Multilingual",
    "swebenchmultilingual(agentmode)": "SWE-bench Multilingual",
    "swebenchverified": "SWE-bench Verified",
    "swebenchverified(droid)": "SWE-bench Verified",
    "swebenchverified(minisweagent)": "SWE-bench Verified",
    "terminalbench2.0": "Terminal-Bench 2.0",
    "terminalbenchhard": "Terminal-Bench Hard",
    "terminalbench": "Terminal-Bench（版本未披露）",
    "gpqadiamond": "GPQA-Diamond",
    "gpqadiamond(pass@1)": "GPQA-Diamond",
    "aime25": "AIME 2025", "aime2025": "AIME 2025",
    "aime2025(pass@1)": "AIME 2025",
    "aime2024(pass@1)": "AIME 2024", "aime2024": "AIME 2024",
  };
  return aliases[key] || name;
}
export function datasetNote(name: string): string {
  if (/terminus/i.test(name)) return "包含执行框架条件，暂不与其他 Terminal-Bench 记录合并";
  if (/terminal.*hard/i.test(name)) return "Hard 范围单列，不与普通或 2.0 版本合并";
  if (/GPQA-D$|SuperGPQA/i.test(name)) return "子集或独立基准身份待核实，保留原名";
  return "仅统一名称；版本、样本范围、指标和方法仍须逐条核对";
}
