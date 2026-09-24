import { LoadingShell } from "@/components/states";

export default function MobileLoading() {
  return (
    <div className="mobile-page">
      <div className="mobile-page-header">
        <div>
          <span className="eyebrow">Loading</span>
          <h1>正在整理資料</h1>
        </div>
      </div>
      <LoadingShell rows={4} />
    </div>
  );
}
