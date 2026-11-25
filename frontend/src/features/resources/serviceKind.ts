export const serviceLabels = {
  local: "标准本地模型服务",
  official: "官方模型服务",
} as const;

export type ServiceKind = keyof typeof serviceLabels;

export function serviceLabel(kind?: ServiceKind | null) {
  return kind ? serviceLabels[kind] : "待确认";
}
