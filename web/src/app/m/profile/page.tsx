import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Inbox,
  Monitor,
  RefreshCw,
  ShieldCheck,
  Terminal,
  UsersRound,
  Wrench,
} from "lucide-react";
import Link from "next/link";

import { MobileSessionAction } from "@/components/mobile-session-action";
import { SubmitButton } from "@/components/submit-button";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import {
  formatDateTime,
  formatNumber,
  formatRelative,
  freshnessLabel,
  statusLabel,
  statusTone,
} from "@/lib/format";
import type {
  DeadLetter,
  SourceHealth,
  SourceRun,
} from "@/lib/types";

import {
  collectSourceAction,
  rebuildClustersAction,
  runMaintenanceAction,
} from "./actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

async function safe<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

export default async function MobileProfilePage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const principal = await api.currentPrincipal().catch(() => null);
  const canOperate = Boolean(
    principal?.roles.some((role) => role === "admin" || role === "operator"),
  );
  const isAdmin = Boolean(principal?.roles.includes("admin"));
  const [sources, runs, deadLetters] = await Promise.all([
    safe(api.internalSources()),
    safe(api.internalRuns(30)),
    safe(api.internalDeadLetters(30)),
  ]);
  const sourceRows = sources ?? [];
  const runRows = runs ?? [];
  const deadRows = deadLetters ?? [];
  const failedRuns = runRows.filter((run) =>
    ["failed", "partial"].includes(run.status),
  ).length;

  if (!sources && !runs && !deadLetters) {
    return (
      <div className="mobile-page">
        <ErrorState
          description="請稍後重試，帳戶登出不受影響。"
          title="無法讀取系統資料"
        />
      </div>
    );
  }

  return (
    <div className="mobile-page">
      <header className="mobile-page-header">
        <div>
          <span className="eyebrow">Account & system</span>
          <h1>我的</h1>
          <p>帳戶、來源健康、採集記錄與內部維護工具。</p>
        </div>
        <span className="mobile-secure-chip">
          <ShieldCheck size={14} aria-hidden="true" />
          內部
        </span>
      </header>

      {first(params.notice) ? (
        <div className="mobile-banner" role="status">
          <CheckCircle2 size={18} aria-hidden="true" />
          <span>{first(params.notice)}</span>
        </div>
      ) : null}
      {first(params.error) ? (
        <div className="mobile-banner mobile-banner--error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{first(params.error)}</span>
        </div>
      ) : null}

      <MobileSessionAction
        email={principal?.email ?? "內部使用者"}
        roles={principal?.roles ?? []}
      />

      <nav className="mobile-link-list" aria-label="帳戶及裝置選項">
        <Link href="/ops">
          <span>
            <Monitor size={18} aria-hidden="true" />
            切換電腦端營運台
          </span>
          <ChevronRight size={18} aria-hidden="true" />
        </Link>
        {isAdmin ? (
          <Link href="/ops/users">
            <span>
              <UsersRound size={18} aria-hidden="true" />
              內部帳戶管理
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </Link>
        ) : null}
      </nav>

      <section
        className="mobile-section"
        id="system"
        aria-labelledby="mobile-system-title"
      >
        <header className="mobile-section__header">
          <div>
            <span className="eyebrow">System</span>
            <h2 id="mobile-system-title">系統與來源</h2>
          </div>
        </header>

        <div className="mobile-summary-strip">
          <div>
            <strong>{sourceRows.length}</strong>
            <span>來源</span>
          </div>
          <div>
            <strong>{failedRuns}</strong>
            <span>異常運行</span>
          </div>
          <div>
            <strong>{deadRows.length}</strong>
            <span>死信</span>
          </div>
        </div>

        {canOperate ? (
          <div className="mobile-maintenance-actions">
            <form action={rebuildClustersAction}>
              <SubmitButton>重建集群</SubmitButton>
            </form>
            <form action={runMaintenanceAction}>
              <SubmitButton>執行維護</SubmitButton>
            </form>
          </div>
        ) : (
          <p className="mobile-list-note">
            目前角色為唯讀，不能重新採集或執行維護。
          </p>
        )}

        <div className="mobile-card-list mobile-card-list--compact">
          {sourceRows.length ? (
            sourceRows.map((source) => (
              <SourceCard
                canOperate={canOperate}
                key={source.source_key}
                source={source}
              />
            ))
          ) : (
            <EmptyState
              description="尚未註冊任何資料來源。"
              title="沒有來源"
            />
          )}
        </div>
      </section>

      <details className="mobile-details">
        <summary>
          <span>
            <Terminal size={17} aria-hidden="true" />
            最近採集
          </span>
          <span>{runRows.length} 筆</span>
        </summary>
        <div className="mobile-details__body">
          {runRows.length ? (
            <div className="mobile-run-list">
              {runRows.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </div>
          ) : (
            <EmptyState
              description="尚未執行採集任務。"
              title="沒有運行紀錄"
            />
          )}
        </div>
      </details>

      <details className="mobile-details">
        <summary>
          <span>
            <Inbox size={17} aria-hidden="true" />
            死信任務
          </span>
          <span>{deadRows.length} 筆</span>
        </summary>
        <div className="mobile-details__body">
          {deadRows.length ? (
            <div className="mobile-run-list">
              {deadRows.map((task) => (
                <DeadLetterRow key={task.id} task={task} />
              ))}
            </div>
          ) : (
            <EmptyState
              description="目前沒有需要人工處理的任務。"
              title="死信隊列為空"
            />
          )}
        </div>
      </details>
    </div>
  );
}

