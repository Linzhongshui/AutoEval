export function ConfigurationDrawer({ children }: { children: React.ReactNode }) {
  return (
    <div className="workflow-backdrop">
      <section className="workflow-drawer" role="dialog" aria-modal="true" aria-label="配置编辑">
        {children}
      </section>
    </div>
  );
}
