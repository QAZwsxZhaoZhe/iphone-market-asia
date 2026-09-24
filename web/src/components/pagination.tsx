import { ArrowRight } from "lucide-react";
import Link from "next/link";

export function NextPageLink({
  cursor,
  params,
}: {
  cursor: string;
  params: Record<string, string | string[] | undefined>;
}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (key === "cursor" || value === undefined) {
      return;
    }
    query.set(key, Array.isArray(value) ? value[0] : value);
  });
  query.set("cursor", cursor);
  return (
    <nav className="pagination" aria-label="分頁">
      <Link className="button button--ghost" href={`/?${query.toString()}`}>
        下一頁 <ArrowRight size={15} aria-hidden="true" />
      </Link>
    </nav>
  );
}
