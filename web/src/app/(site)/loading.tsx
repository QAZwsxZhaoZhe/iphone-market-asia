import { LoadingShell } from "@/components/states";

export default function Loading() {
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">Loading</span>
          <h1>正在整理市場數據</h1>
        </div>
      </div>
      <LoadingShell />
    </div>
  );
}
