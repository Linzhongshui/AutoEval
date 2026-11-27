export const presets = [
  { name: "紫色", color: "#5138ff" },
  { name: "蓝色", color: "#2563eb" },
  { name: "青绿色", color: "#0f766e" },
  { name: "金黄色", color: "#ffd700" },
] as const;

export const layouts = {
  sidebar: "左侧文字栏",
  rail: "左侧图标栏",
  top: "顶部横栏",
} as const;

export type Appearance = { color: string; layout: keyof typeof layouts };
export const defaults: Appearance = { color: presets[0].color, layout: "sidebar" };
const storageKey = "autoeval.appearance.v1";

export function validColor(value: unknown): value is string {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
}

export function readAppearance(): Appearance {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || "null");
    return {
      color: validColor(value?.color) ? value.color.toLowerCase() : defaults.color,
      layout: typeof value?.layout === "string" && Object.hasOwn(layouts, value.layout)
        ? value.layout : defaults.layout,
    };
  } catch {
    return defaults;
  }
}

export function saveAppearance(value: Appearance) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // The current session still uses the selection if storage is unavailable.
  }
}

function luminance(rgb: number[]) {
  const [r, g, b] = rgb.map(channel => {
    const s = channel / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function applyAppearance({ color, layout }: Appearance) {
  const root = document.documentElement;
  root.dataset.menuLayout = layout;
  const rgb = [1, 3, 5].map(start => parseInt(color.slice(start, start + 2), 16));
  const light = luminance(rgb);
  // Select the higher-contrast black/white label for the unmodified button fill.
  const foreground = (light + 0.05) / 0.05 > 1.05 / (light + 0.05) ? "#000" : "#fff";
  // Accent text also sits on tinted surfaces. Bound its luminance for those backgrounds.
  let ink = rgb;
  while (luminance(ink) > 0.12) ink = ink.map(channel => Math.floor(channel * 0.95));
  root.style.setProperty("--accent", color);
  root.style.setProperty("--on-accent", foreground);
  root.style.setProperty("--primary", `rgb(${ink.join(" ")})`);
}
