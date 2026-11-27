import { useLayoutEffect, useState } from "react";
import { ManagementDrawer } from "../shared/ui/ManagementDrawer";
import { version } from "../../package.json";
import {
  applyAppearance, defaults, layouts, presets, readAppearance, saveAppearance, validColor,
  type Appearance,
} from "./appearance";

export function AppearanceSettings() {
  const [appearance, setAppearance] = useState(readAppearance);
  useLayoutEffect(() => applyAppearance(appearance), [appearance]);

  function change(next: Appearance) {
    setAppearance(next);
    saveAppearance(next);
  }

  return (
    <ManagementDrawer title="外观设置">
      <AppearanceForm appearance={appearance} change={change} />
    </ManagementDrawer>
  );
}

function AppearanceForm({ appearance, change }: {
  appearance: Appearance;
  change: (next: Appearance) => void;
}) {
  const [draft, setDraft] = useState(appearance.color);
  const invalid = !validColor(draft);

  function editColor(value: string) {
    setDraft(value);
    if (validColor(value)) change({ ...appearance, color: value.toLowerCase() });
  }

  return <div className="appearance-form">
    <fieldset>
      <legend>主题色</legend>
      <div className="appearance-presets">
        {presets.map(({ name, color }) => (
          <button type="button" key={color} aria-pressed={appearance.color === color}
            onClick={() => editColor(color)}>
            <span className="color-swatch" style={{ background: color }} />{name}
          </button>
        ))}
      </div>
      <div className="appearance-custom">
        <label htmlFor="appearance-hex">自定义颜色</label>
        <input type="color" aria-label="取色器" value={appearance.color}
          onChange={event => editColor(event.target.value)} />
        <input type="text" id="appearance-hex" value={draft} spellCheck={false} aria-invalid={invalid}
          aria-describedby={invalid ? "appearance-error" : undefined}
          onChange={event => editColor(event.target.value)} />
      </div>
      {invalid && <small id="appearance-error" role="status">请输入六位十六进制颜色，例如 #2563EB。</small>}
    </fieldset>
    <fieldset>
      <legend>桌面菜单布局</legend>
      <div className="appearance-layouts">
        {(Object.keys(layouts) as Array<Appearance["layout"]>).map(layout => (
          <label className="appearance-layout" key={layout}>
            <span className="layout-preview" data-layout={layout} aria-hidden="true">
              <span className="preview-nav" /><span className="preview-page" />
            </span>
            <span className="layout-choice">
              <input type="radio" name="menu-layout" checked={appearance.layout === layout}
                onChange={() => change({ ...appearance, layout })} />
              {layouts[layout]}
            </span>
          </label>
        ))}
      </div>
      <small>窄屏使用横向文字菜单。</small>
    </fieldset>
    <footer className="appearance-footer">
      <button type="button" onClick={() => { setDraft(defaults.color); change(defaults); }}>恢复默认</button>
      <small>AutoEval v{version}</small>
    </footer>
  </div>;
}
