import { SearchX } from "lucide-react";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="page">
      <section className="empty-state">
        <div>
          <span className="empty-state__icon" aria-hidden="true">
            <SearchX size={21} />
          </span>
          <h2>找不到這個頁面</h2>
          <p>商品可能已下架，或網址不正確。</p>
          <Link className="button button--primary" href="/">
            返回搜尋
          </Link>
        </div>
      </section>
    </div>
  );
}
