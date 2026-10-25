import { useEffect, useRef, type ReactNode } from 'react';
import { BookOpen, LoaderCircle, ShieldAlert, X } from 'lucide-react';

export function ErrorNotice({ error }: { error: string }) { return error ? <div className="error-notice" role="alert"><ShieldAlert size={17} /><span>{error}</span></div> : null; }
export function Busy({ text = 'Loading…' }: { text?: string }) { return <div className="busy" role="status"><LoaderCircle size={18} className="spin" />{text}</div>; }
export function PageHeading({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <header className="page-heading"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></header>; }
export function Empty({ title, text }: { title: string; text: string }) { return <div className="empty"><span className="empty-icon"><BookOpen size={28} /></span><h3>{title}</h3><p>{text}</p></div>; }
export function Modal({ title, children, onClose, className = '' }: { title: string; children: ReactNode; onClose: () => void; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => { dialog?.close(); }; }, []);
  return <dialog ref={ref} className={`modal ${className}`} aria-label={title} onCancel={(e) => { e.preventDefault(); onClose(); }}>
    <div className="modal-heading"><h2>{title}</h2><button className="icon-button" aria-label={`Close ${title}`} onClick={onClose}><X size={20} /></button></div>{children}
  </dialog>;
}
export function useUnsavedChanges(dirty: boolean, onDirtyChange?: (dirty: boolean) => void) {
  useEffect(() => { onDirtyChange?.(dirty); return () => onDirtyChange?.(false); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
}