function SourceCard({
  source,
  canOperate,
}: {
  source: SourceHealth;
  canOperate: boolean;
}) {
  return (
    <article className="mobile-source-card">
      <header>
        <div>
          <strong>{source.source_name}</strong>
          <span className="mono">{source.source_key}</span>
        </div>
        <span className={`status tone-${statusTone(source.status)}`}>
          {statusLabel(source.status)}
        </span>
      </header>
      <div className="mobile-source-card__stats">
        <div>
          <strong>{formatNumber(source.active_listing_count)}</strong>
          <span>活躍商品</span>
        </div>
        <div>
          <strong>{formatRelative(source.last_success_at)}</strong>
          <span>最近成功</span>
        </div>
        <div>
          <strong>{freshnessLabel(source.freshness_seconds)}</strong>
          <span>資料新鮮度</span>
        </div>
      </div>
      {source.error ? (
        <p className="mobile-source-card__error">{source.error}</p>
      ) : null}
      {canOperate ? (
        <form action={collectSourceAction}>
          <input name="source_key" type="hidden" value={source.source_key} />
          <SubmitButton small>重新採集</SubmitButton>
        </form>
      ) : null}
    </article>
  );
}

function RunRow({ run }: { run: SourceRun }) {
  return (
    <article className="mobile-run-row">
      <div className="mobile-run-row__head">
        <span className={`status tone-${statusTone(run.status)}`}>
          {statusLabel(run.status)}
        </span>
        <span className="mono">{formatDateTime(run.started_at)}</span>
      </div>
      <strong>{run.source_key}</strong>
      <div className="mobile-run-row__meta">
        <span>商品 {formatNumber(run.listing_count)}</span>
        <span>查詢 {formatNumber(run.query_count)}</span>
        <span>嘗試 {run.attempt}</span>
      </div>
      {run.error ? <p>{run.error}</p> : null}
    </article>
  );
}

function DeadLetterRow({ task }: { task: DeadLetter }) {
  return (
    <article className="mobile-run-row mobile-run-row--error">
      <div className="mobile-run-row__head">
        <span className="status tone-negative">死信</span>
        <span className="mono">{formatDateTime(task.created_at)}</span>
      </div>
      <strong className="mono">{task.task_name}</strong>
      <div className="mobile-run-row__meta">
        <span>重試 {task.retry_count}</span>
        <span className="mono">{task.task_id}</span>
      </div>
      <p>{task.error}</p>
    </article>
  );
}
