import {
  AlertTriangle,
  CheckCircle2,
  ShieldCheck,
  UserCog,
  UserPlus,
  Users,
} from "lucide-react";
import Link from "next/link";

import { SubmitButton } from "@/components/submit-button";
import { EmptyState, ErrorState } from "@/components/states";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { User } from "@/lib/types";

import { createStaffUserAction } from "./actions";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{
  notice?: string | string[];
  error?: string | string[];
}>;

const INTERNAL_ROLES = ["admin", "operator", "analyst"] as const;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function StaffUsersPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const principal = await api.currentPrincipal().catch(() => null);
  const isAdmin = Boolean(principal?.roles.includes("admin"));

  if (!isAdmin) {
    return (
      <div className="page">
        <ErrorState
          description="只有管理員可以建立、查看及管理內部員工帳戶。"
          title="沒有帳戶管理權限"
        />
      </div>
    );
  }

  const users = await api.internalUsers().catch(() => [] as User[]);
  const staff = users.filter((user) =>
    user.roles.some((role) =>
      INTERNAL_ROLES.includes(role as (typeof INTERNAL_ROLES)[number]),
    ),
  );
  const adminCount = staff.filter((user) => user.roles.includes("admin")).length;
  const operatorCount = staff.filter((user) =>
    user.roles.includes("operator"),
  ).length;
  const analystCount = staff.filter((user) =>
    user.roles.includes("analyst"),
  ).length;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Access control</span>
          <h1>內部帳戶</h1>
          <p>只建立 ERP 員工帳戶，公開買家及商家帳戶不會出現在這裡。</p>
        </div>
        <Link className="button button--ghost" href="/ops">
          返回營運台
        </Link>
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

      <section className="metrics-grid" aria-label="內部帳戶摘要">
        <article className="metric">
          <span className="metric__label">
            <Users size={13} /> 員工帳戶
          </span>
          <strong className="metric__value">{staff.length}</strong>
          <span className="metric__note">目前可進入 ERP</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <ShieldCheck size={13} /> 管理員
          </span>
          <strong className="metric__value">{adminCount}</strong>
          <span className="metric__note">可管理權限與營運資料</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <UserCog size={13} /> 營運
          </span>
          <strong className="metric__value">{operatorCount}</strong>
          <span className="metric__note">可處理商品與訂單</span>
        </article>
        <article className="metric">
          <span className="metric__label">
            <UserCog size={13} /> 分析
          </span>
          <strong className="metric__value">{analystCount}</strong>
          <span className="metric__note">只讀查看營運資料</span>
        </article>
      </section>

      <div className="section-stack">
        <section className="panel">
          <header className="panel__header">
            <h2>建立內部使用者</h2>
            <span className="subtext">
              <UserPlus size={13} aria-hidden="true" /> 初始密碼至少 10 個字元
            </span>
          </header>
          <div className="panel__body">
            <form
              action={createStaffUserAction}
              className="catalog-form staff-users-form"
            >
              <div className="field">
                <label htmlFor="staff-display-name">名稱</label>
                <input
                  className="input"
                  id="staff-display-name"
                  maxLength={120}
                  name="display_name"
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="staff-email">員工電郵</label>
                <input
                  autoComplete="off"
                  className="input"
                  id="staff-email"
                  name="email"
                  required
                  type="email"
                />
              </div>
              <div className="field">
                <label htmlFor="staff-password">初始密碼</label>
                <input
                  autoComplete="new-password"
                  className="input"
                  id="staff-password"
                  minLength={10}
                  name="password"
                  required
                  type="password"
                />
              </div>
              <div className="field">
                <label htmlFor="staff-role">角色</label>
                <select
                  className="select"
                  defaultValue="operator"
                  id="staff-role"
                  name="role"
                >
                  <option value="operator">營運</option>
                  <option value="analyst">分析</option>
                  <option value="admin">管理員</option>
                </select>
              </div>
              <div className="catalog-form__action">
                <SubmitButton>建立員工帳戶</SubmitButton>
              </div>
            </form>
          </div>
        </section>

        <section className="panel">
          <header className="panel__header">
            <h2>員工帳戶</h2>
            <span className="subtext">角色決定 ERP 可執行的操作</span>
          </header>
          {staff.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>員工</th>
                    <th>角色</th>
                    <th>狀態</th>
                    <th>最近登入</th>
                    <th>建立時間</th>
                  </tr>
                </thead>
                <tbody>
                  {staff.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.display_name}</strong>
                        <div className="subtext">{user.email}</div>
                      </td>
                      <td>
                        <div className="role-chips">
                          {user.roles.map((role) => (
                            <span className="role-chip" key={role}>
                              {roleLabel(role)}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>{user.status === "active" ? "啟用" : user.status}</td>
                      <td>{formatDateTime(user.last_login_at)}</td>
                      <td>{formatDateTime(user.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="panel__body">
              <EmptyState
                description="建立第一個管理員、營運或分析帳戶。"
                title="尚無內部員工"
              />
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function roleLabel(role: string): string {
  return (
    {
      admin: "管理員",
      operator: "營運",
      analyst: "分析",
      merchant: "商家",
      buyer: "買家",
    }[role] ?? role
  );
}
