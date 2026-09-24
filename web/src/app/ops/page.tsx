import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  History,
  Inbox,
  ReceiptText,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Wrench,
} from "lucide-react";
import Link from "next/link";

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
  AuditEntry,
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

async function safe<T>(promise: Promise<T>): Promise<{
  data: T | null;
  error: string | null;
}> {
  try {
    return { data: await promise, error: null };
  } catch (error) {
    return {
      data: null,
      error: error instanceof Error ? error.message : "無法讀取內部資料",
    };
  }
}

export default async function OpsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const principal = await api.currentPrincipal().catch(() => null);
  const canOperate = Boolean(
    principal?.roles.some((role) => role === "admin" || role === "operator"),
  );
  const [sourcesResult, runsResult, auditResult, deadLettersResult] =
    await Promise.all([
      safe(api.internalSources()),
      safe(api.internalRuns(60)),
      safe(api.internalAudit(60)),
      safe(api.internalDeadLetters(60)),
    ]);

  const errors = [
    sourcesResult.error,
    runsResult.error,
    auditResult.error,
    deadLettersResult.error,
  ].filter(Boolean) as string[];
  const sources = sourcesResult.data ?? [];
  const runs = runsResult.data ?? [];
  const audits = auditResult.data ?? [];
  const deadLetters = deadLettersResult.data ?? [];
  const failedRuns = runs.filter(
    (run) => run.status === "failed" || run.status === "partial",
  ).length;

  if (errors.length === 4) {
    return (
      <div className="page">
        <ErrorState
          description={errors[0]}
          title="營運台無法連接內部資料"
        />
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Operations</span>
          <h1>營運控制台</h1>
          <p>
            檢查來源健康、重跑採集、處理失敗任務、重建跨來源集群並追蹤操作審計。
          </p>
        </div>
        <div className="ops-header-actions">
          <span className="badge tone-positive">
            <ShieldCheck size={13} aria-hidden="true" /> 內部介面
          </span>
          <Link className="button button--ghost button--small" href="/ops/catalog">
            <Boxes size={14} aria-hidden="true" />
            商品目錄
          </Link>
          <Link className="button button--ghost button--small" href="/ops/orders">
            <ReceiptText size={14} aria-hidden="true" />
            訂單與結算
          </Link>
        </div>
      </header>

      {first(params.notice) ? (
        <div className="ops-banner" role="status">
          <CheckCircle2 size={17} aria-hidden="true" />
          {first(params.notice)}
        </div>
      ) : null}
      {first(params.error) ? (
        <div className="ops-banner ops-banner--error" role="alert">
          <AlertTriangle size={17} aria-hidden="true" />
          {first(params.error)}
        </div>
      ) : null}

      <section className="metrics-grid" aria-label="營運摘要">
        <article className="metric">
          <span className="metric__label">
            <RefreshCw size={13} /> 已註冊來源
          </span>
          <strong className="metric__value">{sources.length}</strong>
          <span className="metric__note">香港市場來源</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <AlertTriangle size={13} /> 近期異常
          </span>
          <strong className="metric__value">{failedRuns}</strong>
          <span className="metric__note">最近 {runs.length} 次運行</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <Inbox size={13} /> 死信任務
          </span>
          <strong className="metric__value">{deadLetters.length}</strong>
          <span className="metric__note">需要人工判斷</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <History size={13} /> 審計記錄
          </span>
          <strong className="metric__value">{audits.length}</strong>
          <span className="metric__note">最近操作與權限變更</span>
        </article>
      </section>

      {canOperate ? (
        <div className="ops-toolbar">
          <form action={rebuildClustersAction}>
            <SubmitButton>重建跨來源集群</SubmitButton>
          </form>
          <form action={runMaintenanceAction}>
            <SubmitButton>執行估值與提醒維護</SubmitButton>
          </form>
        </div>
      ) : null}

      <section className="panel">
        <header className="panel__header">
          <h2>來源健康</h2>
          <span className="subtext">可個別重新排入採集隊列</span>
        </header>
        {sources.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>來源</th>
                  <th>狀態</th>
                  <th>活躍</th>
                  <th>最近採集</th>
                  <th>新鮮度</th>
                  {canOperate ? <th>操作</th> : null}
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source.source_key}>
                    <td>
                      <strong>{source.source_name}</strong>
                      <div className="subtext mono">
                        {source.source_key}
                      </div>
                    </td>
                    <td>
                      <span
                        className={`status tone-${statusTone(source.status)}`}
                      >
                        {statusLabel(source.status)}
                      </span>
                    </td>
                    <td className="mono">
                      {formatNumber(source.active_listing_count)}
                    </td>
                    <td>{formatRelative(source.last_success_at)}</td>
                    <td>{freshnessLabel(source.freshness_seconds)}</td>
                    {canOperate ? (
                      <td>
                        <form action={collectSourceAction}>
                          <input
                            name="source_key"
                            type="hidden"
                            value={source.source_key}
                          />
                          <SubmitButton small>重新採集</SubmitButton>
                        </form>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="panel__body">
            <EmptyState
              description="目前沒有可顯示的來源。"
              title="尚無來源"
            />
          </div>
        )}
      </section>

      <div className="section-stack">
        <section className="panel">
          <header className="panel__header">
            <h2>最近採集運行</h2>
            <span className="subtext">
              <Terminal size={13} aria-hidden="true" /> 單來源失敗不阻塞其他來源
            </span>
          </header>
          {runs.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>時間</th>
                    <th>來源</th>
                    <th>狀態</th>
                    <th>商品</th>
                    <th>查詢</th>
                    <th>錯誤</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run: SourceRun) => (
                    <tr key={run.id}>
                      <td className="mono">
                        {formatDateTime(run.started_at)}
                      </td>
                      <td>{run.source_key}</td>
                      <td>
                        <span
                          className={`status tone-${statusTone(run.status)}`}
                        >
                          {statusLabel(run.status)}
                        </span>
                      </td>
                      <td>{run.listing_count}</td>
                      <td>{run.query_count}</td>
                      <td>
                        <span className="truncate" title={run.error ?? ""}>
                          {run.error ?? "—"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="尚未執行採集任務。"
                title="沒有運行紀錄"
              />
            </div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <h2>死信任務</h2>
            <span className="subtext">重試耗盡或格式錯誤的任務</span>
          </header>
          {deadLetters.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>時間</th>
                    <th>任務</th>
                    <th>重試</th>
                    <th>錯誤</th>
                  </tr>
                </thead>
                <tbody>
                  {deadLetters.map((task: DeadLetter) => (
                    <tr key={task.id}>
                      <td className="mono">
                        {formatDateTime(task.created_at)}
                      </td>
                      <td>
                        <span className="mono">{task.task_name}</span>
                        <div className="subtext">{task.task_id}</div>
                      </td>
                      <td>{task.retry_count}</td>
                      <td>
                        <span className="truncate" title={task.error}>
                          {task.error}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="目前沒有需要人工處理的死信任務。"
                title="死信隊列為空"
              />
            </div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <h2>操作審計</h2>
            <span className="subtext">
              <Wrench size={13} aria-hidden="true" /> 資料修正、重跑與權限變更
            </span>
          </header>
          {audits.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>時間</th>
                    <th>操作人</th>
                    <th>動作</th>
                    <th>資源</th>
                    <th>細節</th>
                  </tr>
                </thead>
                <tbody>
                  {audits.map((entry: AuditEntry) => (
                    <tr key={entry.id}>
                      <td className="mono">
                        {formatDateTime(entry.created_at)}
                      </td>
                      <td>{entry.actor}</td>
                      <td className="mono">{entry.action}</td>
                      <td>
                        {entry.resource_type}
                        {entry.resource_id ? `:${entry.resource_id}` : ""}
                      </td>
                      <td>
                        <span
                          className="truncate mono"
                          title={JSON.stringify(entry.details)}
                        >
                          {JSON.stringify(entry.details)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="尚未記錄任何內部操作。"
                title="沒有審計紀錄"
              />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
