import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

export function ManagementDrawer({ title, children, onDismiss }: { title: string; children: ReactNode; onDismiss?: () => void }) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [open]);
  const close = () => { setOpen(false); onDismiss?.(); };
  return <>
    <button type="button" className="link" onClick={() => setOpen(true)}>{title}</button>
    {open && createPortal(
      <dialog ref={dialog} className="management-drawer" aria-labelledby={heading}
        onCancel={close}>
        <header className="spread"><h2 id={heading}>{title}</h2>
          <button type="button" aria-label={`关闭${title}`} onClick={close}><X size={20} /></button>
        </header>
        <div className="stack management-content">{children}</div>
      </dialog>, document.body)}
  </>;
}
