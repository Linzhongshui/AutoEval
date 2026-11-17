import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

export function ManagementDrawer({ title, children, onDismiss, open: controlledOpen, onOpenChange, hideTrigger = false }: { title: string; children: ReactNode; onDismiss?: () => void; open?: boolean; onOpenChange?: (open: boolean) => void; hideTrigger?: boolean }) {
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = (value: boolean) => { setLocalOpen(value); onOpenChange?.(value); };
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
    {!hideTrigger && <button type="button" className="link" onClick={() => setOpen(true)}>{title}</button>}
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
