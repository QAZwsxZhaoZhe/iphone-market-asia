import { AlertTriangle, Inbox, LoaderCircle } from "lucide-react";

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className="empty-state">
      <div>
        <span className="empty-state__icon" aria-hidden="true">
          <Inbox size={21} />
        </span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </section>
  );
}

export function ErrorState({
  title = "資料暫時無法讀取",
  description,
}: {
  title?: string;
  description: string;
}) {
  return (
    <section className="error-state" role="alert">
      <div>
        <span className="error-state__icon" aria-hidden="true">
          <AlertTriangle size={21} />
        </span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </section>
  );
}

export function LoadingShell({ rows = 5 }: { rows?: number }) {
  return (
    <div className="loading-shell" aria-label="正在載入">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton" key={index} />
      ))}
    </div>
  );
}

export function InlineLoading({ label }: { label: string }) {
  return (
    <div className="result-bar" role="status">
      <LoaderCircle className="spin" size={15} />
      <span>{label}</span>
    </div>
  );
}
