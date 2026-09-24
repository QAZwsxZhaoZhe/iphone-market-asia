"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="page">
      <section className="error-state" role="alert">
        <div>
          <span className="error-state__icon" aria-hidden="true">
            <AlertTriangle size={21} />
          </span>
          <h2>頁面載入失敗</h2>
          <p>資料服務可能暫時不可用，請稍後重試。</p>
          <button
            className="button button--primary"
            onClick={reset}
            type="button"
          >
            <RotateCcw size={15} />
            重新載入
          </button>
        </div>
      </section>
    </div>
  );
}
